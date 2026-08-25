from __future__ import annotations

from collections.abc import Iterable

import pytest

from django_fast_multipart._core import (
    MultipartParser,
    MultipartState,
    PartBegin,
    PartData,
    PartEnd,
)

Event = PartBegin | PartData | PartEnd


def feed(parser: MultipartParser, data: bytes, sizes: Iterable[int]) -> list[Event]:
    events: list[Event] = []
    offset = 0
    for size in sizes:
        events.extend(parser.feed(data[offset : offset + size]))
        offset += size
    if offset < len(data):
        events.extend(parser.feed(data[offset:]))
    return events


def collect_parts(events: list[Event]) -> list[tuple[list[tuple[bytes, bytes]], bytes]]:
    parts: list[tuple[list[tuple[bytes, bytes]], bytes]] = []
    headers: list[tuple[bytes, bytes]] = []
    data = b""
    for event in events:
        if isinstance(event, PartBegin):
            headers, data = event.headers, b""
        elif isinstance(event, PartData):
            data += event.data
        else:
            parts.append((headers, data))
    return parts


def test_constructor_validation() -> None:
    with pytest.raises(ValueError, match="Boundary length must be between 1 and 70 characters"):
        MultipartParser(b"")
    MultipartParser(b"x" * 70)
    with pytest.raises(ValueError, match="Boundary length must be between 1 and 70 characters"):
        MultipartParser(b"x" * 71)


@pytest.fixture
def parser() -> MultipartParser:
    return MultipartParser(b"boundary")


def test_parser_preamble(parser: MultipartParser) -> None:
    parser.feed(b"--boundary\r")

    assert parser.state == MultipartState.PREAMBLE


def test_parser_header(parser: MultipartParser) -> None:
    parser.feed(b"--boundary\r\n")

    assert parser.state == MultipartState.HEADER


def test_parser_body(parser: MultipartParser) -> None:
    events = parser.feed(b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\n")

    assert parser.state == MultipartState.BODY
    assert len(events) == 1
    begin = events[0]
    assert isinstance(begin, PartBegin)
    assert begin.headers == [(b"Content-Disposition", b"form-data; name=field")]


def test_parser_end(parser: MultipartParser) -> None:
    parser.feed(b"--boundary--")

    assert parser.state == MultipartState.END
    parser.finish()


def test_streams_fields_and_binary_files() -> None:
    body = (
        b"ignored preamble\r\n"
        b"--boundary\r\n"
        b"Content-Disposition: form-data; name=field\r\n"
        b"\r\n"
        b"value\r\n"
        b"--boundary\r\n"
        b'Content-Disposition: FORM-DATA; name="upload"; filename="a\\"b.bin"\r\n'
        b"Content-Type: application/octet-stream; charset=binary\r\n"
        b"\r\n"
        b"\x00\xff\r\n\x80\r\n"
        b"--boundary--\r\n"
        b"ignored epilogue"
    )
    parser = MultipartParser(b"boundary")

    events = feed(parser, body, [1] * len(body))

    assert parser.state == MultipartState.END
    parser.finish()
    parts = collect_parts(events)
    assert parts == [
        ([(b"Content-Disposition", b"form-data; name=field")], b"value"),
        (
            [
                (b"Content-Disposition", b'FORM-DATA; name="upload"; filename="a\\"b.bin"'),
                (b"Content-Type", b"application/octet-stream; charset=binary"),
            ],
            b"\x00\xff\r\n\x80",
        ),
    ]

    assert parser.feed(b"more epilogue") == []
    assert parser.state == MultipartState.END


def test_event_reprs(parser: MultipartParser) -> None:
    events = parser.feed(
        b"--boundary\r\nContent-Disposition: form-data; name=x\r\n\r\ndata\r\n--boundary--"
    )

    begin, data, end = events
    assert repr(begin).startswith("PartBegin(headers=[")
    assert repr(data) == "PartData(data=b'data')"
    assert repr(end) == "PartEnd()"


def test_preserves_terminal_crlf_in_body(parser: MultipartParser) -> None:
    events = parser.feed(
        b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\nvalue\r\n\r\n--boundary--"
    )

    assert collect_parts(events)[0][1] == b"value\r\n"


def test_accepts_transport_padding_and_closing_without_crlf() -> None:
    body = (
        b"--boundary \t\r\nContent-Disposition: form-data; name=field\r\n\r\nvalue\r\n--boundary--"
    )
    parser = MultipartParser(b"boundary")

    events = feed(parser, body, [9, 1, 2, 3])

    assert parser.state == MultipartState.END
    assert collect_parts(events)[0][1] == b"value"


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
@pytest.mark.parametrize("line_break", [b"", b"\r", b"\n", b"\r\n"])
def test_django_compatibility_ends_body_at_raw_boundary_token(
    chunk_size: int, line_break: bytes
) -> None:
    body = b"--boundary\r\n\r\nalpha" + line_break + b"--boundaryX ignored\r\n--boundary--\r\n"
    parser = MultipartParser(b"boundary")

    events = feed(parser, body, [chunk_size] * (len(body) // chunk_size))

    assert collect_parts(events) == [([], b"alpha")]
    assert parser.state == MultipartState.END


def test_ignores_false_preamble_candidates() -> None:
    parser = MultipartParser(b"boundary")
    body = (
        b"prefix--boundaryX\r\n"
        b"--boundaryZ\r\n"
        b"--boundary\r\n"
        b"Content-Disposition: form-data; name=field\r\n"
        b"\r\n"
        b"value\r\n"
        b"--boundary--"
    )

    feed(parser, body, [4, 2, 1, 8])

    assert parser.state == MultipartState.END


def test_accepts_empty_multipart_body(parser: MultipartParser) -> None:
    events = parser.feed(b"--boundary--")

    assert parser.state == MultipartState.END
    assert events == []
    parser.finish()


def test_finish_rejects_truncated_message(parser: MultipartParser) -> None:
    parser.feed(b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\nvalue")

    with pytest.raises(ValueError, match="closing boundary not received"):
        parser.finish()


def test_feed_eof_flushes_retained_body_data_without_ending_part() -> None:
    prefix = b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\n"
    data = b"value\r\n--boundary-"
    parser = MultipartParser(b"boundary")

    events = feed(parser, prefix + data, [1] * (len(prefix) + len(data)))
    eof_events = parser.feed_eof()

    assert (
        b"".join(event.data for event in events + eof_events if isinstance(event, PartData)) == data
    )
    assert len(eof_events) == 1
    assert isinstance(eof_events[0], PartData)
    assert not any(isinstance(event, PartEnd) for event in events + eof_events)
    assert parser.state == MultipartState.BODY
    with pytest.raises(ValueError, match="closing boundary not received"):
        parser.finish()


def test_feed_eof_discards_data_after_invalid_boundary_token() -> None:
    prefix = b"--boundary\r\n\r\n"
    data = b"alpha\r\n--boundaryXomega"
    parser = MultipartParser(b"boundary")

    events = parser.feed(prefix + data)
    eof_events = parser.feed_eof()

    assert collect_parts(events + eof_events) == [([], b"alpha")]
    assert parser.state == MultipartState.DISCARD


def test_feed_eof_with_empty_truncated_body_emits_no_data() -> None:
    parser = MultipartParser(b"boundary")
    parser.feed(b"--boundary\r\n\r\n")

    assert parser.feed_eof() == []
    assert parser.state == MultipartState.BODY


@pytest.mark.parametrize(
    ("data", "state"),
    [
        (b"--bound", MultipartState.PREAMBLE),
        (b"--boundary\r\nX: value", MultipartState.HEADER),
    ],
)
def test_feed_eof_emits_nothing_before_part_body(data: bytes, state: MultipartState) -> None:
    parser = MultipartParser(b"boundary")
    parser.feed(data)

    assert parser.feed_eof() == []
    assert parser.state == state
    with pytest.raises(ValueError, match="closing boundary not received"):
        parser.finish()


def test_feed_eof_is_idempotent_and_prevents_more_input() -> None:
    parser = MultipartParser(b"boundary")
    parser.feed(b"--boundary\r\n\r\ndata")

    assert len(parser.feed_eof()) == 1
    assert parser.feed_eof() == []
    with pytest.raises(ValueError, match="Cannot feed data after EOF"):
        parser.feed(b"")


def test_feed_eof_accepts_complete_message() -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=6)
    parser.feed(b"--boundary--")

    assert parser.feed_eof() == []
    parser.finish()


@pytest.mark.parametrize(
    "data",
    [
        b"--boundary" + b" " * 6,
        b"--boundary\r\nX: 1",
        b"--boundary\r\n\r\ndata\r\n--boundary" + b" " * 6,
    ],
    ids=["preamble", "header", "body"],
)
def test_feed_eof_rejects_incomplete_header_at_exact_total_limit(data: bytes) -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=6)
    parser.feed(data)

    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed_eof()
    assert parser.feed_eof() == []
    with pytest.raises(ValueError, match="Cannot feed data after EOF"):
        parser.feed(b"")


@pytest.mark.parametrize(
    "data",
    [
        b"--boundary" + b" " * 6,
        b"--boundary\r\nX: 1",
        b"--boundary\r\n\r\ndata\r\n--boundary" + b" " * 6,
    ],
    ids=["preamble", "header", "body"],
)
def test_feed_eof_allows_incomplete_header_below_total_limit(data: bytes) -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=7)
    parser.feed(data)

    parser.feed_eof()


def test_feed_eof_allows_complete_header_at_exact_total_limit() -> None:
    header_section = b"X: 1\r\n\r\n"
    total_header_size = len(b"\r\n") + len(header_section)
    parser = MultipartParser(b"boundary", max_total_header_size=total_header_size)
    parser.feed(b"--boundary\r\n" + header_section)

    assert parser.feed_eof() == []


def test_reports_incomplete_boundaries_by_state() -> None:
    parser = MultipartParser(b"boundary")
    parser.feed(b"--bound")
    assert parser.state == MultipartState.PREAMBLE

    parser = MultipartParser(b"boundary")
    events = parser.feed(
        b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\nvalue\r\n--boundary-"
    )
    assert parser.state == MultipartState.BODY
    assert not any(isinstance(event, PartEnd) for event in events)


def test_rejects_bare_line_feeds() -> None:
    parser = MultipartParser(b"boundary")
    with pytest.raises(ValueError, match="Invalid line break after delimiter"):
        parser.feed(b"--boundary\n")

    parser = MultipartParser(b"boundary")
    parser.feed(b"--boundary\r\n")
    with pytest.raises(ValueError, match="Invalid line break in header"):
        parser.feed(b"Content-Disposition: form-data; name=field\n")

    parser = MultipartParser(b"boundary")
    parser.feed(b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\nvalue\r\n")
    events = parser.feed(b"--boundary\n")
    assert isinstance(events[-1], PartEnd)
    assert collect_parts(events) == [([], b"value")]
    assert parser.state == MultipartState.DISCARD


def test_rejects_malformed_headers() -> None:
    malformed = [
        (b"Header without colon\r\n", "Malformed header"),
        (b": value\r\n", "Missing header name"),
        (
            b"Content-Disposition: form-data; name=a\rX-Smuggle: b\r\n",
            "Invalid line break in header",
        ),
        (b"X: y\nZ: w\r\n", "Invalid line break in header"),
    ]

    for header, message in malformed:
        parser = MultipartParser(b"boundary")
        parser.feed(b"--boundary\r\n")
        with pytest.raises(ValueError, match=message):
            parser.feed(header)


def test_preserves_raw_header_bytes_and_order() -> None:
    parser = MultipartParser(b"boundary")
    events = parser.feed(
        b"--boundary\r\n"
        b"X-First: one\r\n"
        b"Content-Disposition: form-data; name=first\r\n"
        b"X-First: two\r\n"
        b"\r\n"
        b"value\r\n"
        b"--boundary--"
    )

    begin = events[0]
    assert isinstance(begin, PartBegin)
    assert begin.headers == [
        (b"X-First", b"one"),
        (b"Content-Disposition", b"form-data; name=first"),
        (b"X-First", b"two"),
    ]


def test_enforces_maximum_size() -> None:
    parser = MultipartParser(b"boundary", max_size=3)
    parser.feed(b"abc")

    with pytest.raises(RuntimeError, match="Data exceeds maximum size"):
        parser.feed(b"d")


def test_enforces_maximum_header_count() -> None:
    parser = MultipartParser(b"boundary", max_header_count=2)
    parser.feed(b"--boundary\r\nX-One: 1\r\nX-Two: 2\r\n")

    with pytest.raises(RuntimeError, match="Part exceeds maximum header count"):
        parser.feed(b"X-Three: 3\r\n")


def test_enforces_maximum_header_size_on_complete_line() -> None:
    parser = MultipartParser(b"boundary", max_header_size=16)

    with pytest.raises(RuntimeError, match="Header line exceeds maximum size"):
        parser.feed(b"--boundary\r\nX-Padding: " + b"x" * 16 + b"\r\n")


def test_enforces_maximum_header_size_while_streaming() -> None:
    parser = MultipartParser(b"boundary", max_header_size=16)
    parser.feed(b"--boundary\r\nX-Padding: ")

    with pytest.raises(RuntimeError, match="Header line exceeds maximum size"):
        parser.feed(b"x" * 16)


def test_header_size_limit_allows_crlf_split_across_chunks() -> None:
    line = b"Content-Disposition: form-data; name=field"
    parser = MultipartParser(b"boundary", max_header_size=len(line))
    parser.feed(b"--boundary\r\n" + line + b"\r")
    events = parser.feed(b"\n\r\nhi\r\n--boundary--")

    parser.finish()
    assert isinstance(events[0], PartBegin)


def test_header_limits_allow_boundary_values() -> None:
    parser = MultipartParser(b"boundary", max_header_count=1, max_header_size=42)
    events = parser.feed(
        b"--boundary\r\nContent-Disposition: form-data; name=field\r\n\r\nhi\r\n--boundary--"
    )

    parser.finish()
    assert isinstance(events[0], PartBegin)


def test_enforces_maximum_total_header_size_on_raw_bytes() -> None:
    raw_header = b"X-Raw: \t value \t "
    header_section = raw_header + b"\r\n\r\n"
    body = b"--boundary\r\n" + header_section + b"data\r\n--boundary--"
    total_header_size = len(b"\r\n") + len(header_section)
    parser = MultipartParser(b"boundary", max_total_header_size=total_header_size)

    events = feed(parser, body, [1] * len(body))

    parser.finish()
    begin = events[0]
    assert isinstance(begin, PartBegin)
    assert begin.headers == [(b"X-Raw", b"value")]

    parser = MultipartParser(b"boundary", max_total_header_size=total_header_size - 1)
    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(body)


def test_enforces_maximum_total_header_size_while_streaming() -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=5)
    parser.feed(b"--boundary\r\nX: ")

    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(b"123")


def test_enforces_maximum_total_header_size_in_boundary_padding() -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=4)
    parser.feed(b"--boundary  ")

    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(b"   ")


def test_total_header_size_counts_boundary_padding() -> None:
    header_section = b"X: 1\r\n\r\n"
    maximum_size = len(b"\r\n") + len(header_section)
    parser = MultipartParser(b"boundary", max_total_header_size=maximum_size)
    parser.feed(b"--boundary\r\n" + header_section + b"data\r\n--boundary--")
    parser.finish()

    parser = MultipartParser(b"boundary", max_total_header_size=maximum_size)
    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(b"--boundary \r\n" + header_section)

    parser = MultipartParser(b"boundary", max_total_header_size=maximum_size)
    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(
            b"--boundary\r\n" + header_section + b"data\r\n--boundary \r\n" + header_section
        )


def test_enforces_maximum_total_header_size_across_lines() -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=13)

    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(b"--boundary\r\nX: 1\r\nY: 2\r\n\r\n")


def test_total_header_size_counts_split_terminating_crlf() -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=9)
    parser.feed(b"--boundary\r\nX: 1\r\n\r")

    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(b"\n")


def test_total_header_size_counts_empty_header_section() -> None:
    parser = MultipartParser(b"boundary", max_total_header_size=4)
    events = parser.feed(b"--boundary\r\n\r\ndata\r\n--boundary--")

    parser.finish()
    assert isinstance(events[0], PartBegin)
    assert events[0].headers == []

    parser = MultipartParser(b"boundary", max_total_header_size=3)
    with pytest.raises(RuntimeError, match="Part exceeds maximum total header size"):
        parser.feed(b"--boundary\r\n\r\n")


def test_total_header_size_is_enforced_per_part_and_excludes_body() -> None:
    header_section = b"X: 1\r\n\r\n"
    body = (
        b"--boundary\r\n"
        + header_section
        + b"x" * 4096
        + b"\r\n--boundary\r\n"
        + header_section
        + b"y" * 4096
        + b"\r\n--boundary--"
    )
    parser = MultipartParser(
        b"boundary",
        max_total_header_size=len(b"\r\n") + len(header_section),
    )

    events = parser.feed(body)

    parser.finish()
    assert collect_parts(events) == [
        ([(b"X", b"1")], b"x" * 4096),
        ([(b"X", b"1")], b"y" * 4096),
    ]

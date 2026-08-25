from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO

import pytest
from django.core.exceptions import (
    RequestDataTooBig,
    TooManyFieldsSent,
    TooManyFilesSent,
)
from django.core.files.uploadhandler import TemporaryFileUploadHandler
from django.core.handlers.wsgi import WSGIRequest
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.test import override_settings

from django_fast_multipart import RustMultiPartParser

DEFAULT_BOUNDARY = b"django-fast-multipart-security"
TOO_MANY_FIELDS_MESSAGE = (
    "The number of GET/POST parameters exceeded settings.DATA_UPLOAD_MAX_NUMBER_FIELDS."
)
TOO_MANY_FILES_MESSAGE = "The number of files exceeded settings.DATA_UPLOAD_MAX_NUMBER_FILES."
TOO_MUCH_DATA_MESSAGE = "Request body exceeded settings.DATA_UPLOAD_MAX_MEMORY_SIZE."
HEADER_TOO_LARGE_MESSAGE = "Request max total header size exceeded."

PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(RustMultiPartParser, id="rust"),
]
CORE_GAP_PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(
        RustMultiPartParser,
        id="rust",
        marks=pytest.mark.xfail(
            strict=True,
            reason="Known compatibility difference in the Rust parser.",
        ),
    ),
]


def make_body(parts, *, boundary=DEFAULT_BOUNDARY):
    body = bytearray()
    for header_lines, data in parts:
        body.extend(b"--" + boundary + b"\r\n")
        for header_line in header_lines:
            body.extend(header_line + b"\r\n")
        body.extend(b"\r\n")
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(b"--" + boundary + b"--\r\n")
    return bytes(body)


def field_part(name, value, *, extra_headers=()):
    return (
        [
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            *extra_headers,
        ],
        value,
    )


def file_part(name, file_name, value, *, extra_headers=()):
    return (
        [
            (f'Content-Disposition: form-data; name="{name}"; filename="{file_name}"').encode(),
            b"Content-Type: application/octet-stream",
            *extra_headers,
        ],
        value,
    )


@contextmanager
def parsed_with(parser_class, body, *, boundary=DEFAULT_BOUNDARY, handlers=()):
    files = None
    try:
        post, files = parser_class(
            {
                "CONTENT_LENGTH": str(len(body)),
                "CONTENT_TYPE": f"multipart/form-data; boundary={boundary.decode()}",
            },
            BytesIO(body),
            list(handlers),
            "utf-8",
        ).parse()
        yield post, files
    finally:
        if files is not None:
            for _, uploaded_files in files.lists():
                for uploaded_file in uploaded_files:
                    uploaded_file.close()
        for handler in handlers:
            if hasattr(handler, "file") and not handler.file.closed:
                handler.file.close()


def assert_parse_error(parser_class, body, exception_class, message, *, boundary=None):
    boundary = boundary or DEFAULT_BOUNDARY
    with pytest.raises(exception_class) as caught:
        with parsed_with(parser_class, body, boundary=boundary):
            pass
    assert str(caught.value) == message


@pytest.mark.parametrize("parser_class", PARSERS)
def test_field_memory_limit_matches_django(parser_class):
    body = make_body([field_part("name", b"value")])

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10):
        assert_parse_error(
            parser_class,
            body,
            RequestDataTooBig,
            TOO_MUCH_DATA_MESSAGE,
        )
    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=11):
        with parsed_with(parser_class, body) as (post, files):
            assert post.get("name") == "value"
            assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_empty_field_still_includes_name_cost_in_memory_limit(parser_class):
    body = make_body([field_part("a", b"")])

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=2):
        assert_parse_error(
            parser_class,
            body,
            RequestDataTooBig,
            TOO_MUCH_DATA_MESSAGE,
        )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_field_memory_limit_is_cumulative(parser_class):
    body = make_body(
        [
            field_part("a", b"x"),
            field_part("bb", b"yy"),
        ]
    )

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=9):
        assert_parse_error(
            parser_class,
            body,
            RequestDataTooBig,
            TOO_MUCH_DATA_MESSAGE,
        )
    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10):
        with parsed_with(parser_class, body) as (post, _):
            assert post.get("a") == "x"
            assert post.get("bb") == "yy"


@pytest.mark.parametrize("parser_class", PARSERS)
def test_file_data_is_excluded_from_field_memory_limit(parser_class):
    body = make_body([file_part("file", "large.bin", b"x" * 4096)])
    handler = TemporaryFileUploadHandler()

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1):
        with parsed_with(parser_class, body, handlers=(handler,)) as (post, files):
            assert post == {}
            assert files["file"].read() == b"x" * 4096


@pytest.mark.parametrize("parser_class", PARSERS)
def test_field_count_limit_matches_django(parser_class):
    body = make_body(
        [
            field_part("first", b"one"),
            field_part("second", b"two"),
        ]
    )

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1):
        assert_parse_error(
            parser_class,
            body,
            TooManyFieldsSent,
            TOO_MANY_FIELDS_MESSAGE,
        )
    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2):
        with parsed_with(parser_class, body) as (post, _):
            assert list(post) == ["first", "second"]


@pytest.mark.parametrize(
    "ignored_headers",
    [
        [b"Content-Disposition: form-data"],
        [b"X-Ignored: value"],
    ],
    ids=["missing-name", "raw-part"],
)
@pytest.mark.parametrize("parser_class", PARSERS)
def test_ignored_parts_are_included_in_field_count(parser_class, ignored_headers):
    body = make_body(
        [
            (ignored_headers, b"ignored"),
            field_part("name", b"value"),
        ]
    )

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1):
        assert_parse_error(
            parser_class,
            body,
            TooManyFieldsSent,
            TOO_MANY_FIELDS_MESSAGE,
        )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_file_count_limit_matches_django(parser_class):
    body = make_body(
        [
            file_part("first", "one.bin", b"one"),
            file_part("second", "two.bin", b"two"),
        ]
    )

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=1):
        assert_parse_error(
            parser_class,
            body,
            TooManyFilesSent,
            TOO_MANY_FILES_MESSAGE,
        )
    with override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=2):
        with parsed_with(parser_class, body) as (post, files):
            assert post == {}
            assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_sanitized_away_filename_is_included_in_file_count(parser_class):
    body = make_body(
        [
            file_part("ignored", "/", b"ignored"),
            file_part("valid", "valid.bin", b"valid"),
        ]
    )

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=1):
        assert_parse_error(
            parser_class,
            body,
            TooManyFilesSent,
            TOO_MANY_FILES_MESSAGE,
        )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_unnamed_file_does_not_consume_field_or_file_quota(parser_class):
    unnamed_file = (
        [
            b'Content-Disposition: form-data; filename="ignored.bin"',
            b"Content-Type: application/octet-stream",
        ],
        b"ignored",
    )
    body = make_body(
        [
            unnamed_file,
            file_part("valid", "valid.bin", b"valid"),
        ]
    )

    with override_settings(
        DATA_UPLOAD_MAX_NUMBER_FIELDS=0,
        DATA_UPLOAD_MAX_NUMBER_FILES=1,
    ):
        with parsed_with(parser_class, body) as (post, files):
            assert post == {}
            assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_limits_can_be_disabled(parser_class):
    body = make_body(
        [
            field_part("first", b"one"),
            field_part("second", b"two"),
            file_part("file", "data.bin", b"file-data"),
        ]
    )

    with override_settings(
        DATA_UPLOAD_MAX_MEMORY_SIZE=None,
        DATA_UPLOAD_MAX_NUMBER_FIELDS=None,
        DATA_UPLOAD_MAX_NUMBER_FILES=None,
    ):
        with parsed_with(parser_class, body) as (post, files):
            assert list(post) == ["first", "second"]
            assert files == {}


@pytest.mark.parametrize("content_length", [None, "", "invalid", 0])
@pytest.mark.parametrize("parser_class", PARSERS)
def test_non_positive_content_length_ignores_the_body(parser_class, content_length):
    body = make_body([field_part("name", b"value")])
    metadata = {"CONTENT_TYPE": f"multipart/form-data; boundary={DEFAULT_BOUNDARY.decode()}"}
    if content_length is not None:
        metadata["CONTENT_LENGTH"] = content_length
    stream = BytesIO(body)

    post, files = parser_class(metadata, stream, [], "utf-8").parse()

    assert post == {}
    assert files == {}
    assert stream.tell() == 0


@pytest.mark.parametrize("parser_class", PARSERS)
def test_negative_content_length_is_rejected(parser_class):
    body = make_body([field_part("name", b"value")])

    with pytest.raises(MultiPartParserError) as caught:
        parser_class(
            {
                "CONTENT_LENGTH": -1,
                "CONTENT_TYPE": (f"multipart/form-data; boundary={DEFAULT_BOUNDARY.decode()}"),
            },
            BytesIO(body),
            [],
            "utf-8",
        )
    assert str(caught.value) == "Invalid content length: -1"


@pytest.mark.parametrize("parser_class", PARSERS)
def test_positive_content_length_does_not_bound_a_direct_stream(parser_class):
    body = make_body([field_part("name", b"value")])
    post, files = parser_class(
        {
            "CONTENT_LENGTH": 1,
            "CONTENT_TYPE": f"multipart/form-data; boundary={DEFAULT_BOUNDARY.decode()}",
        },
        BytesIO(body),
        [],
        "utf-8",
    ).parse()

    assert post.get("name") == "value"
    assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_truncated_wsgi_field_matches_django(parser_class):
    body = make_body([field_part("name", b"value")])
    content_length = len(body) - 8
    expected_value = body[:content_length].split(b"\r\n\r\n", 1)[1].decode()
    request = WSGIRequest(
        {
            "CONTENT_LENGTH": content_length,
            "CONTENT_TYPE": f"multipart/form-data; boundary={DEFAULT_BOUNDARY.decode()}",
            "PATH_INFO": "/upload/",
            "REQUEST_METHOD": "POST",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "wsgi.input": BytesIO(body),
            "wsgi.url_scheme": "http",
        }
    )
    request.multipart_parser_class = parser_class

    assert request.POST.get("name") == expected_value


@pytest.mark.parametrize("parser_class", PARSERS)
def test_exact_boundary_token_at_eof_completes_field(parser_class):
    body = make_body([field_part("name", b"value")])[:-4]

    with parsed_with(parser_class, body) as (post, files):
        assert post.get("name") == "value"
        assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_exact_boundary_token_at_eof_does_not_add_raw_field(parser_class):
    body = b"--" + DEFAULT_BOUNDARY + b"\r\nX-Ignored: value\r\n\r\ndata\r\n--" + DEFAULT_BOUNDARY

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=0):
        with parsed_with(parser_class, body) as (post, files):
            assert post == {}
            assert files == {}


@pytest.mark.parametrize(
    ("suffix", "completed"),
    [
        pytest.param(b"", False, id="exact-token"),
        pytest.param(b"-", True, id="partial-closing-suffix"),
    ],
)
@pytest.mark.parametrize("parser_class", PARSERS)
def test_boundary_token_at_eof_matches_file_lifecycle(parser_class, suffix, completed):
    body = make_body([file_part("file", "data.bin", b"file-data")])[:-4] + suffix
    handler = TemporaryFileUploadHandler()

    with parsed_with(parser_class, body, handlers=(handler,)) as (post, files):
        assert post == {}
        if completed:
            assert files["file"].read() == b"file-data"
        else:
            assert files == {}
            assert handler.file.closed


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(b"-", id="closing-dash"),
        pytest.param(b"\r", id="line-ending-carriage-return"),
        pytest.param(b" ", id="space-padding"),
        pytest.param(b"\t", id="tab-padding"),
        pytest.param(b" \t", id="mixed-padding"),
    ],
)
@pytest.mark.parametrize("parser_class", PARSERS)
def test_partial_boundary_suffix_at_eof_adds_raw_field(
    parser_class,
    suffix,
):
    body = (
        b"--"
        + DEFAULT_BOUNDARY
        + b"\r\nX-Ignored: value\r\n\r\ndata\r\n--"
        + DEFAULT_BOUNDARY
        + suffix
    )

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=0):
        assert_parse_error(
            parser_class,
            body,
            TooManyFieldsSent,
            TOO_MANY_FIELDS_MESSAGE,
        )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_eof_after_open_boundary_preserves_completed_field(parser_class):
    body = make_body([field_part("name", b"value")])[:-4] + b"\r\n"

    with parsed_with(parser_class, body) as (post, files):
        assert post.get("name") == "value"
        assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_empty_truncated_field_matches_django(parser_class):
    headers, _ = field_part("name", b"")
    body = make_body([(headers, b"")]).split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"

    with parsed_with(parser_class, body) as (post, files):
        assert post.get("name") == ""
        assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_eof_flushed_field_data_enforces_memory_limit(parser_class):
    headers, _ = field_part("name", b"")
    body = make_body([(headers, b"")]).split(b"\r\n\r\n", 1)[0]
    body += b"\r\n\r\nvalue"

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10):
        assert_parse_error(
            parser_class,
            body,
            RequestDataTooBig,
            TOO_MUCH_DATA_MESSAGE,
        )
    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=11):
        with parsed_with(parser_class, body) as (post, files):
            assert post.get("name") == "value"
            assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_truncated_field_uses_missing_terminal_raw_allowance(parser_class):
    closing_boundary = b"\r\n--" + DEFAULT_BOUNDARY + b"--\r\n"
    body = make_body([field_part("name", b"value")])
    body = body.removesuffix(closing_boundary)

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=0):
        with parsed_with(parser_class, body) as (post, files):
            assert post.get("name") == "value"
            assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_field_before_truncated_file_uses_missing_terminal_raw_allowance(
    parser_class,
):
    closing_boundary = b"\r\n--" + DEFAULT_BOUNDARY + b"--\r\n"
    body = make_body(
        [
            field_part("name", b"value"),
            file_part("file", "data.bin", b"file data"),
        ]
    )
    body = body.removesuffix(closing_boundary)
    handler = TemporaryFileUploadHandler()

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=0):
        with parsed_with(parser_class, body, handlers=(handler,)) as (post, files):
            assert post.get("name") == "value"
            assert files == {}


@pytest.mark.parametrize("parser_class", PARSERS)
def test_terminal_raw_consumes_field_count_allowance(parser_class):
    body = make_body(
        [
            field_part("name", b"value"),
            file_part("file", "data.bin", b"file data"),
        ]
    )

    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=0):
        assert_parse_error(
            parser_class,
            body,
            TooManyFieldsSent,
            TOO_MANY_FIELDS_MESSAGE,
        )


@pytest.mark.parametrize(
    "body",
    [
        b"preamble without a boundary",
        b"--" + DEFAULT_BOUNDARY + b"\r\nX-Incomplete: value",
    ],
    ids=["preamble", "mid-header"],
)
@pytest.mark.parametrize("parser_class", PARSERS)
def test_eof_before_part_body_returns_empty_results(parser_class, body):
    with parsed_with(parser_class, body) as (post, files):
        assert post == {}
        assert files == {}


@pytest.mark.parametrize("boundary_length", [1, 70, 71, 200, 201])
@pytest.mark.parametrize("parser_class", PARSERS)
def test_supported_boundary_lengths_parse(parser_class, boundary_length):
    boundary = b"x" * boundary_length
    body = make_body([field_part("name", b"value")], boundary=boundary)

    with parsed_with(parser_class, body, boundary=boundary) as (post, _):
        assert post.get("name") == "value"


@pytest.mark.parametrize("parser_class", PARSERS)
def test_boundary_over_201_bytes_is_rejected(parser_class):
    boundary = b"x" * 202
    body = make_body([field_part("name", b"value")], boundary=boundary)

    with pytest.raises(MultiPartParserError, match="^Invalid boundary in multipart:"):
        with parsed_with(parser_class, body, boundary=boundary):
            pass


@pytest.mark.parametrize("parser_class", PARSERS)
def test_single_long_header_enforces_total_header_limit(parser_class):
    body = make_body(
        [
            field_part(
                "name",
                b"value",
                extra_headers=(b"X-Padding: " + b"x" * 1000,),
            )
        ]
    )

    assert_parse_error(
        parser_class,
        body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_single_header_enforces_exact_size_boundary(parser_class):
    accepted_header = b"X: " + b"x" * 1015
    rejected_header = accepted_header + b"x"
    assert len(accepted_header) + 6 == 1024
    assert len(rejected_header) + 6 == 1025

    with parsed_with(parser_class, make_body([([accepted_header], b"")])) as (
        post,
        files,
    ):
        assert post == {}
        assert files == {}
    assert_parse_error(
        parser_class,
        make_body([([rejected_header], b"")]),
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_incomplete_header_enforces_exact_size_boundary_at_eof(parser_class):
    prefix = b"--" + DEFAULT_BOUNDARY + b"\r\nX:"
    accepted_body = prefix + b"x" * 1019
    rejected_body = prefix + b"x" * 1020

    with parsed_with(parser_class, accepted_body) as (post, files):
        assert post == {}
        assert files == {}
    assert_parse_error(
        parser_class,
        rejected_body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_boundary_padding_counts_toward_total_header_limit(parser_class):
    accepted_header = b"X: " + b"x" * 1015
    body = make_body([([accepted_header], b"")])
    opening_boundary = b"--" + DEFAULT_BOUNDARY + b"\r\n"
    padded_boundary = b"--" + DEFAULT_BOUNDARY + b" \r\n"
    body = body.replace(opening_boundary, padded_boundary, 1)

    assert_parse_error(
        parser_class,
        body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_minimal_headers_enforce_exact_count_boundary(parser_class):
    accepted_body = make_body([([b"X:"] * 255, b"")])
    rejected_body = make_body([([b"X:"] * 256, b"")])

    with parsed_with(parser_class, accepted_body) as (post, files):
        assert post == {}
        assert files == {}
    assert_parse_error(
        parser_class,
        rejected_body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_combined_headers_enforce_exact_size_boundary(parser_class):
    first_header = b"X:" + b"x" * 500
    accepted_second_header = b"Y:" + b"y" * 512
    rejected_second_header = accepted_second_header + b"y"
    assert len(first_header) + len(accepted_second_header) + 8 == 1024
    assert len(first_header) + len(rejected_second_header) + 8 == 1025

    with parsed_with(
        parser_class,
        make_body([([first_header, accepted_second_header], b"")]),
    ) as (post, files):
        assert post == {}
        assert files == {}
    assert_parse_error(
        parser_class,
        make_body([([first_header, rejected_second_header], b"")]),
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_combined_headers_enforce_total_header_limit(parser_class):
    headers = tuple(f"X-Padding-{index}: ".encode() + b"x" * 50 for index in range(20))
    body = make_body([field_part("name", b"value", extra_headers=headers)])

    assert_parse_error(
        parser_class,
        body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_more_than_eight_small_headers_are_accepted(parser_class):
    headers = tuple(f"X-Small-{index}: value".encode() for index in range(9))
    body = make_body([field_part("name", b"value", extra_headers=headers)])

    with parsed_with(parser_class, body) as (post, _):
        assert post.get("name") == "value"


@pytest.mark.parametrize("parser_class", PARSERS)
def test_raw_header_whitespace_enforces_total_limit(parser_class):
    headers = tuple(
        f"X-Whitespace-{index}: ".encode() + b" " * 100 + b"value" for index in range(10)
    )
    body = make_body([field_part("name", b"value", extra_headers=headers)])

    assert_parse_error(
        parser_class,
        body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PARSERS)
def test_post_colon_space_enforces_exact_header_limit(parser_class):
    first_header = b"X: " + b"x" * 499
    second_header = b"Y: " + b"y" * 512
    assert len(first_header) + len(second_header) + 8 == 1025
    body = make_body([([first_header, second_header], b"")])

    assert_parse_error(
        parser_class,
        body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", CORE_GAP_PARSERS)
def test_malformed_header_line_tolerance_is_recorded(parser_class):
    body = make_body(
        [
            field_part(
                "name",
                b"value",
                extra_headers=(b"Malformed header without a colon",),
            )
        ]
    )

    with parsed_with(parser_class, body) as (post, _):
        assert post.get("name") == "value"

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
TOO_MANY_FILES_MESSAGE = (
    "The number of files exceeded settings.DATA_UPLOAD_MAX_NUMBER_FILES."
)
TOO_MUCH_DATA_MESSAGE = "Request body exceeded settings.DATA_UPLOAD_MAX_MEMORY_SIZE."
HEADER_TOO_LARGE_MESSAGE = "Request max total header size exceeded."

PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(RustMultiPartParser, id="rust"),
]
PENDING_HEADER_PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(
        RustMultiPartParser,
        id="rust",
        marks=pytest.mark.xfail(
            strict=True,
            reason="Django's total multipart header limit is not enforced yet.",
        ),
    ),
]
PENDING_LIMIT_PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(
        RustMultiPartParser,
        id="rust",
        marks=pytest.mark.xfail(
            strict=True,
            reason="This Django limit-accounting edge is not implemented yet.",
        ),
    ),
]
CORE_GAP_PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(
        RustMultiPartParser,
        id="rust",
        marks=pytest.mark.xfail(
            strict=True,
            reason="The current Rust core cannot reproduce this Django behavior.",
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
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{file_name}"'
            ).encode(),
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


@pytest.mark.parametrize("parser_class", PENDING_LIMIT_PARSERS)
def test_empty_field_name_cost_is_included_in_memory_limit(parser_class):
    body = make_body([field_part("a", b"")])

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=2):
        assert_parse_error(
            parser_class,
            body,
            RequestDataTooBig,
            TOO_MUCH_DATA_MESSAGE,
        )


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
@pytest.mark.parametrize("parser_class", PENDING_LIMIT_PARSERS)
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


@pytest.mark.parametrize("parser_class", PENDING_LIMIT_PARSERS)
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
    metadata = {
        "CONTENT_TYPE": f"multipart/form-data; boundary={DEFAULT_BOUNDARY.decode()}"
    }
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
                "CONTENT_TYPE": (
                    f"multipart/form-data; boundary={DEFAULT_BOUNDARY.decode()}"
                ),
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


@pytest.mark.parametrize("parser_class", CORE_GAP_PARSERS)
def test_truncated_wsgi_field_behavior_is_recorded(parser_class):
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


@pytest.mark.parametrize("boundary_length", [1, 70])
@pytest.mark.parametrize("parser_class", PARSERS)
def test_rfc_boundary_lengths_parse(parser_class, boundary_length):
    boundary = b"x" * boundary_length
    body = make_body([field_part("name", b"value")], boundary=boundary)

    with parsed_with(parser_class, body, boundary=boundary) as (post, _):
        assert post.get("name") == "value"


@pytest.mark.parametrize("boundary_length", [71, 200, 201])
@pytest.mark.parametrize("parser_class", CORE_GAP_PARSERS)
def test_django_legacy_boundary_lengths_are_recorded(parser_class, boundary_length):
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


@pytest.mark.parametrize("parser_class", PENDING_HEADER_PARSERS)
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


@pytest.mark.parametrize("parser_class", PENDING_HEADER_PARSERS)
def test_combined_headers_enforce_total_header_limit(parser_class):
    headers = tuple(
        f"X-Padding-{index}: ".encode() + b"x" * 50
        for index in range(20)
    )
    body = make_body([field_part("name", b"value", extra_headers=headers)])

    assert_parse_error(
        parser_class,
        body,
        MultiPartParserError,
        HEADER_TOO_LARGE_MESSAGE,
    )


@pytest.mark.parametrize("parser_class", PENDING_HEADER_PARSERS)
def test_more_than_eight_small_headers_are_accepted(parser_class):
    headers = tuple(f"X-Small-{index}: value".encode() for index in range(9))
    body = make_body([field_part("name", b"value", extra_headers=headers)])

    with parsed_with(parser_class, body) as (post, _):
        assert post.get("name") == "value"


@pytest.mark.parametrize("parser_class", CORE_GAP_PARSERS)
def test_raw_header_whitespace_gap_is_recorded(parser_class):
    headers = tuple(
        f"X-Whitespace-{index}: ".encode() + b" " * 100 + b"value"
        for index in range(10)
    )
    body = make_body([field_part("name", b"value", extra_headers=headers)])

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

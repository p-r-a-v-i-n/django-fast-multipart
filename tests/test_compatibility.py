from __future__ import annotations

import base64
from io import BytesIO

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from django.core.files.uploadhandler import (
    MemoryFileUploadHandler,
    TemporaryFileUploadHandler,
)
from django.core.handlers.wsgi import WSGIRequest
from django.http import QueryDict
from django.http.multipartparser import MultiPartParser
from django.test import override_settings
from django.utils.datastructures import MultiValueDict

from django_fast_multipart import RustMultiPartParser

BOUNDARY = b"django-fast-multipart-boundary"


class ChunkedInput(BytesIO):
    def __init__(self, body: bytes, chunk_size: int):
        super().__init__(body)
        self.chunk_size = chunk_size
        self.read_sizes = []
        self.returned_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            size = self.chunk_size
        data = super().read(min(size, self.chunk_size))
        self.returned_sizes.append(len(data))
        return data


class SplitInput(BytesIO):
    def __init__(self, body: bytes, split: int):
        super().__init__(body)
        self.split = split
        self.total_size = len(body)

    def read(self, size=-1):
        position = self.tell()
        stop = self.split if position < self.split else self.total_size
        remaining = stop - position
        if size < 0:
            size = remaining
        return super().read(min(size, remaining))


def make_body(parts):
    body = bytearray()
    for headers, data in parts:
        body.extend(b"--" + BOUNDARY + b"\r\n")
        for name, value in headers:
            body.extend(name + b": " + value + b"\r\n")
        body.extend(b"\r\n")
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(b"--" + BOUNDARY + b"--\r\n")
    return bytes(body)


def parse(parser_class, body, chunk_size, handler_classes=(), stream=None):
    stream = stream or ChunkedInput(body, chunk_size)
    handlers = [handler_class() for handler_class in handler_classes]
    metadata = {
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY.decode()}",
    }
    post, files = parser_class(metadata, stream, handlers, "utf-8").parse()
    return post, files, stream


def snapshot(post, files):
    post_values = list(post.lists())
    file_values = []
    for field_name, uploaded_files in files.lists():
        file_values.append(
            (
                field_name,
                [
                    {
                        "type": type(uploaded_file),
                        "name": uploaded_file.name,
                        "field_name": getattr(uploaded_file, "field_name", None),
                        "content_type": uploaded_file.content_type,
                        "content_type_extra": uploaded_file.content_type_extra,
                        "size": uploaded_file.size,
                        "charset": uploaded_file.charset,
                        "content": uploaded_file.read(),
                    }
                    for uploaded_file in uploaded_files
                ],
            )
        )
    return post_values, file_values


def assert_matches_django(body, chunk_size, handler_classes=(), expected_file_type=None):
    expected_files = actual_files = None
    try:
        expected_post, expected_files, expected_stream = parse(
            MultiPartParser, body, chunk_size, handler_classes
        )
        actual_post, actual_files, actual_stream = parse(
            RustMultiPartParser, body, chunk_size, handler_classes
        )
        assert snapshot(actual_post, actual_files) == snapshot(expected_post, expected_files)
        for post, files in ((expected_post, expected_files), (actual_post, actual_files)):
            assert isinstance(post, QueryDict)
            assert isinstance(files, MultiValueDict)
            assert post._mutable is False
        if expected_file_type is not None:
            assert isinstance(expected_files["file"], expected_file_type)
            assert isinstance(actual_files["file"], expected_file_type)
        assert all(size >= 0 for size in actual_stream.read_sizes)
        assert max(actual_stream.returned_sizes) <= chunk_size
        if chunk_size < len(body):
            assert sum(size > 0 for size in actual_stream.returned_sizes) > 1
    finally:
        for file_mapping in (expected_files, actual_files):
            if file_mapping is None:
                continue
            for _, uploaded_files in file_mapping.lists():
                for uploaded_file in uploaded_files:
                    uploaded_file.close()


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
def test_normal_and_repeated_fields_match_django(chunk_size):
    body = make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="name"')], b"Ringo"),
            ([(b"Content-Disposition", b'form-data; name="instrument"')], b"drums"),
            ([(b"Content-Disposition", b'form-data; name="instrument"')], b"vocals"),
        ]
    )

    assert_matches_django(body, chunk_size)


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
@pytest.mark.parametrize(
    "preamble",
    [
        pytest.param(b"standard preamble\r\n", id="line-delimited"),
        pytest.param(b"inline preamble", id="inline"),
        pytest.param(b"bare-line-feed\n", id="bare-line-feed"),
    ],
)
def test_preamble_matches_django(preamble, chunk_size):
    body = preamble + make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="value"')], b"field-data"),
        ]
    )

    assert_matches_django(body, chunk_size)


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
@pytest.mark.parametrize(
    "second_part_prefix",
    [
        pytest.param(b"--" + BOUNDARY + b"\r\n", id="following-boundary"),
        pytest.param(b"", id="closing-boundary-segment"),
    ],
)
def test_part_after_closing_boundary_matches_django(second_part_prefix, chunk_size):
    body = make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="first"')], b"one"),
        ]
    )
    body += (
        second_part_prefix
        + b'Content-Disposition: form-data; name="second"\r\n\r\n'
        + b"two\r\n--"
        + BOUNDARY
        + b"--\r\n"
    )

    assert_matches_django(body, chunk_size)


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
def test_part_after_noncanonical_boundary_suffix_matches_django(chunk_size):
    body = (
        b"preamble--"
        + BOUNDARY
        + b"X ignored\r\n"
        + b'Content-Disposition: form-data; name="value"\r\n\r\n'
        + b"field-data\r\n--"
        + BOUNDARY
        + b"--\r\n"
    )

    assert_matches_django(body, chunk_size)


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
def test_boundary_tokens_in_epilogue_match_django(chunk_size):
    body = make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="value"')], b"field-data"),
        ]
    )
    body += b"epilogue--" + BOUNDARY + b"X ignored\r\n--" + BOUNDARY + b"--\r\n"

    assert_matches_django(body, chunk_size)


@pytest.mark.parametrize("chunk_size", [1, 7, 64 * 1024])
def test_memory_file_upload_matches_django(chunk_size):
    body = make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="description"')], b"binary"),
            (
                [
                    (b"Content-Disposition", b'form-data; name="file"; filename="data.bin"'),
                    (b"Content-Type", b"application/octet-stream"),
                ],
                b"\x00\xff\r\nnot-a-boundary\x80",
            ),
        ]
    )

    assert_matches_django(
        body,
        chunk_size,
        (MemoryFileUploadHandler, TemporaryFileUploadHandler),
        InMemoryUploadedFile,
    )


@pytest.mark.parametrize("chunk_size", [17, 64 * 1024])
def test_temporary_file_upload_matches_django(chunk_size):
    body = make_body(
        [
            (
                [
                    (b"Content-Disposition", b'form-data; name="file"; filename="large.bin"'),
                    (b"Content-Type", b"application/octet-stream"),
                ],
                bytes(range(256)) * 512,
            )
        ]
    )

    with override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=64 * 1024):
        assert_matches_django(
            body,
            chunk_size,
            (MemoryFileUploadHandler, TemporaryFileUploadHandler),
            TemporaryUploadedFile,
        )


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
@pytest.mark.parametrize(
    ("transfer_encoding", "encoded_value"),
    [
        pytest.param(b"base64", b"dmFsdWU=", id="valid"),
        pytest.param(b"BASE64", b"dmFsdWU=", id="case-insensitive-header"),
        pytest.param(b"base64", b"dmFs\r\n dWU=", id="whitespace-is-invalid"),
        pytest.param(b"base64", b"dmFsdWU", id="missing-padding"),
        pytest.param(b"base64", b"%%%!=", id="invalid-alphabet"),
    ],
)
def test_base64_field_matches_django(transfer_encoding, encoded_value, chunk_size):
    body = make_body(
        [
            (
                [
                    (b"Content-Disposition", b'form-data; name="value"'),
                    (b"Content-Transfer-Encoding", transfer_encoding),
                ],
                encoded_value,
            )
        ]
    )

    assert_matches_django(body, chunk_size)


@pytest.mark.parametrize("chunk_size", [1, 3, 17, 64 * 1024])
def test_base64_file_with_whitespace_matches_django(chunk_size):
    file_data = bytes(range(256)) * 8
    encoded = base64.b64encode(file_data)
    encoded_with_whitespace = b" \r\n\t".join(
        encoded[index : index + 13] for index in range(0, len(encoded), 13)
    )
    body = make_body(
        [
            (
                [
                    (b"Content-Disposition", b'form-data; name="file"; filename="data.bin"'),
                    (b"Content-Type", b"application/octet-stream"),
                    (b"Content-Transfer-Encoding", b"BASE64"),
                ],
                encoded_with_whitespace,
            )
        ]
    )

    assert_matches_django(
        body,
        chunk_size,
        (MemoryFileUploadHandler, TemporaryFileUploadHandler),
        InMemoryUploadedFile,
    )


@pytest.mark.parametrize("chunk_size", [1, 64 * 1024])
def test_empty_base64_file_matches_django(chunk_size):
    body = make_body(
        [
            (
                [
                    (b"Content-Disposition", b'form-data; name="file"; filename="empty.bin"'),
                    (b"Content-Type", b"application/octet-stream"),
                    (b"Content-Transfer-Encoding", b"base64"),
                ],
                b"",
            )
        ]
    )

    assert_matches_django(
        body,
        chunk_size,
        (MemoryFileUploadHandler, TemporaryFileUploadHandler),
        InMemoryUploadedFile,
    )


def test_every_two_chunk_split_matches_django():
    body = make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="first"')], b"alpha"),
            ([(b"Content-Disposition", b'form-data; name="second"')], b"omega"),
        ]
    )

    for split in range(1, len(body)):
        expected_post, expected_files, _ = parse(
            MultiPartParser,
            body,
            len(body),
            stream=SplitInput(body, split),
        )
        actual_post, actual_files, _ = parse(
            RustMultiPartParser,
            body,
            len(body),
            stream=SplitInput(body, split),
        )
        assert snapshot(actual_post, actual_files) == snapshot(expected_post, expected_files), split


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
@pytest.mark.parametrize(
    "file_data",
    [
        b"before--" + BOUNDARY + b"X\r\nafter",
        b"before\r--" + BOUNDARY + b"-!\r\nafter",
        b"before\n--" + BOUNDARY + b" \tX\r\nafter",
        b"before\r\n--" + BOUNDARY + b"\nafter",
    ],
)
def test_boundary_prefix_inside_file_matches_django(file_data, chunk_size):
    body = make_body(
        [
            (
                [
                    (b"Content-Disposition", b'form-data; name="file"; filename="data.bin"'),
                    (b"Content-Type", b"application/octet-stream"),
                ],
                file_data,
            ),
            ([(b"Content-Disposition", b'form-data; name="status"')], b"complete"),
        ]
    )

    assert_matches_django(
        body,
        chunk_size,
        (MemoryFileUploadHandler, TemporaryFileUploadHandler),
        InMemoryUploadedFile,
    )


@pytest.mark.parametrize("chunk_size", [1, 3, 64 * 1024])
def test_boundary_token_immediately_after_headers_matches_django(chunk_size):
    body = make_body(
        [
            (
                [(b"Content-Disposition", b'form-data; name="value"')],
                b"--" + BOUNDARY,
            )
        ]
    )

    assert_matches_django(body, chunk_size)


def test_request_multipart_parser_class_integration():
    body = make_body(
        [
            ([(b"Content-Disposition", b'form-data; name="name"')], b"Ringo"),
        ]
    )
    request = WSGIRequest(
        {
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY.decode()}",
            "PATH_INFO": "/upload/",
            "REQUEST_METHOD": "POST",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "wsgi.input": BytesIO(body),
            "wsgi.url_scheme": "http",
        }
    )
    request.multipart_parser_class = RustMultiPartParser

    assert request.POST.get("name") == "Ringo"

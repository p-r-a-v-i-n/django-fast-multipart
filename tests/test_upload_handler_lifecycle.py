from __future__ import annotations

import os
from contextlib import contextmanager
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadhandler import (
    FileUploadHandler,
    SkipFile,
    StopFutureHandlers,
    StopUpload,
    TemporaryFileUploadHandler,
)
from django.http.multipartparser import MultiPartParser

from django_fast_multipart import RustMultiPartParser

BOUNDARY = b"django-fast-multipart-lifecycle"
PARSERS = [
    pytest.param(MultiPartParser, id="django"),
    pytest.param(RustMultiPartParser, id="rust"),
]
class ChunkedInput(BytesIO):
    def __init__(self, body: bytes, chunk_size: int = 1):
        super().__init__(body)
        self.chunk_size = chunk_size

    def read(self, size=-1):
        if size < 0:
            size = self.chunk_size
        return super().read(min(size, self.chunk_size))


class RecordingUploadHandler(FileUploadHandler):
    def __init__(
        self,
        *,
        consume=False,
        return_file=True,
        skip_file_name=None,
        skip_phase=None,
        stop_connection_reset=None,
        stop_future=False,
    ):
        super().__init__()
        self.calls = []
        self.consume = consume
        self.return_file = return_file
        self.skip_file_name = skip_file_name
        self.skip_phase = skip_phase
        self.stop_connection_reset = stop_connection_reset
        self.stop_future = stop_future

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        self.calls.append(("handle_raw_input", content_length, boundary, encoding))

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.calls.append(("new_file", self.field_name, self.file_name))
        self.file = BytesIO()
        if self.file_name == self.skip_file_name and self.skip_phase == "new_file":
            raise SkipFile()
        if self.stop_future:
            raise StopFutureHandlers()

    def receive_data_chunk(self, raw_data, start):
        self.calls.append(("receive_data_chunk", self.file_name, start, raw_data))
        if self.file_name == self.skip_file_name and self.skip_phase == "receive":
            raise SkipFile()
        if self.stop_connection_reset is not None:
            raise StopUpload(connection_reset=self.stop_connection_reset)
        if hasattr(self, "file") and not self.file.closed:
            self.file.write(raw_data)
        if self.consume:
            return None
        return raw_data

    def file_complete(self, file_size):
        self.calls.append(("file_complete", self.file_name, file_size))
        if not self.return_file or not hasattr(self, "file") or self.file.closed:
            return None
        return SimpleUploadedFile(
            self.file_name,
            self.file.getvalue(),
            content_type=self.content_type,
        )

    def upload_interrupted(self):
        self.calls.append(("upload_interrupted",))
        if hasattr(self, "file") and not self.file.closed:
            self.file.close()

    def upload_complete(self):
        self.calls.append(("upload_complete",))


class RecordingTemporaryFileUploadHandler(TemporaryFileUploadHandler):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.temporary_path = None

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        self.calls.append(("handle_raw_input",))

    def new_file(self, *args, **kwargs):
        self.calls.append(("new_file",))
        super().new_file(*args, **kwargs)
        self.temporary_path = self.file.temporary_file_path()

    def receive_data_chunk(self, raw_data, start):
        self.calls.append(("receive_data_chunk", start, raw_data))
        return super().receive_data_chunk(raw_data, start)

    def file_complete(self, file_size):
        self.calls.append(("file_complete", file_size))
        return super().file_complete(file_size)

    def upload_interrupted(self):
        self.calls.append(("upload_interrupted",))
        return super().upload_interrupted()

    def upload_complete(self):
        self.calls.append(("upload_complete",))


def make_body(parts, *, close=True):
    body = bytearray()
    for headers, data in parts:
        body.extend(b"--" + BOUNDARY + b"\r\n")
        for name, value in headers:
            body.extend(name + b": " + value + b"\r\n")
        body.extend(b"\r\n")
        body.extend(data)
        body.extend(b"\r\n")
    if close:
        body.extend(b"--" + BOUNDARY + b"--\r\n")
    return bytes(body)


def file_part(field_name, file_name, data):
    return (
        [
            (
                b"Content-Disposition",
                f'form-data; name="{field_name}"; filename="{file_name}"'.encode(),
            ),
            (b"Content-Type", b"application/octet-stream"),
        ],
        data,
    )


def field_part(field_name, data):
    return (
        [(b"Content-Disposition", f'form-data; name="{field_name}"'.encode())],
        data,
    )


@contextmanager
def parsed_with(parser_class, body, handlers):
    stream = ChunkedInput(body)
    files = None
    try:
        post, files = parser_class(
            {
                "CONTENT_LENGTH": str(len(body)),
                "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY.decode()}",
            },
            stream,
            handlers,
            "utf-8",
        ).parse()
        yield post, files, stream
    finally:
        if files is not None:
            for _, uploaded_files in files.lists():
                for uploaded_file in uploaded_files:
                    uploaded_file.close()
        for handler in handlers:
            if hasattr(handler, "file") and not handler.file.closed:
                handler.file.close()


def call_names(handler):
    return [call[0] for call in handler.calls]


@pytest.mark.parametrize("parser_class", PARSERS)
def test_stop_future_handlers_only_stops_new_file_callbacks(parser_class):
    first = RecordingUploadHandler(stop_future=True, return_file=False)
    second = RecordingUploadHandler(return_file=False)
    body = make_body([file_part("file", "data.bin", b"file-data")])

    with parsed_with(parser_class, body, [first, second]) as (post, files, _):
        assert post == {}
        assert files == {}
        assert call_names(first).count("new_file") == 1
        assert call_names(second).count("new_file") == 0
        assert call_names(first).count("receive_data_chunk") > 0
        assert call_names(second).count("receive_data_chunk") > 0
        assert call_names(first).count("file_complete") == 1
        assert call_names(second).count("file_complete") == 1
        assert call_names(first).count("upload_complete") == 1
        assert call_names(second).count("upload_complete") == 1


@pytest.mark.parametrize("skip_phase", ["new_file", "receive"])
@pytest.mark.parametrize("parser_class", PARSERS)
def test_skip_file_continues_with_later_files(parser_class, skip_phase):
    handler = RecordingUploadHandler(
        skip_file_name="skip.bin",
        skip_phase=skip_phase,
    )
    body = make_body(
        [
            file_part("skipped", "skip.bin", b"discard-me"),
            file_part("kept", "keep.bin", b"keep-me"),
        ]
    )

    with parsed_with(parser_class, body, [handler]) as (post, files, _):
        assert post == {}
        assert list(files) == ["kept"]
        assert files["kept"].read() == b"keep-me"
        assert [call[1] for call in handler.calls if call[0] == "new_file"] == [
            "skipped",
            "kept",
        ]
        assert [call[1] for call in handler.calls if call[0] == "file_complete"] == [
            "keep.bin"
        ]
        assert "upload_interrupted" not in call_names(handler)
        assert call_names(handler).count("upload_complete") == 1


@pytest.mark.parametrize("parser_class", PARSERS)
def test_skipping_last_file_calls_upload_interrupted(parser_class):
    handler = RecordingUploadHandler(
        skip_file_name="skip.bin",
        skip_phase="receive",
    )
    body = make_body(
        [
            file_part("skipped", "skip.bin", b"discard-me"),
            field_part("after", b"field-value"),
        ]
    )

    with parsed_with(parser_class, body, [handler]) as (post, files, _):
        assert post.get("after") == "field-value"
        assert files == {}
        assert "file_complete" not in call_names(handler)
        assert call_names(handler).count("upload_interrupted") == 1
        assert call_names(handler).count("upload_complete") == 1


@pytest.mark.parametrize("connection_reset", [False, True])
@pytest.mark.parametrize("parser_class", PARSERS)
def test_stop_upload_returns_partial_results(parser_class, connection_reset):
    handler = RecordingUploadHandler(stop_connection_reset=connection_reset)
    body = make_body(
        [
            field_part("before", b"field-value"),
            file_part("stopped", "stop.bin", b"x" * 4096),
            field_part("after", b"y" * 4096),
        ]
    )

    with parsed_with(parser_class, body, [handler]) as (post, files, stream):
        assert post.get("before") == "field-value"
        assert post.get("after") is None
        assert files == {}
        assert handler.file.closed
        assert "file_complete" not in call_names(handler)
        assert "upload_interrupted" not in call_names(handler)
        assert call_names(handler).count("upload_complete") == 1
        if connection_reset:
            assert stream.tell() < len(body)
        else:
            assert stream.tell() == len(body)


@pytest.mark.parametrize("parser_class", PARSERS)
def test_interrupted_upload_is_cleaned_up(parser_class):
    handler = RecordingTemporaryFileUploadHandler()
    body = make_body(
        [
            field_part("before", b"field-value"),
            file_part("file", "partial.bin", b"partial-file-data"),
        ],
        close=False,
    )

    with parsed_with(parser_class, body, [handler]) as (post, files, stream):
        assert post.get("before") == "field-value"
        assert files == {}
        assert stream.tell() == len(body)
        assert handler.temporary_path is not None
        assert not os.path.exists(handler.temporary_path)
        assert "file_complete" not in call_names(handler)
        assert call_names(handler).count("upload_interrupted") == 1
        assert call_names(handler).count("upload_complete") == 1

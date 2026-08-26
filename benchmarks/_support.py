from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from io import BytesIO

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATA_UPLOAD_MAX_MEMORY_SIZE=128 * 1024 * 1024,
        DATA_UPLOAD_MAX_NUMBER_FIELDS=1_000,
        DATA_UPLOAD_MAX_NUMBER_FILES=100,
        DEFAULT_CHARSET="utf-8",
        FILE_UPLOAD_MAX_MEMORY_SIZE=64 * 1024 * 1024,
        SECRET_KEY="django-fast-multipart-benchmarks",
    )
django.setup()

from django.core.files.uploadhandler import (  # noqa: E402
    FileUploadHandler,
    MemoryFileUploadHandler,
    TemporaryFileUploadHandler,
)
from django.http.multipartparser import MultiPartParser  # noqa: E402

from django_fast_multipart import RustMultiPartParser  # noqa: E402

BOUNDARY = b"django-fast-multipart-benchmark"
CHUNK_SIZES = (8 * 1024, 64 * 1024)
PARSERS = {
    "django": MultiPartParser,
    "rust": RustMultiPartParser,
}
SCENARIO_NAMES = ("fields-100", "memory-file-1MiB", "temporary-file-8MiB")


class ChunkedInput(BytesIO):
    def __init__(self, body: bytes, chunk_size: int) -> None:
        super().__init__(body)
        self.chunk_size = chunk_size

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.chunk_size
        return super().read(min(size, self.chunk_size))


@dataclass(frozen=True)
class Scenario:
    body: bytes
    handler_classes: tuple[type[FileUploadHandler], ...]
    expected_fields: int
    expected_files: int


def make_body(parts: list[tuple[list[tuple[bytes, bytes]], bytes]]) -> bytes:
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


@cache
def get_scenario(name: str) -> Scenario:
    if name == "fields-100":
        parts = [
            (
                [(b"Content-Disposition", f'form-data; name="field-{index}"'.encode())],
                b"x" * 32,
            )
            for index in range(100)
        ]
        return Scenario(make_body(parts), (), 100, 0)
    if name == "memory-file-1MiB":
        return Scenario(
            make_body(
                [
                    (
                        [
                            (
                                b"Content-Disposition",
                                b'form-data; name="file"; filename="memory.bin"',
                            ),
                            (b"Content-Type", b"application/octet-stream"),
                        ],
                        b"x" * (1024 * 1024),
                    )
                ]
            ),
            (MemoryFileUploadHandler,),
            0,
            1,
        )
    if name == "temporary-file-8MiB":
        return Scenario(
            make_body(
                [
                    (
                        [
                            (
                                b"Content-Disposition",
                                b'form-data; name="file"; filename="temporary.bin"',
                            ),
                            (b"Content-Type", b"application/octet-stream"),
                        ],
                        b"x" * (8 * 1024 * 1024),
                    )
                ]
            ),
            (TemporaryFileUploadHandler,),
            0,
            1,
        )
    raise ValueError(f"Unknown benchmark scenario: {name}")


def run_parser(parser_name: str, scenario_name: str, chunk_size: int) -> None:
    scenario = get_scenario(scenario_name)
    stream = ChunkedInput(scenario.body, chunk_size)
    handlers = [handler_class() for handler_class in scenario.handler_classes]
    metadata = {
        "CONTENT_LENGTH": str(len(scenario.body)),
        "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY.decode()}",
    }
    post = files = None
    try:
        post, files = PARSERS[parser_name](metadata, stream, handlers, "utf-8").parse()
        if len(post) != scenario.expected_fields:
            raise RuntimeError(f"Expected {scenario.expected_fields} fields, received {len(post)}.")
        file_count = sum(len(values) for _, values in files.lists())
        if file_count != scenario.expected_files:
            raise RuntimeError(f"Expected {scenario.expected_files} files, received {file_count}.")
    finally:
        if files is not None:
            for _, uploaded_files in files.lists():
                for uploaded_file in uploaded_files:
                    uploaded_file.close()

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from io import BytesIO

import django
from django.conf import settings

BENCHMARK_MODULE_PREFIX = "benchmarks." if __package__ else ""

if not settings.configured:
    settings.configure(
        ALLOWED_HOSTS=["testserver"],
        DATA_UPLOAD_MAX_MEMORY_SIZE=128 * 1024 * 1024,
        DATA_UPLOAD_MAX_NUMBER_FIELDS=1_000,
        DATA_UPLOAD_MAX_NUMBER_FILES=100,
        DEFAULT_CHARSET="utf-8",
        FILE_UPLOAD_MAX_MEMORY_SIZE=64 * 1024 * 1024,
        MIDDLEWARE=[],
        ROOT_URLCONF=f"{BENCHMARK_MODULE_PREFIX}_django_app",
        SECRET_KEY="django-fast-multipart-benchmarks",
    )
django.setup()

from django.core.files.uploadhandler import (  # noqa: E402
    FileUploadHandler,
    MemoryFileUploadHandler,
    TemporaryFileUploadHandler,
)
from django.http.multipartparser import MultiPartParser  # noqa: E402
from django.test import AsyncRequestFactory, Client  # noqa: E402

from django_fast_multipart import RustMultiPartParser  # noqa: E402

if __package__:
    from benchmarks._django_app import asgi_upload
else:
    from _django_app import asgi_upload

BOUNDARY = b"django-fast-multipart-benchmark"
CHUNK_SIZES = (8 * 1024, 64 * 1024)
PARSERS = {
    "django": MultiPartParser,
    "rust": RustMultiPartParser,
}
SCENARIO_NAMES = (
    "fields-100",
    "mixed-form-1MiB",
    "memory-files-8x128KiB",
    "memory-file-64KiB",
    "memory-file-1MiB",
    "temporary-file-8MiB",
    "temporary-file-32MiB",
)
REQUEST_SCENARIO_NAMES = ("fields-100", "mixed-form-1MiB", "temporary-file-8MiB")


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
    expected_file_bytes: int


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


def field_part(index: int, size: int = 32) -> tuple[list[tuple[bytes, bytes]], bytes]:
    return (
        [(b"Content-Disposition", f'form-data; name="field-{index}"'.encode())],
        b"x" * size,
    )


def file_part(name: str, size: int) -> tuple[list[tuple[bytes, bytes]], bytes]:
    return (
        [
            (
                b"Content-Disposition",
                f'form-data; name="{name}"; filename="{name}.bin"'.encode(),
            ),
            (b"Content-Type", b"application/octet-stream"),
        ],
        b"x" * size,
    )


@cache
def get_scenario(name: str) -> Scenario:
    if name == "fields-100":
        return Scenario(make_body([field_part(index) for index in range(100)]), (), 100, 0, 0)
    if name == "mixed-form-1MiB":
        file_size = 256 * 1024
        parts = [field_part(index) for index in range(20)]
        parts.extend(file_part(f"file-{index}", file_size) for index in range(4))
        return Scenario(
            make_body(parts),
            (MemoryFileUploadHandler,),
            20,
            4,
            4 * file_size,
        )
    if name == "memory-files-8x128KiB":
        file_size = 128 * 1024
        return Scenario(
            make_body([file_part(f"file-{index}", file_size) for index in range(8)]),
            (MemoryFileUploadHandler,),
            0,
            8,
            8 * file_size,
        )
    if name == "memory-file-64KiB":
        file_size = 64 * 1024
        return Scenario(
            make_body([file_part("memory", file_size)]),
            (MemoryFileUploadHandler,),
            0,
            1,
            file_size,
        )
    if name == "memory-file-1MiB":
        file_size = 1024 * 1024
        return Scenario(
            make_body([file_part("memory", file_size)]),
            (MemoryFileUploadHandler,),
            0,
            1,
            file_size,
        )
    if name == "temporary-file-8MiB":
        file_size = 8 * 1024 * 1024
        return Scenario(
            make_body([file_part("temporary", file_size)]),
            (TemporaryFileUploadHandler,),
            0,
            1,
            file_size,
        )
    if name == "temporary-file-32MiB":
        file_size = 32 * 1024 * 1024
        return Scenario(
            make_body([file_part("temporary", file_size)]),
            (TemporaryFileUploadHandler,),
            0,
            1,
            file_size,
        )
    raise ValueError(f"Unknown benchmark scenario: {name}")


def content_type() -> str:
    return f"multipart/form-data; boundary={BOUNDARY.decode()}"


def validate_result(scenario: Scenario, post, files) -> None:
    if len(post) != scenario.expected_fields:
        raise RuntimeError(f"Expected {scenario.expected_fields} fields, received {len(post)}.")
    uploaded_files = [uploaded_file for _, values in files.lists() for uploaded_file in values]
    if len(uploaded_files) != scenario.expected_files:
        raise RuntimeError(
            f"Expected {scenario.expected_files} files, received {len(uploaded_files)}."
        )
    file_bytes = sum(uploaded_file.size for uploaded_file in uploaded_files)
    if file_bytes != scenario.expected_file_bytes:
        raise RuntimeError(
            f"Expected {scenario.expected_file_bytes} file bytes, received {file_bytes}."
        )


def validate_response(scenario: Scenario, response) -> None:
    if response.status_code != 204:
        raise RuntimeError(f"Expected HTTP 204, received {response.status_code}.")
    expected = {
        "X-Benchmark-Fields": scenario.expected_fields,
        "X-Benchmark-Files": scenario.expected_files,
        "X-Benchmark-File-Bytes": scenario.expected_file_bytes,
    }
    for header, value in expected.items():
        if response.headers.get(header) != str(value):
            raise RuntimeError(
                f"Expected {header}={value}, received {response.headers.get(header)!r}."
            )


def run_parser(parser_name: str, scenario_name: str, chunk_size: int) -> None:
    scenario = get_scenario(scenario_name)
    stream = ChunkedInput(scenario.body, chunk_size)
    handlers = [handler_class() for handler_class in scenario.handler_classes]
    metadata = {
        "CONTENT_LENGTH": str(len(scenario.body)),
        "CONTENT_TYPE": content_type(),
    }
    post = files = None
    try:
        post, files = PARSERS[parser_name](metadata, stream, handlers, "utf-8").parse()
        validate_result(scenario, post, files)
    finally:
        if files is not None:
            for _, uploaded_files in files.lists():
                for uploaded_file in uploaded_files:
                    uploaded_file.close()


def run_wsgi_request(
    parser_name: str,
    scenario_name: str,
    client: Client | None = None,
) -> None:
    scenario = get_scenario(scenario_name)
    response = (client or Client()).post(
        f"/benchmark/wsgi/{scenario_name}/{parser_name}/",
        scenario.body,
        content_type=content_type(),
    )
    try:
        validate_response(scenario, response)
    finally:
        response.close()


async def run_asgi_request(parser_name: str, scenario_name: str) -> None:
    scenario = get_scenario(scenario_name)
    path = f"/benchmark/asgi/{scenario_name}/{parser_name}/"
    request = AsyncRequestFactory().post(path, scenario.body, content_type=content_type())
    response = await asgi_upload(request, scenario_name, parser_name)
    try:
        validate_response(scenario, response)
    finally:
        response.close()
        request.close()

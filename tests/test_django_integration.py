from __future__ import annotations

import asyncio
import json
import os
from inspect import iscoroutinefunction

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadhandler import TemporaryFileUploadHandler
from django.core.handlers.asgi import ASGIRequest
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.test import AsyncRequestFactory, Client, override_settings
from django.urls import path

from django_fast_multipart import FastMultipartMiddleware, RustMultiPartParser

FAST_MULTIPART_MIDDLEWARE = "django_fast_multipart.middleware.FastMultipartMiddleware"
CSRF_MIDDLEWARE = "django.middleware.csrf.CsrfViewMiddleware"
MEMORY_UPLOAD_HANDLER = "django.core.files.uploadhandler.MemoryFileUploadHandler"
TEMPORARY_UPLOAD_HANDLER = "django.core.files.uploadhandler.TemporaryFileUploadHandler"
FAILED_UPLOAD_PATHS: list[str] = []
FAILED_HANDLER_PATHS: list[str] = []


class FailingTemporaryFileUploadHandler(TemporaryFileUploadHandler):
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        temporary_path = self.file.temporary_file_path()
        assert os.path.exists(temporary_path)
        FAILED_HANDLER_PATHS.append(temporary_path)

    def receive_data_chunk(self, raw_data, start):
        super().receive_data_chunk(raw_data, start)
        raise RuntimeError("upload handler failed while receiving data")


def upload_response(request: HttpRequest) -> JsonResponse:
    uploaded_file = request.FILES["upload"]
    temporary_path = None
    if hasattr(uploaded_file, "temporary_file_path"):
        temporary_path = uploaded_file.temporary_file_path()
    temporary_path_exists = temporary_path is not None and os.path.exists(temporary_path)
    return JsonResponse(
        {
            "field": request.POST.getlist("field"),
            "file_name": uploaded_file.name,
            "file_content": uploaded_file.read().decode("latin-1"),
            "parser": request.multipart_parser_class.__name__,
            "temporary_path": temporary_path,
            "temporary_path_exists": temporary_path_exists,
            "uploaded_file_class": uploaded_file.__class__.__name__,
        }
    )


def upload_view(request: HttpRequest) -> JsonResponse:
    return upload_response(request)


async def async_upload_view(request: HttpRequest) -> JsonResponse:
    return upload_response(request)


def per_request_upload_view(request: HttpRequest) -> JsonResponse:
    request.multipart_parser_class = RustMultiPartParser
    return upload_response(request)


def non_multipart_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "body": request.body.decode(),
            "parser": request.multipart_parser_class.__name__,
        }
    )


def csrf_upload_view(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse({"token": get_token(request)})
    return upload_response(request)


def failing_upload_view(request: HttpRequest) -> JsonResponse:
    uploaded_file = request.FILES["upload"]
    temporary_path = uploaded_file.temporary_file_path()
    assert os.path.exists(temporary_path)
    FAILED_UPLOAD_PATHS.append(temporary_path)
    raise RuntimeError("view failed after reading the upload")


def failing_handler_view(request: HttpRequest) -> JsonResponse:
    request.upload_handlers = [FailingTemporaryFileUploadHandler(request)]
    return upload_response(request)


urlpatterns = [
    path("async-upload/", async_upload_view),
    path("csrf-upload/", csrf_upload_view),
    path("failing-handler/", failing_handler_view),
    path("failing-upload/", failing_upload_view),
    path("non-multipart/", non_multipart_view),
    path("per-request-upload/", per_request_upload_view),
    path("upload/", upload_view),
]


def uploaded_file() -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "sample.bin",
        b"binary-data\x00\xff",
        content_type="application/octet-stream",
    )


def track_native_parses(monkeypatch: pytest.MonkeyPatch) -> list[RustMultiPartParser]:
    calls = []
    original_parse = RustMultiPartParser.parse

    def tracked_parse(parser: RustMultiPartParser):
        calls.append(parser)
        return original_parse(parser)

    monkeypatch.setattr(RustMultiPartParser, "parse", tracked_parse)
    return calls


@override_settings(ROOT_URLCONF=__name__, MIDDLEWARE=[FAST_MULTIPART_MIDDLEWARE])
def test_middleware_selects_native_parser_in_wsgi_request(monkeypatch):
    calls = track_native_parses(monkeypatch)
    response = Client().post(
        "/upload/",
        {"field": ["first", "second"], "upload": uploaded_file()},
    )
    try:
        assert response.status_code == 200
        assert isinstance(response.wsgi_request, WSGIRequest)
        assert response.json() == {
            "field": ["first", "second"],
            "file_name": "sample.bin",
            "file_content": "binary-data\u0000\u00ff",
            "parser": "RustMultiPartParser",
            "temporary_path": None,
            "temporary_path_exists": False,
            "uploaded_file_class": "InMemoryUploadedFile",
        }
        assert len(calls) == 1
    finally:
        response.close()


@override_settings(ROOT_URLCONF=__name__)
def test_middleware_selects_native_parser_in_asgi_request(monkeypatch):
    calls = track_native_parses(monkeypatch)
    request = AsyncRequestFactory().post(
        "/async-upload/",
        {"field": "async", "upload": uploaded_file()},
    )

    async def get_response(current_request):
        return await async_upload_view(current_request)

    middleware = FastMultipartMiddleware(get_response)
    assert iscoroutinefunction(middleware)
    response = asyncio.run(middleware(request))
    try:
        assert response.status_code == 200
        assert isinstance(request, ASGIRequest)
        response_data = json.loads(response.content)
        assert response_data["field"] == ["async"]
        assert response_data["file_content"] == "binary-data\u0000\u00ff"
        assert response_data["parser"] == "RustMultiPartParser"
        assert len(calls) == 1
    finally:
        response.close()
        request.close()


@override_settings(ROOT_URLCONF=__name__, MIDDLEWARE=[])
def test_view_can_select_native_parser_per_request(monkeypatch):
    calls = track_native_parses(monkeypatch)
    response = Client().post(
        "/per-request-upload/",
        {"field": "view", "upload": uploaded_file()},
    )
    try:
        assert response.status_code == 200
        assert response.json()["field"] == ["view"]
        assert response.json()["parser"] == "RustMultiPartParser"
        assert len(calls) == 1
    finally:
        response.close()


@override_settings(ROOT_URLCONF=__name__, MIDDLEWARE=[FAST_MULTIPART_MIDDLEWARE])
def test_middleware_leaves_non_multipart_request_unchanged(monkeypatch):
    calls = track_native_parses(monkeypatch)
    response = Client().post(
        "/non-multipart/",
        b'{"field":"value"}',
        content_type="application/json",
    )
    try:
        assert response.status_code == 200
        assert response.json() == {
            "body": '{"field":"value"}',
            "parser": "MultiPartParser",
        }
        assert calls == []
    finally:
        response.close()


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[FAST_MULTIPART_MIDDLEWARE, CSRF_MIDDLEWARE],
)
def test_middleware_selects_parser_before_csrf_reads_post(monkeypatch):
    calls = track_native_parses(monkeypatch)
    client = Client(enforce_csrf_checks=True)
    token_response = client.get("/csrf-upload/")
    token = token_response.json()["token"]
    token_response.close()

    response = client.post(
        "/csrf-upload/",
        {
            "csrfmiddlewaretoken": token,
            "field": "csrf",
            "upload": uploaded_file(),
        },
    )
    try:
        assert response.status_code == 200
        assert response.json()["field"] == ["csrf"]
        assert response.json()["parser"] == "RustMultiPartParser"
        assert len(calls) == 1
    finally:
        response.close()


@pytest.mark.parametrize(
    ("handler", "uploaded_file_class"),
    [
        (MEMORY_UPLOAD_HANDLER, "InMemoryUploadedFile"),
        (TEMPORARY_UPLOAD_HANDLER, "TemporaryUploadedFile"),
    ],
)
@override_settings(ROOT_URLCONF=__name__, MIDDLEWARE=[FAST_MULTIPART_MIDDLEWARE])
def test_middleware_respects_configured_upload_handler(handler, uploaded_file_class):
    with override_settings(FILE_UPLOAD_HANDLERS=[handler]):
        response = Client().post(
            "/upload/",
            {"field": "handler", "upload": uploaded_file()},
        )

    temporary_path = response.json()["temporary_path"]
    try:
        assert response.status_code == 200
        assert response.json()["uploaded_file_class"] == uploaded_file_class
        assert response.json()["file_content"] == "binary-data\u0000\u00ff"
        if temporary_path is not None:
            assert response.json()["temporary_path_exists"] is True
    finally:
        response.close()
    if temporary_path is not None:
        assert not os.path.exists(temporary_path)


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[FAST_MULTIPART_MIDDLEWARE],
    FILE_UPLOAD_HANDLERS=[TEMPORARY_UPLOAD_HANDLER],
)
def test_temporary_upload_is_cleaned_after_view_exception():
    FAILED_UPLOAD_PATHS.clear()
    response = Client(raise_request_exception=False).post(
        "/failing-upload/",
        {"upload": uploaded_file()},
    )
    try:
        assert response.status_code == 500
        assert len(FAILED_UPLOAD_PATHS) == 1
    finally:
        response.close()
    assert not os.path.exists(FAILED_UPLOAD_PATHS[0])


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[FAST_MULTIPART_MIDDLEWARE],
)
def test_temporary_upload_is_cleaned_after_upload_handler_exception():
    FAILED_HANDLER_PATHS.clear()
    response = Client(raise_request_exception=False).post(
        "/failing-handler/",
        {"upload": uploaded_file()},
    )
    try:
        assert response.status_code == 400
        assert len(FAILED_HANDLER_PATHS) == 1
    finally:
        response.close()
    assert not os.path.exists(FAILED_HANDLER_PATHS[0])

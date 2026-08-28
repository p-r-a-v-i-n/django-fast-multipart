from __future__ import annotations

from django.core.files.uploadhandler import MemoryFileUploadHandler, TemporaryFileUploadHandler
from django.http import HttpRequest, HttpResponse
from django.urls import path

from django_fast_multipart import RustMultiPartParser


def upload_response(request: HttpRequest, parser_name: str, scenario_name: str) -> HttpResponse:
    if parser_name == "rust":
        request.multipart_parser_class = RustMultiPartParser
    elif parser_name != "django":
        return HttpResponse(status=404)

    if scenario_name.startswith("temporary-file-"):
        request.upload_handlers = [TemporaryFileUploadHandler(request)]
    elif "file" in scenario_name or scenario_name.startswith("mixed-form-"):
        request.upload_handlers = [MemoryFileUploadHandler(request)]
    else:
        request.upload_handlers = []

    post = request.POST
    files = request.FILES
    uploaded_files = [uploaded_file for _, values in files.lists() for uploaded_file in values]

    response = HttpResponse(status=204)
    response.headers["X-Benchmark-Fields"] = str(len(post))
    response.headers["X-Benchmark-Files"] = str(len(uploaded_files))
    response.headers["X-Benchmark-File-Bytes"] = str(
        sum(uploaded_file.size for uploaded_file in uploaded_files)
    )
    return response


def wsgi_upload(request: HttpRequest, scenario_name: str, parser_name: str) -> HttpResponse:
    return upload_response(request, parser_name, scenario_name)


async def asgi_upload(request: HttpRequest, scenario_name: str, parser_name: str) -> HttpResponse:
    return upload_response(request, parser_name, scenario_name)


urlpatterns = [
    path("benchmark/wsgi/<str:scenario_name>/<str:parser_name>/", wsgi_upload),
    path("benchmark/asgi/<str:scenario_name>/<str:parser_name>/", asgi_upload),
]

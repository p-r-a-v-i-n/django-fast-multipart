from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import iscoroutinefunction, markcoroutinefunction

from django.http import HttpRequest, HttpResponseBase

from django_fast_multipart.parser import RustMultiPartParser

Response = HttpResponseBase | Awaitable[HttpResponseBase]
GetResponse = Callable[[HttpRequest], Response]


class FastMultipartMiddleware:
    """Select the Rust-backed parser for multipart requests."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response: GetResponse) -> None:
        if get_response is None:
            raise ValueError("get_response must be provided.")
        self.get_response = get_response
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Response:
        if self.async_mode:
            return self.__acall__(request)
        self._select_parser(request)
        return self.get_response(request)

    async def __acall__(self, request: HttpRequest) -> HttpResponseBase:
        self._select_parser(request)
        return await self.get_response(request)

    @staticmethod
    def _select_parser(request: HttpRequest) -> None:
        if request.content_type == "multipart/form-data":
            request.multipart_parser_class = RustMultiPartParser

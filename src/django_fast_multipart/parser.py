from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import (
    RequestDataTooBig,
    TooManyFieldsSent,
    TooManyFilesSent,
)
from django.core.files.uploadhandler import StopFutureHandlers
from django.http import QueryDict
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.utils.datastructures import MultiValueDict
from django.utils.encoding import force_str
from django.utils.http import parse_header_parameters
from rust_multipart import MultipartParser, PartBegin, PartData, PartEnd


@dataclass
class _Part:
    field_name: str | None = None
    file_name: str | None = None
    content_type: str = ""
    content_length: int | None = None
    charset: bytes | None = None
    content_type_extra: dict[str, bytes] = field(default_factory=dict)
    is_file: bool = False
    ignored: bool = False
    data: bytearray = field(default_factory=bytearray)
    counters: list[int] = field(default_factory=list)


class RustMultiPartParser(MultiPartParser):
    """Experimental Django adapter for ``rust_multipart.MultipartParser``."""

    def _parse(self):
        if self._content_length == 0:
            return QueryDict(encoding=self._encoding), MultiValueDict()

        for handler in self._upload_handlers:
            result = handler.handle_raw_input(
                self._input_data,
                self._meta,
                self._content_length,
                self._boundary,
                self._encoding,
            )
            if result is not None:
                return result

        self._post = QueryDict(mutable=True, encoding=self._encoding)
        self._files = MultiValueDict()
        self._field_bytes = 0
        self._field_count = 0
        self._file_count = 0

        try:
            parser = MultipartParser(self._boundary)
        except (RuntimeError, ValueError) as exc:
            raise MultiPartParserError(str(exc)) from exc

        current_part: _Part | None = None
        try:
            while chunk := self._input_data.read(self._chunk_size):
                for event in parser.feed(chunk):
                    if isinstance(event, PartBegin):
                        if current_part is not None:
                            raise MultiPartParserError(
                                "Received a new multipart part before the previous part ended."
                            )
                        current_part = self._begin_part(event.headers)
                    elif isinstance(event, PartData):
                        if current_part is None:
                            raise MultiPartParserError(
                                "Received multipart data before part headers."
                            )
                        self._receive_part_data(current_part, event.data)
                    elif isinstance(event, PartEnd):
                        if current_part is None:
                            raise MultiPartParserError(
                                "Received a multipart part ending without a beginning."
                            )
                        self._finish_part(current_part)
                        current_part = None

            parser.finish()
        except (RuntimeError, ValueError) as exc:
            if current_part is not None and current_part.is_file:
                self._interrupt_upload()
            raise MultiPartParserError(str(exc)) from exc
        except Exception:
            if current_part is not None and current_part.is_file:
                self._interrupt_upload()
            raise

        any(handler.upload_complete() for handler in self._upload_handlers)
        self._post._mutable = False
        return self._post, self._files

    def _begin_part(self, raw_headers: list[tuple[bytes, bytes]]) -> _Part:
        headers = self._parse_headers(raw_headers)
        content_disposition = headers.get("content-disposition")
        if content_disposition is None:
            return _Part(ignored=True)

        _, disposition = content_disposition
        raw_field_name = disposition.get("name")
        if raw_field_name is None:
            return _Part(ignored=True)

        field_name = force_str(raw_field_name.strip(), self._encoding, errors="replace")
        raw_file_name = disposition.get("filename")
        is_file = bool(raw_file_name)
        file_name = None
        ignored = False
        if is_file:
            file_name = force_str(raw_file_name, self._encoding, errors="replace")
            file_name = self.sanitize_file_name(file_name)
            ignored = file_name is None

        content_type, content_type_parameters = headers.get("content-type", ("", {}))
        content_type_extra = {
            key: value.encode(self._encoding, errors="replace")
            for key, value in content_type_parameters.items()
        }
        charset = content_type_extra.get("charset")

        content_length = None
        raw_content_length = headers.get("content-length")
        if raw_content_length is not None:
            try:
                content_length = int(raw_content_length[0])
            except (TypeError, ValueError):
                pass

        transfer_encoding = headers.get("content-transfer-encoding")
        if transfer_encoding is not None and transfer_encoding[0].strip() == "base64":
            raise MultiPartParserError(
                "Content-Transfer-Encoding: base64 is outside the initial spike scope."
            )

        part = _Part(
            field_name=field_name,
            file_name=file_name,
            content_type=content_type.strip(),
            content_length=content_length,
            charset=charset,
            content_type_extra=content_type_extra,
            is_file=is_file,
            ignored=ignored,
            counters=[0] * len(self._upload_handlers),
        )

        if ignored:
            return part
        if is_file:
            self._file_count += 1
            maximum_files = settings.DATA_UPLOAD_MAX_NUMBER_FILES
            if maximum_files is not None and self._file_count > maximum_files:
                raise TooManyFilesSent(
                    "The number of files exceeded settings.DATA_UPLOAD_MAX_NUMBER_FILES."
                )
            self._start_file(part)
        else:
            self._field_count += 1
            maximum_fields = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
            if maximum_fields is not None and self._field_count > maximum_fields:
                raise TooManyFieldsSent(
                    "The number of GET/POST parameters exceeded "
                    "settings.DATA_UPLOAD_MAX_NUMBER_FIELDS."
                )
        return part

    def _parse_headers(
        self, raw_headers: list[tuple[bytes, bytes]]
    ) -> dict[str, tuple[str, dict[str, str]]]:
        headers = {}
        for raw_name, raw_value in raw_headers:
            try:
                name = raw_name.decode().lower().rstrip(" ")
                value, parameters = parse_header_parameters(raw_value.decode())
            except (UnicodeDecodeError, ValueError, LookupError):
                continue
            headers[name] = value, parameters
        return headers

    def _start_file(self, part: _Part) -> None:
        for handler in self._upload_handlers:
            try:
                handler.new_file(
                    part.field_name,
                    part.file_name,
                    part.content_type,
                    part.content_length,
                    part.charset,
                    part.content_type_extra,
                )
            except StopFutureHandlers:
                break

    def _receive_part_data(self, part: _Part, data: bytes) -> None:
        if part.ignored:
            return
        if not part.is_file:
            part.data.extend(data)
            maximum_size = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
            projected_size = self._field_bytes + len(part.data) + len(part.field_name or "") + 2
            if maximum_size is not None and projected_size > maximum_size:
                raise RequestDataTooBig(
                    "Request body exceeded settings.DATA_UPLOAD_MAX_MEMORY_SIZE."
                )
            return

        chunk: bytes | None = data
        for index, handler in enumerate(self._upload_handlers):
            if chunk is None:
                break
            chunk_length = len(chunk)
            chunk = handler.receive_data_chunk(chunk, part.counters[index])
            part.counters[index] += chunk_length

    def _finish_part(self, part: _Part) -> None:
        if part.ignored:
            return
        if not part.is_file:
            self._field_bytes += len(part.data) + len(part.field_name or "") + 2
            self._post.appendlist(
                part.field_name,
                force_str(bytes(part.data), self._encoding, errors="replace"),
            )
            return

        for index, handler in enumerate(self._upload_handlers):
            uploaded_file = handler.file_complete(part.counters[index])
            if uploaded_file:
                self._files.appendlist(part.field_name, uploaded_file)
                break

    def _interrupt_upload(self) -> None:
        for handler in self._upload_handlers:
            handler.upload_interrupted()

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import (
    RequestDataTooBig,
    TooManyFieldsSent,
    TooManyFilesSent,
)
from django.core.files.uploadhandler import SkipFile, StopFutureHandlers, StopUpload
from django.http import QueryDict
from django.http.multipartparser import (
    MAX_TOTAL_HEADER_SIZE,
    MultiPartParser,
    MultiPartParserError,
)
from django.utils.datastructures import MultiValueDict
from django.utils.encoding import force_str
from django.utils.http import parse_header_parameters

from django_fast_multipart._core import MultipartParser, PartBegin, PartData, PartEnd

HEADER_TOO_LARGE_MESSAGE = "Request max total header size exceeded."
RUST_HEADER_LIMIT_ERRORS = {
    "Header line exceeds maximum size.",
    "Part exceeds maximum header count.",
    "Part exceeds maximum total header size.",
}
# These bounds match Django's boundary suffix and raw header accounting.
MAX_HEADER_COUNT = (MAX_TOTAL_HEADER_SIZE - 2) // 4
MAX_HEADER_LINE_SIZE = MAX_TOTAL_HEADER_SIZE


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
    started: bool = False
    data: bytearray = field(default_factory=bytearray)
    counters: list[int] = field(default_factory=list)


class RustMultiPartParser(MultiPartParser):
    """Django multipart parser backed by the internal Rust streaming parser."""

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
        self._unfinished_upload = False
        # Django's field-count allowance absorbs a terminal RAW segment when
        # a boundary follows the last part, but an EOF-truncated part has none.
        terminal_raw = False

        try:
            parser = MultipartParser(
                self._boundary,
                max_header_count=MAX_HEADER_COUNT,
                max_header_size=MAX_HEADER_LINE_SIZE,
                max_total_header_size=MAX_TOTAL_HEADER_SIZE,
            )
        except (RuntimeError, ValueError) as exc:
            raise self._multipart_error(exc) from exc

        current_part: _Part | None = None
        try:
            while chunk := self._input_data.read(self._chunk_size):
                for event in parser.feed(chunk):
                    if isinstance(event, PartBegin):
                        terminal_raw = False
                        if current_part is not None:
                            raise MultiPartParserError(
                                "Received a new multipart part before the previous part ended."
                            )
                        current_part = self._begin_part(event.headers)
                        if current_part.started:
                            self._unfinished_upload = True
                            try:
                                self._start_file(current_part)
                            except SkipFile:
                                self._close_files()
                                current_part.ignored = True
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
                        terminal_raw = True

            for event in parser.feed_eof():
                if current_part is None or not isinstance(event, PartData):
                    raise MultiPartParserError("Received multipart data before part headers.")
                self._receive_part_data(current_part, event.data)

            try:
                parser.finish()
            except ValueError:
                if current_part is not None and not current_part.is_file:
                    self._finish_part(current_part)
                    current_part = None
        except StopUpload as exc:
            self._close_files()
            if not exc.connection_reset:
                self._drain_input()
        except (RuntimeError, ValueError) as exc:
            self._abort_upload()
            raise self._multipart_error(exc) from exc
        except Exception:
            self._abort_upload()
            raise
        else:
            if terminal_raw:
                self._enforce_field_count()
            if self._unfinished_upload:
                self._interrupt_upload()

        any(handler.upload_complete() for handler in self._upload_handlers)
        self._post._mutable = False
        return self._post, self._files

    def _begin_part(self, raw_headers: list[tuple[bytes, bytes]]) -> _Part:
        headers = self._parse_headers(raw_headers)
        content_disposition = headers.get("content-disposition")
        disposition = content_disposition[1] if content_disposition else {}
        raw_field_name = disposition.get("name")
        raw_file_name = disposition.get("filename")
        is_file = bool(raw_file_name)

        if is_file:
            if raw_field_name is None:
                return _Part(is_file=True, ignored=True)
            self._file_count += 1
            maximum_files = settings.DATA_UPLOAD_MAX_NUMBER_FILES
            if maximum_files is not None and self._file_count > maximum_files:
                raise TooManyFilesSent(
                    "The number of files exceeded settings.DATA_UPLOAD_MAX_NUMBER_FILES."
                )
        else:
            self._field_count += 1
            self._enforce_field_count(allow_missing_terminal_raw=True)
            if raw_field_name is None:
                return _Part(ignored=True)

        field_name = force_str(raw_field_name.strip(), self._encoding, errors="replace")
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
            raise MultiPartParserError("Content-Transfer-Encoding: base64 is not supported.")

        part = _Part(
            field_name=field_name,
            file_name=file_name,
            content_type=content_type.strip(),
            content_length=content_length,
            charset=charset,
            content_type_extra=content_type_extra,
            is_file=is_file,
            ignored=ignored,
            started=is_file and not ignored,
            counters=[0] * len(self._upload_handlers),
        )
        return part

    def _enforce_field_count(self, *, allow_missing_terminal_raw: bool = False) -> None:
        maximum_fields = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
        if maximum_fields is None:
            return
        maximum_fields += int(allow_missing_terminal_raw)
        if self._field_count > maximum_fields:
            raise TooManyFieldsSent(
                "The number of GET/POST parameters exceeded settings.DATA_UPLOAD_MAX_NUMBER_FIELDS."
            )

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
            self._check_field_memory_size(part)
            return

        chunk: bytes | None = data
        try:
            for index, handler in enumerate(self._upload_handlers):
                if chunk is None:
                    break
                chunk_length = len(chunk)
                chunk = handler.receive_data_chunk(chunk, part.counters[index])
                part.counters[index] += chunk_length
        except SkipFile:
            self._close_files()
            part.ignored = True

    def _finish_part(self, part: _Part) -> None:
        if part.ignored:
            return
        if not part.is_file:
            self._check_field_memory_size(part)
            self._field_bytes += len(part.data) + len(part.field_name or "") + 2
            self._post.appendlist(
                part.field_name,
                force_str(bytes(part.data), self._encoding, errors="replace"),
            )
            return

        if not part.field_name:
            return

        for index, handler in enumerate(self._upload_handlers):
            uploaded_file = handler.file_complete(part.counters[index])
            if uploaded_file:
                self._files.appendlist(part.field_name, uploaded_file)
                break
        self._unfinished_upload = False

    def _check_field_memory_size(self, part: _Part) -> None:
        maximum_size = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        projected_size = self._field_bytes + len(part.data) + len(part.field_name or "") + 2
        if maximum_size is not None and projected_size > maximum_size:
            raise RequestDataTooBig("Request body exceeded settings.DATA_UPLOAD_MAX_MEMORY_SIZE.")

    def _abort_upload(self) -> None:
        if self._unfinished_upload:
            with suppress(Exception):
                self._interrupt_upload()
        self._unfinished_upload = False
        with suppress(Exception):
            self._close_files()

    @staticmethod
    def _multipart_error(exc: RuntimeError | ValueError) -> MultiPartParserError:
        message = str(exc)
        if message in RUST_HEADER_LIMIT_ERRORS:
            message = HEADER_TOO_LARGE_MESSAGE
        return MultiPartParserError(message)

    def _interrupt_upload(self) -> None:
        for handler in self._upload_handlers:
            handler.upload_interrupted()

    def _drain_input(self) -> None:
        while self._input_data.read(64 * 1024):
            pass

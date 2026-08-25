from __future__ import annotations

import enum

class MultipartState(enum.IntEnum):
    PREAMBLE = 0
    HEADER = 1
    BODY = 2
    END = 3
    DISCARD = 4

class PartBegin:
    @property
    def headers(self) -> list[tuple[bytes, bytes]]: ...

class PartData:
    @property
    def data(self) -> bytes: ...

class PartEnd: ...

class MultipartParser:
    state: MultipartState

    def __init__(
        self,
        boundary: bytes,
        *,
        max_size: int | None = None,
        max_header_count: int = 8,
        max_header_size: int = 4224,
        max_total_header_size: int | None = None,
    ) -> None: ...
    def feed(self, data: bytes) -> list[PartBegin | PartData | PartEnd]: ...
    def feed_eof(self) -> list[PartData]: ...
    def finish(self) -> None: ...

def parse_options_header(value: str) -> tuple[str, dict[str, str]]: ...

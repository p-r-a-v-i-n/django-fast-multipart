from __future__ import annotations

import base64
import string
from contextlib import nullcontext
from io import BytesIO

from django.core.files.uploadhandler import (
    MemoryFileUploadHandler,
    TemporaryFileUploadHandler,
)
from django.http.multipartparser import MultiPartParser
from django.test import override_settings
from hypothesis import given, settings
from hypothesis import strategies as st

from django_fast_multipart import RustMultiPartParser

BOUNDARY = b"django-fast-multipart-property"
HANDLER_CLASSES = (MemoryFileUploadHandler, TemporaryFileUploadHandler)
NAME_ALPHABET = string.ascii_letters + string.digits + "_-" + "éह"
BOUNDARY_LIKE_DATA = (
    b"--" + BOUNDARY,
    b"\r\n--" + BOUNDARY,
    b"\r\n--" + BOUNDARY + b"X",
    b"\r\n--" + BOUNDARY + b"-",
    b"\r\n--" + BOUNDARY + b"--",
)


class ChunkedInput(BytesIO):
    def __init__(self, body: bytes, chunk_size: int):
        super().__init__(body)
        self.chunk_size = chunk_size

    def read(self, size=-1):
        if size < 0:
            size = self.chunk_size
        return super().read(min(size, self.chunk_size))


def make_body(parts, preamble, epilogue):
    body = bytearray(preamble)
    for headers, data in parts:
        body.extend(b"--" + BOUNDARY + b"\r\n")
        for name, value in headers:
            body.extend(name + b": " + value + b"\r\n")
        body.extend(b"\r\n")
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(b"--" + BOUNDARY + b"--\r\n")
    body.extend(epilogue)
    return bytes(body)


def snapshot(post, files):
    post_values = list(post.lists())
    file_values = []
    for field_name, uploaded_files in files.lists():
        file_values.append(
            (
                field_name,
                [
                    {
                        "type": type(uploaded_file).__name__,
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


def parse_outcome(parser_class, body, chunk_size, limits):
    handlers = [handler_class() for handler_class in HANDLER_CLASSES]
    stream = ChunkedInput(body, chunk_size)
    files = None
    context = override_settings(**limits) if limits else nullcontext()
    try:
        with context:
            post, files = parser_class(
                {
                    "CONTENT_LENGTH": str(len(body)),
                    "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY.decode()}",
                },
                stream,
                handlers,
                "utf-8",
            ).parse()
        return "success", snapshot(post, files)
    except Exception as exc:
        return "error", type(exc).__name__, str(exc)
    finally:
        if files is not None:
            for _, uploaded_files in files.lists():
                for uploaded_file in uploaded_files:
                    uploaded_file.close()
        for handler in handlers:
            if hasattr(handler, "file") and not handler.file.closed:
                handler.file.close()


safe_name = st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=12)
payload = st.one_of(
    st.binary(max_size=256),
    st.sampled_from(BOUNDARY_LIKE_DATA),
    st.tuples(
        st.binary(max_size=64),
        st.sampled_from(BOUNDARY_LIKE_DATA),
        st.binary(max_size=64),
    ).map(b"".join),
)


@st.composite
def multipart_part(draw):
    kind = draw(st.sampled_from(("field", "file", "base64-file")))
    name = draw(safe_name).encode()
    data = draw(payload)
    disposition = b'form-data; name="' + name + b'"'

    if kind == "field":
        return [(b"Content-Disposition", disposition)], data

    file_name = draw(safe_name).encode() + b".bin"
    headers = [
        (b"Content-Disposition", disposition + b'; filename="' + file_name + b'"'),
        (b"Content-Type", b"application/octet-stream"),
    ]
    if kind == "base64-file":
        width = draw(st.integers(min_value=1, max_value=16))
        encoded = base64.b64encode(data)
        data = b" \r\n\t".join(
            encoded[index : index + width] for index in range(0, len(encoded), width)
        )
        headers.append((b"Content-Transfer-Encoding", b"base64"))
    return headers, data


framing_data = st.one_of(
    st.binary(max_size=48),
    st.sampled_from(
        (
            b"preamble\r\n",
            b"inline preamble",
            b"bare-line-feed\n",
            b"epilogue--" + BOUNDARY + b"X",
            b"--" + BOUNDARY + b"--\r\n",
        )
    ),
)


@settings(max_examples=200, deadline=None, derandomize=True, database=None)
@given(
    parts=st.lists(multipart_part(), min_size=0, max_size=4),
    preamble=framing_data,
    epilogue=framing_data,
    chunk_size=st.integers(min_value=1, max_value=128),
    maximum_memory=st.one_of(st.none(), st.integers(min_value=0, max_value=768)),
    maximum_fields=st.one_of(st.none(), st.integers(min_value=0, max_value=5)),
    maximum_files=st.one_of(st.none(), st.integers(min_value=0, max_value=5)),
)
def test_generated_multipart_requests_match_django(
    parts,
    preamble,
    epilogue,
    chunk_size,
    maximum_memory,
    maximum_fields,
    maximum_files,
):
    body = make_body(parts, preamble, epilogue)
    limits = {
        "DATA_UPLOAD_MAX_MEMORY_SIZE": maximum_memory,
        "DATA_UPLOAD_MAX_NUMBER_FIELDS": maximum_fields,
        "DATA_UPLOAD_MAX_NUMBER_FILES": maximum_files,
    }

    expected = parse_outcome(MultiPartParser, body, chunk_size, limits)
    actual = parse_outcome(RustMultiPartParser, body, chunk_size, limits)

    assert actual == expected

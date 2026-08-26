from importlib.metadata import version
from io import BytesIO

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATA_UPLOAD_MAX_MEMORY_SIZE=1024 * 1024,
        DATA_UPLOAD_MAX_NUMBER_FIELDS=10,
        DATA_UPLOAD_MAX_NUMBER_FILES=10,
        DEFAULT_CHARSET="utf-8",
        FILE_UPLOAD_MAX_MEMORY_SIZE=1024 * 1024,
        SECRET_KEY="django-fast-multipart-wheel-smoke",
    )
django.setup()

from django.core.files.uploadhandler import MemoryFileUploadHandler  # noqa: E402

from django_fast_multipart import RustMultiPartParser  # noqa: E402

BOUNDARY = b"django-fast-multipart-wheel"
BODY = b"".join(
    (
        b"--" + BOUNDARY + b"\r\n",
        b'Content-Disposition: form-data; name="field"\r\n\r\n',
        b"value\r\n",
        b"--" + BOUNDARY + b"\r\n",
        b'Content-Disposition: form-data; name="upload"; filename="sample.bin"\r\n',
        b"Content-Type: application/octet-stream\r\n\r\n",
        b"binary-data\x00\xff\r\n",
        b"--" + BOUNDARY + b"--\r\n",
    )
)


def main() -> None:
    metadata = {
        "CONTENT_LENGTH": str(len(BODY)),
        "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY.decode()}",
    }
    post, files = RustMultiPartParser(
        metadata,
        BytesIO(BODY),
        [MemoryFileUploadHandler()],
        "utf-8",
    ).parse()

    uploaded_file = files["upload"]
    try:
        if post.getlist("field") != ["value"]:
            raise RuntimeError(f"Unexpected form fields: {post!r}")
        if uploaded_file.name != "sample.bin":
            raise RuntimeError(f"Unexpected upload name: {uploaded_file.name!r}")
        if uploaded_file.read() != b"binary-data\x00\xff":
            raise RuntimeError("Unexpected uploaded file content.")
    finally:
        uploaded_file.close()

    print(f"Validated django-fast-multipart {version('django-fast-multipart')} wheel.")


if __name__ == "__main__":
    main()

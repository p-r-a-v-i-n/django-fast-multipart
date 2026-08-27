# django-fast-multipart

[![PyPI](https://img.shields.io/pypi/v/django-fast-multipart.svg)](https://pypi.org/project/django-fast-multipart/)
[![Python](https://img.shields.io/pypi/pyversions/django-fast-multipart.svg)](https://pypi.org/project/django-fast-multipart/)
[![Documentation Status](https://readthedocs.org/projects/django-fast-multipart/badge/?version=latest)](https://django-fast-multipart.readthedocs.io/en/latest/)

`django-fast-multipart` is a Rust-backed multipart upload parser for Django.
It uses Django's parser extension point while keeping the existing upload
handlers, request limits, `request.POST`, and `request.FILES` interfaces.

The project currently supports CPython 3.12 or later and Django 6.1.

## Installation

```console
python -m pip install django-fast-multipart
```

Prebuilt wheels are available for Linux x86-64 and ARM64, macOS Intel and
Apple Silicon, and Windows x86-64. Other platforms can build from the source
distribution with a Rust toolchain.

## Quick start

For application-wide use, add the middleware before CSRF or anything else that
reads `request.POST` or `request.FILES`:

```python
MIDDLEWARE = [
    "django_fast_multipart.middleware.FastMultipartMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    # Other middleware...
]
```

Your views continue to use Django's normal request API:

```python
def upload(request):
    description = request.POST.get("description", "")
    uploaded_file = request.FILES["file"]
    # Process the uploaded file.
```

To select it only for one view:

```python
from django_fast_multipart import RustMultiPartParser


def upload(request):
    request.multipart_parser_class = RustMultiPartParser
    uploaded_file = request.FILES["file"]
    # Process the uploaded file.
```

The parser must be selected before request data is read. Both synchronous WSGI
and asynchronous ASGI request stacks are supported, and non-multipart requests
remain unchanged.

## Documentation

Read the complete guide at
[django-fast-multipart.readthedocs.io](https://django-fast-multipart.readthedocs.io/en/latest/).
It covers installation, middleware ordering, per-view setup, upload handlers,
compatibility, performance, troubleshooting, and development.

## Performance

Reference microbenchmarks show the clearest reduction in parser overhead for
field-heavy forms and in-memory uploads. Temporary-file uploads benefit less
because file I/O and upload-handler work dominate. These results are
parser-level measurements, not end-to-end application guarantees; see the
[benchmark methodology](benchmarks/README.md) for details.

## Project status

The project is currently beta. Its behavior is extensively tested against
Django's `MultiPartParser`, including built-in upload handlers, upload limits,
WSGI and ASGI integration, and cleanup after exceptions. Production feedback
for custom upload handlers is welcome.

## Development

```console
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
cargo fmt --manifest-path rust/Cargo.toml --check
cargo clippy --manifest-path rust/Cargo.toml --locked --all-targets --all-features -- -D warnings
uv build
```

See the [development documentation](https://django-fast-multipart.readthedocs.io/en/latest/development.html)
and [release guide](RELEASING.md) for more details.

## License

The project is licensed under MIT. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for the native parser's upstream attribution and licensing details.

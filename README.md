# django-fast-multipart

`django-fast-multipart` provides a Rust-backed implementation of Django's
multipart upload parser interface. It uses the
`HttpRequest.multipart_parser_class` extension point introduced in Django 6.1
and integrates with Django's existing upload-handler contract.

The project is currently pre-alpha. Its behavior is tested against Django's
`MultiPartParser`, but known compatibility differences remain and should be
reviewed before production use.

## Compatibility

The differential test suite sends identical request bodies through Django's
parser and `RustMultiPartParser`, then compares the resulting `POST` and
`FILES` values, exceptions, stream consumption, and upload-handler callbacks.
A deterministic property-based suite also generates multipart structures,
binary and boundary-like payloads, input chunk sizes, and Django upload limits.

The following behavior is covered:

- normal and repeated form fields;
- incremental request reads, including one-byte chunks;
- in-memory and temporary-file upload handlers;
- `StopFutureHandlers`, `SkipFile`, and both `StopUpload` modes;
- interrupted-upload signaling and temporary-file cleanup;
- field-memory, field-count, and file-count limits;
- Django's 1,024-byte aggregate part-header limit;
- truncated fields and interrupted files at end of input;
- raw boundary tokens embedded in part data;
- Django boundary values through 201 bytes;
- Django-compatible handling of malformed part-header lines;
- base64 transfer encoding for form fields and file uploads;
- preambles, epilogues, raw inter-boundary segments, and parts following a
  closing-boundary marker;
- Django's parser constructor and return-value contract.

Known limitations:

- custom upload-handler edge cases beyond those listed above are not yet fully
  covered;

Known differences are represented by strict expected failures in the test
suite, so newly achieved compatibility cannot pass unnoticed.

## Usage

`django-fast-multipart` requires Python 3.12 or later and Django 6.1.

### Middleware

For application-wide use, select the parser in middleware:

```python
from django_fast_multipart import RustMultiPartParser


class FastMultipartMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.content_type == "multipart/form-data":
            request.multipart_parser_class = RustMultiPartParser
        return self.get_response(request)
```

Add this middleware before `django.middleware.csrf.CsrfViewMiddleware` and any
other middleware that accesses `request.POST` or `request.FILES`. Django uses
the parser class that is configured when either collection is first read.

### Per-request selection

The parser can be selected in a view when no earlier middleware has accessed
the request data:

```python
from django_fast_multipart import RustMultiPartParser


def upload(request):
    request.multipart_parser_class = RustMultiPartParser
    uploaded_file = request.FILES["file"]
    # Process the uploaded file.
```

Existing upload-handler configuration remains in effect. The parser uses
Django's configured upload handlers and enforces its field-memory, field-count,
and file-count settings.

## Native core

The native parser is included in this repository and built as the private
`django_fast_multipart._core` extension. It is derived from
[`rust-multipart`](https://github.com/Kludex/rust-multipart). See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the source revision and
licensing details.

Source distributions include the Rust sources and lockfile; installation does
not fetch parser code from a Git repository.

## Development

The locked development environment uses the released Django 6.1 series:

```console
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
cargo fmt --manifest-path rust/Cargo.toml --check
cargo clippy --manifest-path rust/Cargo.toml --locked --all-targets --all-features -- -D warnings
uv build
```

### Native parser fuzzing

The native parser has a libFuzzer target that compares contiguous and
incremental parsing. It requires nightly Rust and `cargo-fuzz`:

```console
cargo +nightly fuzz run --fuzz-dir fuzz multipart_parser -- \
    -dict=fuzz/dictionaries/multipart_parser.dict
```

### Testing against Django main

CI runs an advisory compatibility suite against Django's main branch. To run
the same suite with a local Django checkout:

```console
PYTHONPATH=/path/to/django uv run --no-sync pytest
```

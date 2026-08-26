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
- Django's parser constructor and return-value contract.

Known limitations:

- custom upload-handler edge cases beyond those listed above are not yet fully
  covered;
- preamble, epilogue, and post-closing-boundary behavior is not yet fully
  covered.

Known differences are represented by strict expected failures in the test
suite, so newly achieved compatibility cannot pass unnoticed.

## Usage

Set the parser class before Django accesses `request.POST` or `request.FILES`:

```python
from django_fast_multipart import RustMultiPartParser


def upload(request):
    request.multipart_parser_class = RustMultiPartParser
    uploaded_file = request.FILES["file"]
    # Process the uploaded file.
```

The parser can also be selected in middleware when it should apply to multiple
views. The assignment must occur before another middleware or view reads the
request body.

## Native core

The native parser is included in this repository and built as the private
`django_fast_multipart._core` extension. It is derived from
[`rust-multipart`](https://github.com/Kludex/rust-multipart) commit
`2fc31ceeec0b980fcfe37b9ee2ed0fb3b2b7f437`. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for provenance and licensing
details.

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

### Testing against Django main

CI runs an advisory compatibility suite against Django's main branch. To run
the same suite with a local Django checkout:

```console
PYTHONPATH=/path/to/django uv run --no-sync pytest
```

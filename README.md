# django-fast-multipart

`django-fast-multipart` is an experimental adapter between Django's multipart
upload interface and the Rust-powered
[`rust-multipart`](https://github.com/Kludex/rust-multipart) sans-I/O parser.

The first goal is compatibility evidence, not a production release. Each test
feeds the same request body to Django's `MultiPartParser` and
`RustMultiPartParser`, then compares the resulting `POST` and `FILES` values.

## Current spike scope

- normal and repeated text fields;
- incremental request reads, including one-byte chunks;
- `MemoryFileUploadHandler`;
- `TemporaryFileUploadHandler`;
- `StopFutureHandlers`, `SkipFile`, and both `StopUpload` modes;
- interrupted-upload signaling and temporary-file cleanup;
- field-memory, field-count, and file-count upload limits with Django's
  exception types and messages;
- exact raw aggregate-header enforcement against Django's 1,024-byte limit;
- EOF body-buffer flushing for truncated fields and interrupted files;
- Django's existing parser constructor and return-value contract.

Not yet supported or compatibility-tested:

- `Content-Transfer-Encoding: base64`;
- boundaries longer than the Rust core's RFC 2046 limit of 70 bytes;
- Django's tolerant malformed-header behavior;
- remaining custom upload-handler callback and short-circuit edge cases;
- preamble, epilogue, and post-closing-boundary compatibility.

The compatibility suite records the remaining differences as strict expected
failures. Django accepts boundary values through 201 bytes, while the Rust
core enforces RFC 2046's 70-byte maximum. Django also tolerates malformed
header lines that the Rust core rejects. EOF within a boundary delimiter or
its closing/line-ending suffix can also classify the retained bytes
differently, including for field-count accounting.

Django 6.1 also terminates a part when file data contains a CRLF followed by a
boundary prefix and an extra non-delimiter byte (for example,
`--boundaryX`), while the Rust core preserves that sequence as file data.
These differences need explicit compatibility and security decisions before
production use.

The audited Rust core is included in this repository and built as the private
`django_fast_multipart._core` extension. It is derived from `rust-multipart`
commit `2fc31ceeec0b980fcfe37b9ee2ed0fb3b2b7f437`; provenance and licensing are
recorded in `THIRD_PARTY_NOTICES.md`. Installation no longer depends on a Git
checkout or on changes being accepted upstream.

## Development

The reproducible baseline uses the released Django 6.1 series:

```console
uv sync
uv run pytest
uv run ruff check .
cargo fmt --manifest-path rust/Cargo.toml --check
cargo clippy --manifest-path rust/Cargo.toml --locked --all-targets --all-features -- -D warnings
```

To run the same differential suite against the sibling Django development
checkout without changing the lockfile:

```console
PYTHONPATH=../django uv run --no-sync pytest
```

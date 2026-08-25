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
- multipart per-line and header-count bounds, plus lower-bound aggregate
  checks against Django's 1,024-byte limit;
- Django's existing parser constructor and return-value contract.

Not yet supported or compatibility-tested:

- `Content-Transfer-Encoding: base64`;
- boundaries longer than the Rust core's RFC 2046 limit of 70 bytes;
- exact aggregate-header accounting when the Rust core trims raw whitespace;
- Django's tolerant malformed-header and truncated-field behavior;
- remaining custom upload-handler callback and short-circuit edge cases;
- preamble, epilogue, and post-closing-boundary compatibility.

The compatibility suite records the remaining differences as strict expected
failures. Django accepts boundary values through 201 bytes, while the Rust
core enforces RFC 2046's 70-byte maximum. Django also tolerates malformed
header lines and returns partial text fields at EOF; the Rust core rejects
those inputs. Raw header whitespace cannot yet be counted exactly because it
is trimmed before the adapter receives header events.

Django 6.1 also terminates a part when file data contains a CRLF followed by a
boundary prefix and an extra non-delimiter byte (for example,
`--boundaryX`), while the Rust core preserves that sequence as file data.
These differences need explicit compatibility and security decisions before
production use.

In particular, the multipart header limit is not yet security-equivalent to
Django's. The Rust core trims whitespace before emitting headers, so the
adapter cannot recover the exact raw aggregate size. Individually bounded
headers can therefore exceed Django's 1,024-byte total. Exact enforcement
requires the Rust parser to accept a total-header limit or expose the raw byte
count.

The Rust dependency is pinned to commit
`0bc3df5a55a139d133dc6e2e73f112a08a4e43f8` so results remain reproducible
while the upstream project is under active development.

## Development

The reproducible baseline uses the released Django 6.1 series:

```console
uv sync
uv run pytest
uv run ruff check .
```

To run the same differential suite against the sibling Django development
checkout without changing the lockfile:

```console
PYTHONPATH=../django uv run --no-sync pytest
```

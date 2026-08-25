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
- Django's existing parser constructor and return-value contract.

Not yet supported or compatibility-tested:

- `Content-Transfer-Encoding: base64`;
- boundaries longer than the Rust core's RFC 2046 limit of 70 bytes;
- Django's complete malformed-input behavior;
- `SkipFile`, `StopUpload`, and every custom upload-handler lifecycle edge case;
- all Django upload limits and exception equivalence.

The compatibility suite currently records one strict expected difference:
Django 6.1 terminates a part when file data contains a CRLF followed by a
boundary prefix and an extra non-delimiter byte (for example,
`--boundaryX`), while the Rust core preserves that sequence as file data.
This needs an explicit compatibility/security decision before production use.

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

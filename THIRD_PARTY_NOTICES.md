# Third-party notices

## rust-multipart

The native multipart parser in `rust/` is derived from
[`Kludex/rust-multipart`](https://github.com/Kludex/rust-multipart), including
the adapter-specific work recorded at commit
`2fc31ceeec0b980fcfe37b9ee2ed0fb3b2b7f437` in the project fork.

The original project identifies Marcelo Trylesinski as its author and declares
the code under the MIT License. The MIT terms distributed in this project's
`LICENSE` file apply to these derived portions. Local changes include the
internal module name, Python compatibility floor, Django header-limit support,
and EOF body-buffer handling.

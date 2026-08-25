# Third-party notices

## rust-multipart

The native multipart parser under `rust/` is derived from
[`Kludex/rust-multipart`](https://github.com/Kludex/rust-multipart), including
the Django integration work recorded at commit
`2fc31ceeec0b980fcfe37b9ee2ed0fb3b2b7f437` in the project fork.

The original project identifies Marcelo Trylesinski as its author and declares
the code under the MIT License. The MIT terms distributed in this project's
`LICENSE` file apply to these derived portions. Subsequent local changes include
the private module layout, Python compatibility floor, Django header-limit and
boundary-token behavior, and end-of-input handling.

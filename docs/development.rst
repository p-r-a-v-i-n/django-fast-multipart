Development
===========

Clone the repository and create the locked development environment:

.. code-block:: console

   git clone https://github.com/p-r-a-v-i-n/django-fast-multipart.git
   cd django-fast-multipart
   uv sync

Run the main validation suite:

.. code-block:: console

   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   cargo fmt --manifest-path rust/Cargo.toml --check
   cargo clippy --manifest-path rust/Cargo.toml --locked --all-targets --all-features -- -D warnings
   uv build

Build these documentation pages locally:

.. code-block:: console

   uvx --from Sphinx==9.1.0 sphinx-build -n -W --keep-going -b html docs docs/_build/html

The generated site starts at ``docs/_build/html/index.html``.

Specialized testing
-------------------

The repository also contains:

* deterministic property-based compatibility tests;
* a libFuzzer target under ``fuzz/``;
* timing and peak-memory benchmarks under ``benchmarks/``;
* an advisory test job against Django's main branch;
* installed-wheel smoke tests on Python 3.12 and 3.14.

Run the native parser's libFuzzer target with nightly Rust and ``cargo-fuzz``:

.. code-block:: console

   ASAN_OPTIONS=detect_leaks=0 cargo +nightly fuzz run --fuzz-dir fuzz multipart_parser -- -dict=fuzz/dictionaries/multipart_parser.dict

Run the compatibility suite against a local checkout of Django's main branch:

.. code-block:: console

   PYTHONPATH=/path/to/django uv run --no-sync pytest

See `benchmarks/README.md
<https://github.com/p-r-a-v-i-n/django-fast-multipart/blob/main/benchmarks/README.md>`_
for benchmark commands and interpretation. See `RELEASING.md
<https://github.com/p-r-a-v-i-n/django-fast-multipart/blob/main/RELEASING.md>`_
for the release process.

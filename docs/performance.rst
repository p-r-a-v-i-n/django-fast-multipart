Performance
===========

The Rust core is intended to reduce multipart parsing overhead without
replacing Django's upload-handler system. The benefit depends on where an
application spends its upload time.

The repository's reference microbenchmarks showed the clearest improvement for
field-heavy forms and in-memory uploads. Temporary-file uploads improved much
less because filesystem writes and Django's upload-handler work dominated the
request.

Representative CPU-pinned results from the reference machine were:

.. list-table::
   :header-rows: 1

   * - Case
     - Django
     - Rust
     - Paired speedup
   * - 100 fields, 8 KiB chunks
     - 5.15 ms
     - 2.49 ms
     - 2.07x
   * - 1 MiB in-memory file, 64 KiB chunks
     - 3.28 ms
     - 0.88 ms
     - 3.77x
   * - 8 MiB temporary file, 64 KiB chunks
     - 14.55 ms
     - 13.84 ms
     - 1.07x

.. warning::

   These are parser microbenchmarks from one machine, not end-to-end request
   latency or production throughput guarantees. Hardware, upload handlers,
   storage, request shape, and application work can materially change the
   result.

See the `complete benchmark methodology and results
<https://github.com/p-r-a-v-i-n/django-fast-multipart/blob/main/benchmarks/README.md>`_
for environment details, memory measurements, profiling observations, and the
commands needed to repeat the tests.

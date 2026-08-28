Performance
===========

The Rust core is intended to reduce multipart parsing overhead without
replacing Django's upload-handler system. The benefit depends on where an
application spends its upload time.

Quick results
-------------

The table below shows the WSGI request path from a GitHub Actions run on 28
August 2026. It used CPython 3.14.7 and Django 6.1.

.. list-table::
   :header-rows: 1

   * - Request
     - Django
     - Rust
     - Speedup
   * - 100 fields
     - 2.42 ms
     - 1.15 ms
     - 2.10x
   * - Mixed form with a 1 MiB file
     - 1.54 ms
     - 1.07 ms
     - 1.45x
   * - 8 MiB temporary file
     - 7.89 ms
     - 6.76 ms
     - 1.17x

The main point is simple: forms with many fields get the biggest benefit.
Mixed forms also improve. Large temporary-file uploads improve less because
filesystem writes and Django's upload-handler work take a larger part of the
request.

ASGI request/view measurements showed the same pattern: 2.19x for 100 fields,
1.54x for the mixed form, and 1.13x for the temporary-file upload. This ASGI
test does not include an ASGI server, middleware, routing, or network I/O.

Concurrency
-----------

The threaded WSGI benchmark used the mixed 1 MiB form:

.. list-table::
   :header-rows: 1

   * - Worker threads
     - Django requests/s
     - Rust requests/s
     - Speedup
   * - 1
     - 639
     - 1,180
     - 1.85x
   * - 2
     - 767
     - 1,088
     - 1.42x
   * - 4
     - 673
     - 975
     - 1.45x

This is an in-process WSGI test without a network server. It helps compare the
two parsers under the same conditions, but it is not a production throughput
number.

Memory
------

Peak memory was broadly comparable. Rust used less incremental peak memory in
8 of the 14 paired cases and more in 6. Most differences were small. For
temporary-file uploads, memory stayed almost the same from 8 MiB to 32 MiB,
which confirms that both parsers stream large files instead of keeping the
whole upload in memory.

How to read these results
-------------------------

.. warning::

   These numbers are a reference, not a performance guarantee. GitHub's shared
   runner introduced some noise, especially for temporary-file cases. A real
   application's hardware, storage, middleware, upload handlers, network, and
   view work can change the result.

The request benchmarks validate the uploaded fields and files after parsing.
They do not include TLS, a database, a production WSGI or ASGI server, or
application work beyond that validation. Compare Django and Rust within the
same request path; do not use the table to compare WSGI with ASGI.

See the `complete benchmark methodology and results
<https://github.com/p-r-a-v-i-n/django-fast-multipart/blob/main/benchmarks/README.md>`_
for the parser-only results, memory details, limitations, and commands needed
to repeat the tests.

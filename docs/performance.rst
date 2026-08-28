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
     - 1.55 ms
     - 0.823 ms
     - 1.89x
   * - Mixed form with a 1 MiB file
     - 1.05 ms
     - 0.679 ms
     - 1.55x
   * - 8 MiB temporary file
     - 5.97 ms
     - 4.78 ms
     - 1.25x

The main point is simple: forms with many fields get the biggest benefit.
Mixed forms also improve. Large temporary-file uploads improve less because
filesystem writes and Django's upload-handler work take a larger part of the
request.

ASGI request/view measurements showed the same pattern: 1.98x for 100 fields,
1.60x for the mixed form, and 1.27x for the temporary-file upload. This ASGI
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
     - 505
     - 899
     - 1.78x
   * - 2
     - 568
     - 795
     - 1.40x
   * - 4
     - 552
     - 848
     - 1.54x

This is an in-process WSGI test without a network server. It helps compare the
two parsers under the same conditions, but it is not a production throughput
number.

Memory
------

Peak memory was broadly comparable. Rust used less incremental peak memory in
6 of the 14 paired cases and more in 8. Most differences were small. For
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

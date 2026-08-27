Troubleshooting
===============

The Django parser is still being used
-------------------------------------

Check that ``FastMultipartMiddleware`` appears before CSRF and any middleware
that reads ``request.POST`` or ``request.FILES``. For per-view selection, the
assignment must be the first operation that can cause request parsing.

Also confirm that the request really uses ``multipart/form-data``. The
middleware intentionally ignores JSON and other content types.

The per-view assignment has no effect
-------------------------------------

Django caches parsed form and file data. Once another middleware, decorator,
or earlier line of code accesses ``POST`` or ``FILES``, changing
``multipart_parser_class`` is too late. Use application-wide middleware when
you cannot control earlier access.

Installation tries to compile Rust
----------------------------------

This normally means pip could not find a compatible published wheel. Confirm
that you use CPython 3.12 or later on one of the supported platforms, and
upgrade pip before retrying:

.. code-block:: console

   python -m pip install --upgrade pip
   python -m pip install django-fast-multipart

Unsupported platforms fall back to the source distribution and require Rust.

An upload limit raises an exception
-----------------------------------

The parser intentionally applies Django's configured field-memory, field-count,
file-count, and header limits. Review the corresponding Django upload settings
rather than bypassing the exception in the parser.

A custom upload handler behaves differently
--------------------------------------------

Open an issue with a minimal handler, multipart request, expected Django
behavior, and the observed result. If possible, run the same body through
Django's ``MultiPartParser`` so the lifecycle difference is clear.

Report issues at
https://github.com/p-r-a-v-i-n/django-fast-multipart/issues.

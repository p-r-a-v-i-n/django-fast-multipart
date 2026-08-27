Public API
==========

The supported public API is exported from ``django_fast_multipart``.

FastMultipartMiddleware
-----------------------

.. py:class:: django_fast_multipart.FastMultipartMiddleware(get_response)

   Django middleware that selects
   :py:class:`~django_fast_multipart.RustMultiPartParser` for
   ``multipart/form-data`` requests.

   It is both synchronous and asynchronous capable. Non-multipart requests are
   passed to the next middleware without changing their parser class.

RustMultiPartParser
-------------------

.. py:class:: django_fast_multipart.RustMultiPartParser(META, input_data, upload_handlers, encoding=None)

   A subclass of Django's ``MultiPartParser`` backed by the private Rust
   streaming parser.

   The constructor and ``parse()`` result follow Django's parser contract. In
   normal applications, select this class through
   :py:class:`~django_fast_multipart.FastMultipartMiddleware` or assign it to
   ``request.multipart_parser_class`` before reading the request data.

Private native module
---------------------

``django_fast_multipart._core`` is an implementation detail. Its classes and
event objects may change without following the public compatibility policy.
Application code should import only from ``django_fast_multipart``.

Configuration
=============

Middleware ordering
-------------------

Parser selection must happen before Django parses the request body. Keep the
middleware above:

* ``django.middleware.csrf.CsrfViewMiddleware``;
* authentication or audit middleware that reads form fields;
* project middleware that reads ``request.POST`` or ``request.FILES``.

Middleware that never reads form data may be placed on either side.

Upload handlers
---------------

The parser uses Django's configured upload handlers. Existing settings such as
the following remain effective:

.. code-block:: python

   FILE_UPLOAD_HANDLERS = [
       "django.core.files.uploadhandler.MemoryFileUploadHandler",
       "django.core.files.uploadhandler.TemporaryFileUploadHandler",
   ]

   FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440

Memory uploads still produce ``InMemoryUploadedFile`` objects, and larger
uploads handled on disk still produce ``TemporaryUploadedFile`` objects.
Handlers may also be assigned to ``request.upload_handlers`` before the request
data is read.

Django upload limits
--------------------

The parser enforces Django's multipart-related settings, including:

* ``DATA_UPLOAD_MAX_MEMORY_SIZE`` for form-field data;
* ``DATA_UPLOAD_MAX_NUMBER_FIELDS``;
* ``DATA_UPLOAD_MAX_NUMBER_FILES``;
* Django's aggregate part-header limit.

The configured upload handlers remain responsible for their own file storage
and limits.

Request selection
-----------------

``FastMultipartMiddleware`` selects the Rust-backed parser only when Django
identifies the content type as ``multipart/form-data``. JSON, URL-encoded, and
other request bodies continue to use Django's normal request handling.

There are no package-specific Django settings. Remove the middleware, or stop
assigning ``request.multipart_parser_class`` in a view, to return to Django's
default parser.

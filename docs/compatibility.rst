Compatibility and behavior
==========================

Supported versions and platforms
--------------------------------

.. list-table::
   :header-rows: 1

   * - Component
     - Supported range
   * - Python
     - CPython 3.12 and later
   * - Django
     - Django 6.1
   * - Linux wheels
     - manylinux x86-64 and ARM64
   * - macOS wheels
     - Intel and Apple Silicon
   * - Windows wheels
     - x86-64

Other platforms may install from the source distribution when a compatible
Rust build environment is available.

Tested Django behavior
----------------------

The differential suite sends identical multipart bodies through Django's
``MultiPartParser`` and ``RustMultiPartParser``. It compares ``POST`` and
``FILES`` values, raised exceptions, stream consumption, and upload-handler
callbacks.

Coverage includes:

* regular and repeated form fields;
* mixed form fields and uploaded files;
* incremental reads, including one-byte chunks;
* memory and temporary-file upload handlers;
* ``StopFutureHandlers``, ``SkipFile``, and both ``StopUpload`` modes;
* interrupted uploads and temporary-file cleanup;
* field-memory, field-count, and file-count limits;
* Django's aggregate part-header limit;
* truncated fields and interrupted files;
* raw boundary tokens inside part data;
* malformed part headers handled the same way as Django;
* base64 transfer encoding for fields and files;
* preambles, epilogues, and raw inter-boundary segments;
* WSGI and ASGI request paths;
* cleanup after upload-handler or view exceptions.

Known limitations
-----------------

The package is beta. Built-in upload handlers and several lifecycle controls
are covered, but the ecosystem contains custom upload handlers with behavior
that cannot all be anticipated. Test custom handlers against realistic uploads
before enabling the parser broadly, and report compatibility differences with
a minimal reproduction.

Support for a new Django feature release is added only after its parser
behavior has been compared. This is why the package currently caps Django at
the tested 6.1 series.

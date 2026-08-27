How it works
============

``django-fast-multipart`` changes parser selection, not Django's public upload
API.

For each multipart request:

1. ``FastMultipartMiddleware`` assigns ``RustMultiPartParser`` to
   ``request.multipart_parser_class``.
2. Django constructs that parser when code first reads ``request.POST`` or
   ``request.FILES``.
3. The private Rust core incrementally recognizes boundaries, headers, and part
   data from the request stream.
4. The Python adapter applies Django's field rules and passes file chunks
   through the configured Django upload handlers.
5. The parser returns the usual ``QueryDict`` and ``MultiValueDict`` used by
   ``request.POST`` and ``request.FILES``.

The full request body is not moved into a separate package-specific upload
store. Memory-versus-temporary-file behavior remains the responsibility of
Django's upload handlers.

Native core and attribution
---------------------------

The native parser is built as the private ``django_fast_multipart._core``
extension. It is derived from `rust-multipart
<https://github.com/Kludex/rust-multipart>`_. The repository contains the Rust
source code and lockfile used for the build.

See `THIRD_PARTY_NOTICES.md
<https://github.com/p-r-a-v-i-n/django-fast-multipart/blob/main/THIRD_PARTY_NOTICES.md>`_
for the upstream revision and licensing details. The project itself is
distributed under the MIT license.

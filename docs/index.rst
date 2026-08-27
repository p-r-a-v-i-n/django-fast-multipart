django-fast-multipart
=====================

``django-fast-multipart`` is a Rust-backed alternative to Django's multipart
upload parser. It uses the public ``HttpRequest.multipart_parser_class``
extension point added in Django 6.1 while keeping Django's existing upload
handlers, request limits, ``request.POST``, and ``request.FILES`` interfaces.

It can be enabled for the whole application with middleware or selected only
for individual views. Non-multipart requests are left unchanged.

.. note::

   The project is currently beta. Its behavior is extensively compared with
   Django's parser, but production feedback for custom upload handlers is
   welcome.

Start here
----------

Install the package from PyPI:

.. code-block:: console

   python -m pip install django-fast-multipart

Then place its middleware before CSRF middleware and anything else that reads
``request.POST`` or ``request.FILES``:

.. code-block:: python

   MIDDLEWARE = [
       "django_fast_multipart.middleware.FastMultipartMiddleware",
       "django.middleware.csrf.CsrfViewMiddleware",
       # Other middleware...
   ]

Continue with the :doc:`quickstart` for a complete upload example.

Documentation
-------------

.. toctree::
   :maxdepth: 2

   installation
   quickstart
   configuration
   architecture
   compatibility
   performance
   api
   troubleshooting
   development

Project links
-------------

* `PyPI <https://pypi.org/project/django-fast-multipart/>`_
* `GitHub <https://github.com/p-r-a-v-i-n/django-fast-multipart>`_
* `Issue tracker <https://github.com/p-r-a-v-i-n/django-fast-multipart/issues>`_

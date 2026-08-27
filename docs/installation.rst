Installation
============

Requirements
------------

``django-fast-multipart`` requires:

* CPython 3.12 or later;
* Django 6.1;
* a supported wheel platform, or a Rust toolchain when building from source.

The package currently declares ``Django>=6.1,<6.2`` so that compatibility with
future Django releases can be tested before they are enabled.

Install from PyPI
-----------------

Install the latest release with pip:

.. code-block:: console

   python -m pip install django-fast-multipart

Or add it to a project managed by uv:

.. code-block:: console

   uv add django-fast-multipart

Confirm that the public parser and middleware can be imported:

.. code-block:: console

   python -c "from django_fast_multipart import FastMultipartMiddleware, RustMultiPartParser; print(RustMultiPartParser.__name__)"

Prebuilt wheels
---------------

Stable-ABI wheels are published for:

* manylinux x86-64;
* manylinux ARM64;
* macOS Intel;
* macOS Apple Silicon;
* Windows x86-64.

One stable-ABI wheel per platform supports all compatible CPython versions
starting with Python 3.12. Installing one of these wheels does not require Rust.

Building from source
--------------------

PyPI also provides a source distribution for other platforms. Building it
requires a Rust toolchain and a compatible native build environment. The
source archive contains the Rust sources and lockfile; it does not fetch the
parser implementation from a Git repository during installation.

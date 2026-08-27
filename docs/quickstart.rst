Quick start
===========

Application-wide setup
----------------------

Add ``FastMultipartMiddleware`` to ``MIDDLEWARE`` in the Django settings:

.. code-block:: python

   MIDDLEWARE = [
       "django.middleware.security.SecurityMiddleware",
       "django.contrib.sessions.middleware.SessionMiddleware",
       "django.middleware.common.CommonMiddleware",
       "django_fast_multipart.middleware.FastMultipartMiddleware",
       "django.middleware.csrf.CsrfViewMiddleware",
       "django.contrib.auth.middleware.AuthenticationMiddleware",
       # Other middleware...
   ]

The important rule is that ``FastMultipartMiddleware`` must run before CSRF
middleware or any custom middleware that reads ``request.POST`` or
``request.FILES``. Django chooses the parser when either collection is first
read.

A normal Django upload view needs no parser-specific code:

.. code-block:: python

   from django.http import JsonResponse
   from django.views.decorators.http import require_POST


   @require_POST
   def upload(request):
       uploaded_file = request.FILES["file"]
       return JsonResponse(
           {
               "name": uploaded_file.name,
               "size": uploaded_file.size,
               "description": request.POST.get("description", ""),
           }
       )

The browser or client must send the request as ``multipart/form-data``. For an
HTML form, remember ``enctype``:

.. code-block:: html

   <form method="post" enctype="multipart/form-data">
     {% csrf_token %}
     <input name="description">
     <input type="file" name="file" required>
     <button type="submit">Upload</button>
   </form>

Per-view setup
--------------

To use the parser only for selected views, do not install the middleware.
Assign the parser before anything reads the request data:

.. code-block:: python

   from django.http import JsonResponse
   from django_fast_multipart import RustMultiPartParser


   def upload(request):
       request.multipart_parser_class = RustMultiPartParser
       uploaded_file = request.FILES["file"]
       return JsonResponse({"name": uploaded_file.name})

Per-view selection cannot replace a parser after middleware, a decorator, or
view code has already accessed ``request.POST`` or ``request.FILES``.

WSGI and ASGI
-------------

The middleware supports synchronous WSGI applications and asynchronous ASGI
request stacks. No separate ASGI configuration is required.

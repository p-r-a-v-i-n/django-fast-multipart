import django
from django.conf import settings


def pytest_configure():
    if not settings.configured:
        settings.configure(
            DATA_UPLOAD_MAX_MEMORY_SIZE=2_621_440,
            DATA_UPLOAD_MAX_NUMBER_FIELDS=1_000,
            DATA_UPLOAD_MAX_NUMBER_FILES=100,
            DEFAULT_CHARSET="utf-8",
            FILE_UPLOAD_MAX_MEMORY_SIZE=2_621_440,
            SECRET_KEY="django-fast-multipart-tests",
        )
    django.setup()

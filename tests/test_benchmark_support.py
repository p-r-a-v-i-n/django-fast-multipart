from __future__ import annotations

import asyncio

import pytest
from django.test import override_settings

from benchmarks._support import run_asgi_request, run_parser, run_wsgi_request


@pytest.mark.parametrize("parser_name", ["django", "rust"])
@pytest.mark.parametrize(
    "scenario_name",
    ["mixed-form-1MiB", "memory-files-8x128KiB", "temporary-file-32MiB"],
)
def test_extended_parser_benchmark_scenarios(parser_name, scenario_name):
    run_parser(parser_name, scenario_name, 64 * 1024)


@pytest.mark.parametrize("parser_name", ["django", "rust"])
@pytest.mark.parametrize(
    "scenario_name",
    ["fields-100", "mixed-form-1MiB", "temporary-file-8MiB"],
)
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    MIDDLEWARE=[],
    ROOT_URLCONF="benchmarks._django_app",
)
def test_request_benchmark_paths(parser_name, scenario_name):
    run_wsgi_request(parser_name, scenario_name)
    asyncio.run(run_asgi_request(parser_name, scenario_name))

from __future__ import annotations

import asyncio

import pytest
from django.test import override_settings

from benchmarks._support import get_scenario, run_asgi_request, run_parser, run_wsgi_request
from benchmarks.measure_concurrency import percentile


@pytest.mark.parametrize(
    ("scenario_name", "handler_name", "file_class"),
    [
        ("fields-100", "none", None),
        ("mixed-form-1MiB", "memory", "InMemoryUploadedFile"),
        ("temporary-file-8MiB", "temporary", "TemporaryUploadedFile"),
    ],
)
def test_scenario_declares_upload_handler(scenario_name, handler_name, file_class):
    scenario = get_scenario(scenario_name)
    assert scenario.handler_name == handler_name
    assert scenario.expected_file_class == file_class


def test_percentile_uses_nearest_rank():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 0.5) == 2.0
    assert percentile(values, 0.95) == 4.0
    assert percentile(values, 1) == 4.0


@pytest.mark.parametrize(("values", "percentage"), [([], 0.95), ([1.0], -0.1), ([1.0], 1.1)])
def test_percentile_rejects_invalid_input(values, percentage):
    with pytest.raises(ValueError):
        percentile(values, percentage)


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

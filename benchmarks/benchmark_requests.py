from __future__ import annotations

import django
import pyperf

if __package__:
    from benchmarks._support import (
        PARSERS,
        REQUEST_SCENARIO_NAMES,
        run_asgi_request,
        run_wsgi_request,
    )
else:
    from _support import PARSERS, REQUEST_SCENARIO_NAMES, run_asgi_request, run_wsgi_request


def main() -> None:
    runner = pyperf.Runner()
    runner.metadata["django_version"] = django.get_version()
    runner.metadata["implementation"] = "Django WSGI client lifecycle and ASGI request/view path"

    for scenario_name in REQUEST_SCENARIO_NAMES:
        for parser_name in PARSERS:
            runner.bench_func(
                f"wsgi-{parser_name}-{scenario_name}",
                run_wsgi_request,
                parser_name,
                scenario_name,
            )
            runner.bench_async_func(
                f"asgi-{parser_name}-{scenario_name}",
                run_asgi_request,
                parser_name,
                scenario_name,
            )


if __name__ == "__main__":
    main()

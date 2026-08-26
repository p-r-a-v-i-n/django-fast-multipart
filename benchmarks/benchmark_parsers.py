from __future__ import annotations

import django
import pyperf
from _support import CHUNK_SIZES, PARSERS, SCENARIO_NAMES, run_parser


def main() -> None:
    runner = pyperf.Runner()
    runner.metadata["django_version"] = django.get_version()
    runner.metadata["implementation"] = "Django MultiPartParser versus RustMultiPartParser"

    for scenario_name in SCENARIO_NAMES:
        for chunk_size in CHUNK_SIZES:
            chunk_label = f"{chunk_size // 1024}KiB"
            for parser_name in PARSERS:
                runner.bench_func(
                    f"{parser_name}-{scenario_name}-{chunk_label}",
                    run_parser,
                    parser_name,
                    scenario_name,
                    chunk_size,
                )


if __name__ == "__main__":
    main()

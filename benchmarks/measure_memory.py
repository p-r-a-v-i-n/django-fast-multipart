from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import django
from _support import CHUNK_SIZES, PARSERS, SCENARIO_NAMES, get_scenario, run_parser


def current_rss_bytes() -> int:
    with open("/proc/self/statm", encoding="ascii") as statm:
        resident_pages = int(statm.read().split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE")


def worker(parser_name: str, scenario_name: str, chunk_size: int) -> None:
    if sys.platform != "linux":
        raise SystemExit("Peak RSS measurement currently requires Linux.")
    get_scenario(scenario_name)
    gc.collect()

    child_pid = os.fork()
    if child_pid == 0:
        try:
            baseline = current_rss_bytes()
            run_parser(parser_name, scenario_name, chunk_size)
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            print(
                json.dumps(
                    {
                        "baseline_rss_bytes": baseline,
                        "peak_rss_bytes": peak,
                        "incremental_peak_rss_bytes": max(0, peak - baseline),
                    }
                ),
                flush=True,
            )
        except BaseException:
            traceback.print_exc()
            os._exit(1)
        os._exit(0)

    _, status = os.waitpid(child_pid, 0)
    exit_code = os.waitstatus_to_exitcode(status)
    if exit_code:
        raise SystemExit(exit_code)


def measure(parser_name: str, scenario_name: str, chunk_size: int) -> dict[str, int]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        parser_name,
        scenario_name,
        str(chunk_size),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure isolated parser peak RSS on Linux.")
    parser.add_argument("--output", type=Path, default=Path("benchmark-memory.json"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--worker", nargs=3, metavar=("PARSER", "SCENARIO", "CHUNK_SIZE"))
    arguments = parser.parse_args()

    if arguments.worker:
        parser_name, scenario_name, chunk_size = arguments.worker
        worker(parser_name, scenario_name, int(chunk_size))
        return
    if arguments.runs < 1:
        parser.error("--runs must be at least 1")
    if sys.platform != "linux":
        parser.error("peak RSS measurement currently requires Linux")

    records = []
    for scenario_name in SCENARIO_NAMES:
        for chunk_size in CHUNK_SIZES:
            for parser_name in PARSERS:
                samples = [
                    measure(parser_name, scenario_name, chunk_size) for _ in range(arguments.runs)
                ]
                incremental = [sample["incremental_peak_rss_bytes"] for sample in samples]
                record = {
                    "parser": parser_name,
                    "scenario": scenario_name,
                    "chunk_size": chunk_size,
                    "median_incremental_peak_rss_bytes": int(statistics.median(incremental)),
                    "samples": samples,
                }
                records.append(record)
                mebibytes = record["median_incremental_peak_rss_bytes"] / (1024 * 1024)
                print(
                    f"{parser_name:6} {scenario_name:20} {chunk_size // 1024:>2} KiB "
                    f"{mebibytes:8.2f} MiB"
                )

    output = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "django_version": django.get_version(),
        "measurement": "fork after input preparation",
        "runs_per_case": arguments.runs,
        "records": records,
    }
    arguments.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import django
from django.test import Client

from benchmarks._support import (
    PARSERS,
    REQUEST_SCENARIO_NAMES,
    run_asgi_request,
    run_wsgi_request,
)


@dataclass(frozen=True)
class RoundResult:
    duration_seconds: float
    request_latencies: tuple[float, ...]


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentage + 0.999999) - 1))
    return ordered[index]


def run_wsgi_round(
    parser_name: str,
    scenario_name: str,
    workers: int,
    requests_per_worker: int,
) -> RoundResult:
    ready = Barrier(workers + 1)

    def worker() -> list[float]:
        client = Client()
        latencies = []
        ready.wait()
        for _ in range(requests_per_worker):
            started = time.perf_counter()
            run_wsgi_request(parser_name, scenario_name, client)
            latencies.append(time.perf_counter() - started)
        return latencies

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker) for _ in range(workers)]
        started = time.perf_counter()
        ready.wait()
        latencies = [latency for future in futures for latency in future.result()]
        duration = time.perf_counter() - started
    return RoundResult(duration, tuple(latencies))


async def run_asgi_round(
    parser_name: str,
    scenario_name: str,
    workers: int,
    requests_per_worker: int,
) -> RoundResult:
    ready = asyncio.Event()

    async def worker() -> list[float]:
        latencies = []
        await ready.wait()
        for _ in range(requests_per_worker):
            started = time.perf_counter()
            await run_asgi_request(parser_name, scenario_name)
            latencies.append(time.perf_counter() - started)
        return latencies

    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    started = time.perf_counter()
    ready.set()
    worker_latencies = await asyncio.gather(*tasks)
    duration = time.perf_counter() - started
    return RoundResult(duration, tuple(latency for group in worker_latencies for latency in group))


def measure_round(
    request_path: str,
    parser_name: str,
    scenario_name: str,
    workers: int,
    requests_per_worker: int,
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> RoundResult:
    if request_path == "wsgi":
        return run_wsgi_round(parser_name, scenario_name, workers, requests_per_worker)
    owns_loop = event_loop is None
    loop = event_loop or asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            run_asgi_round(parser_name, scenario_name, workers, requests_per_worker)
        )
    finally:
        if owns_loop:
            loop.close()


def summarize(
    request_path: str,
    parser_name: str,
    scenario_name: str,
    workers: int,
    requests_per_worker: int,
    samples: list[RoundResult],
) -> dict[str, object]:
    request_count = workers * requests_per_worker
    throughput = [request_count / sample.duration_seconds for sample in samples]
    latencies = [latency for sample in samples for latency in sample.request_latencies]
    return {
        "request_path": request_path,
        "parser": parser_name,
        "scenario": scenario_name,
        "concurrency": workers,
        "requests_per_round": request_count,
        "median_requests_per_second": statistics.median(throughput),
        "median_request_latency_seconds": statistics.median(latencies),
        "p95_request_latency_seconds": percentile(latencies, 0.95),
        "rounds": [
            {
                "duration_seconds": sample.duration_seconds,
                "requests_per_second": request_count / sample.duration_seconds,
            }
            for sample in samples
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure concurrent in-process Django multipart requests."
    )
    parser.add_argument("--output", type=Path, default=Path("benchmark-concurrency.json"))
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--requests-per-worker", type=int, default=5)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--paths", nargs="+", choices=("wsgi", "asgi"), default=["wsgi", "asgi"])
    parser.add_argument(
        "--scenario",
        choices=REQUEST_SCENARIO_NAMES,
        default="mixed-form-1MiB",
    )
    arguments = parser.parse_args()

    if arguments.rounds < 1:
        parser.error("--rounds must be at least 1")
    if arguments.requests_per_worker < 1:
        parser.error("--requests-per-worker must be at least 1")
    if any(value < 1 for value in arguments.concurrency):
        parser.error("--concurrency values must be at least 1")

    event_loop = asyncio.new_event_loop() if "asgi" in arguments.paths else None
    try:
        for request_path in arguments.paths:
            for parser_name in PARSERS:
                measure_round(
                    request_path,
                    parser_name,
                    arguments.scenario,
                    1,
                    1,
                    event_loop,
                )

        records = []
        parser_names = list(PARSERS)
        for request_path in arguments.paths:
            for workers in arguments.concurrency:
                samples = {parser_name: [] for parser_name in parser_names}
                for round_index in range(arguments.rounds):
                    order = parser_names if round_index % 2 == 0 else list(reversed(parser_names))
                    for parser_name in order:
                        samples[parser_name].append(
                            measure_round(
                                request_path,
                                parser_name,
                                arguments.scenario,
                                workers,
                                arguments.requests_per_worker,
                                event_loop,
                            )
                        )
                for parser_name in parser_names:
                    record = summarize(
                        request_path,
                        parser_name,
                        arguments.scenario,
                        workers,
                        arguments.requests_per_worker,
                        samples[parser_name],
                    )
                    records.append(record)
                    print(
                        f"{request_path:4} {parser_name:6} concurrency={workers:<2} "
                        f"{record['median_requests_per_second']:8.2f} requests/s "
                        f"p95={record['p95_request_latency_seconds'] * 1_000:8.2f} ms"
                    )
    finally:
        if event_loop is not None:
            event_loop.close()

    output = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "django_version": django.get_version(),
        "measurement": "in-process Django request lifecycle without a network server",
        "rounds_per_case": arguments.rounds,
        "records": records,
    }
    arguments.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

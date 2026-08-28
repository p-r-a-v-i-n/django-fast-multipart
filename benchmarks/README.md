# Parser benchmarks

The timing suite compares Django's `MultiPartParser` with
`RustMultiPartParser` using identical multipart bodies, upload handlers, and
input chunk sizes. `pyperf` provides worker-process isolation, calibration,
and warmups.

The parser cases cover 100 form fields, a mixed form, multiple files, and file
sizes from 64 KiB through 32 MiB. Both memory and temporary-file handlers are
measured with 8 KiB and 64 KiB input chunks.

Two additional suites exercise Django request objects. The lifecycle timing
suite uses Django's test client for the complete in-process WSGI path and
`AsyncRequestFactory` for the ASGI request/view path. The concurrency suite
runs repeated WSGI requests in worker threads. ASGI concurrency requires a
separate production-server benchmark and is not simulated here.

> **Important:** None of these benchmarks includes a production network
> server, socket I/O, TLS, a database, or application work beyond parsing and
> result validation. They do not represent deployment throughput or endpoint
> response-time guarantees.

## Running the benchmarks

Run timing benchmarks:

```console
uv run python -m benchmarks.benchmark_parsers --rigorous -o benchmark-timing.json
```

On Linux, measure peak resident memory in isolated processes:

```console
uv run python -m benchmarks.measure_memory --runs 5 --output benchmark-memory.json
```

Measure the in-process WSGI lifecycle and ASGI request/view path:

```console
uv run python -m benchmarks.benchmark_requests --rigorous -o benchmark-requests.json
```

Measure concurrent WSGI requests at one, two, and four worker threads:

```console
uv run python -m benchmarks.measure_concurrency \
  --rounds 5 \
  --requests-per-worker 5 \
  --output benchmark-concurrency.json
```

Compare timing files with `uv run python -m pyperf compare_to`. Only compare
results collected with equivalent Python and Django versions, native build
profiles, and hardware. The manual GitHub Actions workflow runs the parser,
request-path, and concurrency suites as separate jobs, stores all four result
files as artifacts, and does not enforce performance thresholds.

The concurrency script alternates which parser runs first in each round. It
reports median requests per second plus median and 95th-percentile in-process
request latency for threaded WSGI requests.

The ASGI timing path constructs a real `ASGIRequest` but calls the benchmark
view directly. It excludes `ASGIHandler`, middleware, URL routing, server
body spooling, and network behavior. Compare Django and Rust within the ASGI
path; do not compare its absolute values with WSGI or production servers.

Peak RSS is diagnostic because allocator behavior and operating-system
accounting introduce noise. Each memory case prepares its request body before
forking the measured process, so input construction is excluded from the
parser's incremental peak.

## Reference results

These results are from the manual GitHub Actions workflow run for commit
[`f1a117a`](https://github.com/p-r-a-v-i-n/django-fast-multipart/commit/f1a117aac7c125d0f1f4e7468c4f4f2731ad6712)
on 28 August 2026.

| Environment | Value |
| --- | --- |
| Runner | GitHub-hosted Linux runner, 4 vCPUs |
| CPU | AMD EPYC 7763 |
| Python | CPython 3.14.7 |
| Django | 6.1 |
| Native build | Release profile with LTO and one code-generation unit |

GitHub-hosted runners are shared and are not controlled performance machines.
`pyperf` reported instability for some cases, especially temporary-file
uploads. Treat these numbers as a useful reference, not a fixed baseline.

### Django request paths

| Request | Path | Django | Rust | Speedup |
| --- | --- | ---: | ---: | ---: |
| 100 fields | WSGI | 2.42 ms | 1.15 ms | 2.10x |
| 100 fields | ASGI | 2.25 ms | 1.03 ms | 2.19x |
| Mixed form with a 1 MiB file | WSGI | 1.54 ms | 1.07 ms | 1.45x |
| Mixed form with a 1 MiB file | ASGI | 1.40 ms | 0.909 ms | 1.54x |
| 8 MiB temporary file | WSGI | 7.89 ms | 6.76 ms | 1.17x |
| 8 MiB temporary file | ASGI | 8.12 ms | 7.19 ms | 1.13x |

### WSGI concurrency

This benchmark uses the mixed form with a 1 MiB file.

| Threads | Django requests/s | Rust requests/s | Speedup | Django p95 | Rust p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 639 | 1,180 | 1.85x | 1.88 ms | 1.27 ms |
| 2 | 767 | 1,088 | 1.42x | 6.35 ms | 1.49 ms |
| 4 | 673 | 975 | 1.45x | 14.95 ms | 1.87 ms |

### Parser timing

| Case | Chunk | Django | Rust | Speedup |
| --- | ---: | ---: | ---: | ---: |
| 100 fields | 8 KiB | 2.02 ms | 0.873 ms | 2.32x |
| 100 fields | 64 KiB | 2.03 ms | 0.874 ms | 2.32x |
| Mixed form with a 1 MiB file | 8 KiB | 1.14 ms | 0.630 ms | 1.82x |
| Mixed form with a 1 MiB file | 64 KiB | 1.13 ms | 0.672 ms | 1.68x |
| Eight 128 KiB memory files | 8 KiB | 0.858 ms | 0.491 ms | 1.75x |
| Eight 128 KiB memory files | 64 KiB | 0.760 ms | 0.517 ms | 1.47x |
| 64 KiB memory file | 8 KiB | 0.126 ms | 0.065 ms | 1.92x |
| 64 KiB memory file | 64 KiB | 0.153 ms | 0.085 ms | 1.81x |
| 1 MiB memory file | 8 KiB | 0.578 ms | 0.312 ms | 1.85x |
| 1 MiB memory file | 64 KiB | 1.22 ms | 0.277 ms | 4.40x |
| 8 MiB temporary file | 8 KiB | 7.11 ms | 5.39 ms | 1.32x |
| 8 MiB temporary file | 64 KiB | 5.63 ms | 4.82 ms | 1.17x |
| 32 MiB temporary file | 8 KiB | 30.2 ms | 23.2 ms | 1.30x |
| 32 MiB temporary file | 64 KiB | 22.3 ms | 19.1 ms | 1.17x |

### Incremental peak memory

The values are median incremental peak RSS from five isolated processes.

| Case | Chunk | Django | Rust |
| --- | ---: | ---: | ---: |
| 100 fields | 8 KiB | 1.13 MiB | 1.16 MiB |
| 100 fields | 64 KiB | 1.13 MiB | 1.09 MiB |
| Mixed form with a 1 MiB file | 8 KiB | 1.14 MiB | 1.10 MiB |
| Mixed form with a 1 MiB file | 64 KiB | 1.14 MiB | 1.54 MiB |
| Eight 128 KiB memory files | 8 KiB | 1.14 MiB | 1.16 MiB |
| Eight 128 KiB memory files | 64 KiB | 1.14 MiB | 1.10 MiB |
| 64 KiB memory file | 8 KiB | 1.13 MiB | 1.09 MiB |
| 64 KiB memory file | 64 KiB | 1.13 MiB | 1.28 MiB |
| 1 MiB memory file | 8 KiB | 2.01 MiB | 1.97 MiB |
| 1 MiB memory file | 64 KiB | 2.88 MiB | 2.41 MiB |
| 8 MiB temporary file | 8 KiB | 1.38 MiB | 1.34 MiB |
| 8 MiB temporary file | 64 KiB | 1.63 MiB | 1.78 MiB |
| 32 MiB temporary file | 8 KiB | 1.38 MiB | 1.34 MiB |
| 32 MiB temporary file | 64 KiB | 1.63 MiB | 1.72 MiB |

Rust used less incremental peak memory in 8 of the 14 paired cases and more in
6. Most differences were small, so the correct conclusion is that memory use
was broadly comparable. The 8 MiB and 32 MiB temporary-file cases used almost
the same memory, showing that large files remained streamed.

## What the results mean

The Rust parser gave the clearest improvement for forms with many fields and
in-memory uploads. The improvement remained visible through the Django request
path and under threaded WSGI concurrency. Temporary-file uploads improved less
because file writes and upload-handler work take more of the total time.

These results do not establish production endpoint latency or throughput.
They exclude a production server, socket I/O, TLS, a database, and normal view
work. Before making a deployment decision, repeat the suite on the target
hardware with the application's real upload handlers and request shapes.

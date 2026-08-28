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
[`739254d`](https://github.com/p-r-a-v-i-n/django-fast-multipart/commit/739254d7b7b8afebf338b75808f7cb8cd079edbe)
on 28 August 2026.

| Environment | Value |
| --- | --- |
| Runner | GitHub-hosted Linux runner, 4 vCPUs |
| CPU | AMD EPYC 9V74 |
| Python | CPython 3.14.7 |
| Django | 6.1 |
| Native build | Release profile with LTO and one code-generation unit |

GitHub-hosted runners are shared and are not controlled performance machines.
`pyperf` reported instability for some cases, especially temporary-file
uploads. Treat these numbers as a useful reference, not a fixed baseline.

### Django request paths

| Request | Path | Django | Rust | Speedup |
| --- | --- | ---: | ---: | ---: |
| 100 fields | WSGI | 1.55 ms | 0.823 ms | 1.89x |
| 100 fields | ASGI | 1.45 ms | 0.732 ms | 1.98x |
| Mixed form with a 1 MiB file | WSGI | 1.05 ms | 0.679 ms | 1.55x |
| Mixed form with a 1 MiB file | ASGI | 0.941 ms | 0.589 ms | 1.60x |
| 8 MiB temporary file | WSGI | 5.97 ms | 4.78 ms | 1.25x |
| 8 MiB temporary file | ASGI | 6.37 ms | 5.02 ms | 1.27x |

### WSGI concurrency

This benchmark uses the mixed form with a 1 MiB file.

| Threads | Django requests/s | Rust requests/s | Speedup | Django p95 | Rust p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 505 | 899 | 1.78x | 2.26 ms | 1.45 ms |
| 2 | 568 | 795 | 1.40x | 6.85 ms | 6.19 ms |
| 4 | 552 | 848 | 1.54x | 7.52 ms | 12.22 ms |

### Parser timing

| Case | Chunk | Django | Rust | Speedup |
| --- | ---: | ---: | ---: | ---: |
| 100 fields | 8 KiB | 1.67 ms | 0.804 ms | 2.08x |
| 100 fields | 64 KiB | 1.71 ms | 0.813 ms | 2.10x |
| Mixed form with a 1 MiB file | 8 KiB | 1.01 ms | 0.513 ms | 1.97x |
| Mixed form with a 1 MiB file | 64 KiB | 0.950 ms | 0.522 ms | 1.82x |
| Eight 128 KiB memory files | 8 KiB | 0.739 ms | 0.399 ms | 1.85x |
| Eight 128 KiB memory files | 64 KiB | 0.657 ms | 0.404 ms | 1.62x |
| 64 KiB memory file | 8 KiB | 0.084 ms | 0.044 ms | 1.91x |
| 64 KiB memory file | 64 KiB | 0.102 ms | 0.044 ms | 2.32x |
| 1 MiB memory file | 8 KiB | 0.562 ms | 0.291 ms | 1.93x |
| 1 MiB memory file | 64 KiB | 1.46 ms | 0.212 ms | 6.89x |
| 8 MiB temporary file | 8 KiB | 7.60 ms | 5.55 ms | 1.37x |
| 8 MiB temporary file | 64 KiB | 6.04 ms | 4.60 ms | 1.31x |
| 32 MiB temporary file | 8 KiB | 31.9 ms | 23.7 ms | 1.34x |
| 32 MiB temporary file | 64 KiB | 25.9 ms | 20.2 ms | 1.28x |

### Incremental peak memory

The values are median incremental peak RSS from five isolated processes.

| Case | Chunk | Django | Rust |
| --- | ---: | ---: | ---: |
| 100 fields | 8 KiB | 1.13 MiB | 1.16 MiB |
| 100 fields | 64 KiB | 1.13 MiB | 1.09 MiB |
| Mixed form with a 1 MiB file | 8 KiB | 1.14 MiB | 1.10 MiB |
| Mixed form with a 1 MiB file | 64 KiB | 1.14 MiB | 1.35 MiB |
| Eight 128 KiB memory files | 8 KiB | 1.14 MiB | 1.16 MiB |
| Eight 128 KiB memory files | 64 KiB | 1.14 MiB | 1.16 MiB |
| 64 KiB memory file | 8 KiB | 1.13 MiB | 1.09 MiB |
| 64 KiB memory file | 64 KiB | 1.13 MiB | 1.22 MiB |
| 1 MiB memory file | 8 KiB | 2.01 MiB | 2.03 MiB |
| 1 MiB memory file | 64 KiB | 2.88 MiB | 2.53 MiB |
| 8 MiB temporary file | 8 KiB | 1.38 MiB | 1.34 MiB |
| 8 MiB temporary file | 64 KiB | 1.63 MiB | 1.72 MiB |
| 32 MiB temporary file | 8 KiB | 1.38 MiB | 1.34 MiB |
| 32 MiB temporary file | 64 KiB | 1.63 MiB | 1.78 MiB |

Rust used less incremental peak memory in 6 of the 14 paired cases and more in
8. Most differences were small, so the correct conclusion is that memory use
was broadly comparable. The 8 MiB and 32 MiB temporary-file cases used almost
the same memory, showing that large files remained streamed.

## What the results mean

The Rust parser gave the clearest improvement for forms with many fields and
in-memory uploads. The improvement remained visible through the Django request
path and under threaded WSGI concurrency. Temporary-file uploads improved less
because file writes and upload-handler work take more of the total time.

This run includes the direct body-data mapping added in commit
[`a295faa`](https://github.com/p-r-a-v-i-n/django-fast-multipart/commit/a295faa).
It creates Python `bytes` values from parser-buffer slices without first
copying each slice into an intermediate Rust vector.

These results do not establish production endpoint latency or throughput.
They exclude a production server, socket I/O, TLS, a database, and normal view
work. Before making a deployment decision, repeat the suite on the target
hardware with the application's real upload handlers and request shapes.

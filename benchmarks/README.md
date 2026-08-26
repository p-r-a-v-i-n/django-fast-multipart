# Parser benchmarks

The timing suite compares Django's `MultiPartParser` with
`RustMultiPartParser` using identical multipart bodies, upload handlers, and
input chunk sizes. `pyperf` provides worker-process isolation, calibration,
and warmups.

The cases cover 100 form fields, a 1 MiB in-memory upload, and an 8 MiB
temporary-file upload. Each case is measured with 8 KiB and 64 KiB input
chunks.

> **Important:** These are parser microbenchmarks, not end-to-end Django
> request benchmarks. Their results do not represent application throughput or
> response-time improvements.

## Running the benchmarks

Run timing benchmarks:

```console
uv run python benchmarks/benchmark_parsers.py --rigorous -o benchmark-timing.json
```

On Linux, measure peak resident memory in isolated processes:

```console
uv run python benchmarks/measure_memory.py --runs 5 --output benchmark-memory.json
```

Compare timing files with `uv run python -m pyperf compare_to`. Only compare
results collected with equivalent Python and Django versions, native build
profiles, and hardware. The manual GitHub Actions workflow stores both result
files as artifacts and does not enforce performance thresholds.

Peak RSS is diagnostic because allocator behavior and operating-system
accounting introduce noise. Each memory case prepares its request body before
forking the measured process, so input construction is excluded from the
parser's incremental peak.

## Exploratory reference run

The following results are from one local run on 26 August 2026. The machine
used the environment below. Timing used `pyperf --rigorous`; memory values are
the median incremental peak RSS from five isolated processes.

| Environment | Value |
| --- | --- |
| CPU | AMD Ryzen 3 3250U, 2 cores / 4 threads |
| Operating system | Linux x86-64 |
| Python | CPython 3.14.1 |
| Django | 6.1 |
| Native build | Release profile with LTO and one code-generation unit |
| Power | Battery |
| CPU frequency policy | `schedutil`, 1.4–2.6 GHz, boost enabled |
| CPU isolation | None; normal scheduler and interrupt activity remained |

**The host was not configured as a controlled performance-testing machine.**
`pyperf` reported host jitter or insufficient stability for several cases.
The values below preserve the observed results, but they are not a regression
baseline or a performance guarantee.

### Timing

| Case | Chunk | Django | Rust | Rust speedup |
| --- | ---: | ---: | ---: | ---: |
| 100 fields | 8 KiB | 6.16 ms | 2.54 ms | 2.43x |
| 100 fields | 64 KiB | 5.29 ms | 2.48 ms | 2.13x |
| 1 MiB in-memory file | 8 KiB | 1.68 ms | 1.03 ms | 1.63x |
| 1 MiB in-memory file | 64 KiB | 3.51 ms | 0.82 ms | 4.30x |
| 8 MiB temporary file | 8 KiB | 22.6 ms | 18.4 ms | 1.23x |
| 8 MiB temporary file | 64 KiB | 17.4 ms | 16.1 ms | 1.08x |

### Incremental peak RSS

| Case | Chunk | Django incremental peak RSS | Rust incremental peak RSS |
| --- | ---: | ---: | ---: |
| 100 fields | 8 KiB | 1.21 MiB | 0.99 MiB |
| 100 fields | 64 KiB | 1.21 MiB | 0.99 MiB |
| 1 MiB in-memory file | 8 KiB | 2.18 MiB | 1.95 MiB |
| 1 MiB in-memory file | 64 KiB | 3.16 MiB | 2.53 MiB |
| 8 MiB temporary file | 8 KiB | 1.43 MiB | 1.16 MiB |
| 8 MiB temporary file | 64 KiB | 1.70 MiB | 1.54 MiB |

### CPU-pinned repeatability check

A supplementary check pinned the process to one logical CPU and alternated
which parser ran first in 31 paired blocks. This reduces CPU migration and
ordering bias, but it does not remove frequency scaling, thermal effects, or
background activity.

| Case | Django median | Rust median | Median paired speedup | Paired range |
| --- | ---: | ---: | ---: | ---: |
| 100 fields, 8 KiB chunks | 5.15 ms | 2.49 ms | 2.07x | 1.94–2.23x |
| 1 MiB in-memory file, 64 KiB chunks | 3.28 ms | 0.88 ms | 3.77x | 3.30–4.71x |
| 8 MiB temporary file, 64 KiB chunks | 14.55 ms | 13.84 ms | 1.07x | 0.99–1.15x |

**The direction of the field and in-memory results remained consistent after
pinning.** The temporary-file result was small enough that individual paired
blocks sometimes showed no advantage.

## Profiling observations

Python `cProfile` was used for call attribution on representative cases. Its
instrumentation changes absolute timings, so the profile is used to locate
work rather than calculate speedups.

- **Field-heavy requests:** native `MultipartParser.feed()` accounted for a
  small portion of the Rust path. Python-side part creation, header parameter
  parsing, string conversion, limit enforcement, and `QueryDict` population
  dominated the remaining work.
- **In-memory uploads:** both implementations delivered exactly 1 MiB as 17
  `bytes` chunks to the same `MemoryFileUploadHandler`. The observed difference
  was therefore not caused by Rust passing less data to Django's handler.
- **Temporary-file uploads:** the buffered file write accounted for roughly
  half of the profiled Rust path. Input reads and temporary-file close and
  unlink operations added shared cost, leaving less parser work to accelerate.
- **Native/Python transfer:** the current data path copies input into the Rust
  buffer, copies emitted body data into an event, and then creates a Python
  `bytes` object. Reducing these copies is a more promising file-upload target
  than further boundary-search tuning.

Hardware performance counters were not collected because the host restricts
them with `perf_event_paranoid=4`. The system security setting was not changed
for this run.

## Interpretation and limitations

**What this run supports:** the Rust-backed parser reduced parser overhead for
field-heavy and in-memory cases on this machine. Its advantage was much
narrower when Django's temporary-file handler and filesystem operations
performed most of the work. Incremental peak RSS was lower for Rust in each
measured case.

**What this run does not support:** it does not establish production endpoint
latency, concurrent throughput, behavior under WSGI or ASGI servers, or a
hardware-independent speedup. It also does not cover mixed forms, multiple
files, a broad file-size range, or concurrent uploads.

Before using these numbers for deployment or capacity decisions, repeat the
suite on the target platform with AC power, a fixed CPU-frequency policy,
controlled boost behavior, CPU affinity or isolation, an idle host, and
multiple independent runs. End-to-end Django and concurrent workload
benchmarks should be evaluated separately.

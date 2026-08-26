# Parser benchmarks

The timing suite compares Django's `MultiPartParser` with
`RustMultiPartParser` using identical multipart bodies, upload handlers, and
input chunk sizes. `pyperf` provides worker-process isolation, calibration,
and warmups.

The cases cover 100 form fields, a 1 MiB in-memory upload, and an 8 MiB
temporary-file upload. Each case is measured with 8 KiB and 64 KiB input
chunks.

## Reference run

The following results are from one local run on 26 August 2026. The machine
used an AMD Ryzen 3 3250U, Linux x86-64, CPython 3.14.1, and Django 6.1.
Timing used `pyperf --rigorous`; memory values are the median incremental peak
RSS from five isolated processes.

| Case | Chunk | Django | Rust | Rust speedup |
| --- | ---: | ---: | ---: | ---: |
| 100 fields | 8 KiB | 6.16 ms | 2.54 ms | 2.43x |
| 100 fields | 64 KiB | 5.29 ms | 2.48 ms | 2.13x |
| 1 MiB in-memory file | 8 KiB | 1.68 ms | 1.03 ms | 1.63x |
| 1 MiB in-memory file | 64 KiB | 3.51 ms | 0.82 ms | 4.30x |
| 8 MiB temporary file | 8 KiB | 22.6 ms | 18.4 ms | 1.23x |
| 8 MiB temporary file | 64 KiB | 17.4 ms | 16.1 ms | 1.08x |

| Case | Chunk | Django incremental peak RSS | Rust incremental peak RSS |
| --- | ---: | ---: | ---: |
| 100 fields | 8 KiB | 1.21 MiB | 0.99 MiB |
| 100 fields | 64 KiB | 1.21 MiB | 0.99 MiB |
| 1 MiB in-memory file | 8 KiB | 2.18 MiB | 1.95 MiB |
| 1 MiB in-memory file | 64 KiB | 3.16 MiB | 2.53 MiB |
| 8 MiB temporary file | 8 KiB | 1.43 MiB | 1.16 MiB |
| 8 MiB temporary file | 64 KiB | 1.70 MiB | 1.54 MiB |

This run suggests that parser work accounts for a larger share of field-heavy
and in-memory requests. The difference is narrower when the temporary-file
upload handler performs most of the work. `pyperf` reported host jitter or
insufficient stability for several cases, so these values are illustrative,
not performance guarantees. Re-run the suite in the target environment before
drawing deployment or capacity conclusions.

Run timing benchmarks:

```console
uv run python benchmarks/benchmark_parsers.py --rigorous -o benchmark-timing.json
```

On Linux, measure peak resident memory in isolated processes:

```console
uv run python benchmarks/measure_memory.py --runs 5 --output benchmark-memory.json
```

Compare timing files with `uv run python -m pyperf compare_to`. Results should
only be compared when the Python version, Django version, build profile, and
machine are equivalent. Peak RSS is diagnostic: allocator behavior and
operating-system accounting can introduce noise. Each memory case prepares its
request body before forking the measured process, so input construction is not
included in the parser's incremental peak.

# Parser benchmarks

The timing suite compares Django's `MultiPartParser` with
`RustMultiPartParser` using identical multipart bodies, upload handlers, and
input chunk sizes. `pyperf` provides worker-process isolation, calibration,
and warmups.

The cases cover 100 form fields, a 1 MiB in-memory upload, and an 8 MiB
temporary-file upload. Each case is measured with 8 KiB and 64 KiB input
chunks.

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

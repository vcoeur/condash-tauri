# Performance — benchmarking and optimisation

Durable guidance for measuring and improving performance across helio and helio-web.

## Latency budgets

For interactive commands (`helio search`, `helio grep`), our user-facing budget is:

- **First result**: ≤ 200 ms p95 on warm cache, ≤ 1 s p95 on cold cache, for corpora up to 1 GB.
- **Steady-state throughput**: ≥ 50 MB/s of corpus scanned per second on a commodity NVMe.

Anything above a 1 GB corpus is expected to require an index; the raw-scan budget does not apply.

## Corpus generation

Use `fakelog` for reproducible synthetic corpora:

```bash
pipx install fakelog
fakelog nginx --size 1GiB --status-distribution real --seed 42 > /tmp/access.log
```

The `--seed 42` flag is load-bearing — always pin the seed so benchmarks across machines are comparing the same bytes.

## Warm vs. cold timing

Every benchmark table should distinguish:

- **Cold**: index cache cleared, page cache dropped (`echo 3 > /proc/sys/vm/drop_caches` on Linux, `purge` on macOS), first query after startup.
- **Warm**: index mmap'd, pages in the page cache, second or later query.

Mixing the two in a single number hides regressions. The demo benchmark table in [[fuzzy-search-v2|fuzzy-search-v2/notes/benchmarks/results.md]] shows the expected four-column shape.

## Flamegraphs

For CPU-bound hotspots, profile with `cargo flamegraph` on the Rust side or `py-spy record` on the Python side:

```bash
# Rust
cargo flamegraph --bin helio -- search "pattern" --corpus /tmp/access.log

# Python wrapper + PyO3 boundary
py-spy record --output flame.svg --format flamegraph -- helio search "pattern" --corpus /tmp/access.log
```

Store the resulting SVGs under the conception item's `notes/flamegraphs/` directory. Commit the SVG, not the raw samples.

## Memory

On OOM reports, capture:

- `/proc/<pid>/status` at the moment of kill (requires a wrapper).
- `dmesg` output around the OOM message (the kernel lines include RSS, virtual size, and oom_score_adj).
- A debug-build stack trace from the abort site.

The incident [[search-crash-large-logs]] has a worked example; use its `notes/stack-trace.md` as a template when filing future OOM incidents.

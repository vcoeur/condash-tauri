# Benchmark results — trigram index vs. v1

Synthetic nginx access logs, generated with `fakelog --rate=real`. Each row is a median of 5 runs on a warm page cache. Machine: Ryzen 7 5800X, 32 GB DDR4, NVMe SSD, Linux 6.17.

## Build time

| Corpus | Size | v1 (cold scan) | v2 build | v2 first query |
|---|---|---|---|---|
| 1 day | 120 MB | n/a (scan per query) | 0.7 s | 45 ms |
| 1 week | 820 MB | n/a | 4.2 s | 110 ms |
| 1 month | 3.4 GB | n/a | 17.8 s | 240 ms |

## Query latency (p50 / p95 / p99, ms)

| Corpus | v1 cold | v1 warm | v2 cold | v2 warm |
|---|---|---|---|---|
| 120 MB | 2100 / 2400 / 3100 | 260 / 310 / 480 | 62 / 81 / 140 | 8 / 14 / 22 |
| 820 MB | 11200 / 13800 / 17400 | 1900 / 2200 / 2900 | 210 / 270 / 390 | 34 / 51 / 88 |
| 3.4 GB | 46100 / 53200 / — | 7800 / 9400 / 12100 | 680 / 810 / 1100 | 110 / 160 / 240 |

"Cold" = first query against this corpus after the index cache was invalidated or never built. "Warm" = index mmap'd and in the page cache.

## Notes

- 3.4 GB cold v1 run did not reach p99 within the 60 s benchmark timeout — dropped from the table.
- v2 warm numbers are dominated by stdout writes; switching the benchmark to `--output /dev/null` drops the 120 MB warm p50 from 8 ms to 3 ms. Real-world latency in a terminal will be closer to the number with stdout.
- The 820 MB slice is the one that tripped the OOM tracked as [[search-crash-large-logs]]. Numbers above are post-fix.

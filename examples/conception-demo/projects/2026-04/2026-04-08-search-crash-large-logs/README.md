# `helio search` crashes on large logs

**Date**: 2026-04-08
**Kind**: incident
**Status**: now
**Apps**: `helio`
**Environment**: PROD — user running helio 0.4.0-alpha.2 (trigram-index branch) against nginx access logs from their production edge tier
**Severity**: high — reproducible OOM on any corpus above ~800 MB; the CLI process dies with SIGKILL from the kernel OOM killer, losing all streamed-but-unflushed output

## Description

Reported through the helio mailing list on 2026-04-08 by a user mining a rolling week of nginx access logs (~840 MB concatenated). `helio search "5[0-9][0-9] /api/"` starts streaming results for 200–400 ms, then the process dies with no stderr. The kernel log shows the OOM killer selected the helio PID after it allocated ~28 GB in 1.6 s.

Reproduces locally against a synthetic 1 GB nginx log generated with `fakelog`. Fails identically on Linux and macOS. v1 engine (`--engine=legacy`) is unaffected — the crash is specific to the new trigram path shipped on the [[fuzzy-search-v2]] branch.

## Impact

- Every user on 0.4.0-alpha.2 who tries to search a corpus above ~800 MB is blocked.
- The streaming writer flushes every 16 hits or 50 ms, so partial output reaches the terminal before the kill — it is easy to mistake the crash for a clean exit after 2–3 hits scroll past.
- No data corruption: the index files are written atomically and no writes happen on the query path.
- Blocks further progress on [[fuzzy-search-v2]]: benchmark runs on the 1 GB corpus cannot complete.

## Symptoms

```
$ helio search "5[0-9][0-9] /api/" --corpus /var/log/nginx/
2026-04-08T14:12:03 access.log.3  503 GET /api/reports/4981 ...
2026-04-08T14:12:04 access.log.3  502 GET /api/sync       ...
Killed
$ dmesg | tail -3
[ 4812.441] Out of memory: Killed process 18324 (helio) total-vm:29834124kB, ...
```

Stack trace captured from a debug build in [`notes/stack-trace.md`](notes/stack-trace.md). Repro steps in [`notes/repro.md`](notes/repro.md).

## Root cause

The mmap window over `postings.bin` is sized to the full file length, not to a sliding window. On a 1 GB corpus, `postings.bin` is ~680 MB and the OS page cache happily backs the whole range. That alone is fine — reads are demand-paged.

The crash is in the streaming writer: it collects candidate document byte-ranges in a `Vec<(u64, u64)>` per query without bounding the collection size, then deduplicates at the end. On a 503-status query against a week of logs, the candidate set is ~9.2 million ranges before dedup. Each range is 16 bytes, so the vec itself is ~150 MB; but the allocator's growth strategy (double on realloc) briefly holds two copies during the last realloc, and the reallocation path allocates fresh before freeing, peaking at ~450 MB in user space. Combined with the mmap backing and several working arrays in the scorer, total RSS spikes past the user's available RAM.

Bounded reproduction: setting `RUST_MIN_STACK=8388608` and running under `ulimit -v 2000000` triggers the OOM deterministically on an 800 MB corpus.

## Resolution

- Cap the candidate-range collection at `max(1_000_000, 4 * limit)` entries; spill to on-disk chunks beyond that.
- Dedup incrementally as ranges are added (hash set keyed on `(doc_id, offset)`) instead of at the end.
- Size the postings mmap window to 64 MB with a sliding remap when queries cross the boundary.

All three land together in the [[fuzzy-search-v2]] branch. Ship alongside the rest of that work — no separate release.

## Steps

- [x] Reproduce locally with the user's query on a synthetic 1 GB corpus. Steps recorded in [`notes/repro.md`](notes/repro.md).
- [x] Capture a debug-build stack trace at the OOM moment. See [`notes/stack-trace.md`](notes/stack-trace.md).
- [x] Draft the three-part fix above; discussed with @mkl.
- [~] Implement incremental dedup + bounded candidate vec on the `search/fuzzy-v2` branch.
- [ ] Implement 64 MB sliding mmap window for `postings.bin`.
- [ ] Add regression test: run a synthetic 1 GB corpus through the full `helio search` path under a 2 GB virtual-memory ulimit.
- [ ] Verify fix against the reporter's original 840 MB corpus (they offered to re-run).
- [ ] Close out — link resolution into the [[fuzzy-search-v2]] timeline.

## Deliverables

- [Incident report](deliverables/incident-report.pdf) — formal write-up for users on the 0.4.0-alpha release list.

## Timeline

- 2026-04-08 — Reported on the mailing list. Reproduced locally within 2 hours. Incident filed.
- 2026-04-09 — Debug-build stack trace captured. Root cause pinned to the candidate vec + mmap sizing combination, not to the scorer itself.
- 2026-04-15 — Fix in progress on the fuzzy-v2 branch; first part (bounded vec + incremental dedup) passes the local repro under a 2 GB ulimit.

## Notes

- [`notes/stack-trace.md`](notes/stack-trace.md) — debug-build stack trace at the OOM moment.
- [`notes/repro.md`](notes/repro.md) — five-step reproduction against a synthetic corpus.

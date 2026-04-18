# fuzzy search v2

**Date**: 2026-04-02
**Kind**: project
**Status**: now
**Apps**: `helio`, `helio-web`
**Branch**: `search/fuzzy-v2`

## Goal

Replace the v1 fuzzy-search backend (naive Levenshtein over a scanned corpus) with a trigram-indexed implementation that returns streaming results. The web dashboard's autocomplete endpoint should share the new index so suggestions stay consistent with CLI results.

Motivating feedback from 0.3 users:

- First-query latency on a 500 MB log archive is 11–14 s on a warm SSD. Users expect sub-second feedback for anything typed interactively.
- The web autocomplete calls `helio search --preview` under the hood and stalls the UI on corpora above 200 MB.
- Ranking surprises — partial identifier matches are ranked below single-character matches because the scorer counts edits before length.

## Scope

**In scope**

- New trigram index module under `helio/search/trigram/` with memory-mapped on-disk representation.
- Streaming CLI output: results emitted as they are scored, not after full-corpus scan.
- `helio-web` suggestions endpoint (`GET /api/search/suggest`) reading the same index.
- Backwards-compatible `helio search` flags; v1 stays available behind `--engine=legacy` for one release.
- Benchmark harness (`bench/search.py`) and a comparison table vs. v1.

**Out of scope**

- Query parser changes (field filters, boolean operators). Tracked separately.
- Persistence of the index across log rotation — a separate incremental-update project.
- Web UI redesign. Only the suggestions endpoint moves; the existing search page is untouched.

## Steps

- [x] Spike: trigram index built over `/var/log/nginx/access.log.*` (2.3 GB), measure build time + query latency against v1.
- [x] Write architecture sketch in [`notes/design.md`](notes/design.md); review with @mkl before committing to the memory-mapped layout.
- [~] Implement trigram index for query strings >3 chars; fall back to substring scan for shorter queries.
- [~] Stream results from scorer to stdout writer; flush every 16 hits or every 50 ms, whichever comes first.
- [ ] Benchmark against 1 GB corpus; record p50/p95/p99 in [`notes/benchmarks/results.md`](notes/benchmarks/results.md).
- [ ] Wire `helio-web` `/api/search/suggest` to the new index; update the CORS allowlist for the dashboard origin.
- [ ] Add `--engine=legacy` flag as a deprecation escape hatch; emit a warning when it is used.
- [-] Investigate a WASM build of the scorer for the web client — dropped, the dashboard already proxies through the API and a WASM path doubles our CI surface for a marginal win.
- [ ] Update CLI reference docs and the `helio-web` API reference.
- [ ] Cut a `0.4.0-rc1` pre-release and ask two beta users to run it against their corpora.

Related: see [[search-crash-large-logs|the OOM incident on this branch]] — reproduced during step 3 while stressing the memory-mapped reader against an 800 MB slice.

## Timeline

- 2026-04-02 — Project created after triage of 0.3 feedback.
- 2026-04-05 — Spike results: trigram index builds in 8.1 s on the 2.3 GB corpus, first query in 180 ms. Committed to the approach.
- 2026-04-08 — OOM filed as `[[search-crash-large-logs]]` during stress testing of the streaming writer. Unblocked same day by a guard on the mmap window.
- 2026-04-15 — In progress. Streaming writer and index builder are wired together; benchmark and API work remain.

## Notes

- [`notes/design.md`](notes/design.md) — architecture sketch, index layout, fallback rules.
- [`notes/benchmarks/results.md`](notes/benchmarks/results.md) — comparison table vs. v1 on three corpus sizes.

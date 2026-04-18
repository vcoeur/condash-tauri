# JSON / NDJSON export for read-only commands

**Date**: 2026-04-15
**Kind**: project
**Status**: soon
**Apps**: `helio`

## Goal

Add `--json` and `--ndjson` output modes to every read-only `helio` subcommand so downstream tools can consume structured results without parsing the human-readable terminal output. The two shapes are deliberately different: `--json` for bounded results (one JSON document), `--ndjson` for streaming (one JSON object per line).

## Scope

**In scope**

- `helio search`, `helio grep`, `helio stats`, `helio index list`, `helio config show` — all gain `--json` and `--ndjson` flags.
- A shared `helio/output/structured.py` module that every command calls through; no ad-hoc json.dumps in command code.
- Stable field names and types — documented in `docs/reference/structured-output.md`.
- Snapshot tests for every command's structured output.

**Out of scope**

- YAML, msgpack, CBOR, or any other serialisation. JSON covers 99% of the demand and the remaining 1% can pipe through `jq | yq`.
- Schema versioning. Until the surface stabilises, structured output is best-effort and users should pin the helio version they consume it from.

## Steps

- [ ] Draft the field naming conventions (snake_case, no `_at` suffix on timestamps because values are ISO 8601 strings, enums as lowercase strings).
- [ ] Implement `helio/output/structured.py` with `writer = StructuredWriter(fmt="json" | "ndjson")` + `writer.emit(record)` / `writer.close()`.
- [ ] Convert `helio search` first — streaming NDJSON is the forcing function that makes sure the writer handles backpressure.
- [ ] Convert the remaining read-only commands; one commit per command for reviewability.
- [ ] Add snapshot tests under `tests/structured/`.
- [ ] Write `docs/reference/structured-output.md` with full field tables and one example per command.
- [ ] Tag a `0.5.0-rc1` pre-release and post to the mailing list for feedback.

## Timeline

- 2026-04-15 — Project created; pulled forward in the sprint plan because both [[fuzzy-search-v2]] and [[cli-config-migration]] will be in users' hands and we want JSON output ready as they start scripting around them.

## Notes

- Stays behind `--json` / `--ndjson` flags rather than setting a config default so existing scripts that scrape terminal output aren't broken silently.
- Logs going over NDJSON specifically is the shape that several enterprise users have asked for; it lines up with `jq -c`.

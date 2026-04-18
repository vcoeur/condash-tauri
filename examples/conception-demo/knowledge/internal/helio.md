# helio — conception-side knowledge

The core CLI. Python entry point + PyO3 Rust extension for the hot paths (index build, trigram scoring, streaming writer).

→ Repo-internal facts (stack, architecture, build, test commands) live in [`../../../helio/CLAUDE.md`](../../../helio/CLAUDE.md) once the demo workspace is populated. In the real project, that file is the source of truth.

## Build quirks

- The PyO3 extension requires Rust 1.78+. Older toolchains build but silently miscompile the mmap bounds check (reported and fixed upstream in PyO3 0.22.1 — pin to that or newer).
- On macOS, the Rust build needs `RUSTFLAGS="-C link-arg=-undefined -C link-arg=dynamic_lookup"` exported at build time, not just at `cargo build` time. The `Makefile` handles this but hand-running `cargo build` from the repo root will produce a broken binary.

## Driving from the sandbox

For screenshot captures, benchmarks, or incident reproductions from Claude Code:

```bash
# Assume the workspace path is /tmp/conception-demo-workspace.
cd /tmp/conception-demo-workspace/helio
make install-dev       # uv-backed venv, editable install + dev extras
.venv/bin/helio --version
```

Don't run the real install against `/home/alice/src/` — the demo workspace is the correct sandbox for any helio exercise driven from this conception tree.

## Benchmarking

See [`../topics/performance.md`](../topics/performance.md) for the shared methodology. The `bench/search.py` harness in the helio repo calls `fakelog` under the hood; pin the seed so re-runs compare like with like.

## Rename history

- Pre-0.1 project name was `loglens`. Occasional references may surface in old GitHub Discussions threads; treat them as referring to the current helio.
- The subcommand formerly called `helio scan` was renamed to `helio grep` in 0.2 to match user expectations. Old scripts may still use `scan`; the CLI keeps `scan` as a hidden alias for backwards compatibility.

## Cross-repo gotchas

- [[fuzzy-search-v2]] changes the index file format. When the search branch lands, `helio-web`'s suggestions endpoint must be bumped to a matching version; running a 0.3 `helio-web` against a 0.4 `helio` index will fail on the `MANIFEST` version check, returning HTTP 500. The coordinated release checklist in [`../topics/releases.md`](../topics/releases.md) covers this implicitly (lockstep versioning) but worth calling out for any independent deploys.

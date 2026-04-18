# 2026-04

Items created in 2026-04. One bullet per folder. Descriptions and tags are hand-curated for the demo tree.

## Items

- [`2026-04-02-fuzzy-search-v2/`](2026-04-02-fuzzy-search-v2/README.md) — *Rewrite the `helio search` command on a trigram index, with streaming results and a matching web-UI suggestions endpoint; closing a long-standing cold-start latency gap.* `[project, now, helio, helio-web, search, performance]`
- [`2026-04-08-search-crash-large-logs/`](2026-04-08-search-crash-large-logs/README.md) — *`helio search` segfaults against corpora above ~800 MB on the trigram-index branch; PROD user hit a reproducible OOM while mining a week of nginx logs.* `[incident, now, helio, search, crash, high]`
- [`2026-04-10-plugin-api-proposal/`](2026-04-10-plugin-api-proposal/README.md) — *Design document exploring a minimal plugin surface for helio — lifecycle hooks, configuration, sandboxing — so third parties can add log parsers without forking.* `[document, now, helio, plugin-api, design]`
- [`2026-04-12-cli-config-migration/`](2026-04-12-cli-config-migration/README.md) — *Move `~/.config/helio/config.ini` to a layered TOML scheme (user + project + env), with a one-shot migration and deprecation warning for the legacy path.* `[project, review, helio, config, migration]`
- [`2026-04-15-json-export/`](2026-04-15-json-export/README.md) — *Add `--json` / `--ndjson` output modes to every read-only helio subcommand so downstream tools can consume structured results without parsing terminal output.* `[project, soon, helio, output, json]`
- [`2026-04-16-windows-installer/`](2026-04-16-windows-installer/README.md) — *MSI installer for helio on Windows with PATH wiring and an uninstaller; deferred because Windows usage is under 3% of downloads and the Scoop recipe covers the vocal minority.* `[project, later, helio, windows, packaging]`
- [`2026-04-17-plugin-api/`](2026-04-17-plugin-api/README.md) — *Implement the plugin surface sketched in the proposal document — entry-point discovery, lifecycle hooks, per-plugin configuration, an example parser plugin, and reference docs.* `[project, backlog, helio, plugin-api]`

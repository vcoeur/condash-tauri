# plugin API implementation

**Date**: 2026-04-17
**Kind**: project
**Status**: backlog
**Apps**: `helio`

## Goal

Implement the plugin surface sketched in [[plugin-api-proposal|the plugin-api design document]] — entry-point discovery, lifecycle hooks, per-plugin configuration, and a worked example parser plugin — then cut a release that advertises the capability.

## Scope (follows [[plugin-api-proposal]])

**In scope**

- Entry-point discovery via `importlib.metadata.entry_points(group="helio.parsers")`.
- Plugin protocol class in `helio/plugins/__init__.py`: `on_load`, `parse_record`, `teardown`.
- Per-plugin config section in the layered TOML scheme shipped by [[cli-config-migration]].
- Failure isolation: one broken plugin logs a warning and skips itself; it does not bring down the CLI.
- Example plugin `helio-parser-systemd` published to PyPI.
- Reference docs: `docs/reference/plugins.md` + a tutorial in `docs/guides/write-a-parser.md`.

**Out of scope** (until we have experience with the parser plugin kind)

- Non-parser plugin kinds.
- Hot-reload or live-install flows.
- A plugin marketplace or discovery endpoint.

## Steps

- [ ] Wait for [[plugin-api-proposal]] to reach v1 and be signed off.
- [ ] Stand up the discovery + protocol class; load every advertised plugin on startup.
- [ ] Add per-plugin config section support; test with two conflicting plugin configs.
- [ ] Wire plugin-parsed records into the ingestion path; verify ordering vs. built-in parsers.
- [ ] Build `helio-parser-systemd` against the final API; publish v0.1.0 to PyPI.
- [ ] Write tutorial and reference docs; include the systemd plugin as the worked example.
- [ ] Cut `0.5.0` and announce plugin support.

## Timeline

- 2026-04-17 — Item filed. Blocked on the proposal document.

## Notes

Deliberately in backlog, not soon: the proposal document is still in active review and we do not want to start implementation against a moving target. When that sign-off lands, promote this item to `now`.

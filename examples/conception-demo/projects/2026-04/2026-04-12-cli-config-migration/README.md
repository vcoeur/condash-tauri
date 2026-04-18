# CLI config migration to layered TOML

**Date**: 2026-04-12
**Kind**: project
**Status**: review
**Apps**: `helio`
**Branch**: `config/layered-toml`

## Goal

Move helio's configuration from a single flat `~/.config/helio/config.ini` to a three-layer TOML scheme — system defaults, user config, project-local override — merged deterministically at load time. Ship a one-shot migration that reads the legacy INI and writes the new TOML, with a deprecation warning on the legacy path for one release.

## Scope

**In scope**

- TOML loader in `helio/config/layered.py` with well-specified merge order (system < user < project < env).
- Migration command `helio config migrate` — idempotent, dry-run by default, writes backups of any existing files.
- Deprecation warning on first use of the legacy INI path; silenceable with `HELIO_NO_DEPRECATION=1`.
- Documentation update in `docs/reference/configuration.md`.

**Out of scope**

- New configuration keys. Only the transport changes.
- Per-command overrides via the CLI — already supported, no change.
- Environment-variable naming scheme — already uses `HELIO_*`, no change.

## Steps

- [x] Inventory every config key currently read from the INI; produce a migration map.
- [x] Implement the TOML loader with a layered merge; unit tests cover all precedence combinations.
- [x] Implement `helio config migrate`; manual test against three real user configs shared by the beta group.
- [x] Wire the loader into every CLI entry point; remove the INI reader.
- [x] Add the deprecation warning at the one surviving legacy-path call site.
- [x] Update `docs/reference/configuration.md` with the new layer diagram and the migration walkthrough.
- [x] `make test && make format && make lint` — clean.
- [~] PR open, awaiting review from @mkl. Two inline comments outstanding on the precedence-rules section of the docs.
- [ ] Merge after review; ship in the next helio point release.

## Timeline

- 2026-04-12 — Project created.
- 2026-04-13 — Inventory + loader implemented. 34 new unit tests.
- 2026-04-14 — `helio config migrate` working against the beta configs. No data loss.
- 2026-04-16 — PR opened against `main`. Awaiting review.

## Notes

- The legacy INI path was read in three places; two are trivial and one (the `helio completion install` script) needed more care because it writes a derived file next to the config. Handled by preferring the resolved TOML path whenever it exists.
- The layered scheme lines up with what [[plugin-api-proposal]] assumes for plugin-scoped configuration sections — one less blocker when that lands.

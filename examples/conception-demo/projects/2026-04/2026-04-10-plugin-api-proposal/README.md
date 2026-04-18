# plugin API proposal

**Date**: 2026-04-10
**Kind**: document
**Status**: now
**Apps**: `helio`
**Languages**: en

## Goal

A design document exploring what a minimal, safe plugin surface for helio would look like. Deliverable is a self-contained PDF that we can circulate to two or three external contributors and iterate on before committing implementation time. The follow-on implementation item is [[plugin-api|plugin-api (backlog)]].

## Scope

**In scope**

- Use cases: log parsers for non-standard formats (systemd journal, Kubernetes audit, proprietary app logs).
- Proposed entry-point discovery via Python `entry_points` group `helio.parsers`.
- Lifecycle hooks: `on_load`, `parse_record`, `teardown`. No mutation of core helio state.
- Configuration surface: plugin-scoped config sections in the layered TOML scheme from [[cli-config-migration]].
- Sandboxing boundary: what plugins can and cannot reach. Expected answer: read-only access to the incoming record, no filesystem, no network, explicit opt-in for sidecar files.
- Example plugin walkthrough: `helio-parser-systemd` in 80 lines.

**Out of scope**

- Non-parser plugin types (scorers, exporters). They may exist eventually, but we want to ship one plugin kind and learn before multiplying surface.
- A WASM sandbox — too much engineering for the initial audience.
- A plugin marketplace or discovery UI — third parties install plugins the normal Python way (`pipx install helio-parser-systemd`).

## Steps

- [x] Gather the three community threads asking for parser extension points; summarise in the document's motivation section.
- [x] Sketch the `parse_record` protocol with two example implementations (systemd, k8s audit).
- [~] Write the sandboxing section — specifically what "read-only access to the record" means in a Python plugin world where nothing is truly read-only.
- [ ] Circulate the draft PDF to @mkl, @pri, @tal for written review.
- [ ] Incorporate feedback; bump to v1.
- [ ] Link the implementation follow-on ([[plugin-api]]) once the proposal is accepted.

## Timeline

- 2026-04-10 — Document created. First outline in place.
- 2026-04-14 — Sections 1–3 drafted. Sandboxing section (section 4) is the main remaining work.

## Deliverables

- [Plugin API proposal](deliverables/plugin-api-proposal.pdf) — current draft PDF.

## Notes

The document deliberately stays at "minimum viable" scope. Earlier feedback on the 0.2-era plugin sketch was that we overshot by proposing scorers, exporters, and parsers all at once. This time: one plugin kind, learn, iterate.

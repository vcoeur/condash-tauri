# helio 0.3 release

**Date**: 2026-03-20
**Kind**: project
**Status**: done
**Apps**: `helio`, `helio-web`, `helio-docs`

## Goal

Tag and ship helio 0.3 across all three repos with coordinated release notes, Homebrew-tap bump, and a staged docs deploy.

## Scope

**In scope**

- `helio` 0.3.0 — changelog, tag, GitHub Release, PyPI upload, Homebrew tap bump.
- `helio-web` 0.3.0 — bumped to match, Docker image published, demo site redeployed.
- `helio-docs` rebuild against 0.3 — new pages for any new CLI flags, version selector updated.
- Coordinated announcement on the mailing list once all three are live.

## Steps

- [x] Cut release branches in the three repos.
- [x] Update CHANGELOGs with the user-visible summary.
- [x] Run the full test suites locally and on CI.
- [x] Tag `v0.3.0` in all three; attach built artifacts to the GitHub Releases.
- [x] Push to PyPI (helio) + Docker Hub (helio-web).
- [x] Bump the Homebrew tap; verify `brew upgrade helio` pulls the new version cleanly.
- [x] Deploy the new docs site; verify all nav links.
- [x] Send the announcement email.

## Resolution

All three shipped on 2026-03-20 within a 2-hour window. Announcement went out the same evening.

A follow-on low-severity incident was filed on 2026-03-25 — [[docs-site-404s|docs-site 404s]] — caused by a stale `site/` build committed over the fresh one during the release-branch cleanup. Resolved within the day, no user action required.

## Timeline

- 2026-03-20 — Release cut, tagged, published, announced.
- 2026-03-25 — Post-release docs outage filed as a separate incident.

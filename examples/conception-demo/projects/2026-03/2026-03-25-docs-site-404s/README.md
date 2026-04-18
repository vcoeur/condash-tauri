# helio-docs 404s after 0.3 deploy

**Date**: 2026-03-25
**Kind**: incident
**Status**: done
**Apps**: `helio-docs`
**Environment**: PROD — helio-docs.example.com, post 0.3 deploy
**Severity**: low — every guide page under `/guides/*` returned 404 for ~40 minutes; root and reference pages were unaffected

## Description

After the 0.3 coordinated release ([[helio-0.3-release]]), a user on the mailing list reported that `/guides/getting-started/` 404'd. Quick spot-check confirmed every page under `/guides/*` was missing; `/reference/*` and the landing page rendered fine.

## Impact

- 40-minute window during which the guides section of the docs was unreachable.
- Limited traffic impact — analytics show ~28 unique sessions hit a 404 during the outage.
- No data loss; underlying MkDocs source was intact.

## Root cause

During release-branch cleanup, a stale `site/` build from a pre-release preview was accidentally committed over the fresh build. The pre-release preview was cut before the guides section was renamed from `/tutorials/*` to `/guides/*`, so the stale `site/` had the old paths.

The deploy script uploads `site/` verbatim, so production immediately picked up the stale artefact. CI did not catch this because the stale artefact is, in isolation, a valid site; it just contains the wrong paths.

## Resolution

- Rebuild `site/` from the release-branch sources; redeploy.
- Add `site/` to `.gitignore` in the `helio-docs` repo — there is no reason to version the built output.
- Add a post-deploy smoke test that curls three representative pages (root, one reference page, one guide page) and fails if any returns a non-2xx status.

## Steps

- [x] Reproduce: `curl -I https://helio-docs.example.com/guides/getting-started/` returns 404.
- [x] Rebuild `site/` locally from the release-branch sources; diff against what was deployed — confirmed 51 guide pages missing.
- [x] Redeploy; verify all three representative pages return 200.
- [x] Add `site/` to `.gitignore`; `git rm -r --cached site/` in a follow-up commit.
- [x] Add the post-deploy smoke test; wire into the release workflow.
- [x] Post a short incident note to the mailing list.

## Timeline

- 2026-03-25 14:12 — First report from the mailing list.
- 2026-03-25 14:18 — Reproduced and root cause identified (stale `site/`).
- 2026-03-25 14:34 — Fresh `site/` redeployed. All guide pages return 200.
- 2026-03-25 14:52 — `.gitignore` + post-deploy smoke test merged. Incident closed.
- 2026-03-25 — Short incident note sent to the mailing list.

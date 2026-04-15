# First incident — seed the dashboard

**Date**: 2026-04-15
**Status**: now
**Apps**: `example-app`
**Environment**: `prod`
**Severity**: `minor`

## Symptom

What the user or the monitoring reported. Be specific about the observed behaviour:

- What happened.
- What was expected.
- Where it was observed (URL, endpoint, log source).
- How to reproduce it, if known.

One short paragraph. Details go in the investigation notes.

## Impact

Who is affected and how badly. Example:

- ~20 logged-in users on `example-app` see a blank screen after clicking "Save".
- Workaround available: reloading the page.
- No data loss observed.

## Steps

- [ ] Reproduce in the staging environment
- [ ] Identify the failing call
- [ ] Ship the fix
- [ ] Write the post-mortem

## Timeline

- 2026-04-15 — Incident reported

## Notes

_None yet._

Common notes to add as the investigation progresses:

```markdown
- [`notes/reproduction.md`](notes/reproduction.md) — steps that reliably trigger the bug
- [`notes/root-cause.md`](notes/root-cause.md) — what actually broke
- [`rapport-technique.md`](rapport-technique.md) → `rapport-technique.pdf` — full post-mortem
```

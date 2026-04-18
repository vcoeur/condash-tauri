# Release checklist

Coordinated releases across `helio`, `helio-web`, and `helio-docs`. All three ship together — a user running `brew upgrade` and then visiting the docs site should see a consistent version everywhere.

## Preflight

- [ ] Every open PR for this milestone is merged or explicitly deferred.
- [ ] `CHANGELOG.md` in each repo has an entry for the new version, written in user-visible terms.
- [ ] `make test` green in all three repos locally.
- [ ] Benchmarks (for `helio`) have been re-run if any search or scoring code changed since the last release — see [`performance.md`](performance.md).
- [ ] Draft release notes prepared in the helio repo's `docs/releases/<version>.md`.

## Cut

1. Create release branches `release/<version>` in all three repos.
2. Bump version numbers:
   - `helio/pyproject.toml` and `helio/helio/__init__.py::__version__`.
   - `helio-web/package.json`.
   - `helio-docs/mkdocs.yml` (for the version selector) and `helio-docs/pyproject.toml`.
3. Open one PR per repo titled `Release <version>`.
4. Merge to `main` once CI is green in all three.
5. Tag `v<version>` in all three. Push tags.

## Publish

- helio → PyPI via `make publish`. Homebrew tap auto-bumps from the GitHub Release.
- helio-web → Docker Hub via the tagged-push CI workflow.
- helio-docs → GitHub Pages deploy via the tagged-push CI workflow.

## Verify

- [ ] `pip install helio==<version>` works in a clean venv and `helio --version` matches.
- [ ] `brew upgrade helio` pulls the new version on a machine that had the previous one installed.
- [ ] `docker pull helio-web:<version>` works and the container starts.
- [ ] `https://helio-docs.example.com/` shows the new version in the version selector.
- [ ] Post-deploy smoke test on `helio-docs` returns 200 on three representative pages (root, one reference page, one guide page) — added after [[docs-site-404s]].

## Announce

- [ ] Mailing list post: short summary, link to release notes, link to docs.
- [ ] GitHub Discussions post: same content, pinned for one week.

## Anti-patterns (learned from [[docs-site-404s]])

- Do not commit `site/` artefacts into the helio-docs repo. The deploy workflow builds from source — a versioned `site/` dir is only ever a source of drift.
- The post-deploy smoke test must run after every deploy, not only on release. Point releases and docs-only fixes deploy the same way.

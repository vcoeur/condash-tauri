# Windows MSI installer

**Date**: 2026-04-16
**Kind**: project
**Status**: later
**Apps**: `helio`

## Status note

Deferred in the 2026-04 sprint planning. The decision was driven by:

- Windows accounts for 2.7% of download traffic on GitHub releases (vs. 61% Linux, 36% macOS). The requesting cohort is small and already served by the existing Scoop bucket.
- Building an MSI properly requires signing with a Windows code-signing certificate (~€250/year) plus CI-side infrastructure we would have to stand up.
- The [[fuzzy-search-v2]] and [[plugin-api]] lines of work are more leveraged for the broader user base.

Revisit at the 0.5 planning cycle if download telemetry shifts, or earlier if a downstream consumer brings the code-signing cost to the project.

## Goal (when this moves to `now`)

Ship a signed Windows MSI installer for helio that:

- Installs to `%PROGRAMFILES%\helio\`.
- Adds `helio.exe` to the user `PATH`.
- Registers a proper uninstaller entry in "Installed apps".
- Uses an Authenticode-signed binary to avoid SmartScreen warnings on first run.

## Scope (provisional)

**In scope**

- WiX Toolset-based MSI packaging.
- GitHub Actions workflow to build + sign on `windows-latest`.
- Release flow integration: the MSI is attached to every GitHub Release alongside the Linux/macOS binaries.
- A Scoop manifest update so the Scoop install path remains supported for power users.

**Out of scope**

- Microsoft Store distribution.
- winget manifest — separate smaller item once the MSI is stable.
- ARM64 Windows support — single architecture (x86_64) for the first installer.

## Steps

- [ ] Decide on code-signing provider and fund the first year.
- [ ] Prototype the MSI locally with WiX against the 0.3 binary.
- [ ] Stand up the signing workflow on CI (secret handling, timestamped signatures).
- [ ] Integrate into the release workflow.
- [ ] Document Windows install path in `docs/install.md`.
- [ ] Announce on the mailing list + GitHub Discussions.

## Timeline

- 2026-04-16 — Project filed as `later`; deferred at sprint planning. Pointer kept here so the context survives.

---
title: Install the desktop app (Tauri) · condash guide
description: How to install the unsigned Tauri build of condash on Linux, macOS, and Windows — including the one-time bypass gesture each OS asks for.
---

# Install the desktop app

**When to read this.** You downloaded a `condash-<platform>` binary (or an `.msi` / `.dmg` / `.AppImage` once those bundlers land) from the GitHub Releases page and the operating system is refusing to run it.

The Tauri builds of condash are **unsigned** on purpose. Signing Windows and macOS binaries costs $180–400/year between code-signing certs and the Apple Developer Program, and condash has exactly one user. See [`notes/packaging.md`][notes] in the project repo for the full reasoning.

The upshot: each OS will ask you to confirm once that you trust the download. This page walks through the gesture per platform.

[notes]: https://github.com/vcoeur/conception/blob/main/projects/2026-04/2026-04-21-condash-rust-tauri-port/notes/packaging.md

## Linux — AppImage or raw binary

Nothing to bypass. Linux trusts you.

```bash
chmod +x condash-serve-linux-x86_64
./condash-serve-linux-x86_64
```

or, once the AppImage bundler lands:

```bash
chmod +x condash-<version>.AppImage
./condash-<version>.AppImage
```

If the window doesn't appear, check the stderr log — a missing `CONDASH_CONCEPTION_PATH` or webkit runtime usually shows up there.

## Windows — SmartScreen bypass

1. Download the `.msi` (or the `condash-serve-windows-x86_64.exe` binary) from the release page.
2. Double-click it. Windows dims the screen and shows a blue banner:

   > **Windows protected your PC**
   >
   > Microsoft Defender SmartScreen prevented an unrecognized app from starting.

3. Click the small **More info** link under the banner. A **Run anyway** button appears at the bottom.
4. Click **Run anyway**. The installer / binary launches normally.

You only have to do this on first launch. Windows remembers the per-file decision afterwards, but a new release (different bytes) triggers the same dialog again — this is expected without a code-signing cert.

## macOS — Gatekeeper bypass

macOS keeps tightening Gatekeeper. The steps depend on your version.

### macOS 14 (Sonoma) and earlier

1. Download the `.dmg` and drag `condash.app` to `/Applications` as usual.
2. Open Finder, navigate to `/Applications`, find `condash.app`.
3. **Control-click (or right-click)** the app icon → **Open**.
4. macOS shows: "condash can't be opened because the developer cannot be verified. Are you sure you want to open it?"
5. Click **Open**. The app launches and the approval is remembered.

### macOS 15 (Sequoia) and later

Apple removed the right-click bypass in Sequoia. The new path:

1. Double-click the app. macOS refuses with: "condash cannot be opened because the developer cannot be verified" (or similar).
2. Dismiss the dialog.
3. Open **System Settings → Privacy & Security**.
4. Scroll to the bottom. You'll see a banner like: "condash was blocked from use because it is not from an identified developer."
5. Click **Open Anyway**. Authenticate with your login password when prompted.
6. Relaunch the app. It opens normally, and the approval is remembered.

### If the app still won't open

macOS sometimes flags the downloaded `.dmg` as "damaged" instead of prompting. This is a quarantine attribute issue. Clear it from Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/condash.app
```

…then try again. You may still need to click **Open Anyway** the first time.

## Why no auto-update?

Tauri can ship in-app updates, but unsigned apps on macOS hit a quarantine bug: when the updater replaces the app bundle, macOS re-flags the new files and the relaunched binary silently fails. To avoid the failure mode where updates half-break the install, **the auto-updater is disabled for this build**.

Instead:

- The dashboard footer links to the GitHub Releases page.
- Bumping versions = download the new artifact, drop it over the old one, redo the bypass gesture once.

If condash ever ships to more than one user, [`notes/packaging.md`][notes] lays out the re-enable path: $99/year Apple Developer enrolment, Developer ID signing cert, notarization in the release workflow, then flipping `bundle.updater.active` back on.

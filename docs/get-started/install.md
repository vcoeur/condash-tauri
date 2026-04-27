---
title: Install · condash
description: Download and launch the unsigned Tauri build of condash on Linux, macOS, or Windows — including the one-time bypass gesture each OS asks for.
---

# Install

**When to read this.** You downloaded condash from the GitHub Releases page and your OS is asking whether to trust it.

The Tauri builds of condash are **unsigned on purpose**. Signing Windows and macOS binaries costs $180–400/year in cert fees, and condash is a single-developer tool. Each OS asks you to confirm the download once on first launch; this page walks through the gesture per platform.

## Download

> **Debian/Ubuntu users**: skip the download and jump to [Linux — apt repository](#linux--apt-repository-recommended) below — `apt` will fetch the package and keep it up to date for you.

Start at the [latest release page](https://github.com/vcoeur/condash-tauri/releases/latest) and pick the artifact for your OS:

| OS | Artifact | Typical size |
|---|---|---|
| Linux | `condash_<version>_amd64.AppImage` | ~90 MB |
| Linux (Debian/Ubuntu) | `condash_<version>_amd64.deb` | ~30 MB |
| macOS | `condash_<version>_<arch>.dmg` | ~50 MB |
| Windows | `condash_<version>_x64_en-US.msi` | ~20 MB |

If the page says "No releases" or looks empty, the latest version may still be in draft state. Check **[All releases](https://github.com/vcoeur/condash-tauri/releases)** — draft releases are visible to the repo maintainer only. See **[Releases](releases.md)** for the full story.

## Linux — AppImage

```bash
chmod +x condash_*_amd64.AppImage
./condash_*_amd64.AppImage
```

That's it. Linux trusts you.

If the window doesn't appear, check stderr — a missing WebKitGTK runtime is the usual culprit. Install it with your distro's package manager:

```bash
sudo apt install libwebkit2gtk-4.1-0 libayatana-appindicator3-1   # Debian/Ubuntu
sudo dnf install webkit2gtk4.1 libappindicator-gtk3               # Fedora
```

## Linux — apt repository (recommended)

A signed apt repository at `condash-tauri.vcoeur.com/apt/` lets `apt` track new versions for you — `apt upgrade` becomes the update mechanism.

One-time setup:

```bash
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://condash-tauri.vcoeur.com/apt/pubkey.asc \
  | sudo gpg --dearmor -o /etc/apt/keyrings/condash.gpg
echo "deb [signed-by=/etc/apt/keyrings/condash.gpg] https://condash-tauri.vcoeur.com/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/condash.list

sudo apt update
sudo apt install condash
```

Updates from then on are just:

```bash
sudo apt update && sudo apt upgrade
```

The repository is signed with key fingerprint `BC6C 98E8 D6D8 0FFB C408 057F D1D6 9E3E 4A00 5621`.

## Linux — `.deb` (one-off)

If you don't want to add a repository, install a downloaded `.deb` directly:

```bash
sudo apt install ./condash_*_amd64.deb
condash
```

Apt pulls in the GTK + WebKit deps automatically. Updates require re-running this for every new release.

## macOS — Gatekeeper bypass

macOS tightens Gatekeeper with each release; the bypass gesture depends on your version.

### macOS 14 (Sonoma) and earlier

1. Double-click the `.dmg` and drag `condash.app` to `/Applications`.
2. In Finder, **control-click** `condash.app` → **Open**.
3. macOS shows "condash can't be opened because the developer cannot be verified. Are you sure you want to open it?" — click **Open**.

### macOS 15 (Sequoia) and later

Apple removed the control-click bypass in Sequoia.

1. Double-click `condash.app`. macOS refuses with "condash cannot be opened…".
2. Dismiss the dialog.
3. Open **System Settings → Privacy & Security**.
4. Scroll to the bottom — you'll see "condash was blocked from use because it is not from an identified developer" with an **Open Anyway** button.
5. Click **Open Anyway** and authenticate. Relaunch; condash opens normally.

### If the app still won't open

macOS sometimes flags the `.dmg` as "damaged". Clear the quarantine attribute:

```bash
xattr -dr com.apple.quarantine /Applications/condash.app
```

Then click **Open Anyway** once. The decision is remembered.

## Windows — SmartScreen bypass

1. Double-click the `.msi`. Windows dims the screen and shows "Windows protected your PC".
2. Click the small **More info** link under the banner.
3. Click the **Run anyway** button that appears.

The installer runs normally. You only do this on first launch — but a new release (different bytes) triggers the same dialog again, which is expected for unsigned binaries.

## After install

The first time you launch condash, it opens a folder picker and asks you to select your conception tree. See **[First launch](first-launch.md)** for what that is and how to set it up.

## Why no auto-update?

Unsigned apps on macOS hit a quarantine bug when Tauri's in-app updater replaces the app bundle — macOS re-flags the new files and the relaunched binary fails silently. To avoid partially-broken installs, **the in-app auto-updater is disabled**.

For everything except apt, updating is a manual download:

- Check **[Releases](releases.md)** occasionally, or watch the repo on GitHub.
- Download the new artifact.
- Drop it over the old one (Linux AppImage) or run the installer / DMG (Windows / macOS).
- Redo the bypass gesture once on the first post-update launch.

**Debian/Ubuntu users who installed via the apt repository above are exempt** — `sudo apt update && sudo apt upgrade` picks up new condash versions automatically.

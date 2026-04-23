---
title: Inline dev-server runner · condash reference
description: The per-repo Run/Stop button, the `run:` field, and the single-session-per-repo lock that ties the Code tab to live dev servers.
---

# Inline dev-server runner

Since v0.13.0, each row in the Code tab — every repo and every declared sub-repo — can carry an inline dev-server runner. Click **Run** and condash spawns the command under a PTY; an xterm mounts right under the row streaming live output. The running server survives tab switches, terminal toggles, and even dashboard reloads (the registry lives server-side).

## When to reach for it

- You want to see your frontend rebuild output next to your item card instead of tabbing into a separate terminal.
- You want a one-click way to restart a dev server from whichever checkout you're currently on — main, a worktree, doesn't matter, the button is in the same place.
- You want the dashboard to notice, automatically, when your dev server exits with a non-zero status.

For one-off commands (a test run, a manual repro), keep using the embedded terminal — see [Use the embedded terminal](../guides/terminal.md). The runner is specifically for **long-running** dev processes.

## Configuring a runner

The runner is opt-in per repo and per sub-repo. Declare it in [`configuration.yml`](config.md#repositories) with the `run:` field:

```yaml
repositories:
  primary:
    # Bare string → no runner
    - conception

    # Inline map with `run` → single-level runner
    - { name: notes.vcoeur.com, run: "make dev" }

    # Parent repo with per-submodule runners
    - name: helio
      run: "cargo watch -x run"
      submodules:
        - { name: apps/web, run: "npm --prefix apps/web run dev" }
        - apps/api              # bare string → parent's run: doesn't inherit
```

Rules:

- **`run`** is a single shell-style string. The runner executes it via the configured shell with `-lc`, so `make dev`, pipes, `&&`, environment variables from `~/.bashrc`, and shell builtins all behave as you'd expect.
- **`{path}`** in the template is substituted with the absolute path of the checkout the click originated from (main or a worktree). Omit it and the command runs with `cwd` set to that checkout — either form works.
- **Inheritance is off.** A parent's `run:` doesn't cascade to its submodules; a submodule without its own `run:` has no Run button. This is deliberate — a repo's top-level dev command is almost never what a subdir wants.
- `run` lives on the inline-map form. If you still have a bare-string repo entry, promote it to `{ name: …, run: "…" }` when you add a runner.

The gear modal's YAML editor lets you tweak `run:` directly in `configuration.yml` — no special UI.

## The Run button lifecycle

Each Code-tab row with a configured `run` gets one of three button states, plus a green jump-arrow when a session is live somewhere else.

| State | What you see | What Run does |
|---|---|---|
| **Idle** | `▶ Run` | Starts the command under a PTY. An xterm mounts inline and begins streaming. |
| **Running (this checkout)** | `■ Stop` | Sends `SIGTERM` to the PTY's child process group. After a brief grace period, the PTY closes and the session flips to `exited: <code>`. |
| **Running (elsewhere)** | `↪ Switch here` + green arrow in the row header | The single runner lock is held by another checkout of this repo (main vs. worktree, or vice-versa). Clicking moves the session — stops the current one, starts a new one pinned to this checkout. |
| **Exited** | `▶ Re-run` and `exited: <code>` pill | The PTY has died. The xterm stays mounted showing the final output until you click Stop (remove) or Re-run (spawn a fresh session). |

### The single-session-per-repo lock

Exactly one runner session lives at a time per `<repo>` (top-level) or `<repo>--<submodule>` (sub-repo) key. The key is deliberately repo-scoped, not checkout-scoped: main and every worktree share it. If you click Run on worktree `feat/foo` while the session is already up on main, the dashboard shows `Switch here` instead of a second Run button — two parallel dev servers for the same app would race on the same port, so the UI refuses the footgun.

The jump-arrow next to the repo name lets you scroll to wherever the session is currently mounted without tearing it down.

## The inline xterm

- **Replays on reconnect.** Up to 256 KiB of trailing output is held in a per-session ring buffer. When the websocket reattaches (tab switch, page reload, network blip), the xterm replays the buffer so you don't lose the last stack trace.
- **Pop-out modal.** Click the expand icon on the xterm and a modal takes over the viewport, attached to the same PTY. Closing the modal re-attaches the inline xterm. You can freely switch back and forth — it's one PTY, two views.
- **Input is allowed.** The xterm is a full TTY: `q` to quit a long-running reporter, arrow keys, `Ctrl+C`. If your dev tool has an interactive REPL (vite, bun, a Django management shell), it works.
- **Resize follows the container.** The PTY's `winsize` is updated whenever the container resizes, so long log lines wrap at the right width.

## HTTP and WebSocket routes

For automation or integration:

| Route | Method | Purpose |
|---|---|---|
| `/api/runner/start` | `POST` | Body: `{key, checkout_key}`. Starts the session if idle; no-ops if already running at the given checkout; returns the new location if already running elsewhere. |
| `/api/runner/stop` | `POST` | Body: `{key}`. Stops the session and removes it from the registry. Safe to call on an already-stopped key. |
| `/ws/runner/<key>` | WebSocket | Attach to the PTY. Server sends binary frames of raw terminal output plus the ring-buffer replay on connect. Client frames: JSON `{type: "input", data: "..."}` or `{type: "resize", cols, rows}`. |

See [HTTP and WebSocket API](http-api.md) for the general route reference.

## Fingerprints and auto-refresh

Runner state is folded into the repo-strip fingerprint, so `/check-updates` (the 5 s poll) picks up Run/Stop/exit transitions without a full page reload. A single row's fragment is what gets re-rendered — the rest of the Code tab stays byte-identical. See [internals — fingerprints](../explanation/internals.md#fingerprints-why-the-ui-doesnt-flicker) for why this matters.

## Lifetime

- A session stays alive for as long as the child process is running, regardless of whether any websocket is attached.
- On clean shutdown (`condash` terminated via SIGTERM or the Tauri window closed) every registered runner is reaped: `SIGTERM`, brief wait, `SIGKILL` on a process group basis.
- On a dirty crash (OOM, kill -9 on condash itself) the children are orphaned; you'll find them in `ps` under PID 1. This is the same footprint as the embedded terminal — condash does not install a double-fork sentinel.

## Known limits

- No backoff on rapid Run/Stop cycles — a pathological loop will fork-spawn without throttling. If you're scripting against the API, rate-limit client-side.
- No per-session environment override. The spawned shell inherits condash's process environment, so `PATH`, `LANG`, and `TERM` come from wherever you launched condash. Set `env` in your `Makefile` or a wrapper script if you need a clean slate.
- No cross-repo dependency model. Two repos that should "start together" still need two clicks (or a `make` target in a third repo that invokes both).

## See also

- [Repositories and open-with buttons](../guides/repositories-and-open-with.md) — the related but distinct "launcher slots" that open external IDEs rather than PTY-owned processes.
- [Use the embedded terminal](../guides/terminal.md) — the sibling surface for ad-hoc commands.
- [Config files — `repositories`](config.md#repositories) — the broader schema the `run:` field sits inside.

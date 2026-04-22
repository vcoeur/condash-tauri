//! Inline dev-server runner registry — Rust port of `runners.py`.
//!
//! Each repo (or sub-repo) with a `run:` template in `repositories.yml`
//! gets a keyed slot here. `/api/runner/start` spawns a PTY under
//! [`PtyRegistry`][crate::pty::PtyRegistry] and stashes it in the
//! registry; `/api/runner/stop` SIGTERMs + SIGKILLs with a grace window.
//! `/ws/runner/:key` attaches a live viewer to an existing session — it
//! does not spawn on miss (the Code tab always drives spawn through the
//! HTTP endpoint first).
//!
//! Unlike plain terminals, runner sessions survive *exit* — the UI
//! shows `exited: N` until the user clicks Stop, at which point the
//! registry entry is cleared. The PTY's pump thread writes the final
//! exit code into [`RunnerSession::exit_code`] so the fingerprint layer
//! emits `|run:exit:<stamp>:<code>` instead of `|run:run:<stamp>:<ck>`.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::SystemTime;

use crate::pty::PtySession;

/// Monotonic stamp — bumped on every `start` / `exit` event so the
/// fingerprint layer can distinguish two otherwise-identical states
/// ("exited:42" a few seconds apart isn't the same event).
static STAMP_COUNTER: AtomicU64 = AtomicU64::new(0);

fn next_stamp() -> u64 {
    STAMP_COUNTER.fetch_add(1, Ordering::SeqCst) + 1
}

/// One live (or recently exited) runner. `pty` is `None` only after
/// the session is cleared; while live, it carries the shared
/// [`PtySession`] the PTY handler attaches to.
pub struct RunnerSession {
    pub key: String,
    pub checkout_key: String,
    pub path: String,
    pub template: String,
    pub shell: String,
    pub started_at: SystemTime,
    pub pty: Arc<PtySession>,
    pub stamp: Mutex<u64>,
    pub exit_code: Mutex<Option<i32>>,
}

impl RunnerSession {
    pub fn stamp_now(&self) -> u64 {
        *self.stamp.lock().expect("stamp mutex")
    }
    pub fn exit_code_now(&self) -> Option<i32> {
        *self.exit_code.lock().expect("exit mutex")
    }
}

/// Cloneable handle to the runner registry.
#[derive(Clone, Default)]
pub struct RunnerRegistry {
    inner: Arc<Mutex<HashMap<String, Arc<RunnerSession>>>>,
}

impl RunnerRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get(&self, key: &str) -> Option<Arc<RunnerSession>> {
        self.inner.lock().expect("runners mutex").get(key).cloned()
    }

    pub fn insert(&self, session: Arc<RunnerSession>) {
        self.inner
            .lock()
            .expect("runners mutex")
            .insert(session.key.clone(), session);
    }

    pub fn remove(&self, key: &str) -> Option<Arc<RunnerSession>> {
        self.inner.lock().expect("runners mutex").remove(key)
    }

    pub fn keys(&self) -> Vec<String> {
        self.inner
            .lock()
            .expect("runners mutex")
            .keys()
            .cloned()
            .collect()
    }

    /// Snapshot of every registry entry — the caller iterates to build
    /// whatever aggregate it needs (e.g. the renderer's `LiveRunners`
    /// map) without holding the mutex across the build. Both live and
    /// exited sessions are returned; filter on `exit_code_now()` if
    /// you only want the running ones.
    pub fn snapshot(&self) -> Vec<Arc<RunnerSession>> {
        self.inner
            .lock()
            .expect("runners mutex")
            .values()
            .cloned()
            .collect()
    }

    pub fn len(&self) -> usize {
        self.inner.lock().expect("runners mutex").len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// Spawn a runner under the shared PTY registry. Returns `Err("already
/// active")` if a live (non-exited) session owns `key` — callers must
/// stop it first. An exited session at `key` is dropped and replaced.
pub fn start(
    runners: &RunnerRegistry,
    pty_registry: &crate::pty::PtyRegistry,
    key: &str,
    checkout_key: &str,
    path: &str,
    template: &str,
    shell: &str,
) -> Result<Arc<RunnerSession>, String> {
    if let Some(existing) = runners.get(key) {
        if existing.exit_code_now().is_none() {
            return Err("already active".into());
        }
        // Drop the exited carcass so the new session takes the slot.
        let _ = runners.remove(key);
    }
    let mode = crate::pty::SpawnMode::RunnerCommand {
        shell: shell.into(),
        template: template.into(),
        path: path.into(),
    };
    let pty = crate::pty::spawn_session(pty_registry, mode, std::path::PathBuf::from(path), 80, 24)
        .map_err(|e| format!("spawn: {e}"))?;

    let session = Arc::new(RunnerSession {
        key: key.into(),
        checkout_key: checkout_key.into(),
        path: path.into(),
        template: template.into(),
        shell: shell.into(),
        started_at: SystemTime::now(),
        pty,
        stamp: Mutex::new(next_stamp()),
        exit_code: Mutex::new(None),
    });
    runners.insert(session.clone());

    // Spawn a lightweight "exit watcher" thread that polls the PTY
    // registry. When the PTY session disappears (pump thread reaped on
    // EOF), we stamp the exit onto the runner. portable-pty doesn't
    // expose the wait status on the parent side without moving the
    // Child value, so we default to 0 — the UI only needs a signal
    // that the runner stopped, not the exact code.
    let watcher_runner = session.clone();
    let watcher_pty_reg = pty_registry.clone();
    let watcher_runners = runners.clone();
    let watcher_pty_id = session.pty.session_id.clone();
    let watcher_key = key.to_string();
    std::thread::Builder::new()
        .name(format!("condash-runner-exit-{key}"))
        .spawn(move || loop {
            if watcher_pty_reg.get(&watcher_pty_id).is_none() {
                *watcher_runner.exit_code.lock().expect("exit mutex") = Some(0);
                *watcher_runner.stamp.lock().expect("stamp mutex") = next_stamp();
                // Keep the session in the runner registry — the UI shows
                // `exited: 0` until the user clicks Stop. Just exit the
                // watcher thread.
                break;
            }
            // Also bail if the session was manually cleared.
            if watcher_runners.get(&watcher_key).is_none() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        })
        .map_err(|e| format!("spawn watcher: {e}"))?;

    Ok(session)
}

/// Stop a runner. SIGTERMs the PTY child (dropping its Child handle),
/// waits for `grace` for the pump thread to reap, then drops the
/// registry slot. Returns `Ok(true)` when the slot was cleared,
/// `Ok(false)` when `key` wasn't live, `Err(_)` on non-fatal trouble.
pub async fn stop(
    runners: &RunnerRegistry,
    key: &str,
    grace: std::time::Duration,
) -> Result<bool, String> {
    let Some(session) = runners.get(key) else {
        return Ok(false);
    };
    // Already exited → just clear.
    if session.exit_code_now().is_some() {
        let _ = runners.remove(key);
        return Ok(true);
    }
    session.pty.kill();
    let deadline = tokio::time::Instant::now() + grace;
    while tokio::time::Instant::now() < deadline {
        if session.exit_code_now().is_some() {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    // If the exit watcher hasn't flipped the code yet, stamp it
    // manually so the UI isn't left showing "running" on a dead
    // process.
    if session.exit_code_now().is_none() {
        *session.exit_code.lock().expect("exit mutex") = Some(-15); // matches Python's -SIGTERM convention
        *session.stamp.lock().expect("stamp mutex") = next_stamp();
    }
    let _ = runners.remove(key);
    Ok(true)
}

/// Short token describing the session's visible state — used by the
/// Code-tab fingerprint layer. Matches Python's `fingerprint_token`.
pub fn fingerprint_token(runners: &RunnerRegistry, key: &str) -> String {
    match runners.get(key) {
        None => "off".into(),
        Some(session) => match session.exit_code_now() {
            Some(code) => format!("exit:{}:{}", session.stamp_now(), code),
            None => format!("run:{}:{}", session.stamp_now(), session.checkout_key),
        },
    }
}

/// Drop an exited session without SIGTERM (no-op if live). Mirrors
/// Python's `clear_exited`.
pub fn clear_exited(runners: &RunnerRegistry, key: &str) -> bool {
    let Some(session) = runners.get(key) else {
        return false;
    };
    if session.exit_code_now().is_none() {
        return false;
    }
    runners.remove(key);
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pty::PtyRegistry;

    #[test]
    fn registry_basic() {
        let reg = RunnerRegistry::new();
        assert!(reg.is_empty());
        assert_eq!(fingerprint_token(&reg, "condash"), "off");
        assert_eq!(reg.keys().len(), 0);
    }

    #[cfg(target_os = "linux")]
    #[tokio::test]
    async fn start_runs_and_stop_clears_slot() {
        let pty_reg = PtyRegistry::new();
        let runners = RunnerRegistry::new();
        // A runner that just blocks for 30 s so we have time to stop it
        // deterministically.
        let session = start(
            &runners,
            &pty_reg,
            "demo",
            "demo@main",
            "/tmp",
            "sleep 30",
            "/bin/sh",
        )
        .expect("start ok");
        assert_eq!(runners.len(), 1);
        assert!(session.exit_code_now().is_none());
        assert!(fingerprint_token(&runners, "demo").starts_with("run:"));

        // Stop it — should clear the slot within the grace window.
        let ok = stop(&runners, "demo", std::time::Duration::from_secs(5))
            .await
            .expect("stop ok");
        assert!(ok);
        assert_eq!(runners.len(), 0);
        assert_eq!(fingerprint_token(&runners, "demo"), "off");
    }

    #[cfg(target_os = "linux")]
    #[tokio::test]
    async fn start_refuses_double_start() {
        let pty_reg = PtyRegistry::new();
        let runners = RunnerRegistry::new();
        let _s = start(
            &runners,
            &pty_reg,
            "demo",
            "demo@main",
            "/tmp",
            "sleep 30",
            "/bin/sh",
        )
        .expect("first start");
        let result = start(
            &runners,
            &pty_reg,
            "demo",
            "demo@main",
            "/tmp",
            "sleep 30",
            "/bin/sh",
        );
        match result {
            Err(e) => assert!(e.contains("active"), "unexpected err: {e}"),
            Ok(_) => panic!("second start should have failed"),
        }
        let _ = stop(&runners, "demo", std::time::Duration::from_secs(5)).await;
    }

    #[cfg(target_os = "linux")]
    #[tokio::test]
    async fn clear_exited_drops_exited_slot() {
        let pty_reg = PtyRegistry::new();
        let runners = RunnerRegistry::new();
        let session = start(
            &runners,
            &pty_reg,
            "demo",
            "demo@main",
            "/tmp",
            // Exits immediately.
            "true",
            "/bin/sh",
        )
        .expect("start");
        // Wait for the exit watcher to flip the code.
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
        while tokio::time::Instant::now() < deadline {
            if session.exit_code_now().is_some() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
        assert!(session.exit_code_now().is_some(), "exit code never set");
        assert!(fingerprint_token(&runners, "demo").starts_with("exit:"));
        assert!(clear_exited(&runners, "demo"));
        assert_eq!(fingerprint_token(&runners, "demo"), "off");
    }
}

//! Filesystem-driven staleness push.
//!
//! The watcher emits coarse per-tab events (`projects` / `knowledge` /
//! `code`) whenever a watched path changes. The SSE handler in
//! `server.rs` subscribes to the bus and streams events to the
//! browser; the frontend treats every event as a hint to re-poll
//! `/check-updates`.
//!
//! `configuration.yml` itself is intentionally *not* watched — edits
//! come from the in-app YAML editor which explicitly triggers a
//! `RenderCtx` rebuild on Save. Out-of-band edits (hand-edit from a
//! different tool) require the user to reopen the modal or restart.
//!
//! Fan-out uses a `tokio::sync::broadcast` channel, which gives us
//! lagging-subscriber semantics for free: the client re-polls on lag,
//! which is the same fall-back the reconciler already provides.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use notify::{recommended_watcher, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use tokio::sync::broadcast;

/// Drop duplicate events per tab within this window — a single editor
/// save often produces swap-file + metadata-touch events too.
pub const DEBOUNCE: Duration = Duration::from_millis(750);

/// Payload emitted by the watcher. Wire format is
/// `{"tab": <tab>, "ts": <seconds>}`.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct EventPayload {
    pub tab: String,
    pub ts: u64,
}

impl EventPayload {
    fn new(tab: impl Into<String>) -> Self {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        EventPayload {
            tab: tab.into(),
            ts,
        }
    }

    /// Public factory used by routes that need to publish a tab refresh
    /// (currently the configuration save handler — see
    /// [`server::config_surface`](crate::server::config_surface)).
    pub fn for_tab(tab: impl Into<String>) -> Self {
        Self::new(tab)
    }
}

/// Thread-safe fan-out channel. `Clone` is cheap — the inner broadcast
/// sender is an `Arc` internally.
#[derive(Clone)]
pub struct EventBus {
    tx: broadcast::Sender<EventPayload>,
}

impl EventBus {
    pub fn new(capacity: usize) -> Self {
        let (tx, _rx) = broadcast::channel(capacity);
        EventBus { tx }
    }

    /// Subscribe to the fan-out. Subscribers that fall more than
    /// `capacity` events behind receive `RecvError::Lagged` — the SSE
    /// handler just logs + keeps going, and the browser re-polls
    /// `/check-updates` on the next event it does see.
    pub fn subscribe(&self) -> broadcast::Receiver<EventPayload> {
        self.tx.subscribe()
    }

    /// Publish an event. Silently drops the message when there are no
    /// subscribers (the common case at startup).
    pub fn publish(&self, payload: EventPayload) {
        let _ = self.tx.send(payload);
    }

    /// Number of live receivers — useful for tests and diagnostics.
    pub fn subscriber_count(&self) -> usize {
        self.tx.receiver_count()
    }
}

impl Default for EventBus {
    fn default() -> Self {
        EventBus::new(256)
    }
}

/// Per-tab debouncer — tracks the last-emit instant and suppresses any
/// follow-up within the debounce window.
struct Debouncer {
    window: Duration,
    last: Mutex<Instant>,
}

impl Debouncer {
    fn new(window: Duration) -> Self {
        Debouncer {
            window,
            // Seed `last` far enough in the past that the first event
            // always fires.
            last: Mutex::new(Instant::now() - window - Duration::from_secs(1)),
        }
    }

    fn should_fire(&self) -> bool {
        let mut guard = self.last.lock().expect("Debouncer mutex poisoned");
        let now = Instant::now();
        if now.duration_since(*guard) < self.window {
            return false;
        }
        *guard = now;
        true
    }
}

/// Should the filename (leaf) be ignored? Same rules as Python's
/// `_DebouncedHandler.on_any_event`: swap files (`foo.md~`), hidden
/// files (`.foo`), and editor scratch files start with `.` or end with
/// `~`.
fn is_noise(leaf: &str) -> bool {
    leaf.is_empty() || leaf.starts_with('.') || leaf.ends_with('~')
}

/// Tabs routed by the projects/knowledge/config handlers.
fn leaf_of(path: &Path) -> String {
    path.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// Configuration for which directories to watch. Built once at startup
/// from the `RenderCtx` + conception path.
pub struct WatchConfig {
    pub projects: Option<PathBuf>,
    pub knowledge: Option<PathBuf>,
    pub git_dirs: Vec<PathBuf>,
}

impl WatchConfig {
    /// Derive a [`WatchConfig`] from a conception base dir + optional
    /// workspace / worktrees roots. `configuration.yml` is deliberately
    /// *not* watched (see module docs); the config modal pushes rebuilds
    /// explicitly.
    pub fn from_ctx(base_dir: &Path, workspace: Option<&Path>, worktrees: Option<&Path>) -> Self {
        let projects = base_dir.join("projects");
        let knowledge = base_dir.join("knowledge");

        let mut git_dirs = Vec::new();
        if let Some(ws) = workspace {
            git_dirs.extend(git_dirs_under(ws));
        }
        if let Some(wt) = worktrees {
            if wt.is_dir() {
                if let Ok(entries) = std::fs::read_dir(wt) {
                    for entry in entries.flatten() {
                        let p = entry.path();
                        if p.is_dir() {
                            git_dirs.extend(git_dirs_under(&p));
                        }
                    }
                }
            }
        }

        WatchConfig {
            projects: projects.is_dir().then_some(projects),
            knowledge: knowledge.is_dir().then_some(knowledge),
            git_dirs,
        }
    }
}

/// List `.git` directories one level below `workspace`. Worktrees have
/// `.git` as a *file* (gitdir pointer) — skipped here; the parent .git
/// directory of the real checkout carries the ref updates that matter.
fn git_dirs_under(workspace: &Path) -> Vec<PathBuf> {
    if !workspace.is_dir() {
        return vec![];
    }
    let mut out = Vec::new();
    if let Ok(entries) = std::fs::read_dir(workspace) {
        for entry in entries.flatten() {
            let dir = entry.path();
            if !dir.is_dir() {
                continue;
            }
            let gitdir = dir.join(".git");
            if gitdir.is_dir() {
                out.push(gitdir);
            }
        }
    }
    out
}

/// Handle returned by [`start_watcher`]. Dropping it tears the watcher
/// down.
pub struct WatcherHandle {
    _watcher: RecommendedWatcher,
}

/// Bridge filesystem-watcher events to the shared items/knowledge
/// cache. Without this, the watcher publishes `projects` / `knowledge`
/// events to the SSE fan-out but the server keeps handing back the
/// first-warmed cached slices, so hand-edits and `git pull` never
/// surface until the user hits `/rescan`.
pub fn spawn_cache_invalidator(
    bus: EventBus,
    cache: std::sync::Arc<condash_state::WorkspaceCache>,
) {
    let mut rx = bus.subscribe();
    tokio::spawn(async move {
        loop {
            match rx.recv().await {
                Ok(payload) => {
                    let tab = match payload.tab.as_str() {
                        "projects" => Some(condash_state::Tab::Projects),
                        "knowledge" => Some(condash_state::Tab::Knowledge),
                        // "code" is watched for SSE stale-dots but has no
                        // server-side cache to flush.
                        _ => None,
                    };
                    if let Some(tab) = tab {
                        cache.on_event(tab);
                    }
                }
                // Lagged: we missed events, but the next one we do see
                // will still invalidate — safe to keep going.
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
            }
        }
    });
}

/// Start filesystem watchers for each configured directory. Returns
/// `None` when nothing is configured.
///
/// The watcher runs on notify's own thread — it calls `bus.publish` via
/// the shared `Arc`, so events reach every SSE subscriber without
/// blocking the HTTP runtime.
pub fn start_watcher(bus: EventBus, cfg: WatchConfig) -> Option<WatcherHandle> {
    let projects_deb = Arc::new(Debouncer::new(DEBOUNCE));
    let knowledge_deb = Arc::new(Debouncer::new(DEBOUNCE));
    let code_deb = Arc::new(Debouncer::new(DEBOUNCE));

    let nothing_to_watch =
        cfg.projects.is_none() && cfg.knowledge.is_none() && cfg.git_dirs.is_empty();
    if nothing_to_watch {
        return None;
    }

    let bus_clone = bus.clone();
    let projects_path = cfg.projects.clone();
    let knowledge_path = cfg.knowledge.clone();
    let git_dirs = cfg.git_dirs.clone();

    let mut watcher = recommended_watcher(move |res: notify::Result<Event>| {
        let Ok(event) = res else { return };
        // Skip pure access/open events — they're not interesting and
        // blow through the debounce window needlessly.
        if matches!(event.kind, EventKind::Access(_)) {
            return;
        }
        for src in &event.paths {
            let leaf = leaf_of(src);

            if let Some(root) = &projects_path {
                if src.starts_with(root) && !is_noise(&leaf) && projects_deb.should_fire() {
                    bus_clone.publish(EventPayload::new("projects"));
                    continue;
                }
            }
            if let Some(root) = &knowledge_path {
                if src.starts_with(root) && !is_noise(&leaf) && knowledge_deb.should_fire() {
                    bus_clone.publish(EventPayload::new("knowledge"));
                    continue;
                }
            }
            for gitdir in &git_dirs {
                if src.starts_with(gitdir)
                    && matches!(leaf.as_str(), "HEAD" | "index" | "packed-refs")
                    && code_deb.should_fire()
                {
                    bus_clone.publish(EventPayload::new("code"));
                    break;
                }
            }
        }
    })
    .ok()?;

    if let Some(p) = &cfg.projects {
        let _ = watcher.watch(p, RecursiveMode::Recursive);
    }
    if let Some(p) = &cfg.knowledge {
        let _ = watcher.watch(p, RecursiveMode::Recursive);
    }
    for gitdir in &cfg.git_dirs {
        let _ = watcher.watch(gitdir, RecursiveMode::NonRecursive);
    }

    Some(WatcherHandle { _watcher: watcher })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use tempfile::TempDir;

    #[test]
    fn bus_fanout_delivers_to_all_subscribers() {
        let bus = EventBus::new(16);
        let mut rx1 = bus.subscribe();
        let mut rx2 = bus.subscribe();
        let payload = EventPayload::new("projects");
        bus.publish(payload.clone());
        let got1 = rx1.try_recv().expect("rx1 received");
        let got2 = rx2.try_recv().expect("rx2 received");
        assert_eq!(got1.tab, "projects");
        assert_eq!(got2.tab, "projects");
        let _ = payload;
    }

    #[test]
    fn bus_drop_on_no_subscribers_is_silent() {
        let bus = EventBus::new(4);
        // No subscribers — must not panic.
        bus.publish(EventPayload::new("knowledge"));
        assert_eq!(bus.subscriber_count(), 0);
    }

    #[test]
    fn debouncer_suppresses_rapid_fire() {
        let deb = Debouncer::new(Duration::from_millis(100));
        assert!(deb.should_fire(), "first must fire");
        assert!(!deb.should_fire(), "immediate follow-up must not fire");
        std::thread::sleep(Duration::from_millis(120));
        assert!(deb.should_fire(), "after window must fire again");
    }

    #[test]
    fn is_noise_filters_editor_leaves() {
        assert!(is_noise(""));
        assert!(is_noise(".hidden"));
        assert!(is_noise("foo.md~"));
        assert!(!is_noise("README.md"));
    }

    #[test]
    fn watch_config_skips_missing_dirs() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        // Create only projects/.
        std::fs::create_dir_all(base.join("projects")).unwrap();
        let cfg = WatchConfig::from_ctx(base, None, None);
        assert!(cfg.projects.is_some());
        assert!(cfg.knowledge.is_none());
        assert!(cfg.git_dirs.is_empty());
    }

    #[test]
    fn watch_config_picks_up_git_dirs_under_workspace() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let ws = base.join("src");
        let repo = ws.join("some-project");
        std::fs::create_dir_all(repo.join(".git")).unwrap();
        let cfg = WatchConfig::from_ctx(base, Some(&ws), None);
        assert_eq!(cfg.git_dirs.len(), 1);
        assert!(cfg.git_dirs[0].ends_with(".git"));
    }

    #[test]
    fn watcher_emits_projects_event_on_write() {
        use std::sync::atomic::{AtomicBool, Ordering};

        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let projects = base.join("projects");
        std::fs::create_dir_all(projects.join("2026-04/2026-04-22-demo")).unwrap();
        let bus = EventBus::new(16);
        let mut rx = bus.subscribe();
        let cfg = WatchConfig::from_ctx(base, None, None);
        let _w = start_watcher(bus.clone(), cfg).expect("watcher started");

        // Cross the debounce window before writing so the first event
        // always fires.
        std::thread::sleep(DEBOUNCE + Duration::from_millis(20));

        let f = projects.join("2026-04/2026-04-22-demo/README.md");
        std::fs::write(&f, "# demo\n").unwrap();

        // Give notify up to 2 s to deliver the event.
        let got_event = AtomicBool::new(false);
        for _ in 0..20 {
            if let Ok(payload) = rx.try_recv() {
                if payload.tab == "projects" {
                    got_event.store(true, Ordering::SeqCst);
                    break;
                }
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        assert!(got_event.load(Ordering::SeqCst), "no projects event");
    }
}

//! Filesystem-driven staleness push.
//!
//! The watcher emits two flavours of event:
//!
//! - **Pane-wide** (`projects` / `knowledge` / `code`) when the change
//!   is structural — a new item directory appears, an `index.md` is
//!   touched, configuration is rewritten, etc. The pane container's
//!   `hx-trigger="sse:<pane>"` re-fetches the whole pane fragment.
//! - **Per-item** (`projects-<slug>` / `knowledge-<rel-path>` /
//!   `code-<repo>`) when the change is item-internal — one card's
//!   underlying state moved. The card root carries its own
//!   `hx-trigger="sse:<pane>-<id>"` so only that one card re-fetches a
//!   `<2 KB` fragment and idiomorph patches it in place.
//!
//! `configuration.yml` itself is intentionally *not* watched — edits
//! come from the in-app YAML editor which explicitly triggers a
//! `RenderCtx` rebuild and a pane-wide event for each pane on Save.
//!
//! Fan-out uses a `tokio::sync::broadcast` channel, which gives us
//! lagging-subscriber semantics for free: the client re-polls on lag,
//! which is the same fall-back the reconciler already provides.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use notify::event::{CreateKind, RemoveKind};
use notify::{recommended_watcher, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use tokio::sync::broadcast;

/// Drop duplicate events per (pane, id) within this window — a single
/// editor save often produces swap-file + metadata-touch events too.
pub const DEBOUNCE: Duration = Duration::from_millis(750);

/// Payload emitted by the watcher. Wire format is
/// `{"tab": <pane>, "id": <id?>, "ts": <seconds>}`.
///
/// `tab` is kept (not renamed `pane`) for compatibility with the
/// `events_stream` SSE handler and the `condash-state` cache router that
/// match on the string. `id` is `None` for pane-wide / structural events,
/// `Some(...)` for item-internal events.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct EventPayload {
    pub tab: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub ts: u64,
}

impl EventPayload {
    fn build(tab: impl Into<String>, id: Option<String>) -> Self {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        EventPayload {
            tab: tab.into(),
            id,
            ts,
        }
    }

    /// Pane-wide / structural event factory. Used by the configuration
    /// save handler (see [`server::config_surface`](crate::server::config_surface))
    /// and by the watcher when a path change can't be narrowed to a
    /// single item.
    pub fn for_tab(tab: impl Into<String>) -> Self {
        Self::build(tab, None)
    }

    /// Per-item event factory. The id is the slug / file-path / repo-name
    /// the changed file resolves to. The SSE handler turns this into the
    /// named event `<tab>-<id>` on the wire.
    pub fn for_item(tab: impl Into<String>, id: impl Into<String>) -> Self {
        Self::build(tab, Some(id.into()))
    }

    /// SSE event name used on the wire. `<tab>` for pane-wide,
    /// `<tab>-<id>` for per-item. Slashes in `id` (knowledge file paths)
    /// are kept verbatim; htmx's SSE extension matches the event-name
    /// field as a literal string.
    pub fn event_name(&self) -> String {
        match &self.id {
            None => self.tab.clone(),
            Some(id) => format!("{}-{}", self.tab, id),
        }
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
        EventBus::new(1024)
    }
}

/// Per-key debouncer — tracks the last-emit instant for an arbitrary
/// string key and suppresses any follow-up within the debounce window.
/// The key is `<pane>` for pane-wide events and `<pane>-<id>` for
/// per-item events, so two different items can fire inside the same
/// 750 ms window without one starving the other.
struct KeyedDebouncer {
    window: Duration,
    last: Mutex<HashMap<String, Instant>>,
}

impl KeyedDebouncer {
    fn new(window: Duration) -> Self {
        KeyedDebouncer {
            window,
            last: Mutex::new(HashMap::new()),
        }
    }

    fn should_fire(&self, key: &str) -> bool {
        let mut guard = self.last.lock().expect("KeyedDebouncer mutex poisoned");
        let now = Instant::now();
        if let Some(prev) = guard.get(key) {
            if now.duration_since(*prev) < self.window {
                return false;
            }
        }
        guard.insert(key.to_string(), now);
        true
    }
}

/// Should the filename (leaf) be ignored? Swap files (`foo.md~`),
/// hidden files (`.foo`), and editor scratch files all start with `.`
/// or end with `~`.
fn is_noise(leaf: &str) -> bool {
    leaf.is_empty() || leaf.starts_with('.') || leaf.ends_with('~')
}

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
    /// Parent directory of git worktrees (typically `~/src/worktrees/`).
    /// Watched non-recursively so a brand-new branch directory landing at
    /// runtime triggers a `code` pane refresh — the per-`.git/` watchers
    /// in `git_dirs` only cover subdirs that existed at startup.
    pub worktrees_root: Option<PathBuf>,
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
            worktrees_root: worktrees.and_then(|wt| wt.is_dir().then(|| wt.to_path_buf())),
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

/// Result of `classify`: which pane the path belongs to, and the
/// per-item id when one can be resolved cleanly. `None` from `classify`
/// itself means the path doesn't belong to any watched pane (ignored).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PathClass {
    pub pane: &'static str,
    pub id: Option<String>,
}

/// Resolve a changed filesystem path to `(pane, id?)`. Pure function — no
/// I/O — so it's cheap to call from the notify callback.
pub fn classify(path: &Path, cfg: &WatchConfig) -> Option<PathClass> {
    if let Some(root) = &cfg.projects {
        if let Some(rel) = path.strip_prefix(root).ok() {
            // Components after `projects/` are `<month>/<slug>/...`.
            let parts: Vec<&str> = rel
                .components()
                .filter_map(|c| match c {
                    std::path::Component::Normal(n) => n.to_str(),
                    _ => None,
                })
                .collect();
            if parts.len() >= 3 {
                // Past the slug dir → item-internal.
                return Some(PathClass {
                    pane: "projects",
                    id: Some(parts[1].to_string()),
                });
            }
            // Path is `projects/`, `projects/<month>/`, or
            // `projects/<month>/<slug>/` itself — a structural change
            // (new item dir landed, deletion, etc.). The slug-dir-self
            // event has to land on the pane-wide debouncer key, not the
            // per-item one, so the README write that follows isn't
            // suppressed by a key collision.
            return Some(PathClass {
                pane: "projects",
                id: None,
            });
        }
    }
    if let Some(root) = &cfg.knowledge {
        if let Some(rel) = path.strip_prefix(root).ok() {
            // The card's data-node-id is the path *relative to base*
            // (`knowledge/<rel>`), so re-attach the prefix.
            let id = format!("knowledge/{}", rel.to_string_lossy().replace('\\', "/"));
            // index.md changes affect the parent group's badge, which
            // means a structural-shape refresh; we serve those as
            // pane-wide.
            let leaf = leaf_of(path);
            if leaf == "index.md" {
                return Some(PathClass {
                    pane: "knowledge",
                    id: None,
                });
            }
            // A directory event has no file extension we can rely on —
            // require a `.md` suffix for per-item; everything else is
            // structural (rename, mkdir, etc.).
            let is_md = path.extension().and_then(|e| e.to_str()) == Some("md");
            if !is_md {
                return Some(PathClass {
                    pane: "knowledge",
                    id: None,
                });
            }
            return Some(PathClass {
                pane: "knowledge",
                id: Some(id),
            });
        }
    }
    for gitdir in &cfg.git_dirs {
        if path.starts_with(gitdir) {
            // `<repo>/.git/<file>` → repo name is the parent of `.git`.
            let repo = gitdir
                .parent()
                .and_then(|p| p.file_name())
                .and_then(|n| n.to_str())
                .map(|s| s.to_string());
            return Some(PathClass {
                pane: "code",
                id: repo,
            });
        }
    }
    // Direct child of the worktrees root — a brand-new branch dir
    // landed (or an existing one was renamed/removed). Coarse code-pane
    // event so the frontend re-runs `git worktree list` and picks up
    // the new entry.
    if let Some(root) = &cfg.worktrees_root {
        if path.starts_with(root) {
            return Some(PathClass {
                pane: "code",
                id: None,
            });
        }
    }
    None
}

/// Handle returned by [`start_watcher`]. Dropping it tears the watcher
/// down.
pub struct WatcherHandle {
    _watcher: RecommendedWatcher,
}

/// Bridge filesystem-watcher events to the shared items/knowledge
/// cache. Without this, the watcher publishes events to the SSE fan-out
/// but the server keeps handing back the first-warmed cached slices, so
/// hand-edits and `git pull` never surface until the user hits
/// `/rescan`.
///
/// Both pane-wide and per-item events flow through here. The cache's
/// `on_event` API is coarse (Tab::Projects flushes the whole map), so
/// per-item events still trigger a coarse flush *for now*; the
/// `WorkspaceCache::invalidate_item_at` helper exists for the future
/// fine-grained pathway, but plumbing the README path through the watcher
/// would push all the per-item-detection logic onto this hot path. The
/// extra reparse cost on a hot cache is small — the path → README parse
/// is what the surgical invalidator does anyway.
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
    let nothing_to_watch = cfg.projects.is_none()
        && cfg.knowledge.is_none()
        && cfg.git_dirs.is_empty()
        && cfg.worktrees_root.is_none();
    if nothing_to_watch {
        return None;
    }

    let bus_clone = bus.clone();
    let debouncer = Arc::new(KeyedDebouncer::new(DEBOUNCE));
    // Snapshot the watch roots that the closure needs to reason about.
    // The notify watcher itself holds onto the absolute paths via the
    // `watch()` calls below; this `cfg_for_classify` is just so
    // `classify` keeps working from inside the callback.
    let cfg_for_classify = WatchConfig {
        projects: cfg.projects.clone(),
        knowledge: cfg.knowledge.clone(),
        git_dirs: cfg.git_dirs.clone(),
        worktrees_root: cfg.worktrees_root.clone(),
    };

    let mut watcher = recommended_watcher(move |res: notify::Result<Event>| {
        let Ok(event) = res else { return };
        // Skip pure access/open events — they're not interesting and
        // blow through the debounce window needlessly.
        if matches!(event.kind, EventKind::Access(_)) {
            return;
        }
        for src in &event.paths {
            let leaf = leaf_of(src);
            if is_noise(&leaf) {
                continue;
            }
            // For the code pane the watcher only cares about three ref
            // files; everything else under `.git/` is implementation
            // noise (objects/, lock churn). The check has to live here,
            // not in `classify`, because `classify` is also called from
            // tests with synthetic paths.
            if cfg_for_classify.git_dirs.iter().any(|g| src.starts_with(g))
                && !matches!(leaf.as_str(), "HEAD" | "index" | "packed-refs")
            {
                continue;
            }
            let Some(mut class) = classify(src, &cfg_for_classify) else {
                continue;
            };
            // Directory create/remove events under `projects/` always
            // ride the pane-wide debouncer key. Without this, mkdir of
            // `<slug>/notes/` (per-item key) suppresses the README
            // write event that follows in the same 750 ms window — the
            // exact race that left new projects invisible until the
            // user clicked hard-refresh.
            if class.pane == "projects"
                && matches!(
                    event.kind,
                    EventKind::Create(CreateKind::Folder) | EventKind::Remove(RemoveKind::Folder)
                )
            {
                class.id = None;
            }
            let payload = match &class.id {
                Some(id) => EventPayload::for_item(class.pane, id),
                None => EventPayload::for_tab(class.pane),
            };
            let key = payload.event_name();
            if !debouncer.should_fire(&key) {
                continue;
            }
            bus_clone.publish(payload);
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
    if let Some(wt) = &cfg.worktrees_root {
        // Non-recursive on purpose: we only care about new top-level
        // branch dirs landing here. Recursive would drown the bus in
        // `<branch>/<repo>/.git/objects/` churn that the per-`.git/`
        // watchers above already handle.
        let _ = watcher.watch(wt, RecursiveMode::NonRecursive);
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
        let payload = EventPayload::for_tab("projects");
        bus.publish(payload.clone());
        let got1 = rx1.try_recv().expect("rx1 received");
        let got2 = rx2.try_recv().expect("rx2 received");
        assert_eq!(got1.tab, "projects");
        assert_eq!(got2.tab, "projects");
        assert!(got1.id.is_none());
    }

    #[test]
    fn bus_drop_on_no_subscribers_is_silent() {
        let bus = EventBus::new(4);
        bus.publish(EventPayload::for_tab("knowledge"));
        assert_eq!(bus.subscriber_count(), 0);
    }

    #[test]
    fn keyed_debouncer_suppresses_same_key_only() {
        let deb = KeyedDebouncer::new(Duration::from_millis(100));
        assert!(deb.should_fire("a"), "first 'a' must fire");
        assert!(!deb.should_fire("a"), "second 'a' must be suppressed");
        // Different key must fire even within the window — this is
        // the property that lets two different cards both notify in the
        // same 750 ms tick.
        assert!(deb.should_fire("b"), "'b' independent of 'a'");
        std::thread::sleep(Duration::from_millis(120));
        assert!(deb.should_fire("a"), "'a' fires again after window");
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
    fn classify_routes_projects_paths_to_slug() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        std::fs::create_dir_all(base.join("projects/2026-04/2026-04-22-foo/notes")).unwrap();
        let cfg = WatchConfig::from_ctx(base, None, None);

        // README → item-internal.
        let p = base.join("projects/2026-04/2026-04-22-foo/README.md");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.pane, "projects");
        assert_eq!(c.id.as_deref(), Some("2026-04-22-foo"));

        // Note under the item → still item-internal.
        let p = base.join("projects/2026-04/2026-04-22-foo/notes/a.md");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.id.as_deref(), Some("2026-04-22-foo"));

        // The month dir itself → structural.
        let p = base.join("projects/2026-04");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.pane, "projects");
        assert!(c.id.is_none());

        // The slug dir itself → structural (regression: previously
        // classified as per-item, which collided with the README write
        // on the debouncer and left new projects invisible).
        let p = base.join("projects/2026-04/2026-04-22-foo");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.pane, "projects");
        assert!(c.id.is_none());
    }

    #[test]
    fn watch_config_picks_up_worktrees_root() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let wt = base.join("worktrees");
        std::fs::create_dir_all(&wt).unwrap();
        let cfg = WatchConfig::from_ctx(base, None, Some(&wt));
        assert_eq!(cfg.worktrees_root.as_deref(), Some(wt.as_path()));
    }

    #[test]
    fn classify_routes_new_worktree_dir_to_code_pane() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let wt = base.join("worktrees");
        std::fs::create_dir_all(&wt).unwrap();
        let cfg = WatchConfig::from_ctx(base, None, Some(&wt));

        // Direct child of worktrees/ — a brand-new branch dir landed.
        let p = wt.join("feature-x");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.pane, "code");
        assert!(c.id.is_none());
    }

    #[test]
    fn classify_routes_knowledge_paths_to_relpath() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        std::fs::create_dir_all(base.join("knowledge/internal")).unwrap();
        let cfg = WatchConfig::from_ctx(base, None, None);

        // .md file → item-internal, id is `knowledge/<rel>`.
        let p = base.join("knowledge/internal/condash.md");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.pane, "knowledge");
        assert_eq!(c.id.as_deref(), Some("knowledge/internal/condash.md"));

        // index.md → structural (badge cascades up).
        let p = base.join("knowledge/internal/index.md");
        let c = classify(&p, &cfg).unwrap();
        assert!(c.id.is_none());

        // Non-md file → structural (cover-image add, mkdir, …).
        let p = base.join("knowledge/internal/diagram.svg");
        let c = classify(&p, &cfg).unwrap();
        assert!(c.id.is_none());
    }

    #[test]
    fn classify_routes_code_paths_to_repo_name() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let ws = base.join("src");
        let repo = ws.join("condash");
        std::fs::create_dir_all(repo.join(".git")).unwrap();
        let cfg = WatchConfig::from_ctx(base, Some(&ws), None);

        let p = repo.join(".git/HEAD");
        let c = classify(&p, &cfg).unwrap();
        assert_eq!(c.pane, "code");
        assert_eq!(c.id.as_deref(), Some("condash"));
    }

    #[test]
    fn classify_returns_none_for_unrelated_paths() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let cfg = WatchConfig::from_ctx(base, None, None);
        let p = std::path::PathBuf::from("/etc/passwd");
        assert!(classify(&p, &cfg).is_none());
    }

    #[test]
    fn event_payload_event_name_pane_vs_item() {
        let pane = EventPayload::for_tab("projects");
        assert_eq!(pane.event_name(), "projects");
        let item = EventPayload::for_item("projects", "2026-04-22-foo");
        assert_eq!(item.event_name(), "projects-2026-04-22-foo");
        let knowledge = EventPayload::for_item("knowledge", "knowledge/internal/condash.md");
        assert_eq!(
            knowledge.event_name(),
            "knowledge-knowledge/internal/condash.md"
        );
    }

    #[test]
    fn watcher_emits_per_item_event_on_readme_write() {
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

        // Give notify up to 2 s to deliver the event. Accept either the
        // per-item or the structural variant — depending on how notify
        // reports the create-then-write sequence on the host, we may
        // see the parent dir event first (structural) before or instead
        // of the README file event.
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

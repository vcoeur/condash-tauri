//! PTY session lifecycle for the embedded terminal.
//!
//! A PTY's lifetime is decoupled from any single WebSocket: a tab refresh
//! should detach the viewer without killing the shell. Each session lives
//! in the per-process [`PtyRegistry`], keyed by an opaque session id; the
//! WebSocket attaches and detaches via [`PtySession::attach_ws`] /
//! [`PtySession::detach_ws`], while the pump task drains the PTY master
//! into a ring buffer (and forwards to the attached viewer when one is
//! present).
//!
//! Linux + macOS only for now — `portable-pty` would pick ConPTY on
//! Windows but the launcher/exec flow here isn't wired to it.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use rand::Rng;
use tokio::sync::mpsc;

/// Cap on the per-session scrollback ring buffer. 256 KiB — enough for a
/// few screens of output. Larger pastes trim from the head. Matches
/// Python's `_BUFFER_CAP`.
pub const BUFFER_CAP: usize = 256 * 1024;

/// Bytes emitted by the PTY pump. `Data(b)` is raw output; `Exit` is
/// "the shell is gone, reap the session".
#[derive(Debug)]
pub enum PumpMessage {
    Data(Vec<u8>),
    Exit,
}

/// Server-side PTY session. Decoupled from any WebSocket viewer.
///
/// All mutable state (buffer, attached_ws marker, cols/rows) lives behind
/// a `Mutex` since the pump task runs on a blocking thread and the
/// WebSocket receive loop runs on tokio.
pub struct PtySession {
    pub session_id: String,
    pub shell: String,
    pub cwd: PathBuf,
    /// Shared ring buffer — scrollback the pump task writes into and the
    /// WebSocket attach path reads on first connect.
    pub buffer: Arc<Mutex<Vec<u8>>>,
    /// Last-observed size. Used when a viewer resizes *after* the
    /// session is created.
    pub size: Arc<Mutex<PtySize>>,
    /// Writer end of the PTY (master side). Used to send user input +
    /// resize ioctls.
    writer: Arc<Mutex<Box<dyn Write + Send>>>,
    /// Master PTY — kept so we can issue resize() on it without dropping
    /// the file descriptor.
    master: Arc<Mutex<Box<dyn MasterPty + Send>>>,
    /// Child-process handle — used by `kill()` on shutdown.
    child: Arc<Mutex<Box<dyn Child + Send + Sync>>>,
    /// `Some(tx)` when a viewer is attached; the pump task forwards
    /// chunks to it until the tx is dropped or `None`.
    viewer: Arc<Mutex<Option<mpsc::UnboundedSender<PumpMessage>>>>,
}

impl PtySession {
    pub fn cols(&self) -> u16 {
        self.size.lock().expect("size mutex").cols
    }
    pub fn rows(&self) -> u16 {
        self.size.lock().expect("size mutex").rows
    }
    pub fn snapshot_buffer(&self) -> Vec<u8> {
        self.buffer.lock().expect("buffer mutex").clone()
    }
    /// Attach a viewer to this session. Replaces any existing viewer's
    /// sender (the old one is dropped so its receiver ends, mirroring
    /// Python's "displace the old viewer" behaviour).
    pub fn attach_viewer(&self) -> mpsc::UnboundedReceiver<PumpMessage> {
        let (tx, rx) = mpsc::unbounded_channel();
        // Push the buffer first so the new viewer sees scrollback.
        let replay = self.snapshot_buffer();
        if !replay.is_empty() {
            let _ = tx.send(PumpMessage::Data(replay));
        }
        let mut guard = self.viewer.lock().expect("viewer mutex");
        *guard = Some(tx);
        rx
    }

    /// Detach the viewer — the pump keeps running and buffering output.
    pub fn detach_viewer(&self) {
        let mut guard = self.viewer.lock().expect("viewer mutex");
        *guard = None;
    }

    /// Write user input to the PTY master.
    pub fn write_input(&self, bytes: &[u8]) -> std::io::Result<()> {
        let mut w = self.writer.lock().expect("writer mutex");
        w.write_all(bytes)?;
        w.flush()
    }

    /// Resize the PTY. Clamps to `>=2` rows/cols: many TUIs crash on 0/1.
    pub fn resize(&self, cols: u16, rows: u16) {
        let cols = cols.max(2);
        let rows = rows.max(2);
        let new_size = PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        };
        *self.size.lock().expect("size mutex") = new_size;
        if let Ok(master) = self.master.lock() {
            let _ = master.resize(new_size);
        }
    }

    /// SIGTERM the child — used by [`PtyRegistry::reap_all`].
    pub fn kill(&self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
        }
    }
}

/// Per-process registry of live PTY sessions — cloneable handle shared
/// by the HTTP routes and the shutdown reaper.
#[derive(Clone, Default)]
pub struct PtyRegistry {
    inner: Arc<Mutex<HashMap<String, Arc<PtySession>>>>,
}

impl PtyRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get(&self, session_id: &str) -> Option<Arc<PtySession>> {
        self.inner
            .lock()
            .expect("registry mutex")
            .get(session_id)
            .cloned()
    }

    pub fn insert(&self, session: Arc<PtySession>) {
        self.inner
            .lock()
            .expect("registry mutex")
            .insert(session.session_id.clone(), session);
    }

    pub fn remove(&self, session_id: &str) -> Option<Arc<PtySession>> {
        self.inner
            .lock()
            .expect("registry mutex")
            .remove(session_id)
    }

    pub fn len(&self) -> usize {
        self.inner.lock().expect("registry mutex").len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// SIGTERM every live PTY and drop them from the registry. Called
    /// on server shutdown.
    pub fn reap_all(&self) {
        let mut guard = self.inner.lock().expect("registry mutex");
        for (_, session) in guard.iter() {
            session.kill();
        }
        guard.clear();
    }
}

/// What to execute inside the PTY.
pub enum SpawnMode {
    /// Login shell (`<shell> -l`) — the normal `/ws/term` flow.
    LoginShell { shell: String },
    /// Arbitrary argv parsed from `terminal.launcher_command` — mirrors
    /// Python's `use_launcher=True` path.
    Launcher { argv: Vec<String> },
    /// `<shell> -lc <template-with-path-replaced>` — the runner flow
    /// (Phase 4 slice 2). Kept on this enum so a single spawn path
    /// covers every caller.
    RunnerCommand {
        shell: String,
        template: String,
        path: String,
    },
}

/// Spawn a PTY running the requested command, register it, and start
/// the pump task on `spawn_blocking`. The pump drains PTY master output
/// into the ring buffer (and any attached viewer) until the child exits.
///
/// `cwd` is the directory to start the child in — must already be
/// sandbox-validated by the caller.
pub fn spawn_session(
    registry: &PtyRegistry,
    mode: SpawnMode,
    cwd: PathBuf,
    cols: u16,
    rows: u16,
) -> std::io::Result<Arc<PtySession>> {
    let pty_system = native_pty_system();
    let size = PtySize {
        rows,
        cols,
        pixel_width: 0,
        pixel_height: 0,
    };
    let pair = pty_system
        .openpty(size)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, format!("openpty: {e}")))?;

    let (argv, shell_label): (Vec<String>, String) = match mode {
        SpawnMode::LoginShell { shell } => (vec![shell.clone(), "-l".into()], shell),
        SpawnMode::Launcher { argv } => {
            let label = argv.first().cloned().unwrap_or_default();
            (argv, label)
        }
        SpawnMode::RunnerCommand {
            shell,
            template,
            path,
        } => {
            let resolved = template.replace("{path}", &path);
            (vec![shell.clone(), "-lc".into(), resolved], shell)
        }
    };

    if argv.is_empty() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "empty argv",
        ));
    }

    let mut cmd = CommandBuilder::new(&argv[0]);
    for arg in &argv[1..] {
        cmd.arg(arg);
    }
    cmd.cwd(&cwd);
    cmd.env("TERM", "xterm-256color");

    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, format!("spawn: {e}")))?;
    // Close the slave on the parent side — the child retains its copy.
    drop(pair.slave);

    let reader = pair.master.try_clone_reader().map_err(|e| {
        std::io::Error::new(std::io::ErrorKind::Other, format!("clone reader: {e}"))
    })?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, format!("take writer: {e}")))?;

    let session_id: String = {
        let mut rng = rand::thread_rng();
        (0..16)
            .map(|_| {
                let n: u8 = rng.gen_range(0..36);
                if n < 10 {
                    (b'0' + n) as char
                } else {
                    (b'a' + (n - 10)) as char
                }
            })
            .collect()
    };

    let session = Arc::new(PtySession {
        session_id: session_id.clone(),
        shell: shell_label,
        cwd,
        buffer: Arc::new(Mutex::new(Vec::with_capacity(4096))),
        size: Arc::new(Mutex::new(size)),
        writer: Arc::new(Mutex::new(writer)),
        master: Arc::new(Mutex::new(pair.master)),
        child: Arc::new(Mutex::new(child)),
        viewer: Arc::new(Mutex::new(None)),
    });

    registry.insert(session.clone());

    // Spawn the pump on a blocking thread — portable-pty's reader is
    // synchronous. The pump drives the ring buffer + forwards to any
    // attached viewer, then emits `Exit` on EOF.
    let pump_session = session.clone();
    let pump_registry = registry.clone();
    std::thread::Builder::new()
        .name(format!("condash-pty-pump-{session_id}"))
        .spawn(move || {
            pump_loop(pump_session, pump_registry, reader);
        })
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, format!("pump thread: {e}")))?;

    Ok(session)
}

/// Synchronous pump — runs on a dedicated thread for the PTY's entire
/// lifetime. Reads up to 64 KiB at a time, appends to the ring buffer
/// (trimming the head when past the cap), and forwards to the attached
/// viewer when one is present. On EOF (the shell exited), fires an
/// `Exit` to the viewer and drops the session from the registry.
fn pump_loop(session: Arc<PtySession>, registry: PtyRegistry, mut reader: Box<dyn Read + Send>) {
    let mut buf = [0u8; 64 * 1024];
    loop {
        match reader.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => {
                let chunk = &buf[..n];
                {
                    let mut ring = session.buffer.lock().expect("buffer mutex");
                    ring.extend_from_slice(chunk);
                    let overflow = ring.len().saturating_sub(BUFFER_CAP);
                    if overflow > 0 {
                        ring.drain(..overflow);
                    }
                }
                let viewer = { session.viewer.lock().expect("viewer mutex").clone() };
                if let Some(tx) = viewer {
                    let _ = tx.send(PumpMessage::Data(chunk.to_vec()));
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => break,
        }
    }
    // EOF or read error — tell the viewer and unregister.
    let viewer = { session.viewer.lock().expect("viewer mutex").take() };
    if let Some(tx) = viewer {
        let _ = tx.send(PumpMessage::Exit);
    }
    registry.remove(&session.session_id);
}

/// `pty.supports_pty()` equivalent — we support Linux + macOS. Windows
/// would need a separate spawn path (ConPTY), so the /ws/term handler
/// returns an early error there.
pub fn supports_pty() -> bool {
    cfg!(any(target_os = "linux", target_os = "macos"))
}

/// Resolve the shell to launch for `/ws/term`. Priority:
/// 1. Explicit `override_shell` from the config layer (Phase 4 slice 2).
/// 2. `$SHELL` environment variable.
/// 3. `/bin/bash`.
pub fn resolve_terminal_shell(override_shell: Option<&str>) -> String {
    if let Some(s) = override_shell {
        let trimmed = s.trim();
        if !trimmed.is_empty() {
            return trimmed.into();
        }
    }
    std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_terminal_shell_priority() {
        assert_eq!(resolve_terminal_shell(Some("/bin/zsh")), "/bin/zsh");
        // Empty / whitespace override falls through.
        std::env::set_var("SHELL", "/bin/override-sh");
        assert_eq!(resolve_terminal_shell(Some("   ")), "/bin/override-sh");
        std::env::remove_var("SHELL");
        assert_eq!(resolve_terminal_shell(None), "/bin/bash");
    }

    #[test]
    fn supports_pty_matches_target() {
        let got = supports_pty();
        if cfg!(target_os = "linux") || cfg!(target_os = "macos") {
            assert!(got);
        } else {
            assert!(!got);
        }
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn spawn_pty_echoes_and_exits() {
        // Drive a tiny shell command end-to-end: spawn, collect output,
        // observe exit. Uses sh -c rather than bash for robustness.
        let reg = PtyRegistry::new();
        let mode = SpawnMode::Launcher {
            argv: vec!["/bin/sh".into(), "-c".into(), "printf hello; exit 0".into()],
        };
        let session =
            spawn_session(&reg, mode, std::env::temp_dir(), 80, 24).expect("spawn session");

        // Attach a viewer so the pump forwards chunks in real time (and
        // the initial buffer replay is empty).
        let mut rx = session.attach_viewer();

        // Drain until Exit or timeout.
        let timeout_at = std::time::Instant::now() + std::time::Duration::from_secs(5);
        let mut output = Vec::new();
        let mut exited = false;
        while std::time::Instant::now() < timeout_at {
            match rx.try_recv() {
                Ok(PumpMessage::Data(bytes)) => output.extend_from_slice(&bytes),
                Ok(PumpMessage::Exit) => {
                    exited = true;
                    break;
                }
                Err(tokio::sync::mpsc::error::TryRecvError::Empty) => {
                    std::thread::sleep(std::time::Duration::from_millis(20));
                }
                Err(_) => break,
            }
        }
        assert!(exited, "pump never emitted Exit; output={output:?}");
        let text = String::from_utf8_lossy(&output);
        assert!(
            text.contains("hello"),
            "expected 'hello' in PTY output, got: {text:?}"
        );
        // Session should have been auto-removed by the pump on EOF.
        assert!(
            reg.get(&session.session_id).is_none(),
            "session not removed after exit"
        );
    }
}

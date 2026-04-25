/* Inline dev-server runner viewers.

   Each `.runner-term-mount` element rendered by the repo strip gets its
   own xterm instance + WebSocket to `/ws/runner/<key>`. The mount
   carries `hx-preserve="true"` so a parent `#git-panel` morph swap on
   `sse:code` leaves the WebSocket-attached DOM untouched. Pop-out mode
   detaches the inline ws in favour of a modal-hosted viewer, then
   re-attaches inline when the modal closes.

   `runnerReattachAll()` runs on every `htmx:afterSwap` for `#git-panel`
   to attach viewers to freshly-inserted mounts (a runner that just
   started) and close orphans (one whose mount left the DOM). User
   actions that don't write a file the watcher sees (runner
   start / stop / force-stop) explicitly fire `htmx.trigger(panel,
   'sse:code')` so the same path covers them. */

import { _termClipboardRead, _termClipboardWrite } from './terminal.js';

var _runnerViewers = {};  // "key|checkout" -> {ws, term, fit, mount, exited, isModal}
var _runnerActiveModal = null;
function _runnerDomKey(key, checkout) { return key + '|' + checkout; }

function _runnerCreateViewer(mount, key, checkout, opts) {
    if (typeof Terminal === 'undefined' || typeof FitAddon === 'undefined') return;
    opts = opts || {};
    var host = mount.querySelector('.runner-term-host');
    if (!host) return;
    var term = new Terminal({
        convertEol: false,
        cursorBlink: false,
        fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
        fontSize: 12,
        theme: {background: '#0b0b0e', foreground: '#e6e6e6'},
    });
    var fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(host);
    try { fit.fit(); } catch (e) {}
    // Same copy/paste story as the bottom terminal: Ctrl+C copies the
    // selection if there is one (else falls through to SIGINT), Ctrl+Shift+C
    // always copies, Ctrl+V pastes via the clipboard bridge. Without this
    // handler xterm swallows Ctrl+C as SIGINT before the selection can be
    // read, so users couldn't copy runner output at all.
    term.attachCustomKeyEventHandler(function(ev) {
        if (ev.type !== 'keydown') return true;
        if (ev.ctrlKey && !ev.altKey && !ev.metaKey &&
            (ev.key === 'c' || ev.key === 'C')) {
            if (ev.shiftKey || term.hasSelection()) {
                var sel = term.getSelection();
                if (sel) {
                    _termClipboardWrite(sel);
                    ev.preventDefault();
                    return false;
                }
                if (ev.shiftKey) { ev.preventDefault(); return false; }
            }
            return true;  // fall through to SIGINT
        }
        if (ev.ctrlKey && !ev.altKey && !ev.metaKey &&
            (ev.key === 'v' || ev.key === 'V')) {
            ev.preventDefault();
            _termClipboardRead().then(function(text) {
                if (text && !viewer.exited) term.paste(text);
            });
            return false;
        }
        return true;
    });
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = proto + '//' + location.host + '/ws/runner/' + encodeURIComponent(key);
    var ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    var viewer = {
        ws: ws, term: term, fit: fit, mount: mount,
        key: key, checkout: checkout,
        exited: mount.hasAttribute('data-exit-code'),
        isModal: !!opts.isModal,
    };
    _runnerViewers[_runnerDomKey(key, checkout)] = viewer;

    ws.onopen = function() {
        try {
            ws.send(JSON.stringify({type: 'resize', cols: term.cols, rows: term.rows}));
        } catch (e) {}
    };
    ws.onmessage = function(ev) {
        if (typeof ev.data === 'string') {
            try {
                var obj = JSON.parse(ev.data);
                if (obj.type === 'info') {
                    var status = obj.exit_code == null
                        ? 'running · ' + (obj.template || '')
                        : 'exited: ' + obj.exit_code;
                    _runnerSetStatus(viewer, status);
                    if (obj.exit_code != null) {
                        viewer.exited = true;
                        mount.setAttribute('data-exit-code', String(obj.exit_code));
                        mount.classList.add('runner-exited');
                    }
                } else if (obj.type === 'exit') {
                    // Only refresh on the running → exited transition. The
                    // server also replays an `exit` frame whenever a client
                    // re-attaches to an already-dead session; without this
                    // guard, the refresh re-renders the mount, reattach
                    // spins up a new viewer, the server replays `exit`
                    // again — and the repo row blinks in a tight loop.
                    var wasExited = viewer.exited;
                    viewer.exited = true;
                    mount.setAttribute('data-exit-code', String(obj.exit_code));
                    mount.classList.add('runner-exited');
                    _runnerSetStatus(viewer, 'exited: ' + (obj.exit_code == null ? '?' : obj.exit_code));
                    if (!wasExited) {
                        _runnerScheduleRefresh();
                    }
                } else if (obj.type === 'session-missing') {
                    _runnerSetStatus(viewer, 'no session');
                } else if (obj.type === 'error' && obj.message) {
                    term.write('\r\n\x1b[31m' + obj.message + '\x1b[0m\r\n');
                }
            } catch (e) {}
            return;
        }
        term.write(new Uint8Array(ev.data));
    };
    term.onData(function(data) {
        if (viewer.exited) return;
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(new TextEncoder().encode(data));
        }
    });
    // Defer a second fit pass: the mount may have been inserted with
    // display:none under a collapsed subgroup; xterm opened with cols=0,
    // and the first frame after the mount becomes visible needs a retry.
    requestAnimationFrame(function() {
        try {
            fit.fit();
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'resize', cols: term.cols, rows: term.rows}));
            }
        } catch (e) {}
    });
}

function _runnerSetStatus(viewer, text) {
    var el = viewer.mount.querySelector('.runner-term-status');
    if (el) el.textContent = text;
}

function _runnerDestroyViewer(viewer) {
    if (!viewer) return;
    try { viewer.ws.close(); } catch (e) {}
    try { viewer.term.dispose(); } catch (e) {}
    delete _runnerViewers[_runnerDomKey(viewer.key, viewer.checkout)];
}

function runnerReattachAll() {
    if (typeof Terminal === 'undefined') return;
    var mounts = document.querySelectorAll('.runner-term-mount');
    var seen = {};
    mounts.forEach(function(mount) {
        if (mount.classList.contains('runner-modal-viewer')) return;  // modal path
        var key = mount.dataset.runnerKey;
        var checkout = mount.dataset.runnerCheckout;
        if (!key || !checkout) return;
        var domKey = _runnerDomKey(key, checkout);
        seen[domKey] = true;
        var existing = _runnerViewers[domKey];
        if (existing && existing.mount === mount && !existing.isModal) return;
        // If a modal is hosting this session, leave the inline mount empty.
        if (existing && existing.isModal) return;
        if (existing) _runnerDestroyViewer(existing);
        _runnerCreateViewer(mount, key, checkout);
    });
    // Close viewers whose mount is no longer in the DOM.
    Object.keys(_runnerViewers).forEach(function(domKey) {
        if (seen[domKey]) return;
        var viewer = _runnerViewers[domKey];
        if (viewer.isModal) return;  // modal viewers outlive DOM mounts
        _runnerDestroyViewer(viewer);
    });
}

function _runnerFindMount(key, checkout) {
    var esc = (window.CSS && CSS.escape) ? CSS.escape : function(s) { return s; };
    return document.querySelector(
        '.runner-term-mount[data-runner-key="' + esc(key) + '"]'
        + '[data-runner-checkout="' + esc(checkout) + '"]'
    );
}

/* Trigger a server-side refresh of the Code pane so a runner mount that
   just appeared (or vanished) lands in the DOM. Runner state changes
   don't write a file the watcher catches, so we fire the htmx event
   explicitly. The follow-up `runnerReattachAll()` runs from
   `htmx:afterSwap` on `#git-panel`. */
function _runnerTriggerCodeRefresh() {
    var panel = document.getElementById('git-panel');
    if (panel && window.htmx) window.htmx.trigger(panel, 'sse:code');
}

var _runnerRefreshPending = null;
function _runnerScheduleRefresh() {
    // Debounce rapid state changes — a burst of starts/exits during a
    // confirm-switch flow shouldn't trigger three fragment fetches.
    if (_runnerRefreshPending) clearTimeout(_runnerRefreshPending);
    _runnerRefreshPending = setTimeout(function() {
        _runnerRefreshPending = null;
        _runnerTriggerCodeRefresh();
    }, 120);
}

async function runnerStart(ev, key, checkout, path) {
    if (ev) ev.stopPropagation();
    var res;
    try {
        res = await fetch('/api/runner/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key: key, checkout_key: checkout, path: path}),
        });
    } catch (e) {
        return;
    }
    if (res.status === 409) {
        var data = {};
        try { data = await res.json(); } catch (e) {}
        var other = data.checkout_key || '?';
        if (!confirm('Stop runner on ' + other + ' and start on ' + checkout + '?')) return;
        await _runnerStopFetch(key);
        try {
            await fetch('/api/runner/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key: key, checkout_key: checkout, path: path}),
            });
        } catch (e) {}
    }
    _runnerTriggerCodeRefresh();
}

async function runnerSwitch(ev, key, checkout, path) {
    // Same endpoint as start — server returns 409, client confirms and
    // stops+restarts. Kept as its own entrypoint so the button's onclick
    // is unambiguous in the rendered HTML.
    return runnerStart(ev, key, checkout, path);
}

async function runnerStop(ev, key) {
    if (ev) ev.stopPropagation();
    await _runnerStopFetch(key);
    _runnerTriggerCodeRefresh();
}

function runnerStopInline(btn) {
    var mount = btn.closest('.runner-term-mount');
    if (!mount) return;
    runnerStop(null, mount.dataset.runnerKey);
}

function runnerToggleCollapse(btn) {
    var mount = btn.closest('.runner-term-mount');
    if (!mount) return;
    var collapsed = mount.classList.toggle('runner-collapsed');
    btn.setAttribute('aria-label', collapsed ? 'Expand terminal' : 'Collapse terminal');
    // Refit on expand so xterm picks up the host's new height — otherwise
    // the terminal keeps its pre-collapse row count and the bottom rows
    // render off-screen.
    if (!collapsed) {
        var key = mount.dataset.runnerKey;
        var checkout = mount.dataset.runnerCheckout;
        var viewer = _runnerViewers[_runnerDomKey(key, checkout)];
        if (viewer) {
            requestAnimationFrame(function() {
                try {
                    viewer.fit.fit();
                    if (viewer.ws.readyState === WebSocket.OPEN) {
                        viewer.ws.send(JSON.stringify({
                            type: 'resize', cols: viewer.term.cols, rows: viewer.term.rows,
                        }));
                    }
                } catch (e) {}
            });
        }
    }
}

async function _runnerStopFetch(key) {
    try {
        await fetch('/api/runner/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key: key}),
        });
    } catch (e) {}
}

/* Repo-level force-stop — posts to /api/runner/force-stop which runs
   the user-configured `force_stop` shell command. Unlike runnerStop this
   is NOT scoped to a specific checkout; it's one per repo. Used to
   recover when the port is held by a process condash didn't start
   (stale server from another terminal, previous run killed uncleanly). */
async function runnerForceStop(btn, key) {
    if (btn && btn.disabled) return;
    if (btn) { btn.disabled = true; btn.classList.add('is-busy'); }
    try {
        var res = await fetch('/api/runner/force-stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key: key}),
        });
        if (!res.ok) {
            var txt = '';
            try { txt = (await res.json()).error || ''; } catch (e) {}
            console.warn('force-stop failed:', res.status, txt);
        }
    } catch (e) {
        console.warn('force-stop request errored:', e);
    } finally {
        if (btn) { btn.disabled = false; btn.classList.remove('is-busy'); }
        _runnerTriggerCodeRefresh();
    }
}

function runnerJump(ev, btn) {
    if (ev) ev.stopPropagation();
    // The jump arrow lives on a .peer-card foot; the mount lives inside
    // that same card. Fall back to the enclosing .flat-group so a jump
    // still works if the card scroll region happens to be empty.
    var scope = btn.closest('.peer-card') || btn.closest('.flat-group');
    if (!scope) return;
    var mount = scope.querySelector('.runner-term-mount');
    if (!mount) return;
    try { mount.scrollIntoView({behavior: 'smooth', block: 'center'}); }
    catch (e) { mount.scrollIntoView(); }
    mount.classList.add('runner-term-highlight');
    setTimeout(function() {
        mount.classList.remove('runner-term-highlight');
    }, 1200);
}

function runnerPopout(btn) {
    var mount = btn.closest('.runner-term-mount');
    if (!mount) return;
    if (_runnerActiveModal) _runnerCloseModal();
    var key = mount.dataset.runnerKey;
    var checkout = mount.dataset.runnerCheckout;
    var domKey = _runnerDomKey(key, checkout);
    // Detach inline viewer first — one attached ws per server-side session.
    _runnerDestroyViewer(_runnerViewers[domKey]);

    var modal = document.createElement('div');
    modal.className = 'runner-modal';
    modal.innerHTML = ''
        + '<div class="runner-modal-dialog">'
        + '  <div class="runner-modal-header">'
        + '    <span class="runner-term-label"></span>'
        + '    <span class="runner-term-status" aria-live="polite"></span>'
        + '    <button class="runner-modal-close" aria-label="Close">&times;</button>'
        + '  </div>'
        + '  <div class="runner-term-mount runner-modal-viewer" data-runner-key="'
        + key.replace(/"/g, '&quot;') + '" data-runner-checkout="'
        + checkout.replace(/"/g, '&quot;') + '">'
        + '    <div class="runner-term-host"></div>'
        + '  </div>'
        + '</div>';
    modal.querySelector('.runner-term-label').textContent = key + ' @ ' + checkout;
    document.body.appendChild(modal);
    modal.querySelector('.runner-modal-close').onclick = _runnerCloseModal;
    modal.addEventListener('click', function(ev) {
        if (ev.target === modal) _runnerCloseModal();
    });
    var viewerMount = modal.querySelector('.runner-term-mount');
    _runnerCreateViewer(viewerMount, key, checkout, {isModal: true});
    _runnerActiveModal = {
        modal: modal, key: key, checkout: checkout,
    };
    // Nudge a fit once the modal has laid out.
    requestAnimationFrame(function() {
        var viewer = _runnerViewers[_runnerDomKey(key, checkout)];
        if (!viewer) return;
        try {
            viewer.fit.fit();
            if (viewer.ws.readyState === WebSocket.OPEN) {
                viewer.ws.send(JSON.stringify({
                    type: 'resize', cols: viewer.term.cols, rows: viewer.term.rows,
                }));
            }
        } catch (e) {}
    });
}

function _runnerCloseModal() {
    var active = _runnerActiveModal;
    if (!active) return;
    _runnerActiveModal = null;
    var viewer = _runnerViewers[_runnerDomKey(active.key, active.checkout)];
    _runnerDestroyViewer(viewer);
    if (active.modal && active.modal.parentNode) {
        active.modal.parentNode.removeChild(active.modal);
    }
    // Re-attach inline if the mount still exists.
    var inlineMount = _runnerFindMount(active.key, active.checkout);
    if (inlineMount) _runnerCreateViewer(inlineMount, active.key, active.checkout);
}

function initRunnerViewersSideEffects() {
    // Sweep orphaned viewers + attach fresh ones after every htmx
    // morph swap of `#git-panel`. The mount itself is `hx-preserve`,
    // so existing live viewers survive the swap untouched; this hook
    // only matters for newly-inserted mounts (a runner that just
    // started) and for orphans (one whose mount left the DOM).
    document.body.addEventListener('htmx:afterSwap', function(ev) {
        var target = ev.target;
        if (target && target.id === 'git-panel') {
            try { runnerReattachAll(); } catch (e) {}
        }
    });

    // Initial attach — runs once xterm assets have loaded.
    document.addEventListener('DOMContentLoaded', function() {
        window.addEventListener('load', function() {
            try { runnerReattachAll(); } catch (e) {}
        }, {once: true});
    });
    // Also resize on window resize so the inline xterm tracks layout changes.
    window.addEventListener('resize', function() {
        Object.keys(_runnerViewers).forEach(function(domKey) {
            var v = _runnerViewers[domKey];
            try {
                v.fit.fit();
                if (v.ws.readyState === WebSocket.OPEN) {
                    v.ws.send(JSON.stringify({type: 'resize', cols: v.term.cols, rows: v.term.rows}));
                }
            } catch (e) {}
        });
    });
}

export {
    _runnerViewers,
    runnerReattachAll,
    runnerStart, runnerSwitch, runnerStop, runnerStopInline,
    runnerToggleCollapse, runnerForceStop, runnerJump, runnerPopout,
    initRunnerViewersSideEffects,
};

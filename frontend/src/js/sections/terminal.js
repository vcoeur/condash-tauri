/* Embedded terminal (multi-tab).

   Each tab owns its own xterm instance + pty WebSocket. Server sends
   an `exit` info frame when the shell dies; client closes the tab.
   Closing the last tab hides the pane. The pane's × and the toggle
   shortcut hide/show the pane while leaving the tabs intact.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 2 of
   conception/projects/2026-04-23-condash-frontend-extraction). This
   is the second half of the terminal-tab subsystem P-07 started —
   sections/tab-drag.js already owns _termCreateTab, _termCloseTab,
   _termSyncOpenFlag, _termChipPointerDown, _termStartRename,
   _termDefaultLabel. P-09 cut 2 brings the cross-region state
   (termState) and the shared helpers that tab-drag reaches back in
   for to the same directory. The circular import (terminal.js ↔
   tab-drag.js) is safe under the TDZ rules documented in
   notes/01-p07-tab-drag-split.md §D2. */

import {
    _termChipPointerDown, _termStartRename, _termDefaultLabel,
    _termCloseTab,
} from './tab-drag.js';

/* Clipboard bridge — Tauri 2 exposes an IPC `invoke` under
   `window.__TAURI__.core.invoke` (requires `withGlobalTauri: true` plus a
   capability covering this origin and the `clipboard-manager:allow-*-text`
   permissions; see src-tauri/src/lib.rs::run). We call the plugin's
   commands directly rather than importing `@tauri-apps/plugin-clipboard-manager`
   so the frontend bundle stays `npm install`-free — same reasoning as
   xterm/mermaid/pdfjs, which are vendored flat. Browser-mode
   (`condash-serve`) has no IPC, so `_tauriInvoke` returns null there and
   paste becomes a no-op; that's acceptable — the HTTP `/clipboard` route
   was dropped with the Python build. */
function _tauriInvoke() {
    if (typeof window === 'undefined') return null;
    var g = window.__TAURI__;
    if (g && g.core && typeof g.core.invoke === 'function') return g.core.invoke;
    var internals = window.__TAURI_INTERNALS__;
    if (internals && typeof internals.invoke === 'function') return internals.invoke;
    return null;
}

function _termClipboardWrite(text) {
    if (!text) return;
    var invoke = _tauriInvoke();
    if (!invoke) return;
    try {
        Promise.resolve(invoke('plugin:clipboard-manager|write_text', {text: text}))
            .catch(function() {});
    } catch (e) {}
}

function _termClipboardRead() {
    var invoke = _tauriInvoke();
    if (!invoke) return Promise.resolve('');
    try {
        return Promise.resolve(invoke('plugin:clipboard-manager|read_text'))
            .then(function(t) { return typeof t === 'string' ? t : ''; },
                  function() { return ''; });
    } catch (e) {
        return Promise.resolve('');
    }
}

/* Shared cross-module state for the terminal-tab subsystem. Lives on
   one object so tab-drag can mutate fields in-place — ESM live bindings
   disallow reassigning imported primitive `let` exports from the
   importer side. See
   projects/2026-04-23-condash-frontend-extraction/notes/01-p07-tab-drag-split.md
   §D1 for the design rationale. */
const termState = {
    tabs: [],                               // [{id, side, term, fit, ws, mount, button, shell}]
    active: { left: null, right: null },
    lastFocused: 'left',
};
var _termAssetsWarned = false;

function _termAssetsReady() {
    return typeof Terminal !== 'undefined' && typeof FitAddon !== 'undefined';
}

function _termWarnAssets() {
    if (_termAssetsWarned) return;
    _termAssetsWarned = true;
    document.getElementById('term-mount-left').innerHTML =
        '<p style="color:#faa; padding: 1rem;">Terminal assets failed to load — vendored xterm.js missing from /vendor/xterm/. Reinstall condash.</p>';
}

function _termSideEl(side, which) {
    // which ∈ {'tabs', 'mount', 'side'}
    if (which === 'side') return document.querySelector('.term-side[data-side="' + side + '"]');
    if (which === 'tabs') return document.getElementById('term-tabs-' + side);
    return document.getElementById('term-mount-' + side);
}

function _termTabsOn(side) {
    return termState.tabs.filter(function(t) { return t.side === side; });
}

function _termActiveTab() {
    // Prefer left's active, else right's — the "current" active for
    // header-shell display falls on whichever side was last focused.
    var leftId = termState.active.left, rightId = termState.active.right;
    var pref = termState.lastFocused === 'right' ? rightId : leftId;
    var alt = termState.lastFocused === 'right' ? leftId : rightId;
    return termState.tabs.find(function(t) { return t.id === pref; })
        || termState.tabs.find(function(t) { return t.id === alt; })
        || null;
}

function _termSendResize(tab) {
    if (!tab) tab = _termActiveTab();
    if (!tab || !tab.fit || !tab.ws || tab.ws.readyState !== WebSocket.OPEN) return;
    // Never fit a mount that isn't laid out — inactive tabs (display:none)
    // and tabs on a hidden side have clientHeight 0. FitAddon on a zero
    // box returns bogus dims and leaves xterm's viewport wedged, so the
    // scrollbar thumb/height stops matching the real scrollback.
    if (!tab.mount.clientHeight || !tab.mount.clientWidth) return;
    try {
        tab.fit.fit();
        tab.ws.send(JSON.stringify({type: 'resize', cols: tab.term.cols, rows: tab.term.rows}));
    } catch (e) {}
}

function _termSendResizeAll() {
    termState.tabs.forEach(function(t) { _termSendResize(t); });
}

/* Persist the open-tab list so a page refresh can reattach to the same
   backend ptys. Only tabs that have received their server-assigned
   session_id are persisted — an unacknowledged tab has no ID to reattach
   to and would just spawn a fresh (different) shell on reload. */
function _termPersistTabs() {
    var entries = termState.tabs
        .filter(function(t) { return !!t.session_id; })
        .map(function(t) {
            return {session_id: t.session_id, side: t.side, customName: t.customName || ''};
        });
    try { localStorage.setItem('term-tabs', JSON.stringify(entries)); } catch (e) {}
    var leftActive = null, rightActive = null;
    termState.tabs.forEach(function(t) {
        if (!t.session_id) return;
        if (termState.active[t.side] !== t.id) return;
        if (t.side === 'left') leftActive = t.session_id;
        else rightActive = t.session_id;
    });
    try {
        if (leftActive) localStorage.setItem('term-active-left', leftActive);
        else localStorage.removeItem('term-active-left');
        if (rightActive) localStorage.setItem('term-active-right', rightActive);
        else localStorage.removeItem('term-active-right');
    } catch (e) {}
}

function _termShellLabel(tab) {
    var label = document.getElementById('term-shell');
    if (!label) return;
    label.textContent = tab && tab.shell ? tab.shell : '';
}

function _termSyncActiveSide() {
    var sides = ['left', 'right'];
    sides.forEach(function(side) {
        var el = _termSideEl(side, 'side');
        if (!el) return;
        el.classList.toggle('is-active-side', side === termState.lastFocused);
    });
    // Single-pane mode — no meaningful "active side" distinction.
    var leftVisible = _termTabsOn('left').length > 0;
    var rightVisible = _termTabsOn('right').length > 0;
    if (leftVisible && rightVisible) document.body.removeAttribute('data-single-term');
    else document.body.setAttribute('data-single-term', '1');
}

function _termSetActive(id) {
    var tab = termState.tabs.find(function(t) { return t.id === id; });
    if (!tab) return;
    termState.active[tab.side] = id;
    termState.lastFocused = tab.side;
    termState.tabs.forEach(function(t) {
        if (t.side !== tab.side) return;
        var active = t.id === id;
        t.mount.classList.toggle('active', active);
        t.button.classList.toggle('active', active);
    });
    _termSyncActiveSide();
    _termShellLabel(tab);
    // Defer the fit: the just-activated mount flipped from display:none to
    // display:block one line above, but the browser hasn't reflowed yet in
    // this synchronous tick. rAF lets the layout settle so FitAddon sees
    // real dimensions (otherwise clientHeight === 0 → bogus cols/rows,
    // stale scrollbar thumb until the next window resize).
    requestAnimationFrame(function() {
        _termSendResize(tab);
        tab.term.focus();
    });
    _termPersistTabs();
}

function _termRenderTabChip(tab) {
    var btn = document.createElement('div');
    btn.className = 'term-tab';
    btn.dataset.tabId = String(tab.id);
    btn.onclick = function() { _termSetActive(tab.id); };
    btn.ondblclick = function(ev) {
        // Don't start rename if the user double-clicked the close button.
        if (ev.target && ev.target.classList.contains('term-tab-close')) return;
        _termStartRename(tab);
    };
    // Pointer-event drag: implemented entirely in JS to avoid QtWebEngine's
    // native HTML5 drag-image path, which segfaults pywebview on dragstart
    // of a DOM element this complex.
    btn.addEventListener('pointerdown', function(ev) { _termChipPointerDown(ev, tab); });
    var label = document.createElement('span');
    label.className = 'term-tab-label';
    label.textContent = _termDefaultLabel(tab);
    btn.appendChild(label);
    var close = document.createElement('button');
    close.className = 'term-tab-close';
    close.textContent = '×';
    close.title = 'Close tab';
    close.onclick = function(ev) { ev.stopPropagation(); _termCloseTab(tab.id); };
    btn.appendChild(close);
    tab.button = btn;
    tab.labelEl = label;
    _termSideEl(tab.side, 'tabs').appendChild(btn);
}

export {
    termState,
    _termClipboardWrite, _termClipboardRead,
    _termAssetsReady, _termWarnAssets,
    _termSideEl, _termTabsOn, _termActiveTab,
    _termSendResize, _termSendResizeAll,
    _termPersistTabs, _termShellLabel,
    _termSyncActiveSide, _termSetActive, _termRenderTabChip,
};

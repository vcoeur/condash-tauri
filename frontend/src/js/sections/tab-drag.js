// Terminal-tab subsystem — extracted from dashboard-main.js's
// "/* --- Tab drag (pointer-event based) --- */" region (formerly lines
// 3544–4480). The region is labelled "Tab drag" after its original core
// feature but spans the whole terminal-tab surface: pointer-event drag,
// split-pane ratio, tab create/close/rename, toggle, shortcuts, splitter
// drag, pane-resize drag, screenshot-paste, plus the restore-from-
// localStorage bootstrapping on page load. The file keeps that full
// scope to match the parent audit's region-by-region split plan (P-07
// of conception/projects/2026-04-23-condash-frontend-extraction).
//
// Shared state with the (still-inline) "Embedded terminal" region is
// held in `termState` (imported). _termNextId is private to this
// module because only _termCreateTab mutates it.
//
// Startup side effects live in initTabDragSideEffects() rather than at
// module top level so the circular import with dashboard-main.js stays
// safe — see notes/01-p07-tab-drag-split.md D2.

import {
    termState,
    _termSideEl, _termTabsOn, _termActiveTab,
    _termSendResize, _termSendResizeAll, _termPersistTabs,
    _termShellLabel, _termSyncActiveSide, _termSetActive,
    _termRenderTabChip,
    _termAssetsReady, _termWarnAssets,
    _termClipboardRead, _termClipboardWrite,
} from './terminal.js';

/* --- Tab drag (pointer-event based) -----------------------------------
   The HTML5 drag-and-drop API crashes pywebview: QtWebEngine tries to
   snapshot the dragged element for the native drag image and segfaults
   the whole process on dragstart. We do drag ourselves with pointer
   events, which stays entirely in the page — no native Qt involvement.

   Flow:
     - pointerdown on chip → arm a pending drag (don't start yet, so we
       don't steal clicks / dblclicks). Capture the pointer.
     - pointermove past a small pixel threshold → actually start the
       drag: clone the chip into a floating "ghost" that follows the
       cursor, dim the original, add drop markers based on
       elementFromPoint.
     - pointerup → drop. If dragging: reparent via _termMoveTabTo. If
       not dragging (just a click): let the normal onclick run.
     - pointercancel / escape → abort cleanly.

   Cross-pane moves reparent both the chip button and the xterm mount
   DOM nodes; the pty session keeps running since it's bound to the ws,
   not the DOM. No reconnect, no scrollback loss. */

var _termDrag = null;  // {tab, pointerId, startX, startY, active, ghost, lastDrop}
var _TERM_DRAG_THRESHOLD_PX = 5;
// Per-page-load monotonic tab id. Private to this module because
// _termCreateTab is the only mutator.
var _termNextId = 1;

function _termChipPointerDown(ev, tab) {
    // Only left mouse / primary pointer. Ignore clicks on the close × so
    // it still dismisses via its own onclick.
    if (ev.button !== undefined && ev.button !== 0) return;
    if (ev.target && ev.target.classList && ev.target.classList.contains('term-tab-close')) return;
    // Don't start a drag over the rename input.
    if (ev.target && ev.target.tagName === 'INPUT') return;
    _termDrag = {
        tab: tab,
        pointerId: ev.pointerId,
        startX: ev.clientX,
        startY: ev.clientY,
        active: false,
        ghost: null,
        lastDrop: null,
    };
    try { tab.button.setPointerCapture(ev.pointerId); } catch (e) {}
    tab.button.addEventListener('pointermove', _termChipPointerMove);
    tab.button.addEventListener('pointerup', _termChipPointerUp);
    tab.button.addEventListener('pointercancel', _termChipPointerCancel);
}

function _termChipPointerMove(ev) {
    if (!_termDrag || ev.pointerId !== _termDrag.pointerId) return;
    var dx = ev.clientX - _termDrag.startX;
    var dy = ev.clientY - _termDrag.startY;
    if (!_termDrag.active) {
        if (Math.hypot(dx, dy) < _TERM_DRAG_THRESHOLD_PX) return;
        _termBeginDrag();
    }
    _termDrag.ghost.style.left = (ev.clientX - _termDrag.ghostOffX) + 'px';
    _termDrag.ghost.style.top = (ev.clientY - _termDrag.ghostOffY) + 'px';
    _termUpdateDropMarkers(ev.clientX, ev.clientY);
}

function _termChipPointerUp(ev) {
    if (!_termDrag || ev.pointerId !== _termDrag.pointerId) return;
    var drag = _termDrag;
    _termCleanupDrag();
    if (!drag.active) return;  // Was just a click — onclick already fired.
    if (!drag.lastDrop) return;
    var d = drag.lastDrop;
    if (d.kind === 'chip' && d.target.id === drag.tab.id) return;  // drop on self
    if (d.kind === 'chip') {
        var before = d.before;
        var beforeTab = before ? d.target : _termNextTabOnSide(d.target);
        _termMoveTabTo(drag.tab, d.target.side, beforeTab);
    } else if (d.kind === 'strip') {
        _termMoveTabTo(drag.tab, d.side, null);
    }
}

function _termChipPointerCancel(ev) {
    if (!_termDrag || ev.pointerId !== _termDrag.pointerId) return;
    _termCleanupDrag();
}

function _termBeginDrag() {
    var tab = _termDrag.tab;
    _termDrag.active = true;
    // Build a floating clone that follows the cursor. pointer-events:none
    // on the ghost is critical — without it, elementFromPoint returns the
    // ghost instead of the chip/strip below the cursor.
    var rect = tab.button.getBoundingClientRect();
    var ghost = tab.button.cloneNode(true);
    ghost.classList.add('term-tab-ghost');
    ghost.style.position = 'fixed';
    ghost.style.left = rect.left + 'px';
    ghost.style.top = rect.top + 'px';
    ghost.style.width = rect.width + 'px';
    ghost.style.height = rect.height + 'px';
    ghost.style.pointerEvents = 'none';
    ghost.style.zIndex = '9999';
    ghost.style.opacity = '0.85';
    document.body.appendChild(ghost);
    _termDrag.ghost = ghost;
    _termDrag.ghostOffX = _termDrag.startX - rect.left;
    _termDrag.ghostOffY = _termDrag.startY - rect.top;
    tab.button.classList.add('is-dragging');
    document.getElementById('term-tabs-left').classList.add('is-drop-target');
    document.getElementById('term-tabs-right').classList.add('is-drop-target');
}

function _termUpdateDropMarkers(x, y) {
    // Clear previous markers on every chip.
    document.querySelectorAll('.term-tab.is-drop-before, .term-tab.is-drop-after').forEach(function(el) {
        el.classList.remove('is-drop-before');
        el.classList.remove('is-drop-after');
    });
    _termDrag.lastDrop = null;
    var el = document.elementFromPoint(x, y);
    if (!el) return;
    var chipEl = el.closest ? el.closest('.term-tab') : null;
    if (chipEl && chipEl.classList.contains('term-tab-ghost')) chipEl = null;
    if (chipEl) {
        var id = parseInt(chipEl.dataset.tabId, 10);
        var target = termState.tabs.find(function(t) { return t.id === id; });
        if (target && target.id !== _termDrag.tab.id) {
            var rect = chipEl.getBoundingClientRect();
            var before = x < rect.left + rect.width / 2;
            chipEl.classList.toggle('is-drop-before', before);
            chipEl.classList.toggle('is-drop-after', !before);
            _termDrag.lastDrop = {kind: 'chip', target: target, before: before};
            return;
        }
    }
    var stripEl = el.closest ? el.closest('.term-tabs') : null;
    if (stripEl) {
        var side = stripEl.id === 'term-tabs-right' ? 'right' : 'left';
        _termDrag.lastDrop = {kind: 'strip', side: side};
    }
}

function _termCleanupDrag() {
    if (!_termDrag) return;
    var tab = _termDrag.tab;
    try { tab.button.releasePointerCapture(_termDrag.pointerId); } catch (e) {}
    tab.button.removeEventListener('pointermove', _termChipPointerMove);
    tab.button.removeEventListener('pointerup', _termChipPointerUp);
    tab.button.removeEventListener('pointercancel', _termChipPointerCancel);
    if (_termDrag.ghost && _termDrag.ghost.parentNode) {
        _termDrag.ghost.parentNode.removeChild(_termDrag.ghost);
    }
    tab.button.classList.remove('is-dragging');
    document.querySelectorAll('.term-tab.is-drop-before, .term-tab.is-drop-after').forEach(function(el) {
        el.classList.remove('is-drop-before');
        el.classList.remove('is-drop-after');
    });
    document.querySelectorAll('.term-tabs.is-drop-target').forEach(function(el) {
        el.classList.remove('is-drop-target');
    });
    _termDrag = null;
}

function _termNextTabOnSide(tab) {
    var sideTabs = _termTabsOn(tab.side);
    var idx = sideTabs.findIndex(function(t) { return t.id === tab.id; });
    if (idx < 0 || idx === sideTabs.length - 1) return null;
    return sideTabs[idx + 1];
}

/* Reparent ``tab`` into ``targetSide`` at the position before ``beforeTab``
   (null = append to end). Keeps the pty session alive, updates active/
   last-focused state, refits the xterm, and persists. */
function _termMoveTabTo(tab, targetSide, beforeTab) {
    if (!tab || !tab.button || !tab.mount) return;
    targetSide = targetSide === 'right' ? 'right' : 'left';
    var sourceSide = tab.side;
    var wasActiveOnSource = termState.active[sourceSide] === tab.id;

    // Reparent DOM: chip into target strip; mount into target mount area.
    var targetStrip = _termSideEl(targetSide, 'tabs');
    var targetMount = _termSideEl(targetSide, 'mount');
    if (!targetStrip || !targetMount) return;
    if (beforeTab && beforeTab.button && beforeTab.button.parentNode === targetStrip) {
        targetStrip.insertBefore(tab.button, beforeTab.button);
    } else {
        targetStrip.appendChild(tab.button);
    }
    if (tab.mount.parentNode !== targetMount) {
        targetMount.appendChild(tab.mount);
    }
    tab.side = targetSide;

    // Keep termState.tabs in visual order so _termPersistTabs records
    // the new layout. Remove the dragged tab, then reinsert it at its
    // new index derived from DOM sibling order within the target strip.
    var i = termState.tabs.indexOf(tab);
    if (i >= 0) termState.tabs.splice(i, 1);
    var stripChildren = Array.prototype.slice.call(targetStrip.children);
    var domIdx = stripChildren.indexOf(tab.button);
    // Map the DOM position back to an insertion index in termState.tabs:
    // walk earlier siblings, count how many are in the array (some — e.g.
    // the tab we just moved — are not in the array yet).
    var priorArrayIdx = 0;
    for (var k = 0; k < domIdx; k++) {
        var siblingId = parseInt(stripChildren[k].dataset.tabId, 10);
        var siblingPos = termState.tabs.findIndex(function(t) { return t.id === siblingId; });
        if (siblingPos >= 0) priorArrayIdx = siblingPos + 1;
    }
    termState.tabs.splice(priorArrayIdx, 0, tab);

    // Same-side reorder: keep the currently active tab selected on both
    // sides. Cross-pane move: the moved tab becomes active on its new
    // side; the source side's active slot falls back to the last
    // remaining tab (or null if empty).
    if (sourceSide !== targetSide) {
        if (wasActiveOnSource) {
            var remaining = _termTabsOn(sourceSide);
            termState.active[sourceSide] = remaining.length ? remaining[remaining.length - 1].id : null;
            if (termState.active[sourceSide] !== null) {
                var stillActive = termState.tabs.find(function(t) { return t.id === termState.active[sourceSide]; });
                if (stillActive) {
                    stillActive.mount.classList.add('active');
                    stillActive.button.classList.add('active');
                }
            }
        }
        // Clear any stale active classes on the moved tab, then activate
        // it on its new side.
        tab.mount.classList.remove('active');
        tab.button.classList.remove('active');
        _termSetActive(tab.id);
    }

    _termShowSide(sourceSide, _termTabsOn(sourceSide).length > 0);
    _termShowSide(targetSide, true);
    _termPersistTabs();
    // The moved xterm was laid out against the source side's dimensions;
    // the target side is usually a different width. Refit after the DOM
    // move settles.
    setTimeout(_termSendResizeAll, 0);
}

/* Move the currently active tab to ``targetSide`` via the Ctrl+Left /
   Ctrl+Right shortcut. No-op if no active tab or if the tab is already
   on that side (leaves within-pane ordering alone). */
function _termMoveActiveTabToSide(targetSide) {
    var tab = _termActiveTab();
    if (!tab) return;
    if (tab.side === targetSide) return;
    _termMoveTabTo(tab, targetSide, null);
}

function _termDefaultLabel(tab) {
    var base = tab.shell ? (tab.shell.split('/').pop() || 'sh') : 'sh';
    return base + ' ' + tab.id;
}

function _termRefreshLabel(tab) {
    if (!tab.labelEl) return;
    tab.labelEl.textContent = tab.customName || _termDefaultLabel(tab);
}

function _termStartRename(tab) {
    if (!tab.labelEl) return;
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'term-tab-rename';
    input.value = tab.customName || _termDefaultLabel(tab);
    input.style.width = Math.max(60, tab.labelEl.offsetWidth + 20) + 'px';
    var committed = false;
    var commit = function(save) {
        if (committed) return;
        committed = true;
        if (save) {
            tab.customName = input.value.trim();
            _termPersistTabs();
        }
        if (input.parentNode) {
            tab.button.insertBefore(tab.labelEl, input);
            input.parentNode.removeChild(input);
        }
        _termRefreshLabel(tab);
    };
    input.onkeydown = function(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); commit(true); }
        else if (ev.key === 'Escape') { ev.preventDefault(); commit(false); }
        ev.stopPropagation();
    };
    input.onblur = function() { commit(true); };
    input.onclick = function(ev) { ev.stopPropagation(); };
    tab.button.insertBefore(input, tab.labelEl);
    tab.button.removeChild(tab.labelEl);
    // Focus must happen *after* every requestAnimationFrame queued by the
    // two single-click handlers that preceded this double-click: each
    // click calls _termSetActive, which schedules an rAF that does
    // tab.term.focus(). A synchronous input.focus() here would lose
    // focus to xterm when those rAFs fire next frame, triggering our
    // own onblur and committing an unchanged name. Scheduling input.focus
    // via rAF parks it after the pending focus steals (rAFs run in FIFO
    // order within a frame).
    requestAnimationFrame(function() {
        input.focus();
        input.select();
    });
}

function _termApplySplitRatio() {
    var r = parseFloat(localStorage.getItem('term-split-ratio') || '');
    var leftEl = _termSideEl('left', 'side');
    var rightEl = _termSideEl('right', 'side');
    if (isFinite(r) && r > 0 && r < 1) {
        leftEl.style.flex = r + ' 1 0';
        rightEl.style.flex = (1 - r) + ' 1 0';
    } else {
        leftEl.style.flex = '';
        rightEl.style.flex = '';
    }
}

function _termShowSide(side, show) {
    var sideEl = _termSideEl(side, 'side');
    if (show) sideEl.removeAttribute('hidden');
    else sideEl.setAttribute('hidden', '');
    // Splitter only visible when both sides are populated.
    var leftVisible = _termTabsOn('left').length > 0;
    var rightVisible = _termTabsOn('right').length > 0;
    var splitter = document.getElementById('term-splitter');
    if (leftVisible && rightVisible) {
        splitter.removeAttribute('hidden');
        // Both sides present — apply any saved split ratio.
        _termApplySplitRatio();
    } else {
        splitter.setAttribute('hidden', '');
        // Single side — clear inline flex so the lone side falls back
        // to the CSS default (flex: 1 1 0) and fills the whole .term-body.
        // Flexbox's "sum of grow factors < 1" rule would otherwise leave
        // a gap the width of the old split when the saved ratio is < 50/50
        // on the surviving side.
        _termSideEl('left', 'side').style.flex = '';
        _termSideEl('right', 'side').style.flex = '';
    }
    _termSyncActiveSide();
}

function _termCreateTab(side, opts) {
    if (!_termAssetsReady()) { _termWarnAssets(); return; }
    side = side === 'right' ? 'right' : 'left';
    opts = opts || {};
    var id = _termNextId++;
    var mount = document.createElement('div');
    mount.className = 'term-mount-session';
    _termSideEl(side, 'mount').appendChild(mount);
    // Reveal the side if it was previously empty.
    _termShowSide(side, true);
    var term = new Terminal({
        convertEol: false,
        cursorBlink: true,
        fontFamily: 'ui-monospace, "SF Mono", "Menlo", monospace',
        fontSize: 13,
        theme: {background: '#0b0b0e', foreground: '#e6e6e6'},
    });
    var fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(mount);
    // When the user clicks into this pane directly, mark its side as the
    // active one so the split's accent indicator follows focus (not just
    // tab clicks, which _termSetActive already handles).
    if (term.textarea) {
        term.textarea.addEventListener('focus', function() {
            if (termState.lastFocused !== side) {
                termState.lastFocused = side;
                _termSyncActiveSide();
                _termShellLabel(tab);
            }
        });
    }
    // xterm swallows keys before they bubble. attachCustomKeyEventHandler
    // runs inside xterm's keydown listener — return false + stopPropagation
    // so our shortcut closes the pane from inside the active tab without
    // the document handler firing a second toggle.
    term.attachCustomKeyEventHandler(function(ev) {
        if (ev.type !== 'keydown') return true;
        // Toggle the pane — see comment in _termInit for why we both
        // handle it here and preventDefault+stopPropagation.
        if (_termShortcut && _matchShortcut(ev, _termShortcut)) {
            ev.preventDefault();
            ev.stopPropagation();
            toggleTerminal();
            return false;
        }
        // Screenshot-paste shortcut. Intercept here too — xterm's keydown
        // handler runs before our document listener, and the default
        // Ctrl+Shift+V collides with the Ctrl+V clipboard branch below.
        if (_screenshotPasteShortcut && _matchShortcut(ev, _screenshotPasteShortcut)) {
            ev.preventDefault();
            ev.stopPropagation();
            pasteRecentScreenshot();
            return false;
        }
        // Move-active-tab shortcuts — arrow keys are otherwise consumed by
        // xterm and never bubble to the document handler.
        if (_termMoveLeftShortcut && _matchShortcut(ev, _termMoveLeftShortcut)) {
            ev.preventDefault();
            ev.stopPropagation();
            _termMoveActiveTabToSide('left');
            return false;
        }
        if (_termMoveRightShortcut && _matchShortcut(ev, _termMoveRightShortcut)) {
            ev.preventDefault();
            ev.stopPropagation();
            _termMoveActiveTabToSide('right');
            return false;
        }
        // Ctrl+C: copy the current selection if there is one, otherwise
        // let xterm send ^C (SIGINT) as normal. Ctrl+Shift+C: always copy
        // (no-op without a selection) — matches GNOME Terminal / Ghostty.
        if (ev.ctrlKey && !ev.altKey && !ev.metaKey &&
            (ev.key === 'c' || ev.key === 'C')) {
            if (ev.shiftKey || term.hasSelection()) {
                var sel = term.getSelection();
                if (sel) {
                    _termClipboardWrite(sel);
                    ev.preventDefault();
                    return false;
                }
                // Ctrl+Shift+C with no selection — swallow silently.
                if (ev.shiftKey) { ev.preventDefault(); return false; }
            }
            return true;  // fall through to SIGINT
        }
        // Ctrl+V / Ctrl+Shift+V: read clipboard via the bridge (browser
        // API if allowed, else the /clipboard server endpoint backed by
        // QClipboard). We can't rely on xterm's native paste in Qt
        // webviews because the paste event rarely fires there.
        if (ev.ctrlKey && !ev.altKey && !ev.metaKey &&
            (ev.key === 'v' || ev.key === 'V')) {
            ev.preventDefault();
            _termClipboardRead().then(function(text) {
                if (text) term.paste(text);
            });
            return false;
        }
        return true;
    });

    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = proto + '//' + location.host + '/ws/term';
    // Reattach path: session_id binds the ws to an existing pty + replays
    // its ring buffer. Spawn path: cwd (when set) asks the server to fork
    // the new shell in that directory; it's sandbox-validated server-side
    // and silently ignored if invalid. The two are mutually exclusive —
    // cwd has no meaning when reattaching.
    if (opts.session_id) {
        wsUrl += '?session_id=' + encodeURIComponent(opts.session_id);
    } else {
        var q = [];
        if (opts.cwd) q.push('cwd=' + encodeURIComponent(opts.cwd));
        if (opts.launcher) q.push('launcher=1');
        if (q.length) wsUrl += '?' + q.join('&');
    }
    var ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    var tab = {
        id: id, side: side, term: term, fit: fit, ws: ws, mount: mount,
        shell: '', customName: opts.customName || '',
        session_id: opts.session_id || null,
    };

    ws.onopen = function() { _termSendResize(tab); };
    ws.onmessage = function(ev) {
        if (typeof ev.data === 'string') {
            try {
                var obj = JSON.parse(ev.data);
                if (obj.type === 'session-expired') {
                    // Server doesn't know this session (usually: condash
                    // restarted). Drop the stale tab so the user doesn't
                    // sit in front of an unusable pane. localStorage is
                    // rewritten by _termCloseTab → _termPersistTabs.
                    _termCloseTab(tab.id);
                } else if (obj.type === 'error' && obj.message) {
                    term.write('\r\n\x1b[31m' + obj.message + '\x1b[0m\r\n');
                } else if (obj.type === 'info') {
                    tab.session_id = obj.session_id || tab.session_id;
                    tab.shell = obj.shell || tab.shell;
                    _termRefreshLabel(tab);
                    _termPersistTabs();
                    if (termState.active[tab.side] === tab.id) _termShellLabel(tab);
                } else if (obj.type === 'exit') {
                    _termCloseTab(tab.id);
                }
            } catch (e) {}
            return;
        }
        term.write(new Uint8Array(ev.data));
    };
    ws.onclose = function() {
        // Covers both explicit exits and abnormal drops. _termCloseTab is
        // idempotent (no-op if the tab is already gone).
        _termCloseTab(tab.id);
    };
    term.onData(function(data) {
        if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data));
    });

    _termRenderTabChip(tab);
    termState.tabs.push(tab);
    // _termShowSide at the top of this function ran before the push, so
    // _termTabsOn(side).length was 0 for the in-flight tab on the first
    // right-side create → the splitter stayed hidden. Re-run it now that
    // the tab is counted.
    _termShowSide(side, true);
    fit.fit();
    _termSetActive(id);
    // Revealing the other side (flex 100% → flex share) shrinks any
    // existing tabs on this side too; mirror the close path's refit-all
    // so their xterm cols match the new layout.
    setTimeout(_termSendResizeAll, 0);
}

function _termCloseTab(id) {
    var idx = termState.tabs.findIndex(function(t) { return t.id === id; });
    if (idx < 0) return;
    var tab = termState.tabs[idx];
    var side = tab.side;
    try { tab.ws.close(); } catch (e) {}
    try { tab.term.dispose(); } catch (e) {}
    if (tab.mount && tab.mount.parentNode) tab.mount.parentNode.removeChild(tab.mount);
    if (tab.button && tab.button.parentNode) tab.button.parentNode.removeChild(tab.button);
    termState.tabs.splice(idx, 1);
    var sideTabs = _termTabsOn(side);
    if (sideTabs.length === 0) {
        // This side is empty — hide it; splitter hides too.
        _termShowSide(side, false);
        termState.active[side] = null;
    } else if (termState.active[side] === id) {
        _termSetActive(sideTabs[sideTabs.length - 1].id);
    }
    if (termState.tabs.length === 0) {
        // Both sides empty — hide the pane. Next reopen spawns a fresh tab.
        var pane = document.getElementById('term-pane');
        pane.setAttribute('hidden', '');
        _termSyncOpenFlag(false);
        localStorage.removeItem('term-open');
        _termShellLabel(null);
        return;
    }
    // If the side we just closed matched the "last focused" preference,
    // flip to the other side so the header shell label follows focus.
    if (termState.lastFocused === side && sideTabs.length === 0) {
        termState.lastFocused = side === 'left' ? 'right' : 'left';
        _termShellLabel(_termActiveTab());
    }
    // Re-fit the surviving side so its xterm fills the reclaimed space.
    setTimeout(_termSendResizeAll, 0);
    _termPersistTabs();
}

function termNewTab(side) {
    var pane = document.getElementById('term-pane');
    if (pane.hasAttribute('hidden')) {
        pane.removeAttribute('hidden');
        _termSyncOpenFlag(true);
        localStorage.setItem('term-open', '1');
    }
    _termCreateTab(side || 'left');
}

/* Spawn a pty tab that runs the configured terminal.launcher_command
   (default "claude"). The server forks straight into the launcher argv
   instead of a login shell; when the process exits, the tab closes. */
function termNewLauncherTab(side) {
    if (!_termLauncherCommand) return;
    var pane = document.getElementById('term-pane');
    if (pane.hasAttribute('hidden')) {
        pane.removeAttribute('hidden');
        _termSyncOpenFlag(true);
        localStorage.setItem('term-open', '1');
    }
    var label = _termLauncherCommand.split(/\s+/)[0] || 'launcher';
    _termCreateTab(side || 'left', {launcher: true, customName: label});
}

function _termSyncOpenFlag(open) {
    // Mirror the pane's visibility onto body[data-term-open] so CSS rules
    // that need to react (e.g. the note modal's bottom offset) can match
    // on an attribute selector instead of sniffing the pane's [hidden].
    if (open) document.body.setAttribute('data-term-open', '1');
    else document.body.removeAttribute('data-term-open');
}

function toggleTerminal() {
    var pane = document.getElementById('term-pane');
    var opening = pane.hasAttribute('hidden');
    if (opening) {
        pane.removeAttribute('hidden');
        _termSyncOpenFlag(true);
        localStorage.setItem('term-open', '1');
        if (termState.tabs.length === 0) _termCreateTab('left');
        setTimeout(function() {
            var tab = _termActiveTab();
            if (tab) { _termSendResize(tab); tab.term.focus(); }
        }, 0);
    } else {
        pane.setAttribute('hidden', '');
        _termSyncOpenFlag(false);
        localStorage.removeItem('term-open');
    }
}

/* Split drag: adjust the flex-grow on both sides as the user drags the
   splitter. Ratio persists in localStorage so the width survives
   reloads. Clamp at 15%/85% to keep both sides usable. */
var _termSplitDrag = null;
function termSplitStart(ev) {
    var body = document.querySelector('.term-body');
    var leftEl = _termSideEl('left', 'side');
    var rightEl = _termSideEl('right', 'side');
    _termSplitDrag = {
        startX: ev.clientX,
        totalW: body.clientWidth,
        leftW: leftEl.offsetWidth,
        leftEl: leftEl,
        rightEl: rightEl,
    };
    document.addEventListener('mousemove', _termSplitMove);
    document.addEventListener('mouseup', _termSplitEnd);
    ev.preventDefault();
}
function _termSplitMove(ev) {
    if (!_termSplitDrag) return;
    var d = _termSplitDrag;
    var dx = ev.clientX - d.startX;
    var newLeft = Math.max(d.totalW * 0.15, Math.min(d.totalW * 0.85, d.leftW + dx));
    var leftRatio = newLeft / d.totalW;
    d.leftEl.style.flex = leftRatio + ' 1 0';
    d.rightEl.style.flex = (1 - leftRatio) + ' 1 0';
}
function _termSplitEnd() {
    document.removeEventListener('mousemove', _termSplitMove);
    document.removeEventListener('mouseup', _termSplitEnd);
    if (!_termSplitDrag) return;
    var leftRatio = _termSplitDrag.leftEl.offsetWidth / _termSplitDrag.totalW;
    localStorage.setItem('term-split-ratio', String(leftRatio.toFixed(3)));
    _termSplitDrag = null;
    _termSendResizeAll();
}

/* Drag-resize: adjust the --term-height CSS variable while dragging, then
   persist the final value. Shares the `_termDrag` binding with the chip-
   drag machinery above — `var` hoisting unifies the two declarations, and
   the two gestures can never overlap at runtime (one pointer, one
   mouse-drag at a time). Collision kept verbatim from the pre-split
   source; see notes/01-p07-tab-drag-split.md D5. */
var _termDrag = null;
function termDragStart(ev) {
    _termDrag = {startY: ev.clientY, startH: document.getElementById('term-pane').offsetHeight};
    document.addEventListener('mousemove', _termDragMove);
    document.addEventListener('mouseup', _termDragEnd);
    ev.preventDefault();
}
function _termDragMove(ev) {
    if (!_termDrag) return;
    var dy = _termDrag.startY - ev.clientY;
    var h = Math.max(140, Math.min(window.innerHeight - 80, _termDrag.startH + dy));
    document.documentElement.style.setProperty('--term-height', h + 'px');
}
function _termDragEnd() {
    document.removeEventListener('mousemove', _termDragMove);
    document.removeEventListener('mouseup', _termDragEnd);
    if (!_termDrag) return;
    _termDrag = null;
    var h = document.getElementById('term-pane').offsetHeight;
    localStorage.setItem('term-height', h + 'px');
    // Must refit every tab on both sides, not just the active one: the
    // pane height change is symmetric, but _termSendResize() with no arg
    // only resizes the last-focused tab. With two sides open and the last
    // focus on the right, the left side's xterm stayed wedged at its old
    // row count (and vice versa) — looked like "left vertical resize
    // broken" to the user, because that was the side that usually wasn't
    // last-focused.
    _termSendResizeAll();
}

/* Parse a shortcut spec like "Ctrl+`" / "Ctrl+Shift+T" / "Alt+K" into a
   comparison object. Returns null on malformed input so we can bail
   instead of binding a bogus handler. */
function _parseShortcut(spec) {
    if (!spec || typeof spec !== 'string') return null;
    var parts = spec.split('+').map(function(s){return s.trim();}).filter(Boolean);
    if (!parts.length) return null;
    var mods = {ctrl: false, shift: false, alt: false, meta: false};
    var key = null;
    parts.forEach(function(p) {
        var low = p.toLowerCase();
        if (low === 'ctrl' || low === 'control') mods.ctrl = true;
        else if (low === 'shift') mods.shift = true;
        else if (low === 'alt' || low === 'option') mods.alt = true;
        else if (low === 'meta' || low === 'cmd' || low === 'command' || low === 'super') mods.meta = true;
        else key = p;
    });
    if (!key) return null;
    return {
        ctrl: mods.ctrl, shift: mods.shift, alt: mods.alt, meta: mods.meta,
        // Normalise single chars to lower-case; leave named keys as-is.
        key: key.length === 1 ? key.toLowerCase() : key,
    };
}

function _matchShortcut(ev, spec) {
    if (!spec) return false;
    if (ev.ctrlKey !== spec.ctrl) return false;
    if (ev.shiftKey !== spec.shift) return false;
    if (ev.altKey !== spec.alt) return false;
    if (ev.metaKey !== spec.meta) return false;
    var k = ev.key;
    return (k && k.length === 1 ? k.toLowerCase() : k) === spec.key;
}

var _termShortcut = null;
var _screenshotPasteShortcut = null;
var _termMoveLeftShortcut = null;
var _termMoveRightShortcut = null;
var _termLauncherCommand = '';

async function _loadTermShortcuts() {
    try {
        var res = await fetch('/config');
        if (!res.ok) return;
        var cfg = await res.json();
        var term = cfg.terminal || {};
        _termShortcut = _parseShortcut(term.shortcut || 'Ctrl+`');
        _screenshotPasteShortcut = _parseShortcut(term.screenshot_paste_shortcut || 'Ctrl+Shift+V');
        _termMoveLeftShortcut = _parseShortcut(term.move_tab_left_shortcut || 'Ctrl+Left');
        _termMoveRightShortcut = _parseShortcut(term.move_tab_right_shortcut || 'Ctrl+Right');
        _termLauncherCommand = (term.launcher_command || '').trim();
        _termSyncLauncherButtons();
    } catch (e) {}
}

/* Show or hide the per-side launcher "+" buttons based on whether the
   config has a non-empty launcher_command. Runs on config load and on
   every /config POST that goes through this page. */
function _termSyncLauncherButtons() {
    var show = !!_termLauncherCommand;
    ['left', 'right'].forEach(function(side) {
        var btn = document.getElementById('term-launcher-' + side);
        if (!btn) return;
        if (show) {
            btn.removeAttribute('hidden');
            var label = _termLauncherCommand.split(/\s+/)[0] || 'launcher';
            btn.title = 'New ' + label + ' tab (' + side + ')';
            btn.setAttribute('aria-label', btn.title);
        } else {
            btn.setAttribute('hidden', '');
        }
    });
}

/* Lightweight transient banner shown by keyboard-shortcut actions that
   don't have a button to flash. Reuses one DOM node — multiple calls
   restart the visibility timer rather than stacking. */
var _toastTimer = null;
function _showToast(msg, opts) {
    var el = document.getElementById('shortcut-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'shortcut-toast';
        el.className = 'shortcut-toast';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.toggle('is-err', !!(opts && opts.error));
    // Force reflow so the opacity transition replays on rapid re-fires.
    void el.offsetWidth;
    el.classList.add('is-visible');
    if (_toastTimer) clearTimeout(_toastTimer);
    var ms = (opts && opts.ms) || 1800;
    _toastTimer = setTimeout(function() {
        el.classList.remove('is-visible');
    }, ms);
}

/* Look up the most recent screenshot path server-side and inject it into
   the active terminal tab — no Enter, the user confirms. Mirrors workOn():
   if no tab is open, open the pane + spawn one and poll until ws is ready.
   Surfaces errors via a transient toast since there's no button to flash. */
async function pasteRecentScreenshot() {
    var info;
    try {
        var res = await fetch('/recent-screenshot');
        info = await res.json();
        if (!res.ok) {
            _showToast((info && info.error) || ('HTTP ' + res.status), {error: true});
            return;
        }
    } catch (e) {
        _showToast('Could not query screenshot directory', {error: true});
        return;
    }
    if (!info.path) {
        var dirNote = info.dir ? ' (' + info.dir + ')' : '';
        _showToast('No screenshot found' + dirNote + (info.reason ? ' — ' + info.reason : ''), {error: true});
        return;
    }
    var text = info.path;
    var active = _termActiveTab();
    if (active && active.ws && active.ws.readyState === WebSocket.OPEN) {
        active.ws.send(new TextEncoder().encode(text));
        active.term.focus();
        return;
    }
    var pane = document.getElementById('term-pane');
    if (pane.hasAttribute('hidden')) {
        pane.removeAttribute('hidden');
        _termSyncOpenFlag(true);
        localStorage.setItem('term-open', '1');
    }
    if (termState.tabs.length === 0) _termCreateTab('left');
    var tries = 0;
    (function trySend() {
        var tab = _termActiveTab();
        if (tab && tab.ws && tab.ws.readyState === WebSocket.OPEN) {
            tab.ws.send(new TextEncoder().encode(text));
            tab.term.focus();
            return;
        }
        if (++tries < 40) setTimeout(trySend, 75);
    })();
}

/* Wire up the terminal-tab subsystem's DOM-level side effects. Called
   once from dashboard-main.js after both modules have finished
   evaluating — see notes/01-p07-tab-drag-split.md D3. */
function initTabDragSideEffects() {
    window.addEventListener('resize', function() { _termSendResizeAll(); });

    document.addEventListener('keydown', function(ev) {
        var inEditable = ev.target && (ev.target.tagName === 'INPUT' ||
                                       ev.target.tagName === 'TEXTAREA' ||
                                       ev.target.isContentEditable);
        if (_termShortcut) {
            var hasModifier = _termShortcut.ctrl || _termShortcut.alt || _termShortcut.meta;
            if (!(inEditable && !hasModifier) && _matchShortcut(ev, _termShortcut)) {
                ev.preventDefault();
                toggleTerminal();
                return;
            }
        }
        if (_screenshotPasteShortcut) {
            var hasMod = _screenshotPasteShortcut.ctrl || _screenshotPasteShortcut.alt || _screenshotPasteShortcut.meta;
            // The default Ctrl+Shift+V collides with xterm's paste — that
            // handler is registered inside attachCustomKeyEventHandler and
            // fires first, so we'd never see the event. Catch it here at the
            // capture phase below instead. For non-terminal targets the bubble
            // phase is fine, so we still listen here.
            if (!(inEditable && !hasMod) && _matchShortcut(ev, _screenshotPasteShortcut)) {
                ev.preventDefault();
                pasteRecentScreenshot();
                return;
            }
        }
        if (_termMoveLeftShortcut && _matchShortcut(ev, _termMoveLeftShortcut)) {
            if (!inEditable || _termMoveLeftShortcut.ctrl || _termMoveLeftShortcut.alt || _termMoveLeftShortcut.meta) {
                ev.preventDefault();
                _termMoveActiveTabToSide('left');
                return;
            }
        }
        if (_termMoveRightShortcut && _matchShortcut(ev, _termMoveRightShortcut)) {
            if (!inEditable || _termMoveRightShortcut.ctrl || _termMoveRightShortcut.alt || _termMoveRightShortcut.meta) {
                ev.preventDefault();
                _termMoveActiveTabToSide('right');
                return;
            }
        }
    });

    _loadTermShortcuts();

    // Restore persisted height + open state + any live pty sessions on load.
    (function restoreTerm() {
        var saved = localStorage.getItem('term-height');
        if (saved) document.documentElement.style.setProperty('--term-height', saved);
        if (localStorage.getItem('term-open') !== '1') return;

        var persisted = [];
        try {
            var raw = localStorage.getItem('term-tabs');
            if (raw) persisted = JSON.parse(raw);
            if (!Array.isArray(persisted)) persisted = [];
        } catch (e) { persisted = []; }
        var leftActive = localStorage.getItem('term-active-left') || null;
        var rightActive = localStorage.getItem('term-active-right') || null;

        document.addEventListener('DOMContentLoaded', function() {
            // Defer until xterm scripts have loaded (they use `defer`).
            window.addEventListener('load', function() {
                if (typeof Terminal === 'undefined') return;
                var pane = document.getElementById('term-pane');
                pane.removeAttribute('hidden');
                _termSyncOpenFlag(true);
                if (persisted.length === 0) {
                    // No sessions recorded (fresh open, or first run after
                    // this feature shipped) — preserve the old behaviour of
                    // spawning one fresh left tab.
                    _termCreateTab('left');
                    return;
                }
                persisted.forEach(function(entry) {
                    if (!entry || typeof entry !== 'object') return;
                    if (!entry.session_id) return;
                    _termCreateTab(entry.side === 'right' ? 'right' : 'left', {
                        session_id: entry.session_id,
                        customName: entry.customName || '',
                    });
                });
                // Restore which tab is active per side. Match by session_id
                // because the in-memory `id` is assigned fresh each page load.
                termState.tabs.forEach(function(t) {
                    if (!t.session_id) return;
                    if (t.side === 'left' && t.session_id === leftActive) _termSetActive(t.id);
                    else if (t.side === 'right' && t.session_id === rightActive) _termSetActive(t.id);
                });
            }, {once: true});
        });
    })();
}

export {
    _termChipPointerDown, _termStartRename, _termDefaultLabel, _termCloseTab,
    _termCreateTab, _termSyncOpenFlag, _loadTermShortcuts,
    toggleTerminal, termNewTab, termNewLauncherTab,
    termDragStart, termSplitStart, pasteRecentScreenshot,
    initTabDragSideEffects,
};

/* Git row actions — "open in IDEA / VS Code / terminal / Files" handlers
   for the buttons rendered next to every git status row and every card.

   Extracted from dashboard-main.js on 2026-04-24 (P-08 of
   conception/projects/2026-04-23-condash-frontend-extraction).

   openInTerminal and workOn reach into the terminal-tab subsystem —
   import _termSyncOpenFlag + _termCreateTab from the tab-drag module
   (P-07) and _termActiveTab + _termSendResize + termState from
   dashboard-main.js (the terminal region, earmarked for P-09). All
   cross-module references sit inside function bodies, so the circular
   import (dashboard-main → git-actions → dashboard-main) is safe
   under the same TDZ rules documented in
   notes/01-p07-tab-drag-split.md §D2. */

import { _termCreateTab, _termSyncOpenFlag } from './tab-drag.js';
import { termState, _termActiveTab, _termSendResize } from './terminal.js';

async function openPath(ev, path, tool) {
    ev.stopPropagation();
    var btn = ev.currentTarget;
    // Buttons now hold an inline SVG, so save/restore innerHTML.
    var originalHtml = btn.innerHTML;
    btn.disabled = true;
    function restore() {
        btn.innerHTML = originalHtml;
        btn.classList.remove('is-ok', 'is-err');
        btn.disabled = false;
    }
    function flash(cls, label, ms) {
        btn.classList.add(cls);
        btn.textContent = label;
        setTimeout(restore, ms);
    }
    try {
        var res = await fetch('/open', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: path, tool: tool})
        });
        if (!res.ok) {
            flash('is-err', 'err', 1200);
            return;
        }
        flash('is-ok', 'ok', 800);
    } catch (e) {
        flash('is-err', 'err', 1200);
    }
}

/* Open the integrated terminal pane and spawn a fresh tab cwd'd at the
   given path. The button lives next to the "open with" slots on every
   git row; path is the same absolute directory those slots use, and is
   re-validated server-side against the workspace/worktrees sandbox
   before the pty is forked. */
function openInTerminal(ev, path) {
    if (ev) { ev.stopPropagation(); ev.preventDefault(); }
    var pane = document.getElementById('term-pane');
    if (pane.hasAttribute('hidden')) {
        pane.removeAttribute('hidden');
        _termSyncOpenFlag(true);
        localStorage.setItem('term-open', '1');
    }
    var side = termState.lastFocused === 'right' ? 'right' : 'left';
    // Default tab label to the target directory basename so several tabs
    // opened from different repos are visually distinct. Writes to
    // customName, so double-click-to-rename still overrides it and the
    // choice persists across reloads via _termPersistTabs.
    var basename = String(path).replace(/\/+$/, '').split('/').pop() || '';
    _termCreateTab(side, {cwd: path, customName: basename});
    setTimeout(function() {
        var tab = _termActiveTab();
        if (tab) { _termSendResize(tab); tab.term.focus(); }
    }, 0);
}

/* Per-card "work on <slug>" button — inject the text at the prompt of
   the currently focused terminal tab, no auto-Enter (user confirms). If
   no tab is open, open the terminal pane, spawn one, and inject once
   its WebSocket is ready. */
function workOn(ev, slug) {
    if (ev) { ev.stopPropagation(); ev.preventDefault(); }
    var text = 'work on ' + slug;
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
    // Fresh tab: ws.open is async — poll briefly until the socket is ready.
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

/* Code tab · "open with" popover.

   The code-tab's per-repo strip renders a dropdown of IDE launchers
   (IDEA, VS Code, etc.) behind a "⋯" button. Click toggles the popover;
   a click outside closes every open popover; Escape does the same. Used
   to live at the tail of the runner-viewers region in dashboard-main.js
   — moved here on 2026-04-24 (P-09 cut 2) because it's pure git-row
   wiring, not a runner concern. */
function gitToggleOpenPopover(ev, btn) {
    if (ev) { ev.stopPropagation(); ev.preventDefault(); }
    var grp = btn.closest('.open-grp');
    if (!grp) return;
    var popover = grp.querySelector('.open-popover');
    if (!popover) return;
    var isOpen = !popover.hidden;
    gitClosePopovers();
    if (!isOpen) popover.hidden = false;
}

function gitClosePopovers(root) {
    var scope = root || document;
    scope.querySelectorAll('.open-popover').forEach(function(p) { p.hidden = true; });
}

function initGitActionsSideEffects() {
    document.addEventListener('click', function(ev) {
        // Clicking outside any .open-grp closes every open popover.
        if (ev.target && ev.target.closest && ev.target.closest('.open-grp')) return;
        gitClosePopovers();
    }, true);
    document.addEventListener('keydown', function(ev) {
        if (ev.key === 'Escape') gitClosePopovers();
    });
}

/* Per-card "open folder" button — hand the item's folder to the OS
   default file manager. Mirrors openPath's transient ok/err feedback. */
async function openFolder(ev, relPath) {
    if (ev) { ev.stopPropagation(); ev.preventDefault(); }
    var btn = ev.currentTarget;
    var originalHtml = btn.innerHTML;
    btn.disabled = true;
    function restore() {
        btn.innerHTML = originalHtml;
        btn.classList.remove('is-ok', 'is-err');
        btn.disabled = false;
    }
    function flash(cls, label, ms) {
        btn.classList.add(cls);
        btn.textContent = label;
        setTimeout(restore, ms);
    }
    try {
        var res = await fetch('/open-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: relPath})
        });
        if (!res.ok) { flash('is-err', 'err', 1200); return; }
        flash('is-ok', 'ok', 800);
    } catch (e) {
        flash('is-err', 'err', 1200);
    }
}

export {
    openPath, openInTerminal, workOn, openFolder,
    gitToggleOpenPopover, gitClosePopovers, initGitActionsSideEffects,
};

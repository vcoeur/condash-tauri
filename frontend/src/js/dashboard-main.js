/* Bundled dashboard script — migrated from the classic inline `<script>`
   block in dashboard.html on 2026-04-22 (F3/F4 of condash-frontend-split).
   Originally kept as one big file because the 247 declarations coexisted
   as globals in the inline script; region-level splitting into
   `sections/*.js` is now in progress (P-07..P-10 of
   conception/projects/2026-04-23-condash-frontend-extraction).

   First split: the terminal-tab subsystem (former "Tab drag" region)
   lives in `sections/tab-drag.js`. Imports below + exports scattered
   through the file are the contract between the two halves; see
   notes/01-p07-tab-drag-split.md for the design decisions. The split is
   intentionally circular (dashboard-main.js ↔ sections/tab-drag.js) —
   safe because cross-module references only occur inside function
   bodies, and side-effect registration happens from
   initTabDragSideEffects() called at the bottom of this file. */

import {
    _termChipPointerDown, _termStartRename, _termDefaultLabel, _termCloseTab,
    _termCreateTab, _termSyncOpenFlag, _loadTermShortcuts,
    toggleTerminal, termNewTab, termNewLauncherTab,
    termDragStart, termSplitStart, pasteRecentScreenshot,
    initTabDragSideEffects,
} from './sections/tab-drag.js';
import {
    toggleTheme, initThemeSideEffects,
} from './sections/theme.js';
import {
    openAboutModal, closeAboutModal, initAboutModalSideEffects,
} from './sections/about-modal.js';
import {
    _refreshShadowCache, _consumeShadowCache, _clearShadowCache,
} from './sections/shadow-cache.js';
import {
    openPath, openInTerminal, workOn, openFolder,
    gitToggleOpenPopover, gitClosePopovers, initGitActionsSideEffects,
} from './sections/git-actions.js';
import {
    openNewItemModal, closeNewItemModal, submitNewItem,
    initNewItemModalSideEffects,
} from './sections/new-item-modal.js';
import {
    _NOTES_OPEN_KEY, restoreNotesTreeState, initNotesTreeStateSideEffects,
} from './sections/notes-tree-state.js';
import {
    _cm, _mountCm, _destroyCm, _cmRetheme,
} from './sections/cm6-mount.js';
import {
    initCm6ThemeSyncSideEffects,
} from './sections/cm6-theme-sync.js';
import {
    reloadState,
    _noteModalDirty, _runnerActiveIn,
    _defaultReloadSkipIf, _flushPendingReloads,
} from './sections/reload-guards.js';
import {
    _supportsFragmentFetch,
    _captureDetailsOpenState,
    _restoreDetailsOpenState,
} from './sections/local-subtree-reload.js';
import {
    focusSafeSwap,
} from './sections/dom-swap.js';
import {
    runnerReattachAll,
    runnerStart, runnerSwitch, runnerStop, runnerStopInline,
    runnerToggleCollapse, runnerForceStop, runnerJump, runnerPopout,
    initRunnerViewersSideEffects,
} from './sections/runner-viewers.js';
import {
    staleState,
    _renderStale, _deriveLegacyFlags,
    checkUpdates, _scheduleCheckUpdates,
    updateBaseline, reloadNode, refreshAll,
} from './sections/stale-poll.js';
import {
    initSseSideEffects,
} from './sections/sse.js';
import {
    openNotePreview, noteNavBack, closeNotePreview,
} from './sections/note-preview.js';
import {
    noteSearchRun, noteSearchStep, noteSearchClose,
    initInNoteSearchSideEffects,
} from './sections/in-note-search.js';
import {
    setNoteMode, saveEdit, createNoteFor, startRenameNote,
    initNoteModeSideEffects,
    _syncModeControls,
} from './sections/note-mode.js';
import {
    _reconcileNoteModal,
    _noteReconcileDismiss, _noteReconcileReload,
} from './sections/note-reconcile.js';
import {
    _setDirty,
} from './sections/note-preview.js';
import {
    initActionDispatch, registerAction,
} from './sections/action-dispatch.js';
import { firePostReloadHooks } from './sections/reload-hooks.js';
import {
    openConfigModal, closeConfigModal, saveConfig,
} from './sections/config-modal.js';
import {
    updateTabCounts, filterKnowledge, filterHistory,
    jumpToProject, _openHistoryHit, _reapplySearches,
} from './sections/search-filter.js';
import {
    toggleSection, openDeliverable, cycle, removeStep, updateProgress,
    addStep, stepPointerDown, startEditText,
} from './sections/steps.js';

/* --- Tabs & Cards --- */
function togglePriMenu(wrap) {
    var menu = wrap.querySelector('.pri-menu');
    var isOpen = menu.classList.contains('open');
    closePriMenus();
    if (!isOpen) menu.classList.add('open');
}

function closePriMenus() {
    document.querySelectorAll('.pri-menu.open').forEach(function(m) { m.classList.remove('open'); });
}

function toggleCard(card) {
    card.classList.toggle('collapsed');
}

var PRI_ORDER = {now:0, soon:1, later:2, backlog:3, review:4, done:5};

function sortCards() {
    // Re-append cards and group headings in priority order. Headings carry
    // data-group="<priority>" and are sorted just before their cards.
    var ct = document.getElementById('cards');
    var items = [].slice.call(ct.querySelectorAll(':scope > .card, :scope > .group-heading'));
    items.sort(function(a, b) {
        var pa, pb, ha, hb;
        if (a.classList.contains('group-heading')) {
            pa = PRI_ORDER[a.getAttribute('data-group')]; ha = 0;
        } else {
            pa = a.getAttribute('data-priority') in PRI_ORDER ? PRI_ORDER[a.getAttribute('data-priority')] : 9;
            ha = 1;
        }
        if (b.classList.contains('group-heading')) {
            pb = PRI_ORDER[b.getAttribute('data-group')]; hb = 0;
        } else {
            pb = b.getAttribute('data-priority') in PRI_ORDER ? PRI_ORDER[b.getAttribute('data-priority')] : 9;
            hb = 1;
        }
        if (pa !== pb) return pa - pb;
        if (ha !== hb) return ha - hb;
        return b.id.slice(0,10).localeCompare(a.id.slice(0,10));
    });
    items.forEach(function(c) { ct.appendChild(c); });
}

export var TAB_MAP = {
    current: ['now', 'review'],
    next: ['soon', 'later'],
    backlog: ['backlog'],
    done: ['done'],
};
// Tabs where the priority groups should be labelled with a subheader.
var TAB_SHOWS_HEADINGS = {current: true, next: true};
var PRIMARY_TABS = ['projects', 'code', 'knowledge', 'history'];
var SUBTABS = ['current', 'next', 'backlog', 'done'];
export var _activeTab = 'projects';
export var _activeSubtab = 'current';
// Map legacy `?tab=current` style URLs onto the new (primary, sub) pair.
// History used to be a Projects sub-tab; legacy `?tab=projects&sub=history`
// or `?tab=history-subtab` links land on the new History primary tab.
var LEGACY_TAB_ALIAS = {
    current: ['projects', 'current'],
    next: ['projects', 'next'],
    backlog: ['projects', 'backlog'],
    done: ['projects', 'done'],
    knowledge: ['knowledge', null],
};

function _persistTabState() {
    var url = new URL(location.href);
    url.searchParams.set('tab', _activeTab);
    if (_activeTab === 'projects') url.searchParams.set('sub', _activeSubtab);
    else url.searchParams.delete('sub');
    history.replaceState(null, '', url);
}

export function switchTab(tab) {
    if (!PRIMARY_TABS.includes(tab)) tab = 'projects';
    // Clicking the already-active tab refreshes the dashboard when its
    // Phase 3: the active tab auto-reloads, so the old "click same
    // stale tab = refresh" branch is gone. Clicking an inactive tab
    // that has its binary dot rebuilds #dash-main so the fresh tab
    // content lands before the user sees stale data.
    var clickedSameTab = tab === _activeTab;
    _deriveLegacyFlags();
    var clickedTabStale =
        ((tab === 'projects' || tab === 'history') && staleState.itemsStale) ||
        (tab === 'code' && staleState.gitStale) ||
        (tab === 'knowledge' && staleState.knowledgeStale);
    if (!clickedSameTab && clickedTabStale) {
        // Commit the new tab first so _reloadInPlace's post-swap
        // _rebindDashHandlers → switchTab(_activeTab) lands on it.
        _activeTab = tab;
        _reloadInPlace();
        return;
    }
    _activeTab = tab;
    document.querySelectorAll('.tabs-primary .tab').forEach(function(t) {
        t.classList.toggle('active', t.getAttribute('data-tab') === tab);
    });
    // Reveal the pane matching the active primary tab.
    document.getElementById('projects-pane').style.display = tab === 'projects' ? '' : 'none';
    document.getElementById('code-pane').style.display = tab === 'code' ? '' : 'none';
    document.getElementById('knowledge-pane').style.display = tab === 'knowledge' ? '' : 'none';
    document.getElementById('history-pane').style.display = tab === 'history' ? '' : 'none';
    // The Current/Next/Backlog/Done filter only applies under Projects.
    document.getElementById('projects-subtabs').style.display = tab === 'projects' ? '' : 'none';
    if (tab === 'projects') _applySubtab(_activeSubtab);
    _persistTabState();
    // Re-render dots so the newly-active tab loses its marker and any
    // previously-active tab that remained dirty gains one.
    if (typeof _renderStale === 'function') _renderStale();
}

export function switchSubtab(sub) {
    if (!SUBTABS.includes(sub)) sub = 'current';
    _activeSubtab = sub;
    _applySubtab(sub);
    _persistTabState();
}

export function _applySubtab(sub) {
    document.querySelectorAll('#projects-subtabs .tab').forEach(function(t) {
        t.classList.toggle('active', t.getAttribute('data-subtab') === sub);
    });
    var allowed = TAB_MAP[sub] || [];
    document.querySelectorAll('.card').forEach(function(card) {
        card.classList.toggle('hidden', allowed.indexOf(card.getAttribute('data-priority')) === -1);
    });
    document.querySelectorAll('.group-heading').forEach(function(h) {
        var pri = h.getAttribute('data-group');
        var show = TAB_SHOWS_HEADINGS[sub] && allowed.indexOf(pri) !== -1;
        if (show) {
            var any = document.querySelector('.card[data-priority="' + pri + '"]');
            if (!any) show = false;
        }
        h.classList.toggle('hidden', !show);
    });
}

async function pickPriority(file, val, wrap) {
    closePriMenus();
    var card = wrap.closest('.card');
    var cur = wrap.querySelector('.pri-current');
    var res = await fetch('/set-priority', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, priority: val})
    });
    if (!res.ok) return;
    var result = await res.json();
    if (result.moved) { _reloadInPlace(); return; }
    cur.className = 'pri-current pri-' + val;
    cur.textContent = val;
    card.setAttribute('data-priority', val);
    sortCards();
    switchTab(_activeTab);
    if (_activeTab === 'projects') switchSubtab(_activeSubtab);
    updateTabCounts();
    updateBaseline();
}

document.addEventListener('click', function(e) {
    if (!e.target.closest('.pri-wrap')) closePriMenus();
});

/* In-place refresh: refetch /, parse the fresh HTML, swap #dash-main
   into place, and re-apply tab/subtab state + counters. Used instead of
   location.reload() by mutations that only change dashboard content
   (toggling a step, reordering, …). Keeps:
   - the terminal pane (sibling of #dash-main, with its own pty session
     state preserved server-side by Fix B anyway),
   - open modals (also siblings of #dash-main),
   - window and document-level event listeners,
   - scroll position and focus/selection inside dash-main, restored
     after swap.
   Falls back to location.reload() on any error so the user never ends
   up looking at a half-swapped DOM. */
var _reloadInPlaceInFlight = false;
var _reloadInPlacePending = false;
export async function _reloadInPlace() {
    // Single-flight with trailing coalesce. Two _reloadInPlace calls
    // racing (e.g. a rapid burst of SSE events) used to swap #dash-main
    // twice — and if the responses completed out-of-order (request 1
    // from an older server snapshot resolving after request 2 from a
    // newer one), the older snapshot would land last and briefly render
    // a card in no column / with a stale priority until the next poll
    // fixed it. Queue a trailing run so the last caller's intent still
    // executes, then coalesces. condash#14 (project vanishes after
    // reload / file change).
    if (_reloadInPlaceInFlight) { _reloadInPlacePending = true; return; }
    _reloadInPlaceInFlight = true;
    try {
        // Phase 4: consume the shadow cache when present so a tab click
        // that landed right after a background prefetch doesn't re-issue
        // the same fetch. Any other path falls back to a live fetch.
        var prefetched = _consumeShadowCache();
        var html = prefetched;
        if (!html) {
            var res = await fetch('/', {cache: 'no-store'});
            if (!res.ok) { location.reload(); return; }
            html = await res.text();
        }
        var fresh = new DOMParser()
            .parseFromString(html, 'text/html')
            .getElementById('dash-main');
        var current = document.getElementById('dash-main');
        if (!fresh || !current) { location.reload(); return; }

        var result = focusSafeSwap(current, fresh);
        if (result.skipped) {
            reloadState.pendingInPlace = true;
            return;
        }
        // A successful global swap is authoritative. Clear any residual
        // dirty entries synchronously so the _renderStale inside
        // switchTab (called from _rebindDashHandlers below) doesn't paint
        // a dot based on ids the server just re-rendered for us. The
        // async updateBaseline() that follows confirms the empty set
        // against a fresh /check-updates. condash#14.
        staleState.dirtyNodes = new Set();
        _rebindDashHandlers();
        firePostReloadHooks();
    } catch (e) {
        location.reload();
    } finally {
        _reloadInPlaceInFlight = false;
        if (_reloadInPlacePending) {
            _reloadInPlacePending = false;
            _reloadInPlace();
        }
    }
}

/* Re-apply state to the freshly-swapped #dash-main. Inline onclick
   attributes inside the new HTML are already wired by the browser;
   document/window-level listeners never went away. What's left is to
   restore the active primary/sub tab selection and refresh counters
   + the "stale" reload-indicator baseline. */
function _rebindDashHandlers() {
    switchTab(_activeTab);
    if (_activeTab === 'projects') switchSubtab(_activeSubtab);
    updateTabCounts();
    updateBaseline();
    _reapplySearches();
    restoreNotesTreeState();
}

document.addEventListener('DOMContentLoaded', function() {
    var params = new URLSearchParams(location.search);
    var tab = params.get('tab') || '';
    var sub = params.get('sub') || '';
    // Legacy URL support: old ?tab=current links land on Projects/Current.
    var alias = LEGACY_TAB_ALIAS[tab];
    if (alias) { tab = alias[0]; sub = alias[1] || sub; }
    // History was a Projects sub-tab — legacy `?tab=projects&sub=history`
    // lands on the new History primary tab.
    if (tab === 'projects' && sub === 'history') { tab = 'history'; sub = ''; }
    if (PRIMARY_TABS.indexOf(tab) === -1) tab = 'projects';
    if (tab === 'projects' && SUBTABS.indexOf(sub) !== -1) _activeSubtab = sub;
    switchTab(tab);
    restoreNotesTreeState();
    _restorePreservedSearches();
});

/* Phase 5: pull saved search terms out of sessionStorage and replay
   them through the filter functions. Runs once on initial page load;
   subsequent swaps go through focusSafeSwap which handles restoration
   via data-preserve. */
function _restorePreservedSearches() {
    var mapping = {
        'condash.search.knowledge': {id: 'knowledge-search', fn: 'filterKnowledge'},
        'condash.search.history': {id: 'history-search', fn: 'filterHistory'},
    };
    Object.keys(mapping).forEach(function(key) {
        var raw = null;
        try { raw = sessionStorage.getItem(key); } catch (e) { return; }
        if (!raw) return;
        var payload;
        try { payload = JSON.parse(raw); } catch (e) { return; }
        if (!payload || payload.value == null || payload.value === '') return;
        var input = document.getElementById(mapping[key].id);
        if (!input) return;
        input.value = payload.value;
        if (typeof window[mapping[key].fn] === 'function') {
            window[mapping[key].fn](payload.value);
        }
    });
}

/* Find the node id (`projects/<pri>/<slug>`) of the card that owns
   ``readmePath``. Used so localized actions like upload / mkdir can
   refresh just the affected card via reloadNode() instead of swapping
   the whole dashboard (which would re-collapse every other card). */
function _cardNodeIdFor(readmePath) {
    var parts = (readmePath || '').split('/');
    if (parts.length < 4) return null;
    var slug = parts[2];
    var card = document.getElementById(slug);
    return card ? card.getAttribute('data-node-id') : null;
}

/* Open a hidden file picker, then POST the chosen files to /note/upload
   as multipart/form-data. ``subdir`` is the subdir-relative path (e.g.
   "notes/drafts") or empty for the root. After upload, refresh the
   card so the new files appear, and pre-open the target group. */
/* Upload one or more files into ``<item>/<subdirRelToItem>/``. The
   subdir is the same string the server stored as the group's
   ``rel_dir`` — empty for the item root. */
function uploadToNotes(readmePath, subdirRelToItem) {
    var input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', async function() {
        if (!input.files || !input.files.length) {
            document.body.removeChild(input);
            return;
        }
        var fd = new FormData();
        fd.append('item_readme', readmePath);
        if (subdirRelToItem) fd.append('subdir', subdirRelToItem);
        for (var i = 0; i < input.files.length; i++) {
            fd.append('file', input.files[i], input.files[i].name);
        }
        try {
            var res = await fetch('/note/upload', {method: 'POST', body: fd});
            var data = await res.json().catch(function() { return {}; });
            if (!res.ok) {
                alert('Upload failed: ' + (data.reason || data.error || ('HTTP ' + res.status)));
                return;
            }
            if ((data.rejected || []).length) {
                alert('Some files were rejected:\n' + data.rejected.map(function(r) {
                    return '  ' + (r.filename || '?') + ': ' + r.reason;
                }).join('\n'));
            }
            // Pre-open the target group so the user sees the new files.
            if (subdirRelToItem) {
                var parts = readmePath.split('/');
                if (parts.length >= 4) {
                    var slug = parts[2];
                    try {
                        localStorage.setItem(_NOTES_OPEN_KEY + slug + '/' + subdirRelToItem, 'open');
                    } catch (e) {}
                }
            }
            // Localized refresh: only the affected card swaps in place
            // so other cards keep their expanded/collapsed state.
            var nodeId = _cardNodeIdFor(readmePath);
            if (nodeId) reloadNode(nodeId); else _reloadInPlace();
        } catch (e) {
            alert('Network error: ' + e);
        } finally {
            document.body.removeChild(input);
        }
    });
    input.click();
}

/* Prompt for a subdirectory name and POST /note/mkdir. ``parentRelToItem``
   is the directory the new folder lives in, relative to the item root —
   "" creates a sibling of notes/ at the item root, "notes" creates a
   child of notes/, "notes/drafts" creates a child of notes/drafts. */
async function createNotesSubdir(readmePath, parentRelToItem) {
    var promptLabel = parentRelToItem
        ? 'New subdirectory inside ' + parentRelToItem + '/ (e.g. drafts):'
        : 'New folder at the item root (sibling of notes/, e.g. drawings):';
    var raw = prompt(promptLabel, '');
    if (!raw) return;
    raw = raw.trim().replace(/^\/+|\/+$/g, '');
    if (!raw) return;
    if (!/^[\w.-]+(\/[\w.-]+)*$/.test(raw)) {
        alert('Invalid name: only letters, digits, dot, dash, underscore, and "/" for nesting.');
        return;
    }
    var subpath = parentRelToItem ? parentRelToItem + '/' + raw : raw;
    try {
        var res = await fetch('/note/mkdir', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({item_readme: readmePath, subpath: subpath}),
        });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok) {
            var msg = data.reason === 'exists'
                ? 'A folder with that name already exists.'
                : (data.reason || data.error || ('HTTP ' + res.status));
            alert('Could not create folder: ' + msg);
            return;
        }
        // Pre-open the new group so it's visible right after the refresh.
        if (data.subdir_key) {
            try { localStorage.setItem(_NOTES_OPEN_KEY + data.subdir_key, 'open'); }
            catch (e) {}
        }
        var nodeId = _cardNodeIdFor(readmePath);
        if (nodeId) reloadNode(nodeId); else _reloadInPlace();
    } catch (e) {
        alert('Network error: ' + e);
    }
}


// The "Stale-detection polling" region (checkUpdates, _renderStale,
// staleState, reloadNode, refreshAll, updateBaseline, …) now lives in
// `sections/stale-poll.js`. The "SSE event stream" region
// (_startEventStream, reconnect bookkeeping) now lives in
// `sections/sse.js`. Both were extracted on 2026-04-24 as P-09 cut 3 —
// see notes/05-p09-cut3.md for the design decisions.

// The "Tab drag" region that used to live here (pointer-event drag,
// tab create/close/rename, splitter drag, pane-resize drag, shortcuts,
// restore-on-reload) now lives in `sections/tab-drag.js`. Register its
// DOM-level side effects now that both modules have finished
// evaluating — see the notes for P-07
// (projects/2026-04-23-condash-frontend-extraction/notes/01-p07-tab-drag-split.md).
/* Register all click actions rendered by the server as `data-action`
   attrs. Keep this block in one place so the inventory is obvious — one
   registerAction call per distinct action name, grouped by subsystem. */
function registerDashboardActions() {
    // Top-level navigation
    registerAction('switch-tab',          (_e, _el, d) => switchTab(d.tab));
    registerAction('switch-subtab',       (_e, _el, d) => switchSubtab(d.subtab));
    registerAction('refresh-all',         () => refreshAll());
    registerAction('toggle-theme',        () => toggleTheme());
    registerAction('toggle-terminal',     () => toggleTerminal());

    // Modals — open
    registerAction('open-new-item-modal', () => openNewItemModal());
    registerAction('open-about-modal',    () => openAboutModal());
    registerAction('open-config-modal',   () => openConfigModal());

    // Modals — close (explicit button, and backdrop-click variant)
    registerAction('close-new-item-modal', () => closeNewItemModal());
    registerAction('close-about-modal',    () => closeAboutModal());
    registerAction('close-config-modal',   () => closeConfigModal());
    registerAction('close-note-preview',   () => closeNotePreview());
    registerAction('close-on-backdrop', (event, el) => {
        if (event.target !== el) return;
        const target = el.dataset.target;
        if (target === 'note-preview') closeNotePreview();
        else if (target === 'about-modal') closeAboutModal();
        else if (target === 'config-modal') closeConfigModal();
        else if (target === 'new-item-modal') closeNewItemModal();
    });

    // Terminal
    registerAction('term-new-tab',          (_e, _el, d) => termNewTab(d.side));
    registerAction('term-new-launcher-tab', (_e, _el, d) => termNewLauncherTab(d.side));

    // Note preview / edit
    registerAction('note-nav-back', () => noteNavBack());
    registerAction('set-note-mode', (_e, _el, d) => setNoteMode(d.mode));
    registerAction('save-edit',     () => saveEdit());

    // Note reconcile modal
    registerAction('note-reconcile-dismiss', () => _noteReconcileDismiss());
    registerAction('note-reconcile-reload',  () => _noteReconcileReload());

    // In-note search
    registerAction('note-search-step', (_e, _el, d) => noteSearchStep(parseInt(d.delta, 10) || 0));
    registerAction('note-search-close', () => noteSearchClose());

    // Card header / priority menu
    registerAction('toggle-card',    (_e, el) => toggleCard(el.closest('.card')));
    registerAction('toggle-pri-menu', (_e, el) => togglePriMenu(el));
    registerAction('pick-priority',  (_e, el, d) =>
        pickPriority(d.path, d.priority, el.closest('.pri-wrap')));

    // Steps + section folding
    registerAction('cycle-step',     (_e, el, d) => {
        const step = el.closest('.step');
        cycle(d.filePath, +step.dataset.line, step);
    });
    registerAction('start-edit-text', (_e, el) => startEditText(el));
    registerAction('remove-step',     (_e, el, d) => {
        const step = el.closest('.step');
        removeStep(d.filePath, +step.dataset.line, el);
    });
    registerAction('toggle-section',  (_e, el) => toggleSection(el));
    registerAction('add-step',        (_e, el, d) =>
        addStep(d.filePath, d.heading, el.previousElementSibling));

    // Note preview (cards, history, knowledge, readme link, index badges)
    registerAction('open-note-preview', (_e, _el, d) => openNotePreview(d.path, d.title));

    // History search results (rendered client-side by search-filter.js)
    registerAction('open-history-hit', (_e, el) => _openHistoryHit(el));
    registerAction('jump-to-project',  (_e, el) => jumpToProject(el));

    // Notes/files tree actions
    registerAction('create-note-for', (_e, _el, d) =>
        createNoteFor(d.readmeRel, d.relDir));
    registerAction('upload-to-notes', (_e, _el, d) =>
        uploadToNotes(d.readmeRel, d.relDir));
    registerAction('create-notes-subdir', (_e, _el, d) =>
        createNotesSubdir(d.readmeRel, d.relDir));

    // Deliverables
    registerAction('open-deliverable', (_e, _el, d) => openDeliverable(d.fullPath));

    // Card actions (work-on, open-folder)
    registerAction('work-on',     (event, _el, d) => workOn(event, d.slug));
    registerAction('open-folder', (_e, el, d) => openFolder(el, d.relDir));

    // Git-strip: open-with popover + primary launcher
    registerAction('open-path', (_e, el, d) => {
        openPath(el, d.path, d.tool);
        gitClosePopovers();
    });
    registerAction('open-in-terminal', (_e, _el, d) => {
        openInTerminal(null, d.path);
        gitClosePopovers();
    });
    registerAction('git-toggle-open-popover', (event, el) => gitToggleOpenPopover(event, el));

    // Git-strip: runner tri-state button (start / stop / switch)
    registerAction('runner-start',  (event, _el, d) => runnerStart(event, d.key, d.checkout, d.path));
    registerAction('runner-stop',   (event, _el, d) => runnerStop(event, d.key));
    registerAction('runner-switch', (event, _el, d) => runnerSwitch(event, d.key, d.checkout, d.path));

    // Inline runner mount controls
    registerAction('runner-toggle-collapse', (_e, el) => runnerToggleCollapse(el));
    registerAction('runner-popout',          (_e, el) => runnerPopout(el));
    registerAction('runner-stop-inline',     (_e, el) => runnerStopInline(el));
    registerAction('runner-force-stop',      (_e, el, d) => runnerForceStop(el, d.key));
    registerAction('runner-jump',            (event, el) => runnerJump(event, el));
}
registerDashboardActions();
initActionDispatch();

initTabDragSideEffects();
initThemeSideEffects();
initAboutModalSideEffects();
initNewItemModalSideEffects();
initNotesTreeStateSideEffects();
initCm6ThemeSyncSideEffects();
initGitActionsSideEffects();
initRunnerViewersSideEffects();
initInNoteSearchSideEffects();
initNoteModeSideEffects();

// Phase 6: event-driven staleness. /events streams tab-level hints;
// checkUpdates() runs on connect + every hint to reconcile the real
// node-level dirty set. The 5s poll is gone. If the SSE connection
// drops, a visible indicator surfaces and reconnect logic re-runs
// checkUpdates() as soon as the stream is back.
checkUpdates();
initSseSideEffects();

/* On first load, detect an unset conception_path and surface the setup
   banner + auto-open the config modal so the user lands on the editor. */
(async function detectSetup() {
    try {
        var res = await fetch('/config');
        if (!res.ok) return;
        var cfg = await res.json();
        if (!cfg.conception_path) {
            document.getElementById('setup-banner').style.display = '';
            openConfigModal();
        }
    } catch (e) {}
})();

// The post-data-action residual: a few inline handlers still reach the
// global scope because they fire on non-click events (oninput, onkeydown,
// ondblclick, onsubmit, onmousedown, onpointerdown). Every click-driven
// attribute moved to `data-action` + `registerAction(…)` above. The CM6
// init bridge (`cm6-init.js`) also reads `window._syncModeControls` when
// the CodeMirror bundle finishes loading, since that file is a classic
// (non-ESM) script.
Object.assign(window, {
    addStep,                                  // onkeydown in _macros.html.j2 (Add-step input)
    startRenameNote,                          // ondblclick on the note-modal title
    stepPointerDown,                          // onpointerdown on the step drag handle
    termDragStart, termSplitStart,            // onmousedown on the terminal handles
    filterHistory, filterKnowledge,           // oninput on the search inputs
    noteSearchRun, _setDirty,                 // oninput on the note search bar + textarea
    saveConfig,                               // onsubmit on the config form
    _syncModeControls,                        // cm6-init.js reaches for this on load
});

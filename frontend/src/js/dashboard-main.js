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
    _refreshShadowCache, _consumeShadowCache,
} from './sections/shadow-cache.js';
import {
    openPath, openInTerminal, workOn, openFolder,
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

/* --- In-app config editor --- */
function _setField(form, name, value) {
    var el = form.elements[name];
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!value;
    else el.value = value == null ? '' : value;
}

function _getField(form, name) {
    var el = form.elements[name];
    if (!el) return null;
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'number') return el.value === '' ? 0 : Number(el.value);
    return el.value;
}

function _linesToList(text) {
    return (text || '').split('\n').map(function(s){return s.trim();}).filter(function(s){return s.length;});
}

function _listToLines(list) {
    return (list || []).join('\n');
}

/* Parse a repositories textarea. Each non-empty line is either
   "name" or "name: sub/a, sub/b" — colons inside submodule paths are
   preserved because we only split on the FIRST colon. */
function _linesToRepos(text) {
    return _linesToList(text).map(function(line){
        var idx = line.indexOf(':');
        if (idx < 0) return {name: line, submodules: []};
        var name = line.slice(0, idx).trim();
        var subs = line.slice(idx + 1).split(',')
            .map(function(s){return s.trim();})
            .filter(function(s){return s.length;});
        return {name: name, submodules: subs};
    }).filter(function(entry){return entry.name.length;});
}

function _reposToLines(entries) {
    return (entries || []).map(function(entry){
        if (!entry || !entry.name) return '';
        var subs = entry.submodules || [];
        return subs.length ? (entry.name + ': ' + subs.join(', ')) : entry.name;
    }).filter(function(s){return s.length;}).join('\n');
}

function _setSlotFields(form, slotKey, slot) {
    var container = form.querySelector('[data-slot="' + slotKey + '"]');
    if (!container || !slot) return;
    container.querySelector('[data-field="label"]').value = slot.label || '';
    container.querySelector('[data-field="commands"]').value = _listToLines(slot.commands);
}

function _readSlotFields(form, slotKey) {
    var container = form.querySelector('[data-slot="' + slotKey + '"]');
    if (!container) return null;
    return {
        label: container.querySelector('[data-field="label"]').value || '',
        commands: _linesToList(container.querySelector('[data-field="commands"]').value),
    };
}

function switchConfigTab(name) {
    var tabs = document.querySelectorAll('#config-form .config-tab');
    tabs.forEach(function(t){
        t.classList.toggle('active', t.getAttribute('data-config-tab') === name);
    });
    var panes = document.querySelectorAll('#config-form .config-tab-pane');
    panes.forEach(function(p){
        p.classList.toggle('active', p.getAttribute('data-config-pane') === name);
    });
    // Widen the modal on YAML-backed tabs (split pane wants ~1080px).
    // The General tab stays at the original 720px for a less empty feel.
    var modal = document.querySelector('#config-modal .config-modal');
    if (modal) {
        modal.classList.toggle('config-modal-wide', name !== 'general');
    }
}

function _setYamlSourceHint(elId, source, expected, label) {
    var el = document.getElementById(elId);
    if (!el) return;
    if (source) {
        el.innerHTML = 'These fields are stored in <code>' + source + '</code>.';
    } else if (expected) {
        el.innerHTML = 'These fields migrate to <code>' + expected + '</code> on the next Save.';
    } else {
        el.innerHTML = 'Set a <code>conception_path</code> on the General tab to move these fields into <code>' + label + '</code>.';
    }
    el.style.display = '';
}

async function openConfigModal() {
    var modal = document.getElementById('config-modal');
    var ta = document.getElementById('config-yaml');
    var errEl = document.getElementById('config-error');
    var okEl = document.getElementById('config-saved');
    var pathEl = document.getElementById('config-file-path');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    modal.style.display = 'flex';
    try {
        var res = await fetch('/configuration');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        ta.value = await res.text();
        var path = res.headers.get('X-Condash-Config-Path');
        if (path && pathEl) pathEl.textContent = path;
        // Defer focus so the modal is laid out before we position the cursor.
        setTimeout(function() { ta.focus(); ta.setSelectionRange(0, 0); }, 0);
    } catch (e) {
        errEl.textContent = 'Could not load configuration.yml: ' + e;
        errEl.style.display = 'block';
    }
}

/* Split-pane YAML pane: populate the textarea with raw YAML and stash
   its pristine value so saveConfig can detect local edits. The status
   badge flips to "edited" on input and back to "synced" once the diff
   against pristine is zero. When ``preserveDirty`` is true and the
   user has unsaved edits, we don't overwrite — an external live-reload
   event would otherwise blow away their in-flight work.

   When the CodeMirror 6 bundle (``window.CondashCM``) has loaded, we
   swap the textarea for a real editor (syntax highlight, gutter, the
   whole thing) and keep the original textarea hidden but in the DOM —
   its value stays mirrored so ``_getDirtyYamlFile`` keeps working
   without ever poking at CM6 APIs. If the bundle hasn't arrived yet
   (defer script still loading) we fall back to the textarea for this
   paint; once the modal reopens, CM6 is wired. */
export var _cmViews = {};  // which → EditorView
function _populateYamlEditor(which, body, preserveDirty) {
    var ta = document.querySelector('#config-form textarea[data-yaml-file="' + which + '"]');
    if (!ta) return;
    var dirty = ta.classList.contains('config-yaml-dirty');
    if (preserveDirty && dirty) return;
    if (window.CondashCM) {
        _populateYamlEditorCM(which, ta, body);
        return;
    }
    // Fallback: plain textarea.
    ta.value = body;
    ta.dataset.pristine = body;
    ta.classList.remove('config-yaml-dirty');
    _setYamlStatus(which, 'synced');
    if (!ta.dataset.boundInput) {
        ta.addEventListener('input', function() {
            var pristine = ta.dataset.pristine || '';
            if (ta.value !== pristine) {
                ta.classList.add('config-yaml-dirty');
                _setYamlStatus(which, 'edited — unsaved');
            } else {
                ta.classList.remove('config-yaml-dirty');
                _setYamlStatus(which, 'synced');
            }
        });
        ta.dataset.boundInput = '1';
    }
}

/* CodeMirror-backed pane. On first call for a given file we create an
   EditorView next to the textarea and hide the textarea; subsequent
   calls dispatch a full-document replace transaction. The textarea's
   value is kept in sync via the CM updateListener so the rest of the
   save pipeline can keep reading ``ta.value``. */
function _populateYamlEditorCM(which, ta, body) {
    var CM = window.CondashCM;
    var view = _cmViews[which];
    var themeComp = ta._cmThemeComp;
    if (!view) {
        ta.style.display = 'none';
        themeComp = new CM.Compartment();
        ta._cmThemeComp = themeComp;
        var wrap = document.createElement('div');
        wrap.className = 'config-yaml-editor config-yaml-cm';
        ta.parentNode.insertBefore(wrap, ta.nextSibling);
        var extensions = [
            CM.basicSetup,
            CM.yamlLang(),
            themeComp.of(_currentCmTheme()),
            CM.EditorView.updateListener.of(function(update) {
                if (!update.docChanged) return;
                ta.value = update.state.doc.toString();
                var pristine = ta.dataset.pristine || '';
                if (ta.value !== pristine) {
                    ta.classList.add('config-yaml-dirty');
                    wrap.classList.add('config-yaml-dirty');
                    _setYamlStatus(which, 'edited — unsaved');
                } else {
                    ta.classList.remove('config-yaml-dirty');
                    wrap.classList.remove('config-yaml-dirty');
                    _setYamlStatus(which, 'synced');
                }
            }),
        ];
        try {
            view = new CM.EditorView({
                doc: body,
                extensions: extensions,
                parent: wrap,
            });
            _cmViews[which] = view;
        } catch (err) {
            console.warn('[condash] CodeMirror mount failed for', which, err);
            ta.style.display = '';
            wrap.remove();
            return;
        }
    } else {
        view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: body },
        });
        // Re-apply current theme in case the user toggled light/dark
        // while the modal was closed.
        if (themeComp) {
            view.dispatch({ effects: themeComp.reconfigure(_currentCmTheme()) });
        }
    }
    ta.value = body;
    ta.dataset.pristine = body;
    ta.classList.remove('config-yaml-dirty');
    view.dom.classList.remove('config-yaml-dirty');
    _setYamlStatus(which, 'synced');
}

export function _currentCmTheme() {
    var theme = document.documentElement.getAttribute('data-theme') || 'light';
    return theme === 'dark' ? window.CondashCM.oneDark : [];
}

function _setYamlStatus(which, label) {
    var badge = document.querySelector('[data-yaml-status="' + which + '"]');
    if (badge) badge.textContent = label;
}

function _getDirtyYamlFile() {
    var dirtyTa = document.querySelector('#config-form textarea.config-yaml-editor.config-yaml-dirty');
    if (!dirtyTa) return null;
    return {
        file: dirtyTa.getAttribute('data-yaml-file'),
        body: dirtyTa.value,
    };
}

function closeConfigModal() {
    document.getElementById('config-modal').style.display = 'none';
}

async function saveConfig(ev) {
    ev.preventDefault();
    var ta = document.getElementById('config-yaml');
    var errEl = document.getElementById('config-error');
    var okEl = document.getElementById('config-saved');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    try {
        var res = await fetch('/configuration', {
            method: 'POST',
            headers: {'Content-Type': 'text/yaml; charset=utf-8'},
            body: ta.value,
        });
        if (res.ok) {
            okEl.textContent = 'Saved. Close and reopen condash for changes to take effect.';
            okEl.style.display = 'block';
        } else {
            var msg = await res.text();
            errEl.textContent = 'Save rejected (' + res.status + '): ' + msg;
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = 'Save failed: ' + e;
        errEl.style.display = 'block';
    }
}

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

var TAB_MAP = {
    current: ['now', 'review'],
    next: ['soon', 'later'],
    backlog: ['backlog'],
    done: ['done'],
};
// Tabs where the priority groups should be labelled with a subheader.
var TAB_SHOWS_HEADINGS = {current: true, next: true};
var PRIMARY_TABS = ['projects', 'code', 'knowledge', 'history'];
var SUBTABS = ['current', 'next', 'backlog', 'done'];
var _activeTab = 'projects';
var _activeSubtab = 'current';
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
        ((tab === 'projects' || tab === 'history') && _itemsStale) ||
        (tab === 'code' && _gitStale) ||
        (tab === 'knowledge' && _knowledgeStale);
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

function _applySubtab(sub) {
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
async function _reloadInPlace() {
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
            _pendingReloadInPlace = true;
            return;
        }
        // A successful global swap is authoritative. Clear any residual
        // dirty entries synchronously so the _renderStale inside
        // switchTab (called from _rebindDashHandlers below) doesn't paint
        // a dot based on ids the server just re-rendered for us. The
        // async updateBaseline() that follows confirms the empty set
        // against a fresh /check-updates. condash#14.
        _dirtyNodes = new Set();
        _rebindDashHandlers();
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

function _tabForNodeId(id) {
    if (id === 'projects' || id.indexOf('projects/') === 0) return 'projects';
    if (id === 'code' || id.indexOf('code/') === 0) return 'code';
    if (id === 'knowledge' || id.indexOf('knowledge/') === 0) return 'knowledge';
    return null;
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

function updateTabCounts() {
    // Primary tabs — Projects counts active items under Projects-tab
    // priorities; Code + Knowledge are rendered with a static count from
    // the server and don't need a client-side refresh on priority changes.
    var projectsCount = document.querySelectorAll('#cards .card').length;
    var projectsTab = document.querySelector('.tabs-primary .tab[data-tab="projects"] .tab-count');
    if (projectsTab) projectsTab.textContent = '(' + projectsCount + ')';
    // Projects sub-tabs — these filter the `#cards` grid; count per tab.
    document.querySelectorAll('#projects-subtabs .tab').forEach(function(t) {
        var tab = t.getAttribute('data-subtab');
        var allowed = TAB_MAP[tab] || [];
        var count = [].slice.call(document.querySelectorAll('.card')).filter(function(c) {
            return allowed.indexOf(c.getAttribute('data-priority')) !== -1;
        }).length;
        var span = t.querySelector('.tab-count');
        if (span) span.textContent = '(' + count + ')';
    });
}

/* --- Search: shared helpers used by filterKnowledge + filterHistory ---
   Tokenise on whitespace; a card matches iff every token is a substring of
   its textContent (case-insensitive). textContent covers title, description,
   apps, kind, tags and whatever else the server-rendered card contains, so
   no per-field plumbing is needed. */
function _searchTokens(q) {
    q = (q || '').trim().toLowerCase();
    if (!q) return [];
    return q.split(/\s+/);
}
function _cardMatches(el, tokens) {
    if (tokens.length === 0) return true;
    var hay = (el.textContent || '').toLowerCase();
    for (var i = 0; i < tokens.length; i++) {
        if (hay.indexOf(tokens[i]) === -1) return false;
    }
    return true;
}
function _setEmpty(panel, cls, text) {
    var el = panel.querySelector('.' + cls);
    if (text == null) {
        if (el) el.remove();
        return;
    }
    if (!el) {
        el = document.createElement('p');
        el.className = cls;
        panel.appendChild(el);
    }
    el.textContent = text;
}

/* Last query per pane — re-applied after _reloadInPlace swaps the DOM so
   an active filter survives a background refresh. */
var _historySearchQ = '';
var _knowledgeSearchQ = '';

/* Build an HTML snippet showing ~`radius` chars of context around the
   first token match in `text`, with every token occurrence wrapped in
   <mark>. Returns '' when no token matches. Snaps the cut to the
   nearest space on either side so words aren't sliced mid-letter. */
function _escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function _escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function _buildSnippet(text, tokens, radius) {
    if (!tokens.length || !text) return '';
    var hay = text.toLowerCase();
    var pos = -1, hitLen = 0;
    for (var i = 0; i < tokens.length; i++) {
        var p = hay.indexOf(tokens[i]);
        if (p >= 0 && (pos < 0 || p < pos)) { pos = p; hitLen = tokens[i].length; }
    }
    if (pos < 0) return '';
    var start = Math.max(0, pos - radius);
    var end = Math.min(text.length, pos + hitLen + radius);
    // Snap to nearest word boundary (whitespace) within a small margin.
    if (start > 0) {
        var ws = text.lastIndexOf(' ', start);
        if (ws >= 0 && start - ws < 20) start = ws + 1;
    }
    if (end < text.length) {
        var we = text.indexOf(' ', end);
        if (we >= 0 && we - end < 20) end = we;
    }
    var frag = text.substring(start, end).replace(/\s+/g, ' ').trim();
    var html = _escapeHtml(frag);
    var re = new RegExp('(' + tokens.map(_escapeRegExp).join('|') + ')', 'gi');
    html = html.replace(re, '<mark>$1</mark>');
    return (start > 0 ? '…' : '') + html + (end < text.length ? '…' : '');
}
/* Inject/update a .match-snippet element inside a matching card. Reuses
   the element across keystrokes to avoid DOM churn; removes it on
   non-match or empty tokens. */
function _setSnippet(card, tokens) {
    var existing = card.querySelector(':scope > .match-snippet');
    if (tokens.length === 0) {
        if (existing) existing.remove();
        return;
    }
    // Exclude the title from the snippet source so it surfaces content
    // the user can't already see in the card's static label.
    var titleEl = card.querySelector(':scope > .knowledge-title');
    var titleText = titleEl ? titleEl.textContent : '';
    var full = card.textContent || '';
    var body = titleText && full.indexOf(titleText) === 0
        ? full.substring(titleText.length) : full;
    var html = _buildSnippet(body, tokens, 60);
    if (!html) {
        if (existing) existing.remove();
        return;
    }
    if (!existing) {
        existing = document.createElement('div');
        existing.className = 'match-snippet';
        card.appendChild(existing);
    }
    existing.innerHTML = html;
}

/* --- Generic tree filter (knowledge + history views) ---
   Token-AND substring match against .knowledge-card textContent. Hide
   .knowledge-group groups that end up with zero matches; re-reveal and
   <details>-open each matching card's ancestor groups so deep matches
   surface without showing sibling subdirs; surface an empty-state line
   when the whole panel is empty. Matching cards get a .match-snippet
   showing context around the first token hit. */
function _filterTree(panel, tokens, qTrim, emptyCls, emptyMsg) {
    var groups = panel.querySelectorAll('.knowledge-group');
    var cards = panel.querySelectorAll('.knowledge-card');
    if (tokens.length === 0) {
        groups.forEach(function(g){ g.style.display = ''; });
        cards.forEach(function(c){
            c.style.display = '';
            _setSnippet(c, tokens);
        });
        _setEmpty(panel, emptyCls, null);
        return;
    }
    groups.forEach(function(g){ g.style.display = 'none'; });
    var totalVisible = 0;
    cards.forEach(function(c) {
        var match = _cardMatches(c, tokens);
        c.style.display = match ? '' : 'none';
        _setSnippet(c, match ? tokens : []);
        if (!match) return;
        totalVisible += 1;
        var anc = c.parentElement;
        while (anc && anc !== panel) {
            if (anc.classList && anc.classList.contains('knowledge-group')) {
                anc.style.display = '';
                anc.setAttribute('open', '');
            }
            anc = anc.parentElement;
        }
    });
    _setEmpty(panel, emptyCls, totalVisible === 0 ? emptyMsg : null);
}
function _resetTree(panel, emptyCls) {
    panel.querySelectorAll('.knowledge-group').forEach(function(g){ g.style.display = ''; });
    panel.querySelectorAll('.knowledge-card').forEach(function(c){
        c.style.display = '';
        _setSnippet(c, []);
    });
    _setEmpty(panel, emptyCls, null);
}

/* --- Knowledge search --- */
function filterKnowledge(q) {
    _knowledgeSearchQ = q || '';
    _persistSearch('condash.search.knowledge', _knowledgeSearchQ);
    var panel = document.getElementById('knowledge');
    if (!panel) return;
    var qTrim = (q || '').trim();
    _filterTree(panel, _searchTokens(q), qTrim,
        'knowledge-empty', 'No knowledge pages match "' + qTrim + '".');
}

function _persistSearch(key, value) {
    try {
        if (!value) sessionStorage.removeItem(key);
        else sessionStorage.setItem(key, JSON.stringify({value: value}));
    } catch (e) {}
}

/* --- History search ---
   Empty query → tree view (on-disk layout grouped by month).
   Non-empty query → debounced fetch of /search-history that indexes README
   bodies, note/text-file contents and filenames on the server, rendered as
   a flat results list below the toolbar. */
var _historySearchTimer = null;
var _historySearchAbort = null;
function filterHistory(q) {
    _historySearchQ = q || '';
    _persistSearch('condash.search.history', _historySearchQ);
    var pane = document.getElementById('history-pane');
    var tree = document.getElementById('history');
    var results = document.getElementById('history-results');
    if (!pane || !tree || !results) return;
    var qTrim = _historySearchQ.trim();
    if (!qTrim) {
        if (_historySearchTimer) { clearTimeout(_historySearchTimer); _historySearchTimer = null; }
        if (_historySearchAbort) { _historySearchAbort.abort(); _historySearchAbort = null; }
        pane.classList.remove('history-pane--query');
        results.hidden = true;
        results.innerHTML = '';
        tree.hidden = false;
        return;
    }
    pane.classList.add('history-pane--query');
    tree.hidden = true;
    results.hidden = false;
    if (_historySearchTimer) clearTimeout(_historySearchTimer);
    _historySearchTimer = setTimeout(function(){ _runHistorySearch(qTrim); }, 150);
}

async function _runHistorySearch(q) {
    if (_historySearchAbort) _historySearchAbort.abort();
    _historySearchAbort = new AbortController();
    var results = document.getElementById('history-results');
    if (!results) return;
    try {
        var res = await fetch('/search-history?q=' + encodeURIComponent(q),
                              {signal: _historySearchAbort.signal});
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var hits = await res.json();
        // Discard the response if the query has changed since this fetch
        // started — another keystroke already ran a newer fetch.
        if (_historySearchQ.trim() !== q) return;
        _renderHistoryResults(hits, q);
    } catch (err) {
        if (err && err.name === 'AbortError') return;
        results.innerHTML = '<p class="history-empty">Search failed: ' +
            _escapeHtml(String(err && err.message || err)) + '</p>';
    }
}

function _renderHistoryResults(hits, q) {
    var results = document.getElementById('history-results');
    if (!results) return;
    if (!hits || !hits.length) {
        results.innerHTML = '<p class="history-empty">No projects match "' +
            _escapeHtml(q) + '".</p>';
        return;
    }
    var out = [];
    for (var i = 0; i < hits.length; i++) {
        out.push(_historyResultBlock(hits[i]));
    }
    results.innerHTML = out.join('');
}

function _historyResultBlock(row) {
    var hitsHtml = '';
    for (var i = 0; i < row.hits.length; i++) {
        var h = row.hits[i];
        var pathAttr = _escapeHtml(h.path || '');
        var labelAttr = _escapeHtml(h.label || '');
        // Snippet already comes HTML-escaped with <mark> wrappers from the
        // server — inject as HTML, not text.
        var snippetHtml = h.snippet || '';
        hitsHtml += (
            '<li class="history-hit" ' +
            'data-path="' + pathAttr + '" ' +
            'data-label="' + labelAttr + '" ' +
            'onclick="_openHistoryHit(this)">' +
            '<span class="hit-src hit-src-' + _escapeHtml(h.source) + '">' +
                _escapeHtml(h.label || h.source) + '</span>' +
            '<span class="hit-snippet">' + snippetHtml + '</span>' +
            '</li>'
        );
    }
    return (
        '<div class="history-result" ' +
        'data-slug="' + _escapeHtml(row.slug) + '" ' +
        'data-status="' + _escapeHtml(row.status || '') + '" ' +
        'data-subtab="' + _escapeHtml(row.subtab || 'current') + '">' +
        '<div class="history-result-header">' +
            '<span class="history-result-title">' + _escapeHtml(row.title) + '</span>' +
            '<span class="pill">' + _escapeHtml(row.kind) + '</span>' +
            '<span class="pill pri-' + _escapeHtml(row.status) + '">' +
                _escapeHtml(row.status) + '</span>' +
            '<span class="history-result-month">' + _escapeHtml(row.month) + '</span>' +
            '<button class="history-jump" onclick="jumpToProject(this)" ' +
                'title="Open in Projects tab" aria-label="Jump to project">' +
                '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" ' +
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
                'stroke-linejoin="round" aria-hidden="true">' +
                '<circle cx="12" cy="12" r="9"/>' +
                '<circle cx="12" cy="12" r="5"/>' +
                '<circle cx="12" cy="12" r="1.2" fill="currentColor"/>' +
                '</svg>' +
            '</button>' +
        '</div>' +
        '<ul class="history-result-hits">' + hitsHtml + '</ul>' +
        '</div>'
    );
}

function _openHistoryHit(el) {
    var path = el.getAttribute('data-path');
    var label = el.getAttribute('data-label');
    if (path) openNotePreview(path, label || path);
}

function jumpToProject(btn) {
    var row = btn.closest('.history-result');
    if (!row) return;
    var slug = row.getAttribute('data-slug');
    var sub = row.getAttribute('data-subtab') || 'current';
    switchTab('projects');
    switchSubtab(sub);
    var card = document.getElementById(slug);
    if (!card) return;
    card.classList.remove('collapsed');
    card.scrollIntoView({behavior: 'smooth', block: 'center'});
    card.classList.remove('focus-flash');
    // Re-trigger the animation by forcing a reflow before re-adding.
    void card.offsetWidth;
    card.classList.add('focus-flash');
    setTimeout(function(){ card.classList.remove('focus-flash'); }, 1800);
}

/* Re-apply any active search after the DOM is swapped or the subtab
   changes. Safe to call when the search input isn't present (other
   primary tab active). */
function _reapplySearches() {
    if (_historySearchQ) {
        var h = document.getElementById('history-search');
        if (h) h.value = _historySearchQ;
        // Re-run the query against the fresh DOM. In query mode this also
        // re-fetches /search-history so newly-added files surface.
        filterHistory(_historySearchQ);
    }
    if (_knowledgeSearchQ) {
        var k = document.getElementById('knowledge-search');
        if (k) k.value = _knowledgeSearchQ;
        filterKnowledge(_knowledgeSearchQ);
    }
}

function toggleSection(el) {
    var items = el.nextElementSibling;
    if (items.style.display === 'none') {
        items.style.display = 'block';
        el.classList.add('open');
    } else {
        items.style.display = 'none';
        el.classList.remove('open');
    }
}

/* --- Notes block (collapsible list) --- */
function toggleNotes(el) {
    var list = el.nextElementSibling;
    if (list.style.display === 'none') {
        list.style.display = 'block';
        el.classList.add('open');
    } else {
        list.style.display = 'none';
        el.classList.remove('open');
    }
}

/* --- Note preview modal --- */
function _renderMermaidIn(container) {
    if (!window.mermaid) return;
    var blocks = container.querySelectorAll('pre.mermaid, pre > code.language-mermaid');
    if (!blocks.length) return;
    var nodes = [];
    blocks.forEach(function(block) {
        var pre = block.tagName === 'PRE' ? block : block.parentElement;
        var code = pre.querySelector('code') || pre;
        var src = code.textContent;
        var div = document.createElement('div');
        div.className = 'mermaid';
        div.textContent = src;
        pre.replaceWith(div);
        nodes.push(div);
    });
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    try {
        window.mermaid.initialize({
            startOnLoad: false,
            theme: isDark ? 'dark' : 'default',
            securityLevel: 'strict',
        });
        window.mermaid.run({ nodes: nodes }).catch(function() {});
    } catch (e) {}
}

/* Mount the vendored PDF.js viewer on every .note-pdf-host inside the
   view pane. If the PDF.js ES module (at the bottom of this file) hasn't
   resolved yet, mark hosts pending — the module's ready-hook will flush
   them. Safe to call repeatedly; mount() no-ops on already-mounted hosts. */
function _mountPdfsIn(container) {
    if (!container) return;
    var hosts = container.querySelectorAll('.note-pdf-host');
    for (var i = 0; i < hosts.length; i++) {
        var host = hosts[i];
        if (host.dataset.mounted === '1') continue;
        if (window.__pdfjs && window.__pdfjs.ready) {
            window.__pdfjs.mount(host);
        } else if (window.__pdfjs && window.__pdfjs.error) {
            host.innerHTML = '<div class="pdf-error">PDF viewer failed to load.</div>';
        } else {
            host.dataset.pdfPending = '1';
            host.innerHTML = '<div class="pdf-loading">Loading PDF viewer\u2026</div>';
        }
    }
}

/* Back-navigation stack. Every time a link inside the note modal opens
   a different note (wikilinks, relative .md links), the currently shown
   {path, name} is pushed before the replacement. The back button in the
   modal header pops one level. Cleared on close — this is an in-modal
   navigation history, not a persistent browser history. */
var _noteNavStack = [];

/* Notes open in three modes. The modal carries `data-mode` on its inner
   element (#note-modal-inner); three sibling panes inside #note-modal-body
   are hidden/shown by CSS. `_noteModal` tracks the state shared across
   panes so mode switches preserve user edits and mtime for the save
   contract. */
export var _noteModal = {
    path: null,
    editable: false,     // false when kind is pdf/image/binary — edit modes disabled
    kind: null,          // from /note-raw
    mtime: null,
    renderedHtml: '',    // last server render shown in the view pane
    /* Canonical text shared between CM6 and the plain textarea. Updated
       whenever the user switches away from an edit mode so the other
       mode can start from the same buffer. Reset on open and on save. */
    text: '',
    /* Which edit mode was last active. Ctrl-E from view returns here. */
    lastEditMode: 'cm',
    /* Unsaved-changes flag. Set on every CM6/textarea edit, cleared on
       open and successful save. Drives the Save button's disabled state
       and the close/beforeunload confirms. */
    dirty: false,
};

/* Flip the dirty flag and refresh the Save button. Safe to call on every
   keystroke — the button toggle is the only DOM work. Also drains any
   reload requests that were parked because the modal was dirty. */
export function _setDirty(value) {
    var next = !!value;
    if (_noteModal.dirty === next) return;
    _noteModal.dirty = next;
    _syncSaveButton();
    if (!next && typeof _flushPendingReloads === 'function') {
        _flushPendingReloads();
    }
}

/* Save button is enabled only when there are unsaved edits, so after a
   successful save the user gets a clear "saved" signal and can't click
   again redundantly. Disabled when clean, non-editable, or viewing. */
function _syncSaveButton() {
    var btn = document.getElementById('note-save-btn');
    if (!btn) return;
    var inner = document.getElementById('note-modal-inner');
    var mode = inner ? inner.getAttribute('data-mode') : 'view';
    var editing = mode === 'cm' || mode === 'plain';
    btn.disabled = !editing || !_noteModal.editable || !_noteModal.dirty;
    btn.title = btn.disabled && editing && _noteModal.editable
        ? 'No unsaved changes' : 'Save (Ctrl+S)';
}

async function openNotePreview(path, name) {
    var modal = document.getElementById('note-modal');
    var inner = document.getElementById('note-modal-inner');
    var title = document.getElementById('note-modal-title');
    var viewPane = document.getElementById('note-pane-view');
    var ta = document.getElementById('note-edit-textarea');
    // Reset any in-note search: matches point at DOM nodes we're about
    // to discard and the count would be stale against the new note.
    noteSearchClose();
    _destroyCm();
    title.textContent = name;
    _noteModal.path = path;
    _noteModal.editable = false;
    _noteModal.kind = null;
    _noteModal.mtime = null;
    _noteModal.text = '';
    _noteModal.renderedHtml = '';
    _noteModal.dirty = false;
    _noteShowExternalBanner(false);
    _noteReconcileSuppressedUntilMtime = null;
    ta.value = '';
    viewPane.innerHTML = '<p class="note-loading">Loading\u2026</p>';
    _setNoteModeAttr(inner, 'view');
    _syncModeControls();
    _hideSaveError();
    modal.classList.add('open');
    // Kick off both fetches in parallel. /note returns HTML for the view
    // pane; /note-raw returns text+mtime+kind for the edit panes. The
    // raw fetch is best-effort: pdf/image kinds 4xx here and we leave
    // the edit modes disabled.
    var viewP = fetch('/note?path=' + encodeURIComponent(path)).then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
    });
    var rawP = fetch('/note-raw?path=' + encodeURIComponent(path)).then(function(res) {
        if (!res.ok) return null;
        return res.json();
    }).catch(function() { return null; });
    try {
        var html = await viewP;
        // Guard against late arrival for a different note (user opened
        // another before this one resolved).
        if (_noteModal.path !== path) return;
        viewPane.innerHTML = html;
        viewPane.scrollTop = 0;
        _noteModal.renderedHtml = html;
        _renderMermaidIn(viewPane);
        _wireNoteLinks(viewPane, path);
        _mountPdfsIn(viewPane);
    } catch (e) {
        if (_noteModal.path !== path) return;
        viewPane.innerHTML = '<p class="note-error">Failed to load note.</p>';
    }
    var raw = await rawP;
    if (_noteModal.path !== path) return;
    if (raw && typeof raw.content === 'string') {
        _noteModal.editable = true;
        _noteModal.kind = raw.kind || null;
        _noteModal.mtime = raw.mtime != null ? Number(raw.mtime) : null;
        _noteModal.text = raw.content;
        ta.value = raw.content;
    }
    _syncModeControls();
    _syncNoteBack();
}

/* Push the currently-shown note onto the back stack and open the target.
   Used by link handlers inside the note modal (wikilinks + internal .md).
   The button-driven "back" path calls openNotePreview without pushing so
   the stack only grows on forward navigation. */
async function _navigateToNote(path, name, anchor) {
    if (_noteModal.path) {
        var titleEl = document.getElementById('note-modal-title');
        var currentName = titleEl ? titleEl.textContent : _noteModal.path;
        _noteNavStack.push({path: _noteModal.path, name: currentName});
    }
    await openNotePreview(path, name);
    if (anchor) _scrollNoteToAnchor(anchor);
}

function _syncNoteBack() {
    var btn = document.getElementById('note-modal-back');
    if (!btn) return;
    if (_noteNavStack.length > 0) btn.removeAttribute('hidden');
    else btn.setAttribute('hidden', '');
}

async function noteNavBack() {
    if (_noteNavStack.length === 0) return;
    var entry = _noteNavStack.pop();
    await openNotePreview(entry.path, entry.name);
}

/* Resolve a path relative to `baseDir` — `baseDir/../foo` collapses to
   `foo`, absolute paths drop the leading slash so they are treated as
   conception-tree relative. */
function _resolveNotePath(baseDir, rel) {
    if (rel.startsWith('/')) rel = rel.replace(/^\/+/, '');
    var parts = ((baseDir ? baseDir + '/' : '') + rel).split('/');
    var out = [];
    for (var i = 0; i < parts.length; i++) {
        var p = parts[i];
        if (!p || p === '.') continue;
        if (p === '..') out.pop();
        else out.push(p);
    }
    return out.join('/');
}

/* Scroll a pandoc-generated heading into view inside the modal pane.
   Heading ids are produced by pandoc's gfm auto_identifiers; the caller
   supplies the fragment from a link href. No-op if the id is missing. */
function _scrollNoteToAnchor(anchor) {
    if (!anchor) return;
    var pane = document.getElementById('note-pane-view');
    if (!pane) return;
    var el = null;
    try { el = pane.querySelector('#' + CSS.escape(anchor)); } catch (_) {}
    if (el) el.scrollIntoView({block: 'start'});
}

/* Route note-body link clicks:
   - http(s) → POST /open-external → host browser (bypasses pywebview).
   - in-page anchors (#foo), mailto: → leave default behaviour.
   - relative .md (with optional #anchor) → resolve inside the conception
     tree and open in the same modal via openNotePreview.
   - anything else → resolve against the note's directory and POST /open-doc
     so the OS default viewer handles PDFs, images, and other files. */
function _wireNoteLinks(body, notePath) {
    var noteDir = notePath.lastIndexOf('/') >= 0
        ? notePath.substring(0, notePath.lastIndexOf('/'))
        : '';
    // Wikilinks resolved server-side carry an absolute (conception-tree
    // relative) href. They open inside the modal, not via xdg-open.
    body.querySelectorAll('a.wikilink[href]').forEach(function(a) {
        a.addEventListener('click', function(ev) {
            ev.preventDefault();
            var href = a.getAttribute('href');
            var label = a.textContent || href;
            _navigateToNote(href, label);
        });
    });
    // Unresolved wikilinks: click does nothing but flash the hover title.
    body.querySelectorAll('a.wikilink-missing').forEach(function(a) {
        a.addEventListener('click', function(ev) { ev.preventDefault(); });
    });
    body.querySelectorAll('a[href]:not(.wikilink):not(.wikilink-missing)').forEach(function(a) {
        var href = a.getAttribute('href');
        if (!href) return;
        if (/^https?:\/\//i.test(href)) {
            a.addEventListener('click', function(ev) {
                ev.preventDefault();
                fetch('/open-external', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: href}),
                });
            });
            return;
        }
        if (href.startsWith('#') || href.startsWith('mailto:')) {
            return;
        }
        var hashIdx = href.indexOf('#');
        var pathPart = hashIdx >= 0 ? href.substring(0, hashIdx) : href;
        var anchor = hashIdx >= 0 ? href.substring(hashIdx + 1) : '';
        if (pathPart && /\.md$/i.test(pathPart)) {
            var resolvedMd = _resolveNotePath(noteDir, pathPart);
            a.addEventListener('click', function(ev) {
                ev.preventDefault();
                var label = a.textContent || resolvedMd;
                _navigateToNote(resolvedMd, label, anchor);
            });
            return;
        }
        var resolved = _resolveNotePath(noteDir, pathPart || href);
        a.addEventListener('click', function(ev) {
            ev.preventDefault();
            fetch('/open-doc', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: resolved}),
            });
        });
    });
}

function closeNotePreview() {
    // Capture the active buffer so dirty reflects the latest keystrokes
    // even if the user never switched modes before closing.
    if (_noteModal.editable) _captureActiveBuffer();
    if (_noteModal.dirty) {
        if (!confirm('You have unsaved changes. Discard them?')) return;
    }
    document.getElementById('note-modal').classList.remove('open');
    _destroyCm();
    _hideSaveError();
    _noteModal.path = null;
    _noteModal.dirty = false;
    _noteNavStack = [];
    _syncNoteBack();
    noteSearchClose();
    _noteShowExternalBanner(false);
    _noteReconcileSuppressedUntilMtime = null;
    if (typeof _flushPendingReloads === 'function') _flushPendingReloads();
}

/* --- In-note search (Ctrl+F inside the note modal) ---
   Walks .note-modal-body's text nodes, wraps each case-insensitive
   substring match in <mark class="note-match">, and lets the user step
   through them with Enter / Shift+Enter / F3. Scoped to the preview
   view — Ctrl+F inside the edit textarea falls through so the browser's
   native behaviour still works there. */
var _noteSearch = { matches: [], idx: -1 };
function _clearNoteMarks() {
    var pane = document.getElementById('note-pane-view');
    if (!pane) return;
    pane.querySelectorAll('mark.note-match').forEach(function(m) {
        var parent = m.parentNode;
        while (m.firstChild) parent.insertBefore(m.firstChild, m);
        parent.removeChild(m);
    });
    pane.normalize();
}
/* Return the PDF find API attached to a mounted .note-pdf-host inside
   the open note modal, or null. The PDF viewer's mount() exposes this
   at host.__pdfFind so the shared note-search-bar can drive it. */
function _notePdfFind() {
    var modal = document.getElementById('note-modal');
    if (!modal || !modal.classList.contains('open')) return null;
    var host = modal.querySelector('.note-pdf-host[data-mounted="1"]');
    return host && host.__pdfFind ? host.__pdfFind : null;
}
function _setSearchCount(state, q) {
    var countEl = document.getElementById('note-search-count');
    if (!countEl) return;
    if (!state || !state.matches.length) {
        countEl.textContent = q ? '0/0' : '';
    } else {
        countEl.textContent = (state.idx + 1) + '/' + state.matches.length;
    }
}
function noteSearchRun() {
    var input = document.getElementById('note-search-input');
    var q = input ? input.value : '';
    var countEl = document.getElementById('note-search-count');
    var pdfFind = _notePdfFind();
    if (pdfFind) {
        // Clear any stale view-pane marks and delegate to the PDF viewer.
        _clearNoteMarks();
        _noteSearch.matches = [];
        _noteSearch.idx = -1;
        pdfFind.run(q).then(function(state) { _setSearchCount(state, q); });
        return;
    }
    _clearNoteMarks();
    _noteSearch.matches = [];
    _noteSearch.idx = -1;
    if (!q) {
        if (countEl) countEl.textContent = '';
        return;
    }
    var pane = document.getElementById('note-pane-view');
    if (!pane) return;
    var qLow = q.toLowerCase();
    var qLen = q.length;
    // Collect text nodes first (the walker becomes unreliable once we
    // mutate the tree). Skip script/style just in case; the body is
    // server-rendered markdown but we don't assume.
    var walker = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT, {
        acceptNode: function(n) {
            var tag = n.parentNode && n.parentNode.nodeName;
            if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        }
    });
    var textNodes = [];
    var node;
    while ((node = walker.nextNode())) textNodes.push(node);
    textNodes.forEach(function(n) {
        var low = n.nodeValue.toLowerCase();
        // Iterate in reverse so splitText offsets earlier in the string
        // stay valid as we carve the node from right to left.
        var positions = [];
        var pos = 0;
        while ((pos = low.indexOf(qLow, pos)) !== -1) {
            positions.push(pos);
            pos += qLen;
        }
        for (var i = positions.length - 1; i >= 0; i--) {
            var start = positions[i];
            var matchNode = n.splitText(start);
            matchNode.splitText(qLen);
            var mark = document.createElement('mark');
            mark.className = 'note-match';
            matchNode.parentNode.replaceChild(mark, matchNode);
            mark.appendChild(matchNode);
            _noteSearch.matches.push(mark);
        }
    });
    // Sort matches into document order (per-node reverse iteration left
    // them reverse within each node, and textNodes was walked forward).
    _noteSearch.matches.sort(function(a, b) {
        var cmp = a.compareDocumentPosition(b);
        if (cmp & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
        if (cmp & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        return 0;
    });
    if (_noteSearch.matches.length) {
        _noteSearch.idx = 0;
        _noteSearch.matches[0].classList.add('active');
        _noteSearch.matches[0].scrollIntoView({block: 'center'});
    }
    if (countEl) {
        countEl.textContent = _noteSearch.matches.length
            ? (_noteSearch.idx + 1) + '/' + _noteSearch.matches.length
            : '0/0';
    }
}
function noteSearchStep(dir) {
    var pdfFind = _notePdfFind();
    if (pdfFind) {
        var state = pdfFind.step(dir);
        _setSearchCount(state, '');
        return;
    }
    var n = _noteSearch.matches.length;
    if (!n) return;
    if (_noteSearch.idx >= 0) {
        _noteSearch.matches[_noteSearch.idx].classList.remove('active');
    }
    _noteSearch.idx = (_noteSearch.idx + dir + n) % n;
    var m = _noteSearch.matches[_noteSearch.idx];
    m.classList.add('active');
    m.scrollIntoView({block: 'center'});
    var countEl = document.getElementById('note-search-count');
    if (countEl) countEl.textContent = (_noteSearch.idx + 1) + '/' + n;
}
function noteSearchOpen() {
    var bar = document.getElementById('note-search-bar');
    if (!bar) return;
    bar.hidden = false;
    var input = document.getElementById('note-search-input');
    if (input) { input.focus(); input.select(); }
    // If a query is already typed, re-run so marks come back after the
    // note was reloaded or the bar was reopened.
    if (input && input.value) noteSearchRun();
}
function noteSearchClose() {
    var pdfFind = _notePdfFind();
    if (pdfFind) pdfFind.close();
    var bar = document.getElementById('note-search-bar');
    if (bar) bar.hidden = true;
    _clearNoteMarks();
    _noteSearch.matches = [];
    _noteSearch.idx = -1;
    var input = document.getElementById('note-search-input');
    if (input) input.value = '';
    var countEl = document.getElementById('note-search-count');
    if (countEl) countEl.textContent = '';
}
/* Capture-phase keydown so this beats the existing Escape handler and
   any xterm/editor shortcuts that might swallow Ctrl+F elsewhere. */
document.addEventListener('keydown', function(ev) {
    var modal = document.getElementById('note-modal');
    if (!modal || !modal.classList.contains('open')) return;
    var inner = document.getElementById('note-modal-inner');
    var mode = inner ? inner.getAttribute('data-mode') : 'view';
    var editing = mode === 'cm' || mode === 'plain';
    var isFindKey = (ev.ctrlKey || ev.metaKey) && !ev.altKey
        && (ev.key === 'f' || ev.key === 'F');
    if (isFindKey) {
        if (editing) return;  // let the edit panes keep native behaviour
        ev.preventDefault();
        ev.stopPropagation();
        noteSearchOpen();
        return;
    }
    // Ctrl+E toggles between view and the last-used edit mode.
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === 'e' || ev.key === 'E')) {
        if (!_noteModal.editable) return;
        ev.preventDefault();
        ev.stopPropagation();
        setNoteMode(mode === 'view' ? (_noteModal.lastEditMode || 'cm') : 'view');
        return;
    }
    var bar = document.getElementById('note-search-bar');
    if (!bar || bar.hidden) return;
    var activeInSearch = document.activeElement
        && document.activeElement.id === 'note-search-input';
    if (ev.key === 'Escape') {
        ev.preventDefault();
        ev.stopPropagation();
        noteSearchClose();
    } else if (ev.key === 'Enter' && activeInSearch) {
        ev.preventDefault();
        noteSearchStep(ev.shiftKey ? -1 : 1);
    } else if (ev.key === 'F3') {
        ev.preventDefault();
        noteSearchStep(ev.shiftKey ? -1 : 1);
    }
}, true);

/* Route a ## Deliverables PDF click to the OS default viewer. target="_blank"
   under pywebview routes to the system browser on 127.0.0.1:<port> and fails
   to render inline, so we mirror the note-link pattern and POST /open-doc
   with the conception-tree-relative path — xdg-open / open / startfile
   then opens the local file in the user's native PDF viewer. */
function openDeliverable(path) {
    fetch('/open-doc', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: path}),
    }).catch(function() {});
}

/* --- Note modal mode management ---
   Three sibling panes (view, cm, plain) live inside #note-modal-body;
   the modal's data-mode attribute drives CSS visibility. setNoteMode
   transfers the canonical buffer between the two edit modes on switch
   so edits survive toggling, then updates the chrome (save button,
   toggle state). Save POSTs to /note with expected_mtime — server
   refuses on mtime mismatch so a stale editor can't silently clobber
   out-of-band edits. */

function _setNoteModeAttr(inner, mode) {
    inner.setAttribute('data-mode', mode);
}

function _hideSaveError() {
    var err = document.getElementById('note-edit-error');
    if (err) { err.textContent = ''; err.classList.remove('visible'); }
}

function _showSaveError(msg) {
    var err = document.getElementById('note-edit-error');
    if (!err) return;
    err.textContent = msg;
    err.classList.add('visible');
}

/* Update the mode toggle (disable edit buttons when the file is not
   editable) and show/hide the Save button per mode. */
function _syncModeControls() {
    var inner = document.getElementById('note-modal-inner');
    var mode = inner ? inner.getAttribute('data-mode') : 'view';
    var toggle = document.getElementById('note-mode-toggle');
    var saveBtn = document.getElementById('note-save-btn');
    if (toggle) {
        toggle.querySelector('[data-mode="cm"]').disabled =
            !_noteModal.editable || !window.__cm6;
        toggle.querySelector('[data-mode="plain"]').disabled = !_noteModal.editable;
        if (!window.__cm6) {
            toggle.querySelector('[data-mode="cm"]').title =
                'Loading editor…';
        } else if (!_noteModal.editable) {
            toggle.querySelector('[data-mode="cm"]').title =
                'This file is not editable (binary/preview-only)';
        } else {
            toggle.querySelector('[data-mode="cm"]').title =
                'Edit with syntax highlighting (Ctrl+E)';
        }
    }
    if (saveBtn) saveBtn.style.display = (mode === 'cm' || mode === 'plain') ? '' : 'none';
    _syncSaveButton();
}

/* Pull the active pane's buffer back into _noteModal.text so a mode
   switch starts the next pane from the same content. */
function _captureActiveBuffer() {
    var inner = document.getElementById('note-modal-inner');
    var mode = inner.getAttribute('data-mode');
    if (mode === 'cm' && _cm.view) {
        _noteModal.text = _cm.view.state.doc.toString();
    } else if (mode === 'plain') {
        var ta = document.getElementById('note-edit-textarea');
        if (ta) _noteModal.text = ta.value;
    }
}

/* Hydrate a pane from _noteModal.text so the user sees their latest
   edits after a switch. No-op for view mode — view reflects last-save. */
function _hydratePane(mode) {
    if (mode === 'plain') {
        var ta = document.getElementById('note-edit-textarea');
        if (!ta) return;
        if (ta.value !== _noteModal.text) ta.value = _noteModal.text;
        ta.setSelectionRange(0, 0);
        ta.scrollTop = 0;
    } else if (mode === 'cm') {
        if (!_cm.view) { _mountCm(); return; }
        var cur = _cm.view.state.doc.toString();
        if (cur !== _noteModal.text) {
            _cm.view.dispatch({
                changes: {from: 0, to: cur.length, insert: _noteModal.text},
            });
        }
        _cm.view.dispatch({selection: {anchor: 0}});
        _cm.view.scrollDOM.scrollTop = 0;
    } else if (mode === 'view') {
        var pane = document.getElementById('note-pane-view');
        if (pane) pane.scrollTop = 0;
    }
}

function setNoteMode(next) {
    if (next !== 'view' && next !== 'cm' && next !== 'plain') return;
    if ((next === 'cm' || next === 'plain') && !_noteModal.editable) return;
    if (next === 'cm' && !window.__cm6) return;
    var inner = document.getElementById('note-modal-inner');
    var prev = inner.getAttribute('data-mode');
    if (prev === next) return;
    if (prev === 'cm' || prev === 'plain') _captureActiveBuffer();
    _setNoteModeAttr(inner, next);
    if (next === 'cm' || next === 'plain') _noteModal.lastEditMode = next;
    _hideSaveError();
    _hydratePane(next);
    _syncModeControls();
    if (next === 'cm' && _cm.view) { setTimeout(function() { _cm.view.focus(); }, 0); }
    else if (next === 'plain') {
        var ta = document.getElementById('note-edit-textarea');
        if (ta) setTimeout(function() { ta.focus(); }, 0);
    }
}

export async function saveEdit() {
    var inner = document.getElementById('note-modal-inner');
    var mode = inner.getAttribute('data-mode');
    if (mode !== 'cm' && mode !== 'plain') return;
    if (!_noteModal.path) return;
    _captureActiveBuffer();
    _hideSaveError();
    try {
        var res = await fetch('/note', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                path: _noteModal.path,
                content: _noteModal.text,
                expected_mtime: _noteModal.mtime,
            }),
        });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok) {
            if (res.status === 409 && data.mtime) _noteModal.mtime = Number(data.mtime);
            _showSaveError(data.reason || data.error || ('HTTP ' + res.status));
            return;
        }
        if (data.mtime != null) _noteModal.mtime = Number(data.mtime);
        _setDirty(false);
        // Refresh the view pane from the server render so it stays
        // aligned with what's now on disk.
        var name = document.getElementById('note-modal-title').textContent;
        await _reloadNotePreview(_noteModal.path, name);
    } catch (e) {
        _showSaveError('Save failed: ' + e);
    }
}

/* Prompt for a filename, POST /note/create, and drop into edit mode
   on success. Default extension is `.md`; user can type something else. */
/* Prompt for a filename and POST /note/create. ``subRelToNotes`` is the
   target subdirectory relative to ``<item>/notes/`` ("" for notes/ root)
   so the per-folder + buttons can drop the file into the folder whose
   summary they live on. */
async function createNoteFor(readmePath, subRelToNotes) {
    var raw = prompt('New note filename (e.g. plan.md, decision.txt):', 'new-note.md');
    if (!raw) return;
    raw = raw.trim();
    if (!raw) return;
    if (raw.indexOf('.') < 0) raw = raw + '.md';
    try {
        var res = await fetch('/note/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                item_readme: readmePath,
                filename: raw,
                subdir: subRelToNotes || '',
            }),
        });
        var data = await res.json().catch(function(){return {};});
        if (!res.ok) {
            alert('Could not create note: ' + (data.reason || data.error || ('HTTP ' + res.status)));
            return;
        }
        await openNotePreview(data.path, raw);
        // Drop straight into the preferred edit mode for the new file.
        if (_noteModal.editable) {
            setNoteMode(window.__cm6 ? 'cm' : 'plain');
        }
    } catch (e) {
        alert('Network error: ' + e);
    }
}

/* Double-click the modal title to rename the current note. Only files
   under <item>/notes/** are renamable; READMEs and knowledge/* are
   left alone (server returns 400 for those so the UI fails loud). The
   extension stays fixed — users type a stem, server re-appends the
   suffix. */
var _NOTES_RENAMEABLE_RE = /^projects\/\d{4}-\d{2}\/\d{4}-\d{2}-\d{2}-[\w.\-]+\/notes\//;

function startRenameNote() {
    var titleEl = document.getElementById('note-modal-title');
    var path = _noteModal.path || '';
    if (!_NOTES_RENAMEABLE_RE.test(path)) return;
    if (titleEl.querySelector('.note-rename-input')) return;  // already editing
    var filename = path.substring(path.lastIndexOf('/') + 1);
    var dotIdx = filename.lastIndexOf('.');
    var stem = dotIdx > 0 ? filename.substring(0, dotIdx) : filename;
    var ext = dotIdx > 0 ? filename.substring(dotIdx) : '';
    var originalText = titleEl.textContent;
    var restored = false;
    var restore = function() {
        if (restored) return;
        restored = true;
        titleEl.textContent = originalText;
    };
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'note-rename-input';
    input.value = stem;
    var extEl = document.createElement('span');
    extEl.className = 'note-rename-ext';
    extEl.textContent = ext;
    titleEl.textContent = '';
    titleEl.appendChild(input);
    titleEl.appendChild(extEl);
    input.focus();
    input.select();
    var commit = function() {
        var newStem = input.value.trim();
        if (!newStem || newStem === stem) { restore(); return; }
        fetch('/note/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: path, new_stem: newStem}),
        }).then(function(r) {
            return r.json().then(function(data) { return {ok: r.ok, data: data}; });
        }).then(function(result) {
            if (!result.ok || !result.data.ok) {
                alert('Rename failed: ' + (result.data.error || result.data.reason || 'unknown'));
                restore();
                return;
            }
            _noteModal.path = result.data.path;
            if (result.data.mtime != null) _noteModal.mtime = Number(result.data.mtime);
            var newName = newStem + ext;
            titleEl.textContent = newName;
            restored = true;  // keep the new value
        }).catch(function(err) {
            alert('Rename failed: ' + err);
            restore();
        });
    };
    input.onkeydown = function(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
        else if (ev.key === 'Escape') { ev.preventDefault(); restore(); }
        ev.stopPropagation();
    };
    input.onblur = commit;
    input.onclick = function(ev) { ev.stopPropagation(); };
}

/* --- Phase 7: note modal reconcile ---
   When /events signals a filesystem change, any open note may now
   diverge from its on-disk content. _reconcileNoteModal compares the
   loaded mtime with the live mtime and acts by buffer state:
     - clean buffer → silently reload text + render, restoring selection.
     - dirty buffer → reveal the banner and leave the buffer alone until
       the user picks "Keep my edits" or "Reload from disk".
   The banner dismissal is sticky until a new external change is
   detected (so the user who keeps editing isn't re-nagged).
*/
var _noteReconcileSuppressedUntilMtime = null;

async function _reconcileNoteModal() {
    if (!_noteModal || !_noteModal.path) return;
    var path = _noteModal.path;
    try {
        var res = await fetch('/note-raw?path=' + encodeURIComponent(path));
        if (!res.ok) return;
        var data = await res.json();
        if (_noteModal.path !== path) return;  // user switched notes mid-flight
        var fresh = Number(data.mtime);
        var loaded = Number(_noteModal.mtime);
        if (!isFinite(fresh) || !isFinite(loaded)) return;
        if (fresh <= loaded) return;  // no external change
        if (_noteReconcileSuppressedUntilMtime != null
            && fresh <= _noteReconcileSuppressedUntilMtime) {
            return;  // user said "keep my edits"; wait for a newer change
        }
        if (_noteModal.editable) _captureActiveBuffer();
        if (_noteModal.dirty) {
            _noteShowExternalBanner(true);
        } else {
            await _noteSilentReload(data);
        }
    } catch (e) {}
}

function _noteShowExternalBanner(show) {
    var banner = document.getElementById('note-modal-external-banner');
    if (!banner) return;
    if (show) banner.removeAttribute('hidden');
    else banner.setAttribute('hidden', '');
}

function _noteReconcileDismiss() {
    // Remember the disk mtime we just decided to ignore so repeat
    // polls don't re-show the banner until a newer change lands.
    _noteReconcileSuppressedUntilMtime = Number(_noteModal.mtime) || 0;
    _noteShowExternalBanner(false);
}

async function _noteReconcileReload() {
    try {
        var res = await fetch('/note-raw?path=' + encodeURIComponent(_noteModal.path));
        if (!res.ok) return;
        var data = await res.json();
        await _noteSilentReload(data);
        _noteShowExternalBanner(false);
        _noteReconcileSuppressedUntilMtime = null;
    } catch (e) {}
}

async function _noteSilentReload(rawData) {
    // Update buffer + preview, preserve caret/selection where possible.
    _noteModal.text = rawData.content;
    _noteModal.mtime = Number(rawData.mtime);
    _setDirty(false);
    // Hydrate whichever pane is active. CM6 owns its own state —
    // replace the doc but keep the selection when it still fits.
    if (_cm && _cm.view) {
        var prevSel = null;
        try { prevSel = _cm.view.state.selection; } catch (e) {}
        _cm.view.dispatch({
            changes: {from: 0, to: _cm.view.state.doc.length, insert: _noteModal.text},
        });
        if (prevSel) {
            try {
                var max = _cm.view.state.doc.length;
                var anchor = Math.min(prevSel.main.anchor, max);
                var head = Math.min(prevSel.main.head, max);
                _cm.view.dispatch({selection: {anchor: anchor, head: head}});
            } catch (e) {}
        }
    }
    var ta = document.getElementById('note-edit-textarea');
    if (ta) ta.value = _noteModal.text;
    try {
        await _reloadNotePreview(_noteModal.path, null);
    } catch (e) {}
}

async function _reloadNotePreview(path, name) {
    var pane = document.getElementById('note-pane-view');
    if (name) document.getElementById('note-modal-title').textContent = name;
    pane.innerHTML = '<p class="note-loading">Loading\u2026</p>';
    var res = await fetch('/note?path=' + encodeURIComponent(path));
    if (!res.ok) {
        pane.innerHTML = '<p class="note-error">Failed to load note (' + res.status + ').</p>';
        return;
    }
    var html = await res.text();
    pane.innerHTML = html;
    _noteModal.renderedHtml = html;
    _renderMermaidIn(pane);
    _wireNoteLinks(pane, path);
    _mountPdfsIn(pane);
    pane.scrollTop = 0;
}

document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var noteModal = document.getElementById('note-modal');
    if (noteModal && noteModal.classList.contains('open')) { closeNotePreview(); return; }
    var newItemModal = document.getElementById('new-item-modal');
    if (newItemModal && newItemModal.style.display && newItemModal.style.display !== 'none') {
        closeNewItemModal();
        return;
    }
    var cfgModal = document.getElementById('config-modal');
    if (cfgModal && cfgModal.style.display && cfgModal.style.display !== 'none') {
        closeConfigModal();
        return;
    }
    var aboutModal = document.getElementById('about-modal');
    if (aboutModal && aboutModal.style.display && aboutModal.style.display !== 'none') {
        closeAboutModal();
    }
});

/* Guard window-level navigation (tab close, reload, external nav) while
   a note modal has unsaved edits. The `returnValue` dance is required
   for legacy cross-browser support; modern browsers ignore the string
   and show their own generic confirm. */
window.addEventListener('beforeunload', function(e) {
    var modal = document.getElementById('note-modal');
    if (!modal || !modal.classList.contains('open')) return;
    if (_noteModal.editable) _captureActiveBuffer();
    if (!_noteModal.dirty) return;
    e.preventDefault();
    e.returnValue = '';
    return '';
});

async function cycle(file, line, el) {
    var res = await fetch('/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, line: line})
    });
    if (!res.ok) return;
    var data = await res.json();
    el.className = 'step ' + data.status;
    var dot = el.querySelector('.status-dot');
    dot.className = 'status-dot status-' + data.status;
    dot.textContent = {done: '\u2713', progress: '~', abandoned: '\u2014', open: ''}[data.status] || '';
    updateProgress(el.closest('.card'));
    updateBaseline();
}

async function removeStep(file, line, btn) {
    var res = await fetch('/remove-step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, line: line})
    });
    if (!res.ok) return;
    var step = btn.closest('.step');
    var card = step.closest('.card');
    var removedLine = parseInt(step.getAttribute('data-line'));
    step.remove();
    card.querySelectorAll('.step').forEach(function(s) {
        var ln = parseInt(s.getAttribute('data-line'));
        if (ln > removedLine) s.setAttribute('data-line', ln - 1);
    });
    updateProgress(card);
    updateBaseline();
}

function updateProgress(card) {
    var steps = card.querySelectorAll('.step');
    var done = [].filter.call(steps, function(s) { return s.classList.contains('done') || s.classList.contains('abandoned'); }).length;
    var total = steps.length;
    var el = card.querySelector('.progress-text');
    if (el) {
        var pct = total ? Math.round(done / total * 100) : 0;
        var style = getComputedStyle(document.documentElement);
        var fill = pct === 100 ? style.getPropertyValue('--progress-done') : style.getPropertyValue('--progress-fill');
        var bg = style.getPropertyValue('--progress-track');
        el.innerHTML = done + '/' + total +
            ' <span class="progress-bar" style="background:' + bg + '"><span class="progress-fill" style="width:' +
            pct + '%;background:' + fill + '"></span></span>';
    }
    card.querySelectorAll('.sec-group').forEach(function(group) {
        var items = group.querySelectorAll('.step');
        var d = [].filter.call(items, function(s) { return s.classList.contains('done') || s.classList.contains('abandoned'); }).length;
        var span = group.querySelector('.sec-count');
        if (span) span.textContent = '(' + d + '/' + items.length + ')';
    });
}

async function addStep(file, section, inputEl) {
    var text = inputEl.value.trim();
    if (!text) return;
    var res = await fetch('/add-step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, text: text, section: section})
    });
    if (!res.ok) return;
    var data = await res.json();
    var step = document.createElement('div');
    step.className = 'step open';
    step.setAttribute('data-file', file);
    step.setAttribute('data-line', data.line);
    var handle = document.createElement('span');
    handle.className = 'drag-handle';
    handle.textContent = '\u283f';
    handle.addEventListener('pointerdown', stepPointerDown);
    var dot = document.createElement('span');
    dot.className = 'status-dot';
    dot.onmousedown = function(e) { e.stopPropagation(); e.preventDefault(); };
    dot.onclick = function() { var s = this.closest('.step'); cycle(file, parseInt(s.getAttribute('data-line')), s); };
    var txt = document.createElement('span');
    txt.className = 'text';
    txt.textContent = text;
    txt.onmousedown = function(e) { e.stopPropagation(); };
    txt.onclick = function(e) { e.stopPropagation(); startEditText(this); };
    var btn = document.createElement('button');
    btn.className = 'remove-btn';
    btn.textContent = '\u00d7';
    btn.onmousedown = function(e) { e.stopPropagation(); e.preventDefault(); };
    btn.onclick = function() { var s = this.closest('.step'); removeStep(file, parseInt(s.getAttribute('data-line')), this); };
    step.appendChild(handle);
    step.appendChild(dot);
    step.appendChild(txt);
    step.appendChild(btn);
    inputEl.closest('.add-row').parentNode.insertBefore(step, inputEl.closest('.add-row'));
    var insertedLine = data.line;
    inputEl.closest('.card').querySelectorAll('.step').forEach(function(s) {
        if (s === step) return;
        var ln = parseInt(s.getAttribute('data-line'));
        if (ln >= insertedLine) s.setAttribute('data-line', ln + 1);
    });
    inputEl.value = '';
    inputEl.focus();
    updateProgress(inputEl.closest('.card'));
    updateBaseline();
}

/* Step reorder — pointer-event based for the same reason the terminal tabs
   use pointer events (see _termChipPointerDown): QtWebEngine segfaults
   pywebview on HTML5 dragstart of any moderately complex DOM element.
   Triggered from the drag handle only so click-to-edit on the text span
   and the status-dot cycle both keep working.

   The reorder is committed on pointerup, not during pointermove. An earlier
   version of this code called `insertBefore` on the dragging step during
   move; QtWebEngine drops `setPointerCapture` when the captured handle's
   ancestor is reparented, so pointerup never fired and `.dragging` stuck
   (opacity 0.4). During the gesture we only move a pointer-events:none
   ghost clone and toggle `is-drop-before`/`is-drop-after` markers on
   sibling steps. See #8. */
var _stepDrag = null;
var _STEP_DRAG_THRESHOLD_PX = 4;

function stepPointerDown(ev) {
    if (ev.button !== undefined && ev.button !== 0) return;
    var handle = ev.currentTarget;
    var step = handle.closest('.step');
    if (!step) return;
    _stepDrag = {
        step: step,
        container: step.closest('.sec-items'),
        pointerId: ev.pointerId,
        startX: ev.clientX,
        startY: ev.clientY,
        active: false,
        handle: handle,
        ghost: null,
        ghostOffX: 0,
        ghostOffY: 0,
        drop: null,  // {target: <step>, before: bool}
    };
    try { handle.setPointerCapture(ev.pointerId); } catch (e) {}
    handle.addEventListener('pointermove', stepPointerMove);
    handle.addEventListener('pointerup', stepPointerUp);
    handle.addEventListener('pointercancel', stepPointerCancel);
    ev.preventDefault();
}

function stepPointerMove(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    if (!_stepDrag.active) {
        var dx = ev.clientX - _stepDrag.startX;
        var dy = ev.clientY - _stepDrag.startY;
        if (Math.hypot(dx, dy) < _STEP_DRAG_THRESHOLD_PX) return;
        _stepBeginDrag();
    }
    _stepDrag.ghost.style.left = (ev.clientX - _stepDrag.ghostOffX) + 'px';
    _stepDrag.ghost.style.top = (ev.clientY - _stepDrag.ghostOffY) + 'px';
    _stepUpdateDropMarker(ev.clientX, ev.clientY);
}

function _stepBeginDrag() {
    var step = _stepDrag.step;
    _stepDrag.active = true;
    var rect = step.getBoundingClientRect();
    var ghost = step.cloneNode(true);
    ghost.classList.add('step-ghost');
    ghost.style.position = 'fixed';
    ghost.style.left = rect.left + 'px';
    ghost.style.top = rect.top + 'px';
    ghost.style.width = rect.width + 'px';
    ghost.style.height = rect.height + 'px';
    // pointer-events:none is critical — without it, elementFromPoint would
    // return the ghost and the drop marker could never latch on a sibling.
    ghost.style.pointerEvents = 'none';
    ghost.style.zIndex = '9999';
    ghost.style.opacity = '0.85';
    document.body.appendChild(ghost);
    _stepDrag.ghost = ghost;
    _stepDrag.ghostOffX = _stepDrag.startX - rect.left;
    _stepDrag.ghostOffY = _stepDrag.startY - rect.top;
    step.classList.add('dragging');
}

function _stepUpdateDropMarker(x, y) {
    document.querySelectorAll('.step.is-drop-before, .step.is-drop-after').forEach(function(el) {
        el.classList.remove('is-drop-before');
        el.classList.remove('is-drop-after');
    });
    _stepDrag.drop = null;
    var under = document.elementFromPoint(x, y);
    if (!under) return;
    var target = under.closest && under.closest('.step');
    if (!target || target === _stepDrag.step) return;
    if (target.closest('.sec-items') !== _stepDrag.container) return;
    var rect = target.getBoundingClientRect();
    var before = y < rect.top + rect.height / 2;
    target.classList.toggle('is-drop-before', before);
    target.classList.toggle('is-drop-after', !before);
    _stepDrag.drop = {target: target, before: before};
}

function stepPointerUp(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    var drag = _stepDrag;
    _stepCleanupDrag();
    if (!drag.active) return;  // Just a click on the handle — nothing to do.
    if (!drag.drop) return;
    var drop = drag.drop;
    if (drop.before) {
        drag.container.insertBefore(drag.step, drop.target);
    } else {
        drag.container.insertBefore(drag.step, drop.target.nextSibling);
    }
    var steps = drag.container.querySelectorAll('.step');
    if (!steps.length) return;
    var file = steps[0].getAttribute('data-file');
    var lines = [].map.call(steps, function(s) { return parseInt(s.getAttribute('data-line')); });
    var sorted = lines.slice().sort(function(a, b) { return a - b; });
    if (lines.every(function(v, i) { return v === sorted[i]; })) return;
    fetch('/reorder-all', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, order: lines})
    }).then(function(res) {
        if (!res.ok) return;
        [].forEach.call(steps, function(s, i) { s.setAttribute('data-line', sorted[i]); });
        updateBaseline();
    });
}

function stepPointerCancel(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    _stepCleanupDrag();
}

function _stepCleanupDrag() {
    if (!_stepDrag) return;
    var handle = _stepDrag.handle;
    try { handle.releasePointerCapture(_stepDrag.pointerId); } catch (e) {}
    handle.removeEventListener('pointermove', stepPointerMove);
    handle.removeEventListener('pointerup', stepPointerUp);
    handle.removeEventListener('pointercancel', stepPointerCancel);
    if (_stepDrag.ghost && _stepDrag.ghost.parentNode) {
        _stepDrag.ghost.parentNode.removeChild(_stepDrag.ghost);
    }
    _stepDrag.step.classList.remove('dragging');
    document.querySelectorAll('.step.is-drop-before, .step.is-drop-after').forEach(function(el) {
        el.classList.remove('is-drop-before');
        el.classList.remove('is-drop-after');
    });
    _stepDrag = null;
}

function startEditText(el) {
    if (el.classList.contains('editing')) return;
    var original = el.textContent;
    var cancelled = false;
    el.classList.add('editing');
    el.contentEditable = 'true';
    el.focus();
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    el.onpaste = function(e) {
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text/plain');
        document.execCommand('insertText', false, text.replace(/\n/g, ' '));
    };

    async function commit() {
        el.onblur = null;
        el.onkeydown = null;
        el.onpaste = null;
        el.contentEditable = 'false';
        el.classList.remove('editing');
        if (cancelled) { el.textContent = original; return; }
        var newText = el.textContent.trim();
        if (!newText || newText === original) {
            el.textContent = original;
            return;
        }
        var step = el.closest('.step');
        var file = step.getAttribute('data-file');
        var line = parseInt(step.getAttribute('data-line'));
        var res = await fetch('/edit-step', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({file: file, line: line, text: newText})
        });
        if (!res.ok) el.textContent = original;
        else updateBaseline();
    }

    el.onblur = commit;
    el.onkeydown = function(e) {
        if (e.key === 'Enter') { e.preventDefault(); el.blur(); }
        if (e.key === 'Escape') { cancelled = true; el.blur(); }
    };
}

/* --- Stale-detection polling (localized, per-node) ---
   /check-updates returns a {node_id: hash} map covering every card, group,
   directory, and repo node in the three tabs. We keep the previous map as a
   baseline and, each poll, compute the set of dirty ids (differ / added /
   removed). From that set we drive:
     - `.node-stale` on every DOM element whose own id is dirty (strong dot),
     - `.node-stale-hint` on ancestor elements (muted dot) — so you can
       choose to reload at any level above the actual change,
     - the pre-existing `.stale` dot on the primary tab header (kept for
       coarse orientation).
   Node ids are slash-separated; ancestors are derived by trimming segments
   from the right. */
var _nodeBaseline = null;    // Object id → hash (null until first poll)
var _dirtyNodes = new Set(); // ids whose current hash != baseline, or present on only one side
var _lastFingerprint = null; // kept for back-compat with pickPriority/switchTab
var _lastGitFingerprint = null;

function _deriveLegacyFlags() {
    // Coarse flags the existing tab-switch / mutation code still reads.
    var items = false, git = false, knowledge = false;
    _dirtyNodes.forEach(function(id) {
        if (id === 'projects' || id.indexOf('projects/') === 0) items = true;
        else if (id === 'code' || id.indexOf('code/') === 0) git = true;
        else if (id === 'knowledge' || id.indexOf('knowledge/') === 0) knowledge = true;
    });
    _itemsStale = items;
    _gitStale = git;
    _knowledgeStale = knowledge;
}

function _ancestorsOf(id) {
    // "projects/now/slug" → ["projects/now", "projects"]. Splits on '/';
    // subtree IDs like wt:foo or sub:bar are single segments so this is safe.
    var parts = id.split('/');
    var out = [];
    for (var i = parts.length - 1; i > 0; i--) {
        out.push(parts.slice(0, i).join('/'));
    }
    return out;
}

function _renderStale() {
    // Phase 3: the active tab auto-reloads, so per-node dots and
    // ancestor hints are gone; the only user-visible staleness marker
    // is a single binary dot on each *inactive* tab header.
    // Clear any surviving Phase-1/Phase-2 markers — if a swap was
    // guard-skipped, _renderStale re-renders with the latest state.
    document.querySelectorAll('[data-node-id].node-stale, [data-node-id].node-stale-hint')
        .forEach(function(el) {
            el.classList.remove('node-stale');
            el.classList.remove('node-stale-hint');
        });
    document.querySelectorAll('.group-dirty-leader')
        .forEach(function(el) { el.classList.remove('group-dirty-leader'); });
    document.querySelectorAll('.node-reload-btn')
        .forEach(function(btn) { btn.remove(); });

    _deriveLegacyFlags();
    var staleByTab = {
        projects: _itemsStale,
        code: _gitStale,
        knowledge: _knowledgeStale,
        history: _itemsStale,
    };
    document.querySelectorAll('.tabs-primary .tab').forEach(function(t) {
        var key = t.getAttribute('data-tab');
        // Active tab never shows the dot — it self-refreshes.
        var isStale = !!staleByTab[key] && key !== _activeTab;
        t.classList.toggle('stale', isStale);
        if (isStale) {
            t.title = 'Click to refresh — data has changed on disk';
        } else {
            t.removeAttribute('title');
        }
    });
}

var _itemsStale = false, _gitStale = false, _knowledgeStale = false;

function _diffNodes(baseline, current) {
    var dirty = new Set();
    if (!baseline) return dirty;
    for (var id in current) {
        if (baseline[id] !== current[id]) dirty.add(id);
    }
    for (var id2 in baseline) {
        if (!(id2 in current)) dirty.add(id2);
    }
    return dirty;
}

/* Coalesce rapid checkUpdates triggers. A single user save fires
   multiple watchdog events (the file, its directory, its parents);
   each used to start its own fetch + fragment-swap pass, which
   showed up as a flicker on the active tab. _scheduleCheckUpdates
   collapses calls within a 250ms window into a single run and
   guarantees a trailing pass so the last event isn't dropped. */
var _checkUpdatesTimer = null;
var _checkUpdatesInFlight = false;
var _checkUpdatesPending = false;
function _scheduleCheckUpdates() {
    if (_checkUpdatesInFlight) { _checkUpdatesPending = true; return; }
    if (_checkUpdatesTimer) return;
    _checkUpdatesTimer = setTimeout(function() {
        _checkUpdatesTimer = null;
        checkUpdates();
    }, 250);
}

async function checkUpdates() {
    if (_checkUpdatesInFlight) { _checkUpdatesPending = true; return; }
    _checkUpdatesInFlight = true;
    try {
        var res = await fetch('/check-updates');
        if (!res.ok) return;
        var data = await res.json();
        var current = data.nodes || {};
        if (_nodeBaseline === null) {
            _nodeBaseline = current;
            _lastFingerprint = data.fingerprint;
            _lastGitFingerprint = data.git_fingerprint;
        } else {
            // Once a node is marked dirty, it stays dirty until a local or
            // global reload updates the baseline — so the user can see there
            // was a change even if they weren't on the tab when it happened.
            var fresh = _diffNodes(_nodeBaseline, current);
            fresh.forEach(function(id) { _dirtyNodes.add(id); });
            // Phase 3: staleness on the active tab auto-resolves. Other
            // tabs' dirty state is still tracked; their binary dot
            // surfaces when _renderStale runs below.
            if (fresh.size > 0) _autoReloadActiveTab(fresh);
            // Phase 4: any staleness on an inactive tab kicks off a
            // single background fetch of / so the next tab click can
            // swap instantly.
            var anyInactiveDirty = false;
            fresh.forEach(function(id) {
                var tab = _tabForNodeId(id);
                if (tab && tab !== _activeTab) anyInactiveDirty = true;
            });
            if (anyInactiveDirty) _refreshShadowCache();
        }
        _renderStale();
    } catch (e) {
    } finally {
        _checkUpdatesInFlight = false;
        if (_checkUpdatesPending) {
            _checkUpdatesPending = false;
            _scheduleCheckUpdates();
        }
    }
}

function _activeTabPrefix() {
    // History derives from the same on-disk data as Projects.
    return _activeTab === 'history' ? 'projects' : _activeTab;
}

function _idInTab(id, tab) {
    var prefix = tab === 'history' ? 'projects' : tab;
    return id === prefix || id.indexOf(prefix + '/') === 0;
}

/* --- SSE event stream (Phase 6) ---
   Replaces the 5s polling loop. Every event from /events triggers a
   reconcile call to /check-updates; the real dirty-set computation
   lives there, unchanged. On drop, _setReconnecting(true) surfaces
   the pill and an exponential-backoff retry loop tries to reopen. */
var _eventSource = null;
var _eventReconnectTimer = null;
var _eventReconnectDelay = 1000;

/* Live YAML reload: dispatched from the SSE onmessage handler when the
   filesystem watcher notices an external edit to repositories.yml or
   preferences.yml. The server has already rebuilt its RenderCtx by
   the time this fires, so the client's job is just to:
     (a) refresh the open config modal's form in place, if any, and
     (b) rebuild the dashboard body so server-rendered bits (repo strip,
         open-with buttons, terminal shortcut specs) pick up the change.
   Self-writes from POST /config are suppressed server-side, so this
   only fires on external edits — no infinite loop. */
var _configReloadTimer = null;
function _onConfigChanged(payload) {
    if (_configReloadTimer) clearTimeout(_configReloadTimer);
    _configReloadTimer = setTimeout(async function() {
        _configReloadTimer = null;
        var modal = document.getElementById('config-modal');
        var modalOpen = modal && modal.style.display !== 'none' && modal.style.display !== '';
        if (modalOpen) {
            // Reload the /config payload and push it through the
            // populators, but keep the user's dirty YAML edits if
            // any — clobbering an unsaved edit on every external
            // write would be a foot-gun.
            try {
                var res = await fetch('/config', {cache: 'no-store'});
                if (res.ok) {
                    var cfg = await res.json();
                    _populateYamlEditor('repositories', cfg.repositories_yaml_body || '', true);
                    _populateYamlEditor('preferences', cfg.preferences_yaml_body || '', true);
                    // Only refresh form fields when the YAML pane isn't dirty —
                    // otherwise the form stays as-is and the dirty YAML drives
                    // the upcoming save.
                    if (!_getDirtyYamlFile()) openConfigModal();
                }
            } catch (e) { /* leave modal as-is on transient fetch error */ }
        }
        // Always refresh shortcut specs — they live outside the modal
        // and bind global key handlers.
        if (typeof _loadTermShortcuts === 'function') _loadTermShortcuts();
        // Rebuild the server-rendered dashboard so the repo strip and
        // open-with buttons reflect the new config.
        _reloadInPlace();
    }, 150);
}

function _startEventStream() {
    if (typeof EventSource !== 'function') return;  // no push, stick with boot checkUpdates
    try {
        _eventSource = new EventSource('/events');
    } catch (e) {
        _setReconnecting(true);
        _scheduleEventReconnect();
        return;
    }
    _eventSource.addEventListener('hello', function() {
        _setReconnecting(false);
        _eventReconnectDelay = 1000;
        // Reconcile: the stream may have missed changes during the
        // gap. checkUpdates diffs fingerprints and picks them up.
        checkUpdates();
    });
    _eventSource.addEventListener('ping', function() { /* keepalive */ });
    _eventSource.onmessage = function(ev) {
        // Parse the payload to dispatch on the ``tab`` field. Config
        // events run a dedicated handler (refresh the modal if open,
        // else in-place reload so repo strip + open-with buttons pick
        // up the new YAML). Everything else falls through to the
        // existing staleness pipeline.
        var payload = null;
        try { payload = JSON.parse(ev.data || '{}'); } catch (e) { payload = {}; }
        // Config changes no longer stream over SSE — the watcher on
        // config/*.yml was removed; the modal's Save path handles
        // everything explicitly.
        // Any other non-typed message is a staleness hint. Debounced so
        // a burst of watcher events collapses into a single fetch + swap.
        _scheduleCheckUpdates();
        // Phase 7: open-note reconcile — a disk change anywhere in the
        // watched tree might affect the currently-displayed note.
        _reconcileNoteModal();
    };
    _eventSource.onerror = function() {
        _setReconnecting(true);
        try { _eventSource.close(); } catch (e) {}
        _eventSource = null;
        _scheduleEventReconnect();
    };
}

function _scheduleEventReconnect() {
    if (_eventReconnectTimer) return;
    _eventReconnectTimer = setTimeout(function() {
        _eventReconnectTimer = null;
        _eventReconnectDelay = Math.min(_eventReconnectDelay * 2, 30000);
        _startEventStream();
    }, _eventReconnectDelay);
}

function _setReconnecting(on) {
    var pill = document.getElementById('reconnecting-pill');
    if (!pill) return;
    if (on) pill.removeAttribute('hidden');
    else pill.setAttribute('hidden', '');
}

function _autoReloadActiveTab(freshIds) {
    var freshInActive = [];
    freshIds.forEach(function(id) {
        if (_idInTab(id, _activeTab)) freshInActive.push(id);
    });
    if (freshInActive.length === 0) return;
    // If any fresh id isn't fragment-fetchable (tab roots, priority
    // groups, History) we fall back to a single full rebuild. The
    // focus-safe primitive and the Phase-2 guards still apply.
    var needGlobal = freshInActive.some(function(id) {
        return !_supportsFragmentFetch(id);
    });
    if (needGlobal) { _reloadInPlace(); return; }
    // Dedupe: if both "projects/now/foo" and "projects/now/foo/sub" are
    // dirty, reloading the parent covers the child. Without this every
    // descendant triggers its own fragment swap and the tab flickers.
    var minimal = _minimalRoots(freshInActive);
    minimal.forEach(function(id) { reloadNode(id); });
}

function _minimalRoots(ids) {
    var sorted = ids.slice().sort();
    var out = [];
    sorted.forEach(function(id) {
        var covered = out.some(function(prev) {
            return id === prev || id.indexOf(prev + '/') === 0;
        });
        if (!covered) out.push(id);
    });
    return out;
}

async function updateBaseline() {
    try {
        var res = await fetch('/check-updates');
        if (!res.ok) return;
        var data = await res.json();
        _nodeBaseline = data.nodes || {};
        _dirtyNodes = new Set();
        _lastFingerprint = data.fingerprint;
        _lastGitFingerprint = data.git_fingerprint;
        _renderStale();
    } catch (e) {}
}

/* Hard refresh — last-resort escape hatch. Throws away every piece of
   client-side cached state (baseline, dirty set, shadow cache, pending
   reloads) and does a full `location.reload()` so the browser re-parses
   the page from scratch. Used when the soft in-place reload can't shake
   the UI out of a bad state — e.g. a project rendered in no column, or a
   stuck stale-dot on a tab. Tracked: condash#14. */
export function refreshAll() {
    _nodeBaseline = null;
    _dirtyNodes = new Set();
    _shadowCache = null;
    _pendingReloadNodes.clear();
    _pendingReloadInPlace = false;
    _lastFingerprint = null;
    _lastGitFingerprint = null;
    // Force-invalidate the server-side items/knowledge caches before
    // reloading so the next GET / re-walks the tree from disk. Best
    // effort: reload unconditionally even if the POST errors, since
    // `location.reload()` is also the user-requested action.
    fetch('/rescan', {method: 'POST'})
        .catch(function() {})
        .finally(function() { location.reload(); });
}

/* --- Local subtree reload ---
   Click on a stale marker. For node ids the server knows how to fragment
   (project card, knowledge card, knowledge directory) we fetch just that
   fragment and replace the matching element in place, preserving any
   <details> open-state inside it. For everything else (groups, tabs, code
   nodes) the fragment endpoint returns 404 and we fall back to the global
   _reloadInPlace. Either way the dirty-set entries covered by the reload
   are dropped and the baseline is refreshed for those entries. */
function _supportsFragmentFetch(nodeId) {
    // Project cards: projects/<pri>/<slug>
    if (/^projects\/[a-z]+\/.+/.test(nodeId)) return true;
    // Knowledge directories and cards (not the root).
    if (nodeId === 'knowledge') return false;
    if (/^knowledge\//.test(nodeId)) return true;
    // Repo blocks: code/<group>/<repo>. Group and tab ids still fall
    // back to global reload.
    if (/^code\/[^/]+\/[^/]+$/.test(nodeId)) return true;
    return false;
}

function _captureDetailsOpenState(root) {
    var map = {};
    root.querySelectorAll('details[data-node-id]').forEach(function(d) {
        map[d.getAttribute('data-node-id')] = d.open;
    });
    return map;
}

function _restoreDetailsOpenState(root, map) {
    root.querySelectorAll('details[data-node-id]').forEach(function(d) {
        var id = d.getAttribute('data-node-id');
        if (id in map) d.open = map[id];
    });
}

/* --- Reload guards (Phase 2) ---
   The two production landmines before the overhaul: a fragment swap
   while a runner's WebSocket is live silently kills the build; a
   _reloadInPlace while the note modal has unsaved edits silently
   discards them. Both are now caught by focusSafeSwap's default
   skipIf — the swap is refused, the dirty state is preserved, and a
   retry is queued for when the guard clears. */
function _noteModalDirty() {
    return !!(window._noteModal && _noteModal.dirty);
}

function _runnerActiveIn(targetEl) {
    if (!targetEl || typeof _runnerViewers !== 'object') return false;
    var mounts = targetEl.querySelectorAll &&
        targetEl.querySelectorAll('.runner-term-mount');
    if (!mounts || !mounts.length) return false;
    var activeKeys = {};
    for (var dk in _runnerViewers) {
        var v = _runnerViewers[dk];
        if (v && !v.exited && v.ws && v.ws.readyState === WebSocket.OPEN) {
            activeKeys[v.key] = true;
        }
    }
    for (var i = 0; i < mounts.length; i++) {
        var key = mounts[i].getAttribute('data-runner-key');
        if (key && activeKeys[key]) return true;
    }
    return false;
}

function _defaultReloadSkipIf(targetEl) {
    if (_noteModalDirty()) return 'note-dirty';
    if (_runnerActiveIn(targetEl)) return 'runner-active';
    return null;
}

/* Pending-reload bookkeeping. When a swap is refused, we stash the
   request and retry when the responsible guard clears. Deliberately
   kept small: one boolean for the global rebuild, a set of node ids
   for per-subtree reloads. */
var _pendingReloadNodes = new Set();
var _pendingReloadInPlace = false;

function _flushPendingReloads() {
    if (_noteModalDirty()) return;  // still blocked; caller will re-flush
    if (_pendingReloadInPlace) {
        _pendingReloadInPlace = false;
        _pendingReloadNodes.clear();  // superseded by the global rebuild
        _reloadInPlace();
        return;
    }
    var retry = Array.from(_pendingReloadNodes);
    _pendingReloadNodes.clear();
    retry.forEach(function(id) {
        // Runner-active guard for this specific node is re-checked by
        // focusSafeSwap's skipIf — any still-blocked entries land back
        // in _pendingReloadNodes via reloadNode's skipped-branch.
        reloadNode(id);
    });
}

/* --- Focus-safe DOM swap primitive ---
   Shared helper used by _reloadInPlace (tab-level) and reloadNode
   (per-subtree). Captures anything that would be lost by a naive
   replaceWith — scroll, focus/caret, <details> open state, opt-in
   `data-preserve` form inputs — then restores it onto the fresh DOM.
   Callers extend it via `opts.skipIf(targetEl)` → any truthy return
   aborts the swap and the caller is told the reason (used from
   Phase 2 onwards to defer reloads that would kill a live runner
   or trash unsaved modal edits). Phase 1 introduces no callers of
   skipIf; the primitive is pure refactor. */
function focusSafeSwap(targetEl, freshEl, opts) {
    opts = opts || {};
    var skipIf = opts.skipIf || _defaultReloadSkipIf;
    var reason = skipIf(targetEl);
    if (reason) return {skipped: true, reason: reason};
    var snapshot = _snapshotForSwap(targetEl, opts);
    targetEl.replaceWith(freshEl);
    _restoreFromSnapshot(freshEl, snapshot, opts);
    return {skipped: false, snapshot: snapshot};
}

function _snapshotForSwap(el, opts) {
    var snap = {};
    // Window + #main-scroll position, for tab-level rebuilds where
    // el === #dash-main; harmless when el is a subtree.
    snap.scrollY = window.scrollY;
    var mainScroll = document.getElementById('main-scroll');
    snap.mainScrollTop = mainScroll ? mainScroll.scrollTop : null;
    // Explicit named scroll containers inside the target.
    snap.scrollMap = {};
    el.querySelectorAll('[data-scroll-key]').forEach(function(n) {
        snap.scrollMap[n.getAttribute('data-scroll-key')] = {
            top: n.scrollTop, left: n.scrollLeft,
        };
    });
    // <details> by data-node-id (inside el).
    snap.detailsMap = _captureDetailsOpenState(el);
    // Active element focus + caret (text inputs / textareas only).
    var active = document.activeElement;
    if (active && el.contains(active) && active.id) {
        snap.focusId = active.id;
        try {
            snap.focusSel = {
                start: active.selectionStart, end: active.selectionEnd,
            };
        } catch (e) {}
    }
    // data-preserve inputs → sessionStorage (Phase 5 lights up the
    // callers that care, but the plumbing is harmless today).
    el.querySelectorAll('input[data-preserve],textarea[data-preserve]').forEach(function(n) {
        var key = n.getAttribute('data-preserve');
        if (!key) return;
        var payload = {value: n.value};
        try {
            payload.sel = {start: n.selectionStart, end: n.selectionEnd};
        } catch (e) {}
        try { sessionStorage.setItem(key, JSON.stringify(payload)); }
        catch (e) {}
    });
    return snap;
}

function _restoreFromSnapshot(el, snap, opts) {
    if (snap.scrollY != null) window.scrollTo(0, snap.scrollY);
    var mainScroll = document.getElementById('main-scroll');
    if (mainScroll && snap.mainScrollTop != null) {
        mainScroll.scrollTop = snap.mainScrollTop;
    }
    el.querySelectorAll('[data-scroll-key]').forEach(function(n) {
        var saved = snap.scrollMap && snap.scrollMap[n.getAttribute('data-scroll-key')];
        if (saved) { n.scrollTop = saved.top; n.scrollLeft = saved.left; }
    });
    _restoreDetailsOpenState(el, snap.detailsMap || {});
    if (snap.focusId) {
        var f = document.getElementById(snap.focusId);
        if (f) {
            try { f.focus(); } catch (e) {}
            if (snap.focusSel && f.setSelectionRange) {
                try { f.setSelectionRange(snap.focusSel.start, snap.focusSel.end); }
                catch (e) {}
            }
        }
    }
    el.querySelectorAll('input[data-preserve],textarea[data-preserve]').forEach(function(n) {
        var key = n.getAttribute('data-preserve');
        if (!key) return;
        try {
            var raw = sessionStorage.getItem(key);
            if (!raw) return;
            var payload = JSON.parse(raw);
            if (payload.value != null && n.value !== payload.value) {
                n.value = payload.value;
            }
            if (payload.sel && n.setSelectionRange &&
                document.activeElement === n) {
                try { n.setSelectionRange(payload.sel.start, payload.sel.end); }
                catch (e) {}
            }
        } catch (e) {}
    });
}

async function reloadNode(nodeId) {
    // Fall back to global reload for tab-level, group-level, and code nodes.
    if (!_supportsFragmentFetch(nodeId)) {
        _reloadInPlace();
        return;
    }
    try {
        var res = await fetch('/fragment?id=' + encodeURIComponent(nodeId),
                              {cache: 'no-store'});
        if (!res.ok) { _reloadInPlace(); return; }
        var html = await res.text();
        var esc = (window.CSS && CSS.escape) ? CSS.escape(nodeId) : nodeId;
        var existing = document.querySelector('[data-node-id="' + esc + '"]');
        if (!existing) { _reloadInPlace(); return; }

        var tpl = document.createElement('template');
        tpl.innerHTML = html.trim();
        var fresh = tpl.content.firstElementChild;
        if (!fresh) { _reloadInPlace(); return; }

        // Card .collapsed/.expanded toggle is held only in the live
        // class list; the server always re-renders the card collapsed.
        // Preserve whatever the user had open across the swap so a
        // localized refresh doesn't snap the card shut on them.
        var wasExpanded = existing.classList.contains('card')
            && !existing.classList.contains('collapsed');

        var result = focusSafeSwap(existing, fresh);
        if (result.skipped) {
            // Guard tripped (runner live, or note modal dirty). Park the
            // request; _flushPendingReloads replays it when the guard
            // clears. Dirty-set + baseline are intentionally preserved.
            _pendingReloadNodes.add(nodeId);
            return;
        }
        if (wasExpanded && fresh.classList && fresh.classList.contains('card')) {
            fresh.classList.remove('collapsed');
        }
        // Notes-tree groups persist in localStorage (no data-node-id),
        // so a per-key restore is needed after the swap.
        restoreNotesTreeState();

        // Refresh baseline BEFORE dropping dirty entries: otherwise a
        // checkUpdates poll landing in the await-gap below would compare
        // the post-swap current hash against the pre-swap baseline, see
        // a diff, re-add the id to _dirtyNodes, and strand the dot on
        // the tab forever. Updating the baseline first means a racing
        // poll sees baseline == current and short-circuits with no diff.
        // condash#14 (stale tab-dot after tab-away-and-back).
        await _refreshBaselineFor(nodeId);
        var prefix = nodeId + '/';
        var dropped = [];
        _dirtyNodes.forEach(function(id) {
            if (id === nodeId || id.indexOf(prefix) === 0) dropped.push(id);
        });
        dropped.forEach(function(id) { _dirtyNodes.delete(id); });
        // The server-rendered fragment is always visible (no .hidden class).
        // Re-apply the active subtab filter so a card whose priority falls
        // outside the current subtab slides back into its proper hidden
        // state — and one whose priority just entered the current subtab
        // becomes visible.
        if (_activeTab === 'projects') _applySubtab(_activeSubtab);
        _renderStale();
    } catch (e) {
        _reloadInPlace();
    }
}

async function _refreshBaselineFor(nodeId) {
    // Re-fetch /check-updates and adopt the current hash for the reloaded
    // subtree so the next poll doesn't immediately re-dirty it. Other
    // nodes' dirty state is preserved.
    try {
        var res = await fetch('/check-updates');
        if (!res.ok) return;
        var data = await res.json();
        var current = data.nodes || {};
        if (!_nodeBaseline) _nodeBaseline = {};
        var prefix = nodeId + '/';
        for (var id in current) {
            if (id === nodeId || id.indexOf(prefix) === 0) {
                _nodeBaseline[id] = current[id];
            }
        }
    } catch (e) {}
}

/* --- Embedded terminal (multi-tab) ---
   Each tab owns its own xterm instance + pty WebSocket. Server sends an
   `exit` info frame when the shell dies; client closes the tab. Closing
   the last tab hides the pane. The pane's × and the toggle shortcut
   hide/show the pane while leaving the tabs intact. */
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

export function _termClipboardWrite(text) {
    if (!text) return;
    var invoke = _tauriInvoke();
    if (!invoke) return;
    try {
        Promise.resolve(invoke('plugin:clipboard-manager|write_text', {text: text}))
            .catch(function() {});
    } catch (e) {}
}

export function _termClipboardRead() {
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

/* Shared cross-module state for the terminal-tab subsystem. Exported so
   sections/tab-drag.js can mutate these fields in-place — ESM live
   bindings disallow reassigning imported primitive `let` exports from
   the importer side, so we keep everything on one object. See
   projects/2026-04-23-condash-frontend-extraction/notes/01-p07-tab-drag-split.md
   D1 for the design rationale. P-09 will move this declaration into
   the terminal section file when the "Embedded terminal" region itself
   is extracted. */
export const termState = {
    tabs: [],                               // [{id, side, term, fit, ws, mount, button, shell}]
    active: { left: null, right: null },
    lastFocused: 'left',
};
var _termAssetsWarned = false;

export function _termAssetsReady() {
    return typeof Terminal !== 'undefined' && typeof FitAddon !== 'undefined';
}

export function _termWarnAssets() {
    if (_termAssetsWarned) return;
    _termAssetsWarned = true;
    document.getElementById('term-mount-left').innerHTML =
        '<p style="color:#faa; padding: 1rem;">Terminal assets failed to load — vendored xterm.js missing from /vendor/xterm/. Reinstall condash.</p>';
}

export function _termSideEl(side, which) {
    // which ∈ {'tabs', 'mount', 'side'}
    if (which === 'side') return document.querySelector('.term-side[data-side="' + side + '"]');
    if (which === 'tabs') return document.getElementById('term-tabs-' + side);
    return document.getElementById('term-mount-' + side);
}

export function _termTabsOn(side) {
    return termState.tabs.filter(function(t) { return t.side === side; });
}

export function _termActiveTab() {
    // Prefer left's active, else right's — the "current" active for
    // header-shell display falls on whichever side was last focused.
    var leftId = termState.active.left, rightId = termState.active.right;
    var pref = termState.lastFocused === 'right' ? rightId : leftId;
    var alt = termState.lastFocused === 'right' ? leftId : rightId;
    return termState.tabs.find(function(t) { return t.id === pref; })
        || termState.tabs.find(function(t) { return t.id === alt; })
        || null;
}

export function _termSendResize(tab) {
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

export function _termSendResizeAll() {
    termState.tabs.forEach(function(t) { _termSendResize(t); });
}

/* Persist the open-tab list so a page refresh can reattach to the same
   backend ptys. Only tabs that have received their server-assigned
   session_id are persisted — an unacknowledged tab has no ID to reattach
   to and would just spawn a fresh (different) shell on reload. */
export function _termPersistTabs() {
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

export function _termShellLabel(tab) {
    var label = document.getElementById('term-shell');
    if (!label) return;
    label.textContent = tab && tab.shell ? tab.shell : '';
}

export function _termSyncActiveSide() {
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

export function _termSetActive(id) {
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

export function _termRenderTabChip(tab) {
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
    close.textContent = '\u00d7';
    close.title = 'Close tab';
    close.onclick = function(ev) { ev.stopPropagation(); _termCloseTab(tab.id); };
    btn.appendChild(close);
    tab.button = btn;
    tab.labelEl = label;
    _termSideEl(tab.side, 'tabs').appendChild(btn);
}

// The "Tab drag" region that used to live here (pointer-event drag,
// tab create/close/rename, splitter drag, pane-resize drag, shortcuts,
// restore-on-reload) now lives in `sections/tab-drag.js`. Register its
// DOM-level side effects now that both modules have finished
// evaluating — see the notes for P-07
// (projects/2026-04-23-condash-frontend-extraction/notes/01-p07-tab-drag-split.md).
initTabDragSideEffects();
initThemeSideEffects();
initAboutModalSideEffects();
initNewItemModalSideEffects();
initNotesTreeStateSideEffects();
initCm6ThemeSyncSideEffects();

// Phase 6: event-driven staleness. /events streams tab-level hints;
// checkUpdates() runs on connect + every hint to reconcile the real
// node-level dirty set. The 5s poll is gone. If the SSE connection
// drops, a visible indicator surfaces and reconnect logic re-runs
// checkUpdates() as soon as the stream is back.
checkUpdates();
_startEventStream();

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

/* --- Inline dev-server runner viewers ---
   Each `.runner-term-mount` element rendered by the repo strip gets its
   own xterm instance + WebSocket to `/ws/runner/<key>`. Attach and
   detach do not kill the server-side pty; reloadNode / _reloadInPlace
   swaps the mount DOM, and runnerReattachAll() closes orphaned viewers
   and creates fresh ones for any newly-inserted mounts. Pop-out mode
   detaches the inline ws in favour of a modal-hosted viewer, then
   re-attaches inline when the modal closes. */
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
                        _runnerScheduleRefresh(key, checkout);
                        if (typeof _flushPendingReloads === 'function') {
                            _flushPendingReloads();
                        }
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
    ws.onclose = function() {
        // Runner teardown clears the runner-active guard for this node —
        // drain any reload that was parked while the runner was live.
        if (typeof _flushPendingReloads === 'function') _flushPendingReloads();
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

function _runnerRepoNodeIdFor(key, checkout) {
    var mount = _runnerFindMount(key, checkout);
    if (!mount) return null;
    var group = mount.closest('.flat-group');
    return group ? group.getAttribute('data-node-id') : null;
}

async function _runnerRefreshRepoNode(repoNodeId) {
    if (!repoNodeId) { await _reloadInPlace(); runnerReattachAll(); return; }
    await reloadNode(repoNodeId);
    runnerReattachAll();
}

var _runnerRefreshPending = null;
function _runnerScheduleRefresh(key, checkout) {
    // Debounce rapid state changes — a burst of starts/exits during a
    // confirm-switch flow shouldn't trigger three fragment fetches.
    if (_runnerRefreshPending) clearTimeout(_runnerRefreshPending);
    var repoId = _runnerRepoNodeIdFor(key, checkout)
        || document.querySelector('.flat-group[data-node-id*="/' + key.split('--')[0] + '"]');
    if (repoId && repoId.getAttribute) repoId = repoId.getAttribute('data-node-id');
    _runnerRefreshPending = setTimeout(function() {
        _runnerRefreshPending = null;
        _runnerRefreshRepoNode(repoId);
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
    await _runnerRefreshRepoNode(_findRepoNodeIdByKey(key));
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
    await _runnerRefreshRepoNode(_findRepoNodeIdByKey(key));
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
async function runnerForceStop(ev, key) {
    if (ev) ev.stopPropagation();
    var btn = ev && ev.currentTarget;
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
        await _runnerRefreshRepoNode(_findRepoNodeIdByKey(key));
    }
}

/* ─── Code tab · open-with popover ─────────── */

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

document.addEventListener('click', function(ev) {
    // Clicking outside any .open-grp closes every open popover.
    if (ev.target && ev.target.closest && ev.target.closest('.open-grp')) return;
    gitClosePopovers();
}, true);
document.addEventListener('keydown', function(ev) {
    if (ev.key === 'Escape') gitClosePopovers();
});

function _findRepoNodeIdByKey(key) {
    var repoName = key.indexOf('--') >= 0 ? key.split('--')[0] : key;
    var esc = (window.CSS && CSS.escape) ? CSS.escape : function(s) { return s; };
    // The repo node id is "code/<group>/<repo>". We match by suffix.
    var nodes = document.querySelectorAll('.flat-group[data-node-id]');
    for (var i = 0; i < nodes.length; i++) {
        var id = nodes[i].getAttribute('data-node-id');
        if (id && id.endsWith('/' + repoName)) return id;
    }
    return null;
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

// Hook runner reattachment into the existing refresh paths. Patch
// _reloadInPlace and reloadNode just after their definitions so every
// DOM swap leads into a viewer sweep without scattering calls across
// call sites.
(function() {
    var origReloadInPlace = window._reloadInPlace;
    if (typeof origReloadInPlace === 'function') {
        window._reloadInPlace = async function() {
            var ret = await origReloadInPlace.apply(this, arguments);
            try { runnerReattachAll(); } catch (e) {}
            return ret;
        };
    }
    var origReloadNode = window.reloadNode;
    if (typeof origReloadNode === 'function') {
        window.reloadNode = async function() {
            var ret = await origReloadNode.apply(this, arguments);
            try { runnerReattachAll(); } catch (e) {}
            return ret;
        };
    }
})();

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

// Re-export the externally-called surface so Jinja-rendered onclick
// handlers, Python-rendered HTML, and the CM6 mount trailer (cm6-mount.js)
// can find these functions on window — identical to the global visibility
// the inline <script> block used to provide. Functions listed in the
// original spec are all declared above. Additional entries
// (openNotePreview, addStep, removeStep, cycle, pickPriority,
// createNoteFor, createNotesSubdir, openFolder, openConfigModal,
// openAboutModal, closeAboutModal, closeConfigModal, closeNewItemModal,
// closeNotePreview, toggleTheme, toggleTerminal, termNewTab,
// termNewLauncherTab, switchTab, switchSubtab, switchConfigTab,
// refreshAll, setNoteMode, noteSearchStep, noteSearchClose, saveEdit,
// noteNavBack, jumpToProject, _openHistoryHit, _noteReconcileDismiss,
// _noteReconcileReload) were added after grepping src/condash/render.py,
// src/condash/templates/*.j2, and the residual markup in dashboard.html
// for onclick="<name>(" occurrences.
Object.assign(window, {
    toggleCard, togglePriMenu, uploadToNotes, workOn, toggleSection,
    openInTerminal, startEditText, stepPointerDown, openDeliverable,
    startRenameNote, runnerStart, runnerStop, runnerSwitch,
    runnerForceStop,
    runnerToggleCollapse, runnerJump, runnerPopout,
    runnerStopInline, gitToggleOpenPopover, gitClosePopovers,
    updateProgress, _syncModeControls,
    openNotePreview, addStep, removeStep, cycle, pickPriority,
    createNoteFor, createNotesSubdir, openFolder,
    openConfigModal, openNewItemModal, openAboutModal,
    closeConfigModal, closeNewItemModal, closeAboutModal, closeNotePreview,
    toggleTheme, toggleTerminal, termNewTab, termNewLauncherTab,
    termDragStart, termSplitStart,
    switchTab, switchSubtab, switchConfigTab, refreshAll, setNoteMode,
    noteSearchStep, noteSearchClose, noteSearchRun, saveEdit, noteNavBack,
    openPath,
    filterHistory, filterKnowledge,
    saveConfig, submitNewItem, _setDirty,
    jumpToProject, _openHistoryHit,
    _noteReconcileDismiss, _noteReconcileReload,
});

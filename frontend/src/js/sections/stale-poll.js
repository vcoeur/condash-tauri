/* Stale-detection polling (localized, per-node).

   /check-updates returns a {node_id: hash} map covering every card,
   group, directory, and repo node in the three tabs. We keep the
   previous map as a baseline and, each poll, compute the set of dirty
   ids (differ / added / removed). From that set we drive per-tab
   staleness dots (other tabs) and auto-reload of the active tab.

   Node ids are slash-separated; ancestors are derived by trimming
   segments from the right.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 3 of
   conception/projects/2026-04-23-condash-frontend-extraction).

   The five module-level stale bindings (_nodeBaseline, _dirtyNodes,
   _itemsStale, _gitStale, _knowledgeStale) are exposed as a single
   `staleState` object — same trick as termState + reloadState — so
   callers in dashboard-main.js can write `staleState.dirtyNodes = new
   Set()` without the ESM live-binding limit on reassigning
   `var`/`let` exports.

   reloadNode + refreshAll live here too: both are primarily about
   reconciling the baseline + dirty set after a DOM swap, and both are
   imported by other sections that used to pull them out of
   dashboard-main.js. */

import { _activeTab, _activeSubtab, _reloadInPlace, _applySubtab } from '../dashboard-main.js';
import { reloadState } from './reload-guards.js';
import { _refreshShadowCache, _clearShadowCache } from './shadow-cache.js';
import { _supportsFragmentFetch } from './local-subtree-reload.js';
import { focusSafeSwap } from './dom-swap.js';
import { restoreNotesTreeState } from './notes-tree-state.js';
import { firePostReloadHooks } from './reload-hooks.js';

const staleState = {
    nodeBaseline: null,     // Object id → hash (null until first poll)
    dirtyNodes: new Set(),  // ids whose current hash != baseline, or present on only one side
    itemsStale: false,
    gitStale: false,
    knowledgeStale: false,
};

function _deriveLegacyFlags() {
    // Coarse flags the existing tab-switch / mutation code still reads.
    var items = false, git = false, knowledge = false;
    staleState.dirtyNodes.forEach(function(id) {
        if (id === 'projects' || id.indexOf('projects/') === 0) items = true;
        else if (id === 'code' || id.indexOf('code/') === 0) git = true;
        else if (id === 'knowledge' || id.indexOf('knowledge/') === 0) knowledge = true;
    });
    staleState.itemsStale = items;
    staleState.gitStale = git;
    staleState.knowledgeStale = knowledge;
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
        projects: staleState.itemsStale,
        code: staleState.gitStale,
        knowledge: staleState.knowledgeStale,
        history: staleState.itemsStale,
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
        if (staleState.nodeBaseline === null) {
            staleState.nodeBaseline = current;
        } else {
            // Once a node is marked dirty, it stays dirty until a local or
            // global reload updates the baseline — so the user can see there
            // was a change even if they weren't on the tab when it happened.
            var fresh = _diffNodes(staleState.nodeBaseline, current);
            fresh.forEach(function(id) { staleState.dirtyNodes.add(id); });
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

function _tabForNodeId(id) {
    if (id === 'projects' || id.indexOf('projects/') === 0) return 'projects';
    if (id === 'code' || id.indexOf('code/') === 0) return 'code';
    if (id === 'knowledge' || id.indexOf('knowledge/') === 0) return 'knowledge';
    return null;
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
        staleState.nodeBaseline = data.nodes || {};
        staleState.dirtyNodes = new Set();
        _renderStale();
    } catch (e) {}
}

/* Hard refresh — last-resort escape hatch. Throws away every piece of
   client-side cached state (baseline, dirty set, shadow cache, pending
   reloads) and does a full `location.reload()` so the browser re-parses
   the page from scratch. Used when the soft in-place reload can't shake
   the UI out of a bad state — e.g. a project rendered in no column, or a
   stuck stale-dot on a tab. Tracked: condash#14. */
function refreshAll() {
    staleState.nodeBaseline = null;
    staleState.dirtyNodes = new Set();
    _clearShadowCache();
    reloadState.pendingNodes.clear();
    reloadState.pendingInPlace = false;
    // Force-invalidate the server-side items/knowledge caches before
    // reloading so the next GET / re-walks the tree from disk. Best
    // effort: reload unconditionally even if the POST errors, since
    // `location.reload()` is also the user-requested action.
    fetch('/rescan', {method: 'POST'})
        .catch(function() {})
        .finally(function() { location.reload(); });
}

async function reloadNode(nodeId) {
    // Fall back to global reload for tab-level, group-level, and code nodes.
    if (!_supportsFragmentFetch(nodeId)) {
        _reloadInPlace();
        return;
    }
    try {
        // `no-cache` still returns the cached 304 body when the server
        // confirms it, so unchanged fragments reuse the local bytes.
        var res = await fetch('/fragment?id=' + encodeURIComponent(nodeId),
                              {cache: 'no-cache'});
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
            reloadState.pendingNodes.add(nodeId);
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
        // a diff, re-add the id to staleState.dirtyNodes, and strand the
        // dot on the tab forever. Updating the baseline first means a
        // racing poll sees baseline == current and short-circuits with
        // no diff. condash#14 (stale tab-dot after tab-away-and-back).
        await _refreshBaselineFor(nodeId);
        var prefix = nodeId + '/';
        var dropped = [];
        staleState.dirtyNodes.forEach(function(id) {
            if (id === nodeId || id.indexOf(prefix) === 0) dropped.push(id);
        });
        dropped.forEach(function(id) { staleState.dirtyNodes.delete(id); });
        // The server-rendered fragment is always visible (no .hidden class).
        // Re-apply the active subtab filter so a card whose priority falls
        // outside the current subtab slides back into its proper hidden
        // state — and one whose priority just entered the current subtab
        // becomes visible.
        if (_activeTab === 'projects') _applySubtab(_activeSubtab);
        _renderStale();
        firePostReloadHooks();
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
        if (!staleState.nodeBaseline) staleState.nodeBaseline = {};
        var prefix = nodeId + '/';
        for (var id in current) {
            if (id === nodeId || id.indexOf(prefix) === 0) {
                staleState.nodeBaseline[id] = current[id];
            }
        }
    } catch (e) {}
}

export {
    staleState,
    _deriveLegacyFlags, _renderStale, _diffNodes,
    _scheduleCheckUpdates, checkUpdates,
    _activeTabPrefix, _idInTab, _tabForNodeId,
    _autoReloadActiveTab, _minimalRoots,
    updateBaseline, _refreshBaselineFor,
    refreshAll, reloadNode,
};

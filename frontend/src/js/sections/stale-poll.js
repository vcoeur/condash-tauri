/* Per-node mutation reloads (the husk left after the htmx migration).

   Pre-migration this module owned a polling-based dirty-set: every
   SSE message → `/check-updates` → diff per-node fingerprints → drive
   stale-tab dots, auto-reload the active tab, and prefetch the others.
   Under htmx all of that has moved into `hx-trigger="sse:<tab>"` on
   each pane plus `htmx:sseOpen`/`sseError` on the reconnecting pill;
   the diff layer is no longer needed because every pane's content is
   live by construction.

   What survives here:

   - `reloadNode(nodeId)`  — fragment-fetch + `focusSafeSwap` of one
     subtree (a project card or a knowledge group). Called explicitly
     after step / priority / note mutations to repaint just the affected
     card without waiting for the watcher → SSE round-trip. Falls back
     to `_reloadInPlace` for ids that the `/fragment` endpoint can't
     serve, mirroring the original.
   - `refreshAll()`        — the hard-refresh button. Invalidates the
     server-side caches via `/rescan` and does a real `location.reload`.
   - `updateBaseline()`    — kept as a no-op stub. Old call sites in
     `steps.js` invoked it after a successful mutation to "reset the
     dirty baseline so the next /check-updates poll doesn't re-flag the
     same node"; with the polling layer gone there's nothing to reset,
     but leaving the symbol means we don't have to chase those call
     sites in this PR.

   The previously-exported `staleState`, `checkUpdates`,
   `_scheduleCheckUpdates`, `_renderStale`, `_deriveLegacyFlags`,
   `_autoReloadActiveTab`, `_idInTab`, `_tabForNodeId`,
   `_minimalRoots` are gone — htmx + per-pane fragments cover their
   work, and importing-but-not-calling them in dashboard-main is no
   longer required. */

import { _activeTab, _activeSubtab, _reloadInPlace, _applySubtab } from '../dashboard-main.js';
import { reloadState } from './reload-guards.js';
import { _supportsFragmentFetch } from './local-subtree-reload.js';
import { focusSafeSwap } from './dom-swap.js';
import { restoreNotesTreeState } from './notes-tree-state.js';
import { firePostReloadHooks } from './reload-hooks.js';

/* No-op now — see header. Kept so steps.js can keep calling it
   without an import-graph chase in this PR. */
function updateBaseline() {}

/* Hard refresh — last-resort escape hatch. Invalidates the
   server-side items/knowledge caches via /rescan, then does a real
   `location.reload()` so the browser re-parses the page from scratch.
   Used when SSE-driven refresh + reloadNode haven't recovered the UI
   from a bad state. Tracked: condash#14. */
function refreshAll() {
    reloadState.pendingNodes.clear();
    reloadState.pendingInPlace = false;
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

        // Preserve whatever expand state the user had on a card across
        // the swap — the server always re-renders cards collapsed.
        var wasExpanded = existing.classList.contains('card')
            && !existing.classList.contains('collapsed');

        var result = focusSafeSwap(existing, fresh);
        if (result.skipped) {
            // Guard tripped (runner live, or note modal dirty). Park
            // the request; _flushPendingReloads replays it when the
            // guard clears.
            reloadState.pendingNodes.add(nodeId);
            return;
        }
        if (wasExpanded && fresh.classList && fresh.classList.contains('card')) {
            fresh.classList.remove('collapsed');
        }
        restoreNotesTreeState();
        // htmx attaches its triggers + SSE wiring on element processing;
        // a plain `replaceWith` doesn't fire the htmx MutationObserver,
        // so process the swapped subtree explicitly.
        if (window.htmx) window.htmx.process(fresh);
        if (_activeTab === 'projects') _applySubtab(_activeSubtab);
        firePostReloadHooks();
    } catch (e) {
        _reloadInPlace();
    }
}

export { reloadNode, refreshAll, updateBaseline };

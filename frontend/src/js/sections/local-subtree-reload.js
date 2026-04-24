/* Local subtree reload.

   Click on a stale marker. For node ids the server knows how to
   fragment (project card, knowledge card, knowledge directory) we
   fetch just that fragment and replace the matching element in place,
   preserving any <details> open-state inside it. For everything else
   (groups, tabs, code nodes) the fragment endpoint returns 404 and we
   fall back to the global _reloadInPlace. Either way the dirty-set
   entries covered by the reload are dropped and the baseline is
   refreshed for those entries.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 of
   conception/projects/2026-04-23-condash-frontend-extraction). Three
   pure helpers — no cross-region state — so no imports, no side
   effects. Callers live in the stale-poll + dom-swap + reloadNode
   paths and reach in via function-body imports. */

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

export {
    _supportsFragmentFetch,
    _captureDetailsOpenState,
    _restoreDetailsOpenState,
};

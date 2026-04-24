/* Shadow pre-reload cache (Phase 4).

   When staleness lands on an inactive tab, kick off a background fetch
   of the dashboard HTML. On the user's next tab click that would have
   triggered a live _reloadInPlace, the cached HTML is applied instead,
   so the switch feels instant. The cache is a single entry because `/`
   returns the whole app — any tab's fresh content is already included.

   Extracted from dashboard-main.js on 2026-04-24 (P-08 of
   conception/projects/2026-04-23-condash-frontend-extraction). No
   cross-module references — both callers live in other regions that
   reach in via function-body calls (_consumeShadowCache in Tabs &
   Cards, _refreshShadowCache in the SSE region). */

var _shadowCache = null;  // {html, at} | {inflight: true} | null

async function _refreshShadowCache() {
    if (_shadowCache && _shadowCache.inflight) return;
    _shadowCache = {inflight: true};
    try {
        var res = await fetch('/', {cache: 'no-store'});
        if (!res.ok) { _shadowCache = null; return; }
        var html = await res.text();
        _shadowCache = {html: html, at: Date.now()};
    } catch (e) {
        _shadowCache = null;
    }
}

function _consumeShadowCache() {
    if (!_shadowCache || _shadowCache.inflight || !_shadowCache.html) return null;
    var html = _shadowCache.html;
    _shadowCache = null;
    return html;
}

export { _refreshShadowCache, _consumeShadowCache };

/* Hard-refresh button — last-resort escape hatch when SSE-driven
   per-pane refresh hasn't recovered the UI from a bad state. POSTs
   /rescan to invalidate the items / knowledge caches, then does a real
   `location.reload()` so the browser re-parses the page. */

function refreshAll() {
    fetch('/rescan', {method: 'POST'})
        .catch(function() {})
        .finally(function() { location.reload(); });
}

export { refreshAll };

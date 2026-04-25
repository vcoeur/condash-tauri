/* SSE side-effect bridge.

   The dashboard SSE stream (`/events`) is now opened by htmx — the
   `sse-connect="/events"` attribute on `<body>` and the SSE extension
   loaded in `dashboard.html`. Per-pane `hx-trigger="sse:<tab>"`
   listeners drive the per-tab fragment refreshes directly.

   What's left for this module is the connection-lifecycle UI plus the
   "any disk change might affect the open note modal" reconcile pass.
   We hang both off the htmx SSE events:

   - `htmx:sseOpen`    → hide the reconnecting pill
   - `htmx:sseError`   → show the reconnecting pill
   - `htmx:sseClose`   → show the reconnecting pill
   - `htmx:sseMessage` → run `_reconcileNoteModal` so the open-note
                         modal refreshes if its underlying file just
                         changed on disk.

   This replaces the hand-rolled EventSource lifecycle that used to
   live here (own EventSource, exponential-backoff reconnect, separate
   addEventListener per tab name, dispatch into stale-poll's
   `_scheduleCheckUpdates`) — htmx's extension owns the connection +
   retry now, and per-tab refreshes go through `hx-trigger="sse:<tab>"`
   directly without round-tripping through stale-poll. The export
   shape (`initSseSideEffects`) is unchanged so `dashboard-main.js`
   doesn't need to know. */

import { _reconcileNoteModal } from './note-reconcile.js';

function _setReconnecting(on) {
    var pill = document.getElementById('reconnecting-pill');
    if (!pill) return;
    if (on) pill.removeAttribute('hidden');
    else pill.setAttribute('hidden', '');
}

function initSseSideEffects() {
    document.body.addEventListener('htmx:sseOpen', function() {
        _setReconnecting(false);
    });
    document.body.addEventListener('htmx:sseError', function() {
        _setReconnecting(true);
    });
    document.body.addEventListener('htmx:sseClose', function() {
        _setReconnecting(true);
    });
    document.body.addEventListener('htmx:sseMessage', function() {
        _reconcileNoteModal();
    });
}

export { initSseSideEffects };

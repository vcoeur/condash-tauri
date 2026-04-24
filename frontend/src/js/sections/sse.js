/* SSE event stream. Every event from /events triggers a reconcile call
   to /check-updates; the real dirty-set computation lives in
   stale-poll.js. On drop, _setReconnecting(true) surfaces the pill and
   an exponential-backoff retry loop tries to reopen. */

import { checkUpdates, _scheduleCheckUpdates } from './stale-poll.js';
import { _reconcileNoteModal } from './note-reconcile.js';

const sseState = {
    eventSource: null,
    reconnectTimer: null,
    reconnectDelay: 1000,
};

function _startEventStream() {
    if (typeof EventSource !== 'function') return;  // no push, stick with boot checkUpdates
    try {
        sseState.eventSource = new EventSource('/events');
    } catch (e) {
        _setReconnecting(true);
        _scheduleEventReconnect();
        return;
    }
    sseState.eventSource.addEventListener('hello', function() {
        _setReconnecting(false);
        sseState.reconnectDelay = 1000;
        // Reconcile: the stream may have missed changes during the
        // gap. checkUpdates diffs fingerprints and picks them up.
        checkUpdates();
    });
    sseState.eventSource.addEventListener('ping', function() { /* keepalive */ });
    sseState.eventSource.onmessage = function(ev) {
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
    sseState.eventSource.onerror = function() {
        _setReconnecting(true);
        try { sseState.eventSource.close(); } catch (e) {}
        sseState.eventSource = null;
        _scheduleEventReconnect();
    };
}

function _scheduleEventReconnect() {
    if (sseState.reconnectTimer) return;
    sseState.reconnectTimer = setTimeout(function() {
        sseState.reconnectTimer = null;
        sseState.reconnectDelay = Math.min(sseState.reconnectDelay * 2, 30000);
        _startEventStream();
    }, sseState.reconnectDelay);
}

function _setReconnecting(on) {
    var pill = document.getElementById('reconnecting-pill');
    if (!pill) return;
    if (on) pill.removeAttribute('hidden');
    else pill.setAttribute('hidden', '');
}

/* Register the stream. Called from dashboard-main.js's module-init
   trailer so we know stale-poll.js + the note-reconcile function
   dashboard-main.js still owns have finished evaluating. */
function initSseSideEffects() {
    _startEventStream();
}

export {
    sseState,
    _startEventStream, _scheduleEventReconnect, _setReconnecting,
    initSseSideEffects,
};

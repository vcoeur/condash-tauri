/* SSE event stream (Phase 6).

   Replaces the 5s polling loop. Every event from /events triggers a
   reconcile call to /check-updates; the real dirty-set computation
   lives in stale-poll.js, unchanged. On drop, _setReconnecting(true)
   surfaces the pill and an exponential-backoff retry loop tries to
   reopen.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 3 of
   conception/projects/2026-04-23-condash-frontend-extraction).

   Module-level bindings (_eventSource, reconnect timer/delay,
   configReloadTimer) are grouped under `sseState` — same pattern as
   termState / reloadState / staleState — so any future importer that
   needs to inspect the stream state doesn't hit the ESM live-binding
   limit on reassigning `var` exports. No current caller does, but the
   grouping keeps the shape consistent with the other extracted
   regions. */

import { _populateYamlEditor, _getDirtyYamlFile, openConfigModal, _reloadInPlace, _reconcileNoteModal } from '../dashboard-main.js';
import { _loadTermShortcuts } from './tab-drag.js';
import { checkUpdates, _scheduleCheckUpdates } from './stale-poll.js';

const sseState = {
    eventSource: null,
    reconnectTimer: null,
    reconnectDelay: 1000,
    configReloadTimer: null,
};

/* Live YAML reload: dispatched from the SSE onmessage handler when the
   filesystem watcher notices an external edit to repositories.yml or
   preferences.yml. The server has already rebuilt its RenderCtx by
   the time this fires, so the client's job is just to:
     (a) refresh the open config modal's form in place, if any, and
     (b) rebuild the dashboard body so server-rendered bits (repo strip,
         open-with buttons, terminal shortcut specs) pick up the change.
   Self-writes from POST /config are suppressed server-side, so this
   only fires on external edits — no infinite loop.

   Currently unreachable: config/*.yml watching was removed server-side
   so no SSE message carries a config-change payload anymore, and the
   onmessage handler below no longer dispatches to this function. Kept
   here for topical completeness; a future simplification PR can remove
   it outright along with its only caller (long since gone). */
function _onConfigChanged(payload) {
    if (sseState.configReloadTimer) clearTimeout(sseState.configReloadTimer);
    sseState.configReloadTimer = setTimeout(async function() {
        sseState.configReloadTimer = null;
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
    _onConfigChanged, _startEventStream, _scheduleEventReconnect, _setReconnecting,
    initSseSideEffects,
};

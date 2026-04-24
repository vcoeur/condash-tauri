/* Reload guards (Phase 2).

   The two production landmines before the overhaul: a fragment swap
   while a runner's WebSocket is live silently kills the build; a
   _reloadInPlace while the note modal has unsaved edits silently
   discards them. Both are now caught by focusSafeSwap's default
   skipIf — the swap is refused, the dirty state is preserved, and a
   retry is queued for when the guard clears.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 of
   conception/projects/2026-04-23-condash-frontend-extraction).

   The pending-reload bookkeeping was previously two module-top-level
   bindings (_pendingReloadNodes, _pendingReloadInPlace) mutated from
   three other regions (tab switch, refreshAll, reloadNode). ESM live
   bindings don't permit importer-side reassignment of `let`/`var`
   exports, so we expose the state as a single `reloadState` object —
   the same trick P-07's design note §D1 used for termState — so
   callers can write `reloadState.pendingInPlace = true` without
   rebinding the import. */

import { _noteModal, _reloadInPlace, reloadNode, _runnerViewers } from '../dashboard-main.js';

const reloadState = {
    pendingNodes: new Set(),
    pendingInPlace: false,
};

function _noteModalDirty() {
    return !!(_noteModal && _noteModal.dirty);
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

function _flushPendingReloads() {
    if (_noteModalDirty()) return;  // still blocked; caller will re-flush
    if (reloadState.pendingInPlace) {
        reloadState.pendingInPlace = false;
        reloadState.pendingNodes.clear();  // superseded by the global rebuild
        _reloadInPlace();
        return;
    }
    var retry = Array.from(reloadState.pendingNodes);
    reloadState.pendingNodes.clear();
    retry.forEach(function(id) {
        // Runner-active guard for this specific node is re-checked by
        // focusSafeSwap's skipIf — any still-blocked entries land back
        // in reloadState.pendingNodes via reloadNode's skipped-branch.
        reloadNode(id);
    });
}

export {
    reloadState,
    _noteModalDirty, _runnerActiveIn,
    _defaultReloadSkipIf, _flushPendingReloads,
};

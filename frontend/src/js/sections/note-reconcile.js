/* Note modal reconcile (Phase 7).

   When /events signals a filesystem change, any open note may now
   diverge from its on-disk content. `_reconcileNoteModal` compares the
   loaded mtime with the live mtime and acts by buffer state:
     - clean buffer → silently reload text + render, restoring selection.
     - dirty buffer → reveal the banner and leave the buffer alone until
       the user picks "Keep my edits" or "Reload from disk".
   The banner dismissal is sticky until a new external change is
   detected (so the user who keeps editing isn't re-nagged).

   `reconcileState.suppressedUntilMtime` is reset from note-preview.js
   whenever a note is opened or closed — same live-binding-safe pattern
   as termState / reloadState / staleState / sseState.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 4 of
   conception/projects/2026-04-23-condash-frontend-extraction). */

import { _noteModal, _setDirty, _reloadNotePreview } from './note-preview.js';
import { _captureActiveBuffer } from './note-mode.js';
import { _cm } from './cm6-mount.js';

const reconcileState = {
    suppressedUntilMtime: null,
};

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
        if (reconcileState.suppressedUntilMtime != null
            && fresh <= reconcileState.suppressedUntilMtime) {
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
    reconcileState.suppressedUntilMtime = Number(_noteModal.mtime) || 0;
    _noteShowExternalBanner(false);
}

async function _noteReconcileReload() {
    try {
        var res = await fetch('/note-raw?path=' + encodeURIComponent(_noteModal.path));
        if (!res.ok) return;
        var data = await res.json();
        await _noteSilentReload(data);
        _noteShowExternalBanner(false);
        reconcileState.suppressedUntilMtime = null;
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

export {
    reconcileState,
    _reconcileNoteModal,
    _noteShowExternalBanner,
    _noteReconcileDismiss,
    _noteReconcileReload,
};

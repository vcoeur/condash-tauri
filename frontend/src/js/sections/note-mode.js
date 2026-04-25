/* Note modal mode management — view / cm / plain.

   Three sibling panes (view, cm, plain) live inside #note-modal-body;
   the modal's `data-mode` attribute drives CSS visibility. `setNoteMode`
   transfers the canonical buffer between the two edit modes on switch
   so edits survive toggling, then updates the chrome (save button,
   toggle state). `saveEdit` POSTs to /note with expected_mtime so a
   stale editor can't silently clobber an out-of-band change — the
   server returns 409 and we surface the error banner.

   Also owns `createNoteFor` (create + drop into edit mode) and
   `startRenameNote` (double-click-to-rename on the modal title) — both
   of them chain into note-preview via `openNotePreview` / `_noteModal`,
   but they're editing-flow concerns, not view concerns.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 4 of
   conception/projects/2026-04-23-condash-frontend-extraction). */

import { _noteModal, _setDirty, openNotePreview, _reloadNotePreview } from './note-preview.js';
import { _cm, _mountCm } from './cm6-mount.js';

function _setNoteModeAttr(inner, mode) {
    inner.setAttribute('data-mode', mode);
}

function _hideSaveError() {
    var err = document.getElementById('note-edit-error');
    if (err) { err.textContent = ''; err.classList.remove('visible'); }
}

function _showSaveError(msg) {
    var err = document.getElementById('note-edit-error');
    if (!err) return;
    err.textContent = msg;
    err.classList.add('visible');
}

/* Save button is enabled only when there are unsaved edits, so after a
   successful save the user gets a clear "saved" signal and can't click
   again redundantly. Disabled when clean, non-editable, or viewing.
   Called from _setDirty (preview) and _syncModeControls (here). */
function _syncSaveButton() {
    var btn = document.getElementById('note-save-btn');
    if (!btn) return;
    var inner = document.getElementById('note-modal-inner');
    var mode = inner ? inner.getAttribute('data-mode') : 'view';
    var editing = mode === 'cm' || mode === 'plain';
    btn.disabled = !editing || !_noteModal.editable || !_noteModal.dirty;
    btn.title = btn.disabled && editing && _noteModal.editable
        ? 'No unsaved changes' : 'Save (Ctrl+S)';
}

/* Update the mode toggle (disable edit buttons when the file is not
   editable) and show/hide the Save button per mode. */
function _syncModeControls() {
    var inner = document.getElementById('note-modal-inner');
    var mode = inner ? inner.getAttribute('data-mode') : 'view';
    var toggle = document.getElementById('note-mode-toggle');
    var saveBtn = document.getElementById('note-save-btn');
    if (toggle) {
        toggle.querySelector('[data-mode="cm"]').disabled =
            !_noteModal.editable || !window.__cm6;
        toggle.querySelector('[data-mode="plain"]').disabled = !_noteModal.editable;
        if (!window.__cm6) {
            toggle.querySelector('[data-mode="cm"]').title =
                'Loading editor…';
        } else if (!_noteModal.editable) {
            toggle.querySelector('[data-mode="cm"]').title =
                'This file is not editable (binary/preview-only)';
        } else {
            toggle.querySelector('[data-mode="cm"]').title =
                'Edit with syntax highlighting (Ctrl+E)';
        }
    }
    if (saveBtn) saveBtn.style.display = (mode === 'cm' || mode === 'plain') ? '' : 'none';
    _syncSaveButton();
}

/* Pull the active pane's buffer back into _noteModal.text so a mode
   switch starts the next pane from the same content. */
function _captureActiveBuffer() {
    var inner = document.getElementById('note-modal-inner');
    var mode = inner.getAttribute('data-mode');
    if (mode === 'cm' && _cm.view) {
        _noteModal.text = _cm.view.state.doc.toString();
    } else if (mode === 'plain') {
        var ta = document.getElementById('note-edit-textarea');
        if (ta) _noteModal.text = ta.value;
    }
}

/* Hydrate a pane from _noteModal.text so the user sees their latest
   edits after a switch. No-op for view mode — view reflects last-save. */
function _hydratePane(mode) {
    if (mode === 'plain') {
        var ta = document.getElementById('note-edit-textarea');
        if (!ta) return;
        if (ta.value !== _noteModal.text) ta.value = _noteModal.text;
        ta.setSelectionRange(0, 0);
        ta.scrollTop = 0;
    } else if (mode === 'cm') {
        if (!_cm.view) { _mountCm(); return; }
        var cur = _cm.view.state.doc.toString();
        if (cur !== _noteModal.text) {
            _cm.view.dispatch({
                changes: {from: 0, to: cur.length, insert: _noteModal.text},
            });
        }
        _cm.view.dispatch({selection: {anchor: 0}});
        _cm.view.scrollDOM.scrollTop = 0;
    } else if (mode === 'view') {
        var pane = document.getElementById('note-pane-view');
        if (pane) pane.scrollTop = 0;
    }
}

function setNoteMode(next) {
    if (next !== 'view' && next !== 'cm' && next !== 'plain') return;
    if ((next === 'cm' || next === 'plain') && !_noteModal.editable) return;
    if (next === 'cm' && !window.__cm6) return;
    var inner = document.getElementById('note-modal-inner');
    var prev = inner.getAttribute('data-mode');
    if (prev === next) return;
    if (prev === 'cm' || prev === 'plain') _captureActiveBuffer();
    _setNoteModeAttr(inner, next);
    if (next === 'cm' || next === 'plain') _noteModal.lastEditMode = next;
    _hideSaveError();
    _hydratePane(next);
    _syncModeControls();
    if (next === 'cm' && _cm.view) { setTimeout(function() { _cm.view.focus(); }, 0); }
    else if (next === 'plain') {
        var ta = document.getElementById('note-edit-textarea');
        if (ta) setTimeout(function() { ta.focus(); }, 0);
    }
}

async function saveEdit() {
    var inner = document.getElementById('note-modal-inner');
    var mode = inner.getAttribute('data-mode');
    if (mode !== 'cm' && mode !== 'plain') return;
    if (!_noteModal.path) return;
    _captureActiveBuffer();
    _hideSaveError();
    try {
        var res = await fetch('/note', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                path: _noteModal.path,
                content: _noteModal.text,
                expected_mtime: _noteModal.mtime,
            }),
        });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok) {
            if (res.status === 409 && data.mtime) _noteModal.mtime = Number(data.mtime);
            _showSaveError(data.reason || data.error || ('HTTP ' + res.status));
            return;
        }
        if (data.mtime != null) _noteModal.mtime = Number(data.mtime);
        _setDirty(false);
        // Refresh the view pane from the server render so it stays
        // aligned with what's now on disk.
        var name = document.getElementById('note-modal-title').textContent;
        await _reloadNotePreview(_noteModal.path, name);
    } catch (e) {
        _showSaveError('Save failed: ' + e);
    }
}

/* Prompt for a filename and POST /note/create. ``subRelToNotes`` is the
   target subdirectory relative to ``<item>/notes/`` ("" for notes/ root)
   so the per-folder + buttons can drop the file into the folder whose
   summary they live on. */
async function createNoteFor(readmePath, subRelToNotes) {
    var raw = prompt('New note filename (e.g. plan.md, decision.txt):', 'new-note.md');
    if (!raw) return;
    raw = raw.trim();
    if (!raw) return;
    if (raw.indexOf('.') < 0) raw = raw + '.md';
    try {
        var res = await fetch('/note/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                item_readme: readmePath,
                filename: raw,
                subdir: subRelToNotes || '',
            }),
        });
        var data = await res.json().catch(function(){return {};});
        if (!res.ok) {
            alert('Could not create note: ' + (data.reason || data.error || ('HTTP ' + res.status)));
            return;
        }
        await openNotePreview(data.path, raw);
        // Drop straight into the preferred edit mode for the new file.
        if (_noteModal.editable) {
            setNoteMode(window.__cm6 ? 'cm' : 'plain');
        }
    } catch (e) {
        alert('Network error: ' + e);
    }
}

/* Double-click the modal title to rename the current note. Only files
   under <item>/notes/** are renamable; READMEs and knowledge/* are
   left alone (server returns 400 for those so the UI fails loud). The
   extension stays fixed — users type a stem, server re-appends the
   suffix. */
var _NOTES_RENAMEABLE_RE = /^projects\/\d{4}-\d{2}\/\d{4}-\d{2}-\d{2}-[\w.\-]+\/notes\//;

function startRenameNote() {
    var titleEl = document.getElementById('note-modal-title');
    var path = _noteModal.path || '';
    if (!_NOTES_RENAMEABLE_RE.test(path)) return;
    if (titleEl.querySelector('.note-rename-input')) return;  // already editing
    var filename = path.substring(path.lastIndexOf('/') + 1);
    var dotIdx = filename.lastIndexOf('.');
    var stem = dotIdx > 0 ? filename.substring(0, dotIdx) : filename;
    var ext = dotIdx > 0 ? filename.substring(dotIdx) : '';
    var originalText = titleEl.textContent;
    var restored = false;
    var restore = function() {
        if (restored) return;
        restored = true;
        titleEl.textContent = originalText;
    };
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'note-rename-input';
    input.value = stem;
    var extEl = document.createElement('span');
    extEl.className = 'note-rename-ext';
    extEl.textContent = ext;
    titleEl.textContent = '';
    titleEl.appendChild(input);
    titleEl.appendChild(extEl);
    input.focus();
    input.select();
    var commit = function() {
        var newStem = input.value.trim();
        if (!newStem || newStem === stem) { restore(); return; }
        fetch('/note/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: path, new_stem: newStem}),
        }).then(function(r) {
            return r.json().then(function(data) { return {ok: r.ok, data: data}; });
        }).then(function(result) {
            if (!result.ok || !result.data.ok) {
                alert('Rename failed: ' + (result.data.error || result.data.reason || 'unknown'));
                restore();
                return;
            }
            _noteModal.path = result.data.path;
            if (result.data.mtime != null) _noteModal.mtime = Number(result.data.mtime);
            var newName = newStem + ext;
            titleEl.textContent = newName;
            restored = true;  // keep the new value
        }).catch(function(err) {
            alert('Rename failed: ' + err);
            restore();
        });
    };
    input.onkeydown = function(ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
        else if (ev.key === 'Escape') { ev.preventDefault(); restore(); }
        ev.stopPropagation();
    };
    input.onblur = commit;
    input.onclick = function(ev) { ev.stopPropagation(); };
}

/* beforeunload guard for unsaved note edits. The `returnValue` dance is
   required for legacy cross-browser support; modern browsers ignore the
   string and show their own generic confirm. Registered from here
   because the guard hinges on the dirty flag which this module owns via
   _captureActiveBuffer. */
function initNoteModeSideEffects() {
    window.addEventListener('beforeunload', function(e) {
        var modal = document.getElementById('note-modal');
        if (!modal || !modal.classList.contains('open')) return;
        if (_noteModal.editable) _captureActiveBuffer();
        if (!_noteModal.dirty) return;
        e.preventDefault();
        e.returnValue = '';
        return '';
    });
    document.addEventListener('condash:cm6-ready', _syncModeControls);
}

export {
    _setNoteModeAttr, _hideSaveError, _showSaveError,
    _syncSaveButton, _syncModeControls,
    _captureActiveBuffer, _hydratePane,
    setNoteMode, saveEdit,
    createNoteFor,
    _NOTES_RENAMEABLE_RE, startRenameNote,
    initNoteModeSideEffects,
};

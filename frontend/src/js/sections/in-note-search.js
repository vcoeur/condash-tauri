/* In-note search (Ctrl+F inside the note modal).

   Walks .note-modal-body's text nodes, wraps each case-insensitive
   substring match in <mark class="note-match">, and lets the user step
   through them with Enter / Shift+Enter / F3. Scoped to the preview
   view — Ctrl+F inside the edit textarea falls through so the browser's
   native behaviour still works there. When the view pane hosts a PDF
   (note.pdf via PDF.js), delegates to the viewer's own find API.

   Also owns the Ctrl+E mode-toggle shortcut because it's registered
   from the same capture-phase keydown listener and would double-bind
   if the two shortcuts lived in separate listeners.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 4 of
   conception/projects/2026-04-23-condash-frontend-extraction). */

import { _noteModal } from './note-preview.js';
import { setNoteMode } from './note-mode.js';

var _noteSearch = { matches: [], idx: -1 };

function _clearNoteMarks() {
    var pane = document.getElementById('note-pane-view');
    if (!pane) return;
    pane.querySelectorAll('mark.note-match').forEach(function(m) {
        var parent = m.parentNode;
        while (m.firstChild) parent.insertBefore(m.firstChild, m);
        parent.removeChild(m);
    });
    pane.normalize();
}

/* Return the PDF find API attached to a mounted .note-pdf-host inside
   the open note modal, or null. The PDF viewer's mount() exposes this
   at host.__pdfFind so the shared note-search-bar can drive it. */
function _notePdfFind() {
    var modal = document.getElementById('note-modal');
    if (!modal || !modal.classList.contains('open')) return null;
    var host = modal.querySelector('.note-pdf-host[data-mounted="1"]');
    return host && host.__pdfFind ? host.__pdfFind : null;
}

function _setSearchCount(state, q) {
    var countEl = document.getElementById('note-search-count');
    if (!countEl) return;
    if (!state || !state.matches.length) {
        countEl.textContent = q ? '0/0' : '';
    } else {
        countEl.textContent = (state.idx + 1) + '/' + state.matches.length;
    }
}

function noteSearchRun() {
    var input = document.getElementById('note-search-input');
    var q = input ? input.value : '';
    var countEl = document.getElementById('note-search-count');
    var pdfFind = _notePdfFind();
    if (pdfFind) {
        // Clear any stale view-pane marks and delegate to the PDF viewer.
        _clearNoteMarks();
        _noteSearch.matches = [];
        _noteSearch.idx = -1;
        pdfFind.run(q).then(function(state) { _setSearchCount(state, q); });
        return;
    }
    _clearNoteMarks();
    _noteSearch.matches = [];
    _noteSearch.idx = -1;
    if (!q) {
        if (countEl) countEl.textContent = '';
        return;
    }
    var pane = document.getElementById('note-pane-view');
    if (!pane) return;
    var qLow = q.toLowerCase();
    var qLen = q.length;
    // Collect text nodes first (the walker becomes unreliable once we
    // mutate the tree). Skip script/style just in case; the body is
    // server-rendered markdown but we don't assume.
    var walker = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT, {
        acceptNode: function(n) {
            var tag = n.parentNode && n.parentNode.nodeName;
            if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        }
    });
    var textNodes = [];
    var node;
    while ((node = walker.nextNode())) textNodes.push(node);
    textNodes.forEach(function(n) {
        var low = n.nodeValue.toLowerCase();
        // Iterate in reverse so splitText offsets earlier in the string
        // stay valid as we carve the node from right to left.
        var positions = [];
        var pos = 0;
        while ((pos = low.indexOf(qLow, pos)) !== -1) {
            positions.push(pos);
            pos += qLen;
        }
        for (var i = positions.length - 1; i >= 0; i--) {
            var start = positions[i];
            var matchNode = n.splitText(start);
            matchNode.splitText(qLen);
            var mark = document.createElement('mark');
            mark.className = 'note-match';
            matchNode.parentNode.replaceChild(mark, matchNode);
            mark.appendChild(matchNode);
            _noteSearch.matches.push(mark);
        }
    });
    // Sort matches into document order (per-node reverse iteration left
    // them reverse within each node, and textNodes was walked forward).
    _noteSearch.matches.sort(function(a, b) {
        var cmp = a.compareDocumentPosition(b);
        if (cmp & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
        if (cmp & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        return 0;
    });
    if (_noteSearch.matches.length) {
        _noteSearch.idx = 0;
        _noteSearch.matches[0].classList.add('active');
        _noteSearch.matches[0].scrollIntoView({block: 'center'});
    }
    if (countEl) {
        countEl.textContent = _noteSearch.matches.length
            ? (_noteSearch.idx + 1) + '/' + _noteSearch.matches.length
            : '0/0';
    }
}

function noteSearchStep(dir) {
    var pdfFind = _notePdfFind();
    if (pdfFind) {
        var state = pdfFind.step(dir);
        _setSearchCount(state, '');
        return;
    }
    var n = _noteSearch.matches.length;
    if (!n) return;
    if (_noteSearch.idx >= 0) {
        _noteSearch.matches[_noteSearch.idx].classList.remove('active');
    }
    _noteSearch.idx = (_noteSearch.idx + dir + n) % n;
    var m = _noteSearch.matches[_noteSearch.idx];
    m.classList.add('active');
    m.scrollIntoView({block: 'center'});
    var countEl = document.getElementById('note-search-count');
    if (countEl) countEl.textContent = (_noteSearch.idx + 1) + '/' + n;
}

function noteSearchOpen() {
    var bar = document.getElementById('note-search-bar');
    if (!bar) return;
    bar.hidden = false;
    var input = document.getElementById('note-search-input');
    if (input) { input.focus(); input.select(); }
    // If a query is already typed, re-run so marks come back after the
    // note was reloaded or the bar was reopened.
    if (input && input.value) noteSearchRun();
}

function noteSearchClose() {
    var pdfFind = _notePdfFind();
    if (pdfFind) pdfFind.close();
    var bar = document.getElementById('note-search-bar');
    if (bar) bar.hidden = true;
    _clearNoteMarks();
    _noteSearch.matches = [];
    _noteSearch.idx = -1;
    var input = document.getElementById('note-search-input');
    if (input) input.value = '';
    var countEl = document.getElementById('note-search-count');
    if (countEl) countEl.textContent = '';
}

/* Capture-phase keydown so this beats the existing Escape handler and
   any xterm/editor shortcuts that might swallow Ctrl+F elsewhere. Also
   hosts Ctrl+E (mode toggle) because it shares the modal-open gate. */
function initInNoteSearchSideEffects() {
    document.addEventListener('keydown', function(ev) {
        var modal = document.getElementById('note-modal');
        if (!modal || !modal.classList.contains('open')) return;
        var inner = document.getElementById('note-modal-inner');
        var mode = inner ? inner.getAttribute('data-mode') : 'view';
        var editing = mode === 'cm' || mode === 'plain';
        var isFindKey = (ev.ctrlKey || ev.metaKey) && !ev.altKey
            && (ev.key === 'f' || ev.key === 'F');
        if (isFindKey) {
            if (editing) return;  // let the edit panes keep native behaviour
            ev.preventDefault();
            ev.stopPropagation();
            noteSearchOpen();
            return;
        }
        // Ctrl+E toggles between view and the last-used edit mode.
        if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === 'e' || ev.key === 'E')) {
            if (!_noteModal.editable) return;
            ev.preventDefault();
            ev.stopPropagation();
            setNoteMode(mode === 'view' ? (_noteModal.lastEditMode || 'cm') : 'view');
            return;
        }
        var bar = document.getElementById('note-search-bar');
        if (!bar || bar.hidden) return;
        var activeInSearch = document.activeElement
            && document.activeElement.id === 'note-search-input';
        if (ev.key === 'Escape') {
            ev.preventDefault();
            ev.stopPropagation();
            noteSearchClose();
        } else if (ev.key === 'Enter' && activeInSearch) {
            ev.preventDefault();
            noteSearchStep(ev.shiftKey ? -1 : 1);
        } else if (ev.key === 'F3') {
            ev.preventDefault();
            noteSearchStep(ev.shiftKey ? -1 : 1);
        }
    }, true);
}

export {
    noteSearchRun, noteSearchStep, noteSearchOpen, noteSearchClose,
    initInNoteSearchSideEffects,
};

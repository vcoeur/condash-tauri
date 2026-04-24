/* Note preview modal — open / close / navigate + link wiring + server
   render mount (markdown, mermaid, PDF).

   Owner of the shared `_noteModal` state object and the `_noteNavStack`
   back-stack. The three sibling note-modal modules (note-mode.js,
   in-note-search.js, note-reconcile.js) all read/write `_noteModal`
   through this module — `_noteModal` is a plain object, so the ESM
   live-binding limit on reassigning `var`/`let` exports doesn't apply
   (no caller ever reassigns `_noteModal` itself, only its fields).

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 4 of
   conception/projects/2026-04-23-condash-frontend-extraction). */

import { _destroyCm } from './cm6-mount.js';
import { _flushPendingReloads } from './reload-guards.js';
import { _syncSaveButton, _captureActiveBuffer, _syncModeControls, _setNoteModeAttr, _hideSaveError } from './note-mode.js';
import { noteSearchClose } from './in-note-search.js';
import { reconcileState, _noteShowExternalBanner } from './note-reconcile.js';

function _renderMermaidIn(container) {
    if (!window.mermaid) return;
    var blocks = container.querySelectorAll('pre.mermaid, pre > code.language-mermaid');
    if (!blocks.length) return;
    var nodes = [];
    blocks.forEach(function(block) {
        var pre = block.tagName === 'PRE' ? block : block.parentElement;
        var code = pre.querySelector('code') || pre;
        var src = code.textContent;
        var div = document.createElement('div');
        div.className = 'mermaid';
        div.textContent = src;
        pre.replaceWith(div);
        nodes.push(div);
    });
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    try {
        window.mermaid.initialize({
            startOnLoad: false,
            theme: isDark ? 'dark' : 'default',
            securityLevel: 'strict',
        });
        window.mermaid.run({ nodes: nodes }).catch(function() {});
    } catch (e) {}
}

/* Mount the vendored PDF.js viewer on every .note-pdf-host inside the
   view pane. If the PDF.js ES module (at the bottom of dashboard-main.js)
   hasn't resolved yet, mark hosts pending — the module's ready-hook will
   flush them. Safe to call repeatedly; mount() no-ops on already-mounted
   hosts. */
function _mountPdfsIn(container) {
    if (!container) return;
    var hosts = container.querySelectorAll('.note-pdf-host');
    for (var i = 0; i < hosts.length; i++) {
        var host = hosts[i];
        if (host.dataset.mounted === '1') continue;
        if (window.__pdfjs && window.__pdfjs.ready) {
            window.__pdfjs.mount(host);
        } else if (window.__pdfjs && window.__pdfjs.error) {
            host.innerHTML = '<div class="pdf-error">PDF viewer failed to load.</div>';
        } else {
            host.dataset.pdfPending = '1';
            host.innerHTML = '<div class="pdf-loading">Loading PDF viewer…</div>';
        }
    }
}

/* Back-navigation stack. Every time a link inside the note modal opens
   a different note (wikilinks, relative .md links), the currently shown
   {path, name} is pushed before the replacement. The back button in the
   modal header pops one level. Cleared on close — this is an in-modal
   navigation history, not a persistent browser history. */
var _noteNavStack = [];

/* Notes open in three modes. The modal carries `data-mode` on its inner
   element (#note-modal-inner); three sibling panes inside #note-modal-body
   are hidden/shown by CSS. `_noteModal` tracks the state shared across
   panes so mode switches preserve user edits and mtime for the save
   contract. */
const _noteModal = {
    path: null,
    editable: false,     // false when kind is pdf/image/binary — edit modes disabled
    kind: null,          // from /note-raw
    mtime: null,
    renderedHtml: '',    // last server render shown in the view pane
    /* Canonical text shared between CM6 and the plain textarea. Updated
       whenever the user switches away from an edit mode so the other
       mode can start from the same buffer. Reset on open and on save. */
    text: '',
    /* Which edit mode was last active. Ctrl-E from view returns here. */
    lastEditMode: 'cm',
    /* Unsaved-changes flag. Set on every CM6/textarea edit, cleared on
       open and successful save. Drives the Save button's disabled state
       and the close/beforeunload confirms. */
    dirty: false,
};

/* Flip the dirty flag and refresh the Save button. Safe to call on every
   keystroke — the button toggle is the only DOM work. Also drains any
   reload requests that were parked because the modal was dirty. */
function _setDirty(value) {
    var next = !!value;
    if (_noteModal.dirty === next) return;
    _noteModal.dirty = next;
    _syncSaveButton();
    if (!next && typeof _flushPendingReloads === 'function') {
        _flushPendingReloads();
    }
}

async function openNotePreview(path, name) {
    var modal = document.getElementById('note-modal');
    var inner = document.getElementById('note-modal-inner');
    var title = document.getElementById('note-modal-title');
    var viewPane = document.getElementById('note-pane-view');
    var ta = document.getElementById('note-edit-textarea');
    // Reset any in-note search: matches point at DOM nodes we're about
    // to discard and the count would be stale against the new note.
    noteSearchClose();
    _destroyCm();
    title.textContent = name;
    _noteModal.path = path;
    _noteModal.editable = false;
    _noteModal.kind = null;
    _noteModal.mtime = null;
    _noteModal.text = '';
    _noteModal.renderedHtml = '';
    _noteModal.dirty = false;
    _noteShowExternalBanner(false);
    reconcileState.suppressedUntilMtime = null;
    ta.value = '';
    viewPane.innerHTML = '<p class="note-loading">Loading…</p>';
    _setNoteModeAttr(inner, 'view');
    _syncModeControls();
    _hideSaveError();
    modal.classList.add('open');
    // Kick off both fetches in parallel. /note returns HTML for the view
    // pane; /note-raw returns text+mtime+kind for the edit panes. The
    // raw fetch is best-effort: pdf/image kinds 4xx here and we leave
    // the edit modes disabled.
    var viewP = fetch('/note?path=' + encodeURIComponent(path)).then(function(res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
    });
    var rawP = fetch('/note-raw?path=' + encodeURIComponent(path)).then(function(res) {
        if (!res.ok) return null;
        return res.json();
    }).catch(function() { return null; });
    try {
        var html = await viewP;
        // Guard against late arrival for a different note (user opened
        // another before this one resolved).
        if (_noteModal.path !== path) return;
        viewPane.innerHTML = html;
        viewPane.scrollTop = 0;
        _noteModal.renderedHtml = html;
        _renderMermaidIn(viewPane);
        _wireNoteLinks(viewPane, path);
        _mountPdfsIn(viewPane);
    } catch (e) {
        if (_noteModal.path !== path) return;
        viewPane.innerHTML = '<p class="note-error">Failed to load note.</p>';
    }
    var raw = await rawP;
    if (_noteModal.path !== path) return;
    if (raw && typeof raw.content === 'string') {
        _noteModal.editable = true;
        _noteModal.kind = raw.kind || null;
        _noteModal.mtime = raw.mtime != null ? Number(raw.mtime) : null;
        _noteModal.text = raw.content;
        ta.value = raw.content;
    }
    _syncModeControls();
    _syncNoteBack();
}

/* Push the currently-shown note onto the back stack and open the target.
   Used by link handlers inside the note modal (wikilinks + internal .md).
   The button-driven "back" path calls openNotePreview without pushing so
   the stack only grows on forward navigation. */
async function _navigateToNote(path, name, anchor) {
    if (_noteModal.path) {
        var titleEl = document.getElementById('note-modal-title');
        var currentName = titleEl ? titleEl.textContent : _noteModal.path;
        _noteNavStack.push({path: _noteModal.path, name: currentName});
    }
    await openNotePreview(path, name);
    if (anchor) _scrollNoteToAnchor(anchor);
}

function _syncNoteBack() {
    var btn = document.getElementById('note-modal-back');
    if (!btn) return;
    if (_noteNavStack.length > 0) btn.removeAttribute('hidden');
    else btn.setAttribute('hidden', '');
}

async function noteNavBack() {
    if (_noteNavStack.length === 0) return;
    var entry = _noteNavStack.pop();
    await openNotePreview(entry.path, entry.name);
}

/* Resolve a path relative to `baseDir` — `baseDir/../foo` collapses to
   `foo`, absolute paths drop the leading slash so they are treated as
   conception-tree relative. */
function _resolveNotePath(baseDir, rel) {
    if (rel.startsWith('/')) rel = rel.replace(/^\/+/, '');
    var parts = ((baseDir ? baseDir + '/' : '') + rel).split('/');
    var out = [];
    for (var i = 0; i < parts.length; i++) {
        var p = parts[i];
        if (!p || p === '.') continue;
        if (p === '..') out.pop();
        else out.push(p);
    }
    return out.join('/');
}

/* Scroll a pandoc-generated heading into view inside the modal pane.
   Heading ids are produced by pandoc's gfm auto_identifiers; the caller
   supplies the fragment from a link href. No-op if the id is missing. */
function _scrollNoteToAnchor(anchor) {
    if (!anchor) return;
    var pane = document.getElementById('note-pane-view');
    if (!pane) return;
    var el = null;
    try { el = pane.querySelector('#' + CSS.escape(anchor)); } catch (_) {}
    if (el) el.scrollIntoView({block: 'start'});
}

/* Route note-body link clicks:
   - http(s) → POST /open-external → host browser (bypasses pywebview).
   - in-page anchors (#foo), mailto: → leave default behaviour.
   - relative .md (with optional #anchor) → resolve inside the conception
     tree and open in the same modal via openNotePreview.
   - anything else → resolve against the note's directory and POST /open-doc
     so the OS default viewer handles PDFs, images, and other files. */
function _wireNoteLinks(body, notePath) {
    var noteDir = notePath.lastIndexOf('/') >= 0
        ? notePath.substring(0, notePath.lastIndexOf('/'))
        : '';
    // Wikilinks resolved server-side carry an absolute (conception-tree
    // relative) href. They open inside the modal, not via xdg-open.
    body.querySelectorAll('a.wikilink[href]').forEach(function(a) {
        a.addEventListener('click', function(ev) {
            ev.preventDefault();
            var href = a.getAttribute('href');
            var label = a.textContent || href;
            _navigateToNote(href, label);
        });
    });
    // Unresolved wikilinks: click does nothing but flash the hover title.
    body.querySelectorAll('a.wikilink-missing').forEach(function(a) {
        a.addEventListener('click', function(ev) { ev.preventDefault(); });
    });
    body.querySelectorAll('a[href]:not(.wikilink):not(.wikilink-missing)').forEach(function(a) {
        var href = a.getAttribute('href');
        if (!href) return;
        if (/^https?:\/\//i.test(href)) {
            a.addEventListener('click', function(ev) {
                ev.preventDefault();
                fetch('/open-external', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: href}),
                });
            });
            return;
        }
        if (href.startsWith('#') || href.startsWith('mailto:')) {
            return;
        }
        var hashIdx = href.indexOf('#');
        var pathPart = hashIdx >= 0 ? href.substring(0, hashIdx) : href;
        var anchor = hashIdx >= 0 ? href.substring(hashIdx + 1) : '';
        if (pathPart && /\.md$/i.test(pathPart)) {
            var resolvedMd = _resolveNotePath(noteDir, pathPart);
            a.addEventListener('click', function(ev) {
                ev.preventDefault();
                var label = a.textContent || resolvedMd;
                _navigateToNote(resolvedMd, label, anchor);
            });
            return;
        }
        var resolved = _resolveNotePath(noteDir, pathPart || href);
        a.addEventListener('click', function(ev) {
            ev.preventDefault();
            fetch('/open-doc', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: resolved}),
            });
        });
    });
}

function closeNotePreview() {
    // Capture the active buffer so dirty reflects the latest keystrokes
    // even if the user never switched modes before closing.
    if (_noteModal.editable) _captureActiveBuffer();
    if (_noteModal.dirty) {
        if (!confirm('You have unsaved changes. Discard them?')) return;
    }
    document.getElementById('note-modal').classList.remove('open');
    _destroyCm();
    _hideSaveError();
    _noteModal.path = null;
    _noteModal.dirty = false;
    _noteNavStack = [];
    _syncNoteBack();
    noteSearchClose();
    _noteShowExternalBanner(false);
    reconcileState.suppressedUntilMtime = null;
    if (typeof _flushPendingReloads === 'function') _flushPendingReloads();
}

/* Refresh the view pane from /note. Owned here because it touches the
   preview DOM + the shared _renderMermaidIn / _wireNoteLinks / _mountPdfsIn
   helpers. Called by saveEdit (note-mode.js) after a successful save and
   by _noteSilentReload (note-reconcile.js) after an external-change
   reload. */
async function _reloadNotePreview(path, name) {
    var pane = document.getElementById('note-pane-view');
    if (name) document.getElementById('note-modal-title').textContent = name;
    pane.innerHTML = '<p class="note-loading">Loading…</p>';
    var res = await fetch('/note?path=' + encodeURIComponent(path));
    if (!res.ok) {
        pane.innerHTML = '<p class="note-error">Failed to load note (' + res.status + ').</p>';
        return;
    }
    var html = await res.text();
    pane.innerHTML = html;
    _noteModal.renderedHtml = html;
    _renderMermaidIn(pane);
    _wireNoteLinks(pane, path);
    _mountPdfsIn(pane);
    pane.scrollTop = 0;
}

export {
    _noteModal, _setDirty,
    openNotePreview, _navigateToNote, noteNavBack, closeNotePreview,
    _wireNoteLinks, _resolveNotePath, _scrollNoteToAnchor,
    _renderMermaidIn, _mountPdfsIn,
    _reloadNotePreview,
};

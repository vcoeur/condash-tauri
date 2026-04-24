/* CodeMirror 6 mount / unmount.

   CM6 is loaded lazily by the <script type="module"> block at the end
   of the document. Once ready, it sets window.__cm6 = {EditorView,
   EditorState, basicSetup, markdown, keymap, Compartment, themeC,
   buildTheme} and calls window.__cm6OnReady(). Before that, the "Edit"
   toggle stays disabled.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 of
   conception/projects/2026-04-23-condash-frontend-extraction). Reaches
   into three symbols from the note-modal sections (as of P-09 cut 4):
   _noteModal + _setDirty from note-preview.js (object-field writes),
   saveEdit from note-mode.js. All references are inside function
   bodies; no top-level side effects. */

import { _noteModal, _setDirty } from './note-preview.js';
import { saveEdit } from './note-mode.js';

var _cm = { view: null, themeC: null };

function _mountCm() {
    if (!window.__cm6) return;
    var host = document.getElementById('note-pane-cm');
    if (!host) return;
    if (_cm.view) return;
    // Clear any placeholder text.
    host.innerHTML = '';
    var cm6 = window.__cm6;
    _cm.themeC = new cm6.Compartment();
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var exts = [
        cm6.basicSetup,
        cm6.markdown(),
        cm6.EditorView.lineWrapping,
        cm6.keymap.of([
            {key: 'Mod-s', preventDefault: true, run: function() { saveEdit(); return true; }},
        ]),
        _cm.themeC.of(cm6.buildTheme(isDark)),
        cm6.EditorView.updateListener.of(function(u) {
            // Reflect edits into the canonical buffer live so a mode
            // switch doesn't need a separate capture path.
            if (u.docChanged) {
                _noteModal.text = u.state.doc.toString();
                _setDirty(true);
            }
        }),
    ];
    _cm.view = new cm6.EditorView({
        doc: _noteModal.text || '',
        parent: host,
        extensions: exts,
    });
    // Caret at offset 0, scroll to top, focus.
    _cm.view.dispatch({selection: {anchor: 0}});
    _cm.view.scrollDOM.scrollTop = 0;
    _cm.view.focus();
}

function _destroyCm() {
    if (_cm.view) { try { _cm.view.destroy(); } catch (e) {} }
    _cm.view = null;
    _cm.themeC = null;
    var host = document.getElementById('note-pane-cm');
    if (host) host.innerHTML = '';
}

/* Called by the theme toggle to repaint CM6 without remounting. */
function _cmRetheme() {
    if (!_cm.view || !_cm.themeC || !window.__cm6) return;
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    _cm.view.dispatch({
        effects: _cm.themeC.reconfigure(window.__cm6.buildTheme(isDark)),
    });
}

export { _cm, _mountCm, _destroyCm, _cmRetheme };

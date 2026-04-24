/* CM6 init bridge: run at bundle load to populate window.__cm6 from the
   vendored CondashCM global. The ESM mount/unmount helpers live next to
   the note-mode code in sections/cm6-mount.js; this file only bridges
   the classic vendored script to the shape the rest of the code reads. */

/* Mount the markdown-pane surface (window.__cm6) on top of the vendored
   CodeMirror 6 bundle (window.CondashCM) loaded via /vendor/codemirror/.
   The bundle's classic <script> tag is `defer`, so by the time this
   (also-classic, also-deferred) script runs the global is populated.
   If the bundle failed to load (should only happen on broken install)
   we leave __cm6 unset — the "Edit" toggle stays disabled and users
   fall back to the plain textarea.

   The markdown pane reuses CondashCM.EditorView / EditorState /
   Compartment / basicSetup / keymap and consumes the new
   CondashCM.markdownLang entry; all dedup happens at bundle build
   time via npm's flat tree, so no `?deps=` trick is needed here. */
(function() {
    if (!window.CondashCM) {
        console.warn('[condash] CodeMirror 6 bundle missing — note editor stays as plain textarea.');
        return;
    }
    var CM = window.CondashCM;
    var EditorView = CM.EditorView;

    /* Build a theme bound to condash's CSS variables so the editor
       stays aligned with dark/light without a second theme system.
       Passing {dark: true/false} flips CM's semantic colours
       (selection, cursor) for the right palette. */
    function buildTheme(isDark) {
        var styles = getComputedStyle(document.documentElement);
        var v = function(name, fb) { return styles.getPropertyValue(name).trim() || fb; };
        var bg = v('--bg-card', isDark ? '#18181b' : '#fff');
        var fg = v('--text', isDark ? '#e4e4e7' : '#18181b');
        var accent = v('--accent', '#2563eb');
        var accentBg = v('--accent-bg', 'rgba(37,99,235,0.1)');
        var pillBg = v('--pill-bg', isDark ? '#27272a' : '#f4f4f5');
        var border = v('--border', isDark ? '#3f3f46' : '#e4e4e7');
        var muted = v('--text-muted', '#a1a1aa');
        return EditorView.theme({
            '&': {color: fg, backgroundColor: bg, height: '100%'},
            '.cm-content': {caretColor: accent},
            '&.cm-focused': {outline: 'none'},
            '.cm-gutters': {
                backgroundColor: pillBg, color: muted,
                borderRight: '1px solid ' + border,
            },
            '.cm-activeLineGutter, .cm-activeLine': {
                backgroundColor: accentBg,
            },
            '.cm-selectionMatch, ::selection': {backgroundColor: accentBg},
            '.cm-cursor, .cm-dropCursor': {borderLeftColor: accent},
            '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
                backgroundColor: accentBg,
            },
        }, {dark: isDark});
    }

    window.__cm6 = {
        EditorView: EditorView,
        EditorState: CM.EditorState,
        Compartment: CM.Compartment,
        keymap: CM.keymap,
        basicSetup: CM.basicSetup,
        markdown: CM.markdownLang,
        buildTheme: buildTheme,
    };
    // Re-enable the Edit (CM6) toggle if the modal is already open.
    if (typeof window._syncModeControls === 'function') window._syncModeControls();
})();

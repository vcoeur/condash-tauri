/* CodeMirror 6 theme re-sync.

   When the user flips dark/light, the theme-loader script in <head>
   updates documentElement.data-theme synchronously. We watch that
   attribute and retheme the live EditorView (no remount) so the
   markdown editor picks up the new palette in the same frame.

   Extracted from dashboard-main.js on 2026-04-24 (P-09 of
   conception/projects/2026-04-23-condash-frontend-extraction). The
   MutationObserver registration is a top-level side effect, wrapped
   in initCm6ThemeSyncSideEffects() per the discipline note 01 §D3. */

import { _cmRetheme } from './cm6-mount.js';

function initCm6ThemeSyncSideEffects() {
    new MutationObserver(function() {
        if (typeof _cmRetheme === 'function') _cmRetheme();
    }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
}

export { initCm6ThemeSyncSideEffects };

// Bundled CodeMirror 6 surface for condash's config modal YAML pane.
//
// Built via `make update-codemirror` (esbuild → single minified IIFE),
// written to src/condash/assets/vendor/codemirror/codemirror.min.js.
// The IIFE exposes `window.CondashCM` with the pieces dashboard.html
// needs — no direct module imports from the browser, so condash stays
// offline-first with a single <script> tag.

import { EditorView, basicSetup } from "codemirror";
import { EditorState, Compartment } from "@codemirror/state";
import { yaml as yamlLang } from "@codemirror/lang-yaml";
import { oneDark } from "@codemirror/theme-one-dark";

window.CondashCM = {
    EditorView,
    EditorState,
    Compartment,
    basicSetup,
    yamlLang,
    oneDark,
};

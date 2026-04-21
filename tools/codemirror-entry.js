// Bundled CodeMirror 6 surface for condash.
//
// Built via `make update-codemirror` (esbuild → single minified IIFE),
// written to src/condash/assets/vendor/codemirror/codemirror.min.js.
// The IIFE exposes `window.CondashCM` with the pieces dashboard.html
// needs — both the config modal's YAML pane and the note editor's
// markdown pane read from it. A single <script> tag keeps condash
// offline-first with no runtime CDN fetch.

import { EditorView, basicSetup } from "codemirror";
import { keymap } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import { yaml as yamlLang } from "@codemirror/lang-yaml";
import { markdown as markdownLang } from "@codemirror/lang-markdown";
import { oneDark } from "@codemirror/theme-one-dark";

window.CondashCM = {
    EditorView,
    EditorState,
    Compartment,
    basicSetup,
    keymap,
    yamlLang,
    markdownLang,
    oneDark,
};

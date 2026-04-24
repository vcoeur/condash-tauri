/* Theme toggle + persistence. Extracted from dashboard-main.js on
   2026-04-24 (P-08 of conception/projects/2026-04-23-condash-frontend-extraction).

   Reads the saved preference from localStorage, falls back to the
   system colour-scheme, and writes the chosen value back on every
   toggle. Also live-swaps any mounted CodeMirror editors so their
   colour scheme tracks the dashboard's.

   Circular-import rule (see notes/01-p07-tab-drag-split.md §D2): the
   CodeMirror bindings (_cmViews, _currentCmTheme) are referenced only
   inside applyTheme's function body, never at top level. Side-effect
   registration (the first applyTheme call) is deferred to
   initThemeSideEffects(), invoked from dashboard-main.js's tail. */

import { _cmViews, _currentCmTheme } from './config-modal.js';

function getPreferredTheme() {
    var saved = localStorage.getItem('dashboard-theme');
    if (saved) return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    var icon = document.getElementById('theme-icon');
    var label = document.getElementById('theme-label');
    if (theme === 'dark') {
        icon.innerHTML = '&#9790;';
        label.textContent = 'Dark';
    } else {
        icon.innerHTML = '&#9788;';
        label.textContent = 'Light';
    }
    // Live-swap any open CodeMirror editors to the matching theme.
    if (window.CondashCM && typeof _cmViews === 'object') {
        Object.keys(_cmViews).forEach(function(which) {
            var view = _cmViews[which];
            var ta = document.querySelector('#config-form textarea[data-yaml-file="' + which + '"]');
            var comp = ta && ta._cmThemeComp;
            if (view && comp) {
                view.dispatch({ effects: comp.reconfigure(_currentCmTheme()) });
            }
        });
    }
}

function toggleTheme() {
    var current = document.documentElement.getAttribute('data-theme') || 'light';
    var next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem('dashboard-theme', next);
    applyTheme(next);
}

function initThemeSideEffects() {
    applyTheme(getPreferredTheme());
}

export { getPreferredTheme, applyTheme, toggleTheme, initThemeSideEffects };

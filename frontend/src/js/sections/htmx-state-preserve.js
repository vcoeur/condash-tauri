/* htmx swap-time hooks for client-only state preservation.

   Idiomorph keys elements by `id` and morphs attributes wholesale —
   that means user-driven state (`<details open>`, expanded cards,
   active filters) gets clobbered when the server fragment, which has
   no idea what the user clicked, lands. This module captures that
   state in `htmx:beforeSwap` and re-applies it in `htmx:afterSwap`,
   per swap target.

   Three targets carry preservable state:

   - `#cards`              — card.collapsed class, card.expanded class
   - `#knowledge`          — <details data-node-id> open state, then
                             re-apply the client-side filterKnowledge
                             query
   - `#git-panel`          — runner-viewer mounts already carry
                             `hx-preserve="true"` server-side, so
                             nothing to do here; included for symmetry. */

import { restoreNotesTreeState } from './notes-tree-state.js';
import { _activeSubtab, _applySubtab } from '../dashboard-main.js';

/* Per-swap-id snapshots. Keyed by element id ("cards" / "knowledge"),
   keeps the captured state between beforeSwap and afterSwap. */
var _snap = {};

function _captureCardsState(el) {
    var expanded = [];
    el.querySelectorAll('.card[id]').forEach(function(c) {
        if (!c.classList.contains('collapsed')) expanded.push(c.id);
    });
    return { expanded: expanded };
}

function _restoreCardsState(el, snap) {
    if (!snap || !snap.expanded) return;
    snap.expanded.forEach(function(id) {
        var c = el.querySelector('.card[id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
        if (c) c.classList.remove('collapsed');
    });
    // The Projects subtab filter is purely class-based on cards. Re-apply
    // it so a card whose priority just changed slides into the right
    // bucket — and one whose priority left the active subtab vanishes.
    if (typeof _applySubtab === 'function' && _activeSubtab) {
        _applySubtab(_activeSubtab);
    }
}

function _captureKnowledgeState(el) {
    var open = {};
    el.querySelectorAll('details[data-node-id]').forEach(function(d) {
        open[d.getAttribute('data-node-id')] = d.open;
    });
    var input = document.getElementById('knowledge-search');
    return {
        open: open,
        query: input ? input.value : '',
    };
}

function _restoreKnowledgeState(el, snap) {
    if (!snap) return;
    if (snap.open) {
        el.querySelectorAll('details[data-node-id]').forEach(function(d) {
            var id = d.getAttribute('data-node-id');
            if (id in snap.open) d.open = snap.open[id];
        });
    }
    // notes-tree-state.js stores additional folder open state in
    // localStorage; replay it so any folder the user opened earlier
    // (and that survived the swap) keeps its state.
    restoreNotesTreeState();
    // Re-apply the active filter against the fresh DOM. filterKnowledge
    // is exposed on `window` (it's reached via oninput=) so we don't
    // need an import here.
    if (snap.query && typeof window.filterKnowledge === 'function') {
        window.filterKnowledge(snap.query);
    }
}

function initHtmxStatePreserve() {
    document.body.addEventListener('htmx:beforeSwap', function(ev) {
        var target = ev.target;
        if (!target || !target.id) return;
        if (target.id === 'cards') _snap.cards = _captureCardsState(target);
        else if (target.id === 'knowledge') _snap.knowledge = _captureKnowledgeState(target);
    });
    document.body.addEventListener('htmx:afterSwap', function(ev) {
        var target = ev.target;
        if (!target || !target.id) return;
        if (target.id === 'cards') {
            _restoreCardsState(target, _snap.cards);
            _snap.cards = null;
        } else if (target.id === 'knowledge') {
            _restoreKnowledgeState(target, _snap.knowledge);
            _snap.knowledge = null;
        }
    });
}

export { initHtmxStatePreserve };

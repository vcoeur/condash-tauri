/* Focus-safe DOM swap primitive.

   Shared helper used by _reloadInPlace (tab-level) and reloadNode
   (per-subtree). Captures anything that would be lost by a naive
   replaceWith — scroll, focus/caret, <details> open state, opt-in
   `data-preserve` form inputs — then restores it onto the fresh DOM.
   Callers extend it via `opts.skipIf(targetEl)` → any truthy return
   aborts the swap and the caller is told the reason (used from
   Phase 2 onwards to defer reloads that would kill a live runner or
   trash unsaved modal edits).

   Extracted from dashboard-main.js on 2026-04-24 (P-09 cut 2 of
   conception/projects/2026-04-23-condash-frontend-extraction). No new
   cross-module imports beyond what's already routed through the
   previously extracted guards + local-subtree helpers. */

import { _defaultReloadSkipIf } from './reload-guards.js';
import {
    _captureDetailsOpenState, _restoreDetailsOpenState,
} from './local-subtree-reload.js';

function focusSafeSwap(targetEl, freshEl, opts) {
    opts = opts || {};
    var skipIf = opts.skipIf || _defaultReloadSkipIf;
    var reason = skipIf(targetEl);
    if (reason) return {skipped: true, reason: reason};
    var snapshot = _snapshotForSwap(targetEl, opts);
    targetEl.replaceWith(freshEl);
    _restoreFromSnapshot(freshEl, snapshot, opts);
    return {skipped: false, snapshot: snapshot};
}

function _snapshotForSwap(el, opts) {
    var snap = {};
    // Window + #main-scroll position, for tab-level rebuilds where
    // el === #dash-main; harmless when el is a subtree.
    snap.scrollY = window.scrollY;
    var mainScroll = document.getElementById('main-scroll');
    snap.mainScrollTop = mainScroll ? mainScroll.scrollTop : null;
    // Explicit named scroll containers inside the target.
    snap.scrollMap = {};
    el.querySelectorAll('[data-scroll-key]').forEach(function(n) {
        snap.scrollMap[n.getAttribute('data-scroll-key')] = {
            top: n.scrollTop, left: n.scrollLeft,
        };
    });
    // <details> by data-node-id (inside el).
    snap.detailsMap = _captureDetailsOpenState(el);
    // Active element focus + caret (text inputs / textareas only).
    var active = document.activeElement;
    if (active && el.contains(active) && active.id) {
        snap.focusId = active.id;
        try {
            snap.focusSel = {
                start: active.selectionStart, end: active.selectionEnd,
            };
        } catch (e) {}
    }
    // data-preserve inputs → sessionStorage (Phase 5 lights up the
    // callers that care, but the plumbing is harmless today).
    el.querySelectorAll('input[data-preserve],textarea[data-preserve]').forEach(function(n) {
        var key = n.getAttribute('data-preserve');
        if (!key) return;
        var payload = {value: n.value};
        try {
            payload.sel = {start: n.selectionStart, end: n.selectionEnd};
        } catch (e) {}
        try { sessionStorage.setItem(key, JSON.stringify(payload)); }
        catch (e) {}
    });
    return snap;
}

function _restoreFromSnapshot(el, snap, opts) {
    if (snap.scrollY != null) window.scrollTo(0, snap.scrollY);
    var mainScroll = document.getElementById('main-scroll');
    if (mainScroll && snap.mainScrollTop != null) {
        mainScroll.scrollTop = snap.mainScrollTop;
    }
    el.querySelectorAll('[data-scroll-key]').forEach(function(n) {
        var saved = snap.scrollMap && snap.scrollMap[n.getAttribute('data-scroll-key')];
        if (saved) { n.scrollTop = saved.top; n.scrollLeft = saved.left; }
    });
    _restoreDetailsOpenState(el, snap.detailsMap || {});
    if (snap.focusId) {
        var f = document.getElementById(snap.focusId);
        if (f) {
            try { f.focus(); } catch (e) {}
            if (snap.focusSel && f.setSelectionRange) {
                try { f.setSelectionRange(snap.focusSel.start, snap.focusSel.end); }
                catch (e) {}
            }
        }
    }
    el.querySelectorAll('input[data-preserve],textarea[data-preserve]').forEach(function(n) {
        var key = n.getAttribute('data-preserve');
        if (!key) return;
        try {
            var raw = sessionStorage.getItem(key);
            if (!raw) return;
            var payload = JSON.parse(raw);
            if (payload.value != null && n.value !== payload.value) {
                n.value = payload.value;
            }
            if (payload.sel && n.setSelectionRange &&
                document.activeElement === n) {
                try { n.setSelectionRange(payload.sel.start, payload.sel.end); }
                catch (e) {}
            }
        } catch (e) {}
    });
}

export { focusSafeSwap };

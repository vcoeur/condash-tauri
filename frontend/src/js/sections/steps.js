/* Steps subsystem — the check/cycle/add/remove/reorder actions + the
   drag-reorder machinery + section folding + inline text editing.

   Extracted from `dashboard-main.js` as part of C-08 of the
   `2026-04-24-condash-dashboard-main-split` project. Pure behaviour-
   preserving move.

   The module owns:
   - `cycle` — advance a step through its state machine.
   - `removeStep` — delete a step line.
   - `addStep` — insert a new step under a heading.
   - `toggleSection` — fold/unfold a section.
   - `updateProgress` — recompute the done/total header on a card.
   - `openDeliverable` — launch a deliverable PDF via the server route.
   - `startEditText` — inline rename/edit of a step's label.
   - `stepPointerDown` / `Move` / `Up` / `Cancel` — touch/mouse drag
     reorder. Cross-module consumers (window.*) reach `stepPointerDown`
     and `addStep` through the residual inline-handler export list. */

import { updateTabCounts } from './search-filter.js';
import { closeNotePreview } from './note-preview.js';
import { closeNewItemModal } from './new-item-modal.js';
import { closeAboutModal } from './about-modal.js';
import { closeConfigModal } from './config-modal.js';

export function toggleSection(el) {
    var items = el.nextElementSibling;
    if (items.style.display === 'none') {
        items.style.display = 'block';
        el.classList.add('open');
    } else {
        items.style.display = 'none';
        el.classList.remove('open');
    }
}


/* Route a ## Deliverables PDF click to the OS default viewer. target="_blank"
   under pywebview routes to the system browser on 127.0.0.1:<port> and fails
   to render inline, so we mirror the note-link pattern and POST /open-doc
   with the conception-tree-relative path — xdg-open / open / startfile
   then opens the local file in the user's native PDF viewer. */
export function openDeliverable(path) {
    fetch('/open-doc', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: path}),
    }).catch(function() {});
}


document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var noteModal = document.getElementById('note-modal');
    if (noteModal && noteModal.classList.contains('open')) { closeNotePreview(); return; }
    var newItemModal = document.getElementById('new-item-modal');
    if (newItemModal && newItemModal.style.display && newItemModal.style.display !== 'none') {
        closeNewItemModal();
        return;
    }
    var cfgModal = document.getElementById('config-modal');
    if (cfgModal && cfgModal.style.display && cfgModal.style.display !== 'none') {
        closeConfigModal();
        return;
    }
    var aboutModal = document.getElementById('about-modal');
    if (aboutModal && aboutModal.style.display && aboutModal.style.display !== 'none') {
        closeAboutModal();
    }
});


export async function cycle(file, line, el) {
    var res = await fetch('/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, line: line})
    });
    if (!res.ok) return;
    var data = await res.json();
    el.className = 'step ' + data.status;
    var dot = el.querySelector('.status-dot');
    dot.className = 'status-dot status-' + data.status;
    dot.textContent = {done: '\u2713', progress: '~', abandoned: '\u2014', open: ''}[data.status] || '';
    updateProgress(el.closest('.card'));
}

export async function removeStep(file, line, btn) {
    var res = await fetch('/remove-step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, line: line})
    });
    if (!res.ok) return;
    var step = btn.closest('.step');
    var card = step.closest('.card');
    var removedLine = parseInt(step.getAttribute('data-line'));
    step.remove();
    card.querySelectorAll('.step').forEach(function(s) {
        var ln = parseInt(s.getAttribute('data-line'));
        if (ln > removedLine) s.setAttribute('data-line', ln - 1);
    });
    updateProgress(card);
}

export function updateProgress(card) {
    var steps = card.querySelectorAll('.step');
    var done = [].filter.call(steps, function(s) { return s.classList.contains('done') || s.classList.contains('abandoned'); }).length;
    var total = steps.length;
    var el = card.querySelector('.progress-text');
    if (el) {
        var pct = total ? Math.round(done / total * 100) : 0;
        var style = getComputedStyle(document.documentElement);
        var fill = pct === 100 ? style.getPropertyValue('--progress-done') : style.getPropertyValue('--progress-fill');
        var bg = style.getPropertyValue('--progress-track');
        el.innerHTML = done + '/' + total +
            ' <span class="progress-bar" style="background:' + bg + '"><span class="progress-fill" style="width:' +
            pct + '%;background:' + fill + '"></span></span>';
    }
    card.querySelectorAll('.sec-group').forEach(function(group) {
        var items = group.querySelectorAll('.step');
        var d = [].filter.call(items, function(s) { return s.classList.contains('done') || s.classList.contains('abandoned'); }).length;
        var span = group.querySelector('.sec-count');
        if (span) span.textContent = '(' + d + '/' + items.length + ')';
    });
}

export async function addStep(file, section, inputEl) {
    var text = inputEl.value.trim();
    if (!text) return;
    var res = await fetch('/add-step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, text: text, section: section})
    });
    if (!res.ok) return;
    var data = await res.json();
    var step = document.createElement('div');
    step.className = 'step open';
    step.setAttribute('data-file', file);
    step.setAttribute('data-line', data.line);
    var handle = document.createElement('span');
    handle.className = 'drag-handle';
    handle.textContent = '\u283f';
    handle.addEventListener('pointerdown', stepPointerDown);
    var dot = document.createElement('span');
    dot.className = 'status-dot';
    dot.onmousedown = function(e) { e.stopPropagation(); e.preventDefault(); };
    dot.onclick = function() { var s = this.closest('.step'); cycle(file, parseInt(s.getAttribute('data-line')), s); };
    var txt = document.createElement('span');
    txt.className = 'text';
    txt.textContent = text;
    txt.onmousedown = function(e) { e.stopPropagation(); };
    txt.onclick = function(e) { e.stopPropagation(); startEditText(this); };
    var btn = document.createElement('button');
    btn.className = 'remove-btn';
    btn.textContent = '\u00d7';
    btn.onmousedown = function(e) { e.stopPropagation(); e.preventDefault(); };
    btn.onclick = function() { var s = this.closest('.step'); removeStep(file, parseInt(s.getAttribute('data-line')), this); };
    step.appendChild(handle);
    step.appendChild(dot);
    step.appendChild(txt);
    step.appendChild(btn);
    inputEl.closest('.add-row').parentNode.insertBefore(step, inputEl.closest('.add-row'));
    var insertedLine = data.line;
    inputEl.closest('.card').querySelectorAll('.step').forEach(function(s) {
        if (s === step) return;
        var ln = parseInt(s.getAttribute('data-line'));
        if (ln >= insertedLine) s.setAttribute('data-line', ln + 1);
    });
    inputEl.value = '';
    inputEl.focus();
    updateProgress(inputEl.closest('.card'));
}

/* Step reorder — pointer-event based for the same reason the terminal tabs
   use pointer events (see _termChipPointerDown): QtWebEngine segfaults
   pywebview on HTML5 dragstart of any moderately complex DOM element.
   Triggered from the drag handle only so click-to-edit on the text span
   and the status-dot cycle both keep working.

   The reorder is committed on pointerup, not during pointermove. An earlier
   version of this code called `insertBefore` on the dragging step during
   move; QtWebEngine drops `setPointerCapture` when the captured handle's
   ancestor is reparented, so pointerup never fired and `.dragging` stuck
   (opacity 0.4). During the gesture we only move a pointer-events:none
   ghost clone and toggle `is-drop-before`/`is-drop-after` markers on
   sibling steps. See #8. */
var _stepDrag = null;
var _STEP_DRAG_THRESHOLD_PX = 4;

export function stepPointerDown(ev) {
    if (ev.button !== undefined && ev.button !== 0) return;
    var handle = ev.currentTarget;
    var step = handle.closest('.step');
    if (!step) return;
    _stepDrag = {
        step: step,
        container: step.closest('.sec-items'),
        pointerId: ev.pointerId,
        startX: ev.clientX,
        startY: ev.clientY,
        active: false,
        handle: handle,
        ghost: null,
        ghostOffX: 0,
        ghostOffY: 0,
        drop: null,  // {target: <step>, before: bool}
    };
    try { handle.setPointerCapture(ev.pointerId); } catch (e) {}
    handle.addEventListener('pointermove', stepPointerMove);
    handle.addEventListener('pointerup', stepPointerUp);
    handle.addEventListener('pointercancel', stepPointerCancel);
    ev.preventDefault();
}

function stepPointerMove(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    if (!_stepDrag.active) {
        var dx = ev.clientX - _stepDrag.startX;
        var dy = ev.clientY - _stepDrag.startY;
        if (Math.hypot(dx, dy) < _STEP_DRAG_THRESHOLD_PX) return;
        _stepBeginDrag();
    }
    _stepDrag.ghost.style.left = (ev.clientX - _stepDrag.ghostOffX) + 'px';
    _stepDrag.ghost.style.top = (ev.clientY - _stepDrag.ghostOffY) + 'px';
    _stepUpdateDropMarker(ev.clientX, ev.clientY);
}

function _stepBeginDrag() {
    var step = _stepDrag.step;
    _stepDrag.active = true;
    var rect = step.getBoundingClientRect();
    var ghost = step.cloneNode(true);
    ghost.classList.add('step-ghost');
    ghost.style.position = 'fixed';
    ghost.style.left = rect.left + 'px';
    ghost.style.top = rect.top + 'px';
    ghost.style.width = rect.width + 'px';
    ghost.style.height = rect.height + 'px';
    // pointer-events:none is critical — without it, elementFromPoint would
    // return the ghost and the drop marker could never latch on a sibling.
    ghost.style.pointerEvents = 'none';
    ghost.style.zIndex = '9999';
    ghost.style.opacity = '0.85';
    document.body.appendChild(ghost);
    _stepDrag.ghost = ghost;
    _stepDrag.ghostOffX = _stepDrag.startX - rect.left;
    _stepDrag.ghostOffY = _stepDrag.startY - rect.top;
    step.classList.add('dragging');
}

function _stepUpdateDropMarker(x, y) {
    document.querySelectorAll('.step.is-drop-before, .step.is-drop-after').forEach(function(el) {
        el.classList.remove('is-drop-before');
        el.classList.remove('is-drop-after');
    });
    _stepDrag.drop = null;
    var under = document.elementFromPoint(x, y);
    if (!under) return;
    var target = under.closest && under.closest('.step');
    if (!target || target === _stepDrag.step) return;
    if (target.closest('.sec-items') !== _stepDrag.container) return;
    var rect = target.getBoundingClientRect();
    var before = y < rect.top + rect.height / 2;
    target.classList.toggle('is-drop-before', before);
    target.classList.toggle('is-drop-after', !before);
    _stepDrag.drop = {target: target, before: before};
}

function stepPointerUp(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    var drag = _stepDrag;
    _stepCleanupDrag();
    if (!drag.active) return;  // Just a click on the handle — nothing to do.
    if (!drag.drop) return;
    var drop = drag.drop;
    if (drop.before) {
        drag.container.insertBefore(drag.step, drop.target);
    } else {
        drag.container.insertBefore(drag.step, drop.target.nextSibling);
    }
    var steps = drag.container.querySelectorAll('.step');
    if (!steps.length) return;
    var file = steps[0].getAttribute('data-file');
    var lines = [].map.call(steps, function(s) { return parseInt(s.getAttribute('data-line')); });
    var sorted = lines.slice().sort(function(a, b) { return a - b; });
    if (lines.every(function(v, i) { return v === sorted[i]; })) return;
    fetch('/reorder-all', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: file, order: lines})
    }).then(function(res) {
        if (!res.ok) return;
        [].forEach.call(steps, function(s, i) { s.setAttribute('data-line', sorted[i]); });
    });
}

function stepPointerCancel(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    _stepCleanupDrag();
}

function _stepCleanupDrag() {
    if (!_stepDrag) return;
    var handle = _stepDrag.handle;
    try { handle.releasePointerCapture(_stepDrag.pointerId); } catch (e) {}
    handle.removeEventListener('pointermove', stepPointerMove);
    handle.removeEventListener('pointerup', stepPointerUp);
    handle.removeEventListener('pointercancel', stepPointerCancel);
    if (_stepDrag.ghost && _stepDrag.ghost.parentNode) {
        _stepDrag.ghost.parentNode.removeChild(_stepDrag.ghost);
    }
    _stepDrag.step.classList.remove('dragging');
    document.querySelectorAll('.step.is-drop-before, .step.is-drop-after').forEach(function(el) {
        el.classList.remove('is-drop-before');
        el.classList.remove('is-drop-after');
    });
    _stepDrag = null;
}

export function startEditText(el) {
    if (el.classList.contains('editing')) return;
    var original = el.textContent;
    var cancelled = false;
    el.classList.add('editing');
    el.contentEditable = 'true';
    el.focus();
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    el.onpaste = function(e) {
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text/plain');
        document.execCommand('insertText', false, text.replace(/\n/g, ' '));
    };

    async function commit() {
        el.onblur = null;
        el.onkeydown = null;
        el.onpaste = null;
        el.contentEditable = 'false';
        el.classList.remove('editing');
        if (cancelled) { el.textContent = original; return; }
        var newText = el.textContent.trim();
        if (!newText || newText === original) {
            el.textContent = original;
            return;
        }
        var step = el.closest('.step');
        var file = step.getAttribute('data-file');
        var line = parseInt(step.getAttribute('data-line'));
        var res = await fetch('/edit-step', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({file: file, line: line, text: newText})
        });
        if (!res.ok) el.textContent = original;
    }

    el.onblur = commit;
    el.onkeydown = function(e) {
        if (e.key === 'Enter') { e.preventDefault(); el.blur(); }
        if (e.key === 'Escape') { cancelled = true; el.blur(); }
    };
}

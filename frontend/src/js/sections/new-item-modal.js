/* New-item modal — lives next to the gear button. Collects the minimal
   fields the README parser cares about (kind, status, title, slug, apps
   + kind-specific extras) and POSTs /api/items. Everything else — goal,
   scope, steps, body prose — the user types in their editor.

   Extracted from dashboard-main.js on 2026-04-24 (P-08 of
   conception/projects/2026-04-23-condash-frontend-extraction). The
   form-wiring IIFE becomes initNewItemModalSideEffects() per the
   circular-import discipline (see notes/01-p07-tab-drag-split.md §D2
   + §D3). submitNewItem's post-create tab-switch calls switchTab /
   switchSubtab via imports; both are referenced inside a function
   body so the cycle remains TDZ-safe. */

import { switchTab, switchSubtab } from '../dashboard-main.js';

/* Remove accents + punctuation and produce a YYYY-MM-DD-compatible
   slug. Keeps letters, digits, spaces; collapses spaces into single
   hyphens. Lives client-side so the preview matches what lands on
   disk, but the server re-validates. */
function _deriveSlug(title) {
    return (title || '')
        .normalize('NFD').replace(/[̀-ͯ]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

function _newItemSubtab(status) {
    // Map Status → the Projects sub-tab that renders it.
    if (status === 'now' || status === 'review') return 'current';
    if (status === 'soon') return 'next';
    if (status === 'done') return 'done';
    return 'backlog';
}

function openNewItemModal() {
    var modal = document.getElementById('new-item-modal');
    var form = document.getElementById('new-item-form');
    if (!modal || !form) return;
    form.reset();
    document.getElementById('new-item-error').style.display = 'none';
    // Reset the default-checked radios the browser loses on reset().
    var k = form.querySelector('input[name="kind"][value="project"]');
    if (k) k.checked = true;
    var s = form.querySelector('input[name="status"][value="now"]');
    if (s) s.checked = true;
    _syncNewItemKindFields();
    modal.style.display = 'flex';
    setTimeout(function() {
        var title = document.getElementById('new-item-title');
        if (title) title.focus();
    }, 40);
}

function closeNewItemModal() {
    document.getElementById('new-item-modal').style.display = 'none';
}

function _syncNewItemKindFields() {
    var form = document.getElementById('new-item-form');
    if (!form) return;
    var kindEl = form.querySelector('input[name="kind"]:checked');
    var kind = kindEl ? kindEl.value : 'project';
    form.querySelectorAll('[data-kind-fields]').forEach(function(fs) {
        fs.style.display = (fs.getAttribute('data-kind-fields') === kind) ? '' : 'none';
    });
}

function initNewItemModalSideEffects() {
    document.addEventListener('DOMContentLoaded', function() {
        var form = document.getElementById('new-item-form');
        if (!form) return;
        // Kind toggles show/hide the conditional fieldset.
        form.querySelectorAll('input[name="kind"]').forEach(function(el) {
            el.addEventListener('change', _syncNewItemKindFields);
        });
        // Auto-derive the slug from the title unless the user has typed
        // into the slug field themselves.
        var title = document.getElementById('new-item-title');
        var slug = document.getElementById('new-item-slug');
        if (title && slug) {
            slug.addEventListener('input', function() { slug.dataset.manual = '1'; });
            title.addEventListener('input', function() {
                if (slug.dataset.manual === '1' && slug.value.trim() !== '') return;
                slug.value = _deriveSlug(title.value);
                delete slug.dataset.manual;
            });
        }
    });
}

async function submitNewItem(ev) {
    ev.preventDefault();
    var form = document.getElementById('new-item-form');
    var errEl = document.getElementById('new-item-error');
    errEl.style.display = 'none';

    var kind = (form.querySelector('input[name="kind"]:checked') || {}).value || 'project';
    var status = (form.querySelector('input[name="status"]:checked') || {}).value || 'now';
    var environment = (form.querySelector('input[name="environment"]:checked') || {}).value || '';
    var severity = (form.querySelector('input[name="severity"]:checked') || {}).value || '';
    var payload = {
        kind: kind,
        status: status,
        title: form.elements['title'].value.trim(),
        slug: form.elements['slug'].value.trim(),
        apps: (form.elements['apps'] || {}).value || '',
        environment: kind === 'incident' ? environment : '',
        severity: kind === 'incident' ? severity : '',
        languages: kind === 'document' ? ((form.elements['languages'] || {}).value || '') : '',
    };

    var submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
        var res = await fetch('/api/items', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        var data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        if (!res.ok || !data.ok) {
            errEl.textContent = data.reason || ('Create failed (HTTP ' + res.status + ')');
            errEl.style.display = 'block';
            return;
        }
        closeNewItemModal();
        // Switch to Projects → matching sub-tab; the README write fires
        // the file watcher → SSE `projects` event → htmx repaints
        // `#cards` with the new card. Expand it once it lands.
        try { switchTab('projects'); } catch (e) {}
        try { switchSubtab(_newItemSubtab(status)); } catch (e) {}
        var target = data.folder_name || data.slug;
        setTimeout(function() { _expandCardBySlug(target); }, 500);
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

function _expandCardBySlug(slug) {
    if (!slug) return;
    var cards = document.querySelectorAll('.card');
    for (var i = 0; i < cards.length; i++) {
        var c = cards[i];
        if ((c.id || '').indexOf(slug) >= 0) {
            c.classList.remove('collapsed');
            c.scrollIntoView({block: 'start', behavior: 'smooth'});
            return;
        }
    }
}

export {
    openNewItemModal, closeNewItemModal, submitNewItem,
    initNewItemModalSideEffects,
};

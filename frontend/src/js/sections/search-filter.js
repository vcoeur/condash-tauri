/* Search + filter for the Knowledge tab + History-tab navigation helpers.

   The History pane's input-driven filtering moved off this module on
   the htmx-history-spike branch: `/fragment/history` now returns the
   tree or search-results HTML directly and htmx swaps it into
   `#history-content`. The two helpers History still needs from this
   module — `_openHistoryHit` and `jumpToProject` — stay because their
   wiring (server-rendered `data-action` attributes) is unchanged.

   The module owns:
   - `updateTabCounts` — recomputes the counts shown in the primary tabs.
   - `filterKnowledge` — debounced input-driven filtering of the
     Knowledge tree (still reached via `window.filterKnowledge` from the
     `oninput=` attribute in server-rendered HTML).
   - `jumpToProject` / `_openHistoryHit` — history-tab navigation
     helpers wired up via `data-action` dispatch in `dashboard-main.js`.
   - `_reapplySearches` — re-runs the Knowledge filter after an
     in-place reload.
   - Private helpers (`_searchTokens`, `_cardMatches`, `_buildSnippet`, …)
     that are implementation details of the filter logic. */

import { TAB_MAP, switchTab, switchSubtab } from '../dashboard-main.js';
import { openNotePreview } from './note-preview.js';

export function updateTabCounts() {
    // Primary tabs — Projects counts active items under Projects-tab
    // priorities; Code + Knowledge are rendered with a static count from
    // the server and don't need a client-side refresh on priority changes.
    var projectsCount = document.querySelectorAll('#cards .card').length;
    var projectsTab = document.querySelector('.tabs-primary .tab[data-tab="projects"] .tab-count');
    if (projectsTab) projectsTab.textContent = '(' + projectsCount + ')';
    // Projects sub-tabs — these filter the `#cards` grid; count per tab.
    document.querySelectorAll('#projects-subtabs .tab').forEach(function(t) {
        var tab = t.getAttribute('data-subtab');
        var allowed = TAB_MAP[tab] || [];
        var count = [].slice.call(document.querySelectorAll('.card')).filter(function(c) {
            return allowed.indexOf(c.getAttribute('data-priority')) !== -1;
        }).length;
        var span = t.querySelector('.tab-count');
        if (span) span.textContent = '(' + count + ')';
    });
}

/* --- Search: shared helpers used by filterKnowledge + filterHistory ---
   Tokenise on whitespace; a card matches iff every token is a substring of
   its textContent (case-insensitive). textContent covers title, description,
   apps, kind, tags and whatever else the server-rendered card contains, so
   no per-field plumbing is needed. */
function _searchTokens(q) {
    q = (q || '').trim().toLowerCase();
    if (!q) return [];
    return q.split(/\s+/);
}
function _cardMatches(el, tokens) {
    if (tokens.length === 0) return true;
    var hay = (el.textContent || '').toLowerCase();
    for (var i = 0; i < tokens.length; i++) {
        if (hay.indexOf(tokens[i]) === -1) return false;
    }
    return true;
}
function _setEmpty(panel, cls, text) {
    var el = panel.querySelector('.' + cls);
    if (text == null) {
        if (el) el.remove();
        return;
    }
    if (!el) {
        el = document.createElement('p');
        el.className = cls;
        panel.appendChild(el);
    }
    el.textContent = text;
}

/* Last Knowledge query — re-applied after htmx morph-swaps `#knowledge`
   so an active filter survives a background refresh (see
   `htmx-state-preserve.js`). The History pane uses `data-preserve` on
   its input so htmx re-fires `hx-get` against the saved value. */
var _knowledgeSearchQ = '';

/* Build an HTML snippet showing ~`radius` chars of context around the
   first token match in `text`, with every token occurrence wrapped in
   <mark>. Returns '' when no token matches. Snaps the cut to the
   nearest space on either side so words aren't sliced mid-letter. */
function _escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function _escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function _buildSnippet(text, tokens, radius) {
    if (!tokens.length || !text) return '';
    var hay = text.toLowerCase();
    var pos = -1, hitLen = 0;
    for (var i = 0; i < tokens.length; i++) {
        var p = hay.indexOf(tokens[i]);
        if (p >= 0 && (pos < 0 || p < pos)) { pos = p; hitLen = tokens[i].length; }
    }
    if (pos < 0) return '';
    var start = Math.max(0, pos - radius);
    var end = Math.min(text.length, pos + hitLen + radius);
    // Snap to nearest word boundary (whitespace) within a small margin.
    if (start > 0) {
        var ws = text.lastIndexOf(' ', start);
        if (ws >= 0 && start - ws < 20) start = ws + 1;
    }
    if (end < text.length) {
        var we = text.indexOf(' ', end);
        if (we >= 0 && we - end < 20) end = we;
    }
    var frag = text.substring(start, end).replace(/\s+/g, ' ').trim();
    var html = _escapeHtml(frag);
    var re = new RegExp('(' + tokens.map(_escapeRegExp).join('|') + ')', 'gi');
    html = html.replace(re, '<mark>$1</mark>');
    return (start > 0 ? '…' : '') + html + (end < text.length ? '…' : '');
}
/* Inject/update a .match-snippet element inside a matching card. Reuses
   the element across keystrokes to avoid DOM churn; removes it on
   non-match or empty tokens. */
function _setSnippet(card, tokens) {
    var existing = card.querySelector(':scope > .match-snippet');
    if (tokens.length === 0) {
        if (existing) existing.remove();
        return;
    }
    // Exclude the title from the snippet source so it surfaces content
    // the user can't already see in the card's static label.
    var titleEl = card.querySelector(':scope > .knowledge-title');
    var titleText = titleEl ? titleEl.textContent : '';
    var full = card.textContent || '';
    var body = titleText && full.indexOf(titleText) === 0
        ? full.substring(titleText.length) : full;
    var html = _buildSnippet(body, tokens, 60);
    if (!html) {
        if (existing) existing.remove();
        return;
    }
    if (!existing) {
        existing = document.createElement('div');
        existing.className = 'match-snippet';
        card.appendChild(existing);
    }
    existing.innerHTML = html;
}

/* --- Generic tree filter (knowledge + history views) ---
   Token-AND substring match against .knowledge-card textContent. Hide
   .knowledge-group groups that end up with zero matches; re-reveal and
   <details>-open each matching card's ancestor groups so deep matches
   surface without showing sibling subdirs; surface an empty-state line
   when the whole panel is empty. Matching cards get a .match-snippet
   showing context around the first token hit. */
function _filterTree(panel, tokens, qTrim, emptyCls, emptyMsg) {
    var groups = panel.querySelectorAll('.knowledge-group');
    var cards = panel.querySelectorAll('.knowledge-card');
    if (tokens.length === 0) {
        groups.forEach(function(g){ g.style.display = ''; });
        cards.forEach(function(c){
            c.style.display = '';
            _setSnippet(c, tokens);
        });
        _setEmpty(panel, emptyCls, null);
        return;
    }
    groups.forEach(function(g){ g.style.display = 'none'; });
    var totalVisible = 0;
    cards.forEach(function(c) {
        var match = _cardMatches(c, tokens);
        c.style.display = match ? '' : 'none';
        _setSnippet(c, match ? tokens : []);
        if (!match) return;
        totalVisible += 1;
        var anc = c.parentElement;
        while (anc && anc !== panel) {
            if (anc.classList && anc.classList.contains('knowledge-group')) {
                anc.style.display = '';
                anc.setAttribute('open', '');
            }
            anc = anc.parentElement;
        }
    });
    _setEmpty(panel, emptyCls, totalVisible === 0 ? emptyMsg : null);
}
function _resetTree(panel, emptyCls) {
    panel.querySelectorAll('.knowledge-group').forEach(function(g){ g.style.display = ''; });
    panel.querySelectorAll('.knowledge-card').forEach(function(c){
        c.style.display = '';
        _setSnippet(c, []);
    });
    _setEmpty(panel, emptyCls, null);
}

/* --- Knowledge search --- */
export function filterKnowledge(q) {
    _knowledgeSearchQ = q || '';
    _persistSearch('condash.search.knowledge', _knowledgeSearchQ);
    var panel = document.getElementById('knowledge');
    if (!panel) return;
    var qTrim = (q || '').trim();
    _filterTree(panel, _searchTokens(q), qTrim,
        'knowledge-empty', 'No knowledge pages match "' + qTrim + '".');
}

function _persistSearch(key, value) {
    try {
        if (!value) sessionStorage.removeItem(key);
        else sessionStorage.setItem(key, JSON.stringify({value: value}));
    } catch (e) {}
}

/* History pane behavior moved server-side. The input drives htmx
   `hx-get="/fragment/history"` directly (see #history-content in
   dashboard.html); the empty-q tree view and the non-empty results
   list are both rendered by `render_history_pane` in
   condash-render. The two helpers below stay because the
   server-rendered fragment still emits `data-action="open-history-hit"`
   and `data-action="jump-to-project"` on the result rows. */

export function _openHistoryHit(el) {
    var path = el.getAttribute('data-path');
    var label = el.getAttribute('data-label');
    if (path) openNotePreview(path, label || path);
}

export function jumpToProject(btn) {
    var row = btn.closest('.history-result');
    if (!row) return;
    var slug = row.getAttribute('data-slug');
    var sub = row.getAttribute('data-subtab') || 'current';
    switchTab('projects');
    switchSubtab(sub);
    var card = document.getElementById(slug);
    if (!card) return;
    card.classList.remove('collapsed');
    card.scrollIntoView({behavior: 'smooth', block: 'center'});
    card.classList.remove('focus-flash');
    // Re-trigger the animation by forcing a reflow before re-adding.
    void card.offsetWidth;
    card.classList.add('focus-flash');
    setTimeout(function(){ card.classList.remove('focus-flash'); }, 1800);
}

/* Re-apply any active Knowledge search after the DOM is swapped or
   the subtab changes. Safe to call when the search input isn't present
   (other primary tab active). The History pane's equivalent is
   handled by htmx's `hx-trigger="load"` on `#history-content` which
   re-fires the fetch using the (data-preserve-restored) input value. */
export function _reapplySearches() {
    if (_knowledgeSearchQ) {
        var k = document.getElementById('knowledge-search');
        if (k) k.value = _knowledgeSearchQ;
        filterKnowledge(_knowledgeSearchQ);
    }
}


/* Configuration modal — YAML-backed editor for `configuration.yml`.

   Extracted from `dashboard-main.js` as part of C-08 of the
   `2026-04-24-condash-dashboard-main-split` project. Pure behaviour-
   preserving move — same logic, same public surface.

   The module owns:
   - `openConfigModal` / `closeConfigModal` — show and hide the modal,
     fetch the current YAML body on open.
   - `saveConfig` — POST the edited YAML back to `/configuration`.
   - `_populateYamlEditor` — populate the textarea (falling back from
     the CodeMirror-backed view if the CM6 bundle isn't loaded yet).
   - `_getDirtyYamlFile` — returns the YAML body currently being edited
     if it's dirty, or `null`; used by SSE handlers to avoid clobbering.
   - `_cmViews` + `_currentCmTheme` — the CM6-specific bindings used by
     `sections/theme.js` to live-swap themes on toggle.
   - Form-state helpers (`_setField`, `_getField`, `_linesToList`, …)
     kept private to the module. */
/* --- In-app config editor --- */
function _setField(form, name, value) {
    var el = form.elements[name];
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!value;
    else el.value = value == null ? '' : value;
}

function _getField(form, name) {
    var el = form.elements[name];
    if (!el) return null;
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'number') return el.value === '' ? 0 : Number(el.value);
    return el.value;
}

function _linesToList(text) {
    return (text || '').split('\n').map(function(s){return s.trim();}).filter(function(s){return s.length;});
}

function _listToLines(list) {
    return (list || []).join('\n');
}

/* Parse a repositories textarea. Each non-empty line is either
   "name" or "name: sub/a, sub/b" — colons inside submodule paths are
   preserved because we only split on the FIRST colon. */
function _linesToRepos(text) {
    return _linesToList(text).map(function(line){
        var idx = line.indexOf(':');
        if (idx < 0) return {name: line, submodules: []};
        var name = line.slice(0, idx).trim();
        var subs = line.slice(idx + 1).split(',')
            .map(function(s){return s.trim();})
            .filter(function(s){return s.length;});
        return {name: name, submodules: subs};
    }).filter(function(entry){return entry.name.length;});
}

function _reposToLines(entries) {
    return (entries || []).map(function(entry){
        if (!entry || !entry.name) return '';
        var subs = entry.submodules || [];
        return subs.length ? (entry.name + ': ' + subs.join(', ')) : entry.name;
    }).filter(function(s){return s.length;}).join('\n');
}

function _setSlotFields(form, slotKey, slot) {
    var container = form.querySelector('[data-slot="' + slotKey + '"]');
    if (!container || !slot) return;
    container.querySelector('[data-field="label"]').value = slot.label || '';
    container.querySelector('[data-field="commands"]').value = _listToLines(slot.commands);
}

function _readSlotFields(form, slotKey) {
    var container = form.querySelector('[data-slot="' + slotKey + '"]');
    if (!container) return null;
    return {
        label: container.querySelector('[data-field="label"]').value || '',
        commands: _linesToList(container.querySelector('[data-field="commands"]').value),
    };
}

function switchConfigTab(name) {
    var tabs = document.querySelectorAll('#config-form .config-tab');
    tabs.forEach(function(t){
        t.classList.toggle('active', t.getAttribute('data-config-tab') === name);
    });
    var panes = document.querySelectorAll('#config-form .config-tab-pane');
    panes.forEach(function(p){
        p.classList.toggle('active', p.getAttribute('data-config-pane') === name);
    });
    // Widen the modal on YAML-backed tabs (split pane wants ~1080px).
    // The General tab stays at the original 720px for a less empty feel.
    var modal = document.querySelector('#config-modal .config-modal');
    if (modal) {
        modal.classList.toggle('config-modal-wide', name !== 'general');
    }
}

function _setYamlSourceHint(elId, source, expected, label) {
    var el = document.getElementById(elId);
    if (!el) return;
    if (source) {
        el.innerHTML = 'These fields are stored in <code>' + source + '</code>.';
    } else if (expected) {
        el.innerHTML = 'These fields migrate to <code>' + expected + '</code> on the next Save.';
    } else {
        el.innerHTML = 'Set a <code>conception_path</code> on the General tab to move these fields into <code>' + label + '</code>.';
    }
    el.style.display = '';
}

export async function openConfigModal() {
    var modal = document.getElementById('config-modal');
    var ta = document.getElementById('config-yaml');
    var errEl = document.getElementById('config-error');
    var okEl = document.getElementById('config-saved');
    var pathEl = document.getElementById('config-file-path');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    modal.style.display = 'flex';
    try {
        var res = await fetch('/configuration');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        ta.value = await res.text();
        var path = res.headers.get('X-Condash-Config-Path');
        if (path && pathEl) pathEl.textContent = path;
        // Defer focus so the modal is laid out before we position the cursor.
        setTimeout(function() { ta.focus(); ta.setSelectionRange(0, 0); }, 0);
    } catch (e) {
        errEl.textContent = 'Could not load configuration.yml: ' + e;
        errEl.style.display = 'block';
    }
}

/* Split-pane YAML pane: populate the textarea with raw YAML and stash
   its pristine value so saveConfig can detect local edits. The status
   badge flips to "edited" on input and back to "synced" once the diff
   against pristine is zero. When ``preserveDirty`` is true and the
   user has unsaved edits, we don't overwrite — an external live-reload
   event would otherwise blow away their in-flight work.

   When the CodeMirror 6 bundle (``window.CondashCM``) has loaded, we
   swap the textarea for a real editor (syntax highlight, gutter, the
   whole thing) and keep the original textarea hidden but in the DOM —
   its value stays mirrored so ``_getDirtyYamlFile`` keeps working
   without ever poking at CM6 APIs. If the bundle hasn't arrived yet
   (defer script still loading) we fall back to the textarea for this
   paint; once the modal reopens, CM6 is wired. */
export var _cmViews = {};  // which → EditorView
export function _populateYamlEditor(which, body, preserveDirty) {
    var ta = document.querySelector('#config-form textarea[data-yaml-file="' + which + '"]');
    if (!ta) return;
    var dirty = ta.classList.contains('config-yaml-dirty');
    if (preserveDirty && dirty) return;
    if (window.CondashCM) {
        _populateYamlEditorCM(which, ta, body);
        return;
    }
    // Fallback: plain textarea.
    ta.value = body;
    ta.dataset.pristine = body;
    ta.classList.remove('config-yaml-dirty');
    _setYamlStatus(which, 'synced');
    if (!ta.dataset.boundInput) {
        ta.addEventListener('input', function() {
            var pristine = ta.dataset.pristine || '';
            if (ta.value !== pristine) {
                ta.classList.add('config-yaml-dirty');
                _setYamlStatus(which, 'edited — unsaved');
            } else {
                ta.classList.remove('config-yaml-dirty');
                _setYamlStatus(which, 'synced');
            }
        });
        ta.dataset.boundInput = '1';
    }
}

/* CodeMirror-backed pane. On first call for a given file we create an
   EditorView next to the textarea and hide the textarea; subsequent
   calls dispatch a full-document replace transaction. The textarea's
   value is kept in sync via the CM updateListener so the rest of the
   save pipeline can keep reading ``ta.value``. */
function _populateYamlEditorCM(which, ta, body) {
    var CM = window.CondashCM;
    var view = _cmViews[which];
    var themeComp = ta._cmThemeComp;
    if (!view) {
        ta.style.display = 'none';
        themeComp = new CM.Compartment();
        ta._cmThemeComp = themeComp;
        var wrap = document.createElement('div');
        wrap.className = 'config-yaml-editor config-yaml-cm';
        ta.parentNode.insertBefore(wrap, ta.nextSibling);
        var extensions = [
            CM.basicSetup,
            CM.yamlLang(),
            themeComp.of(_currentCmTheme()),
            CM.EditorView.updateListener.of(function(update) {
                if (!update.docChanged) return;
                ta.value = update.state.doc.toString();
                var pristine = ta.dataset.pristine || '';
                if (ta.value !== pristine) {
                    ta.classList.add('config-yaml-dirty');
                    wrap.classList.add('config-yaml-dirty');
                    _setYamlStatus(which, 'edited — unsaved');
                } else {
                    ta.classList.remove('config-yaml-dirty');
                    wrap.classList.remove('config-yaml-dirty');
                    _setYamlStatus(which, 'synced');
                }
            }),
        ];
        try {
            view = new CM.EditorView({
                doc: body,
                extensions: extensions,
                parent: wrap,
            });
            _cmViews[which] = view;
        } catch (err) {
            console.warn('[condash] CodeMirror mount failed for', which, err);
            ta.style.display = '';
            wrap.remove();
            return;
        }
    } else {
        view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: body },
        });
        // Re-apply current theme in case the user toggled light/dark
        // while the modal was closed.
        if (themeComp) {
            view.dispatch({ effects: themeComp.reconfigure(_currentCmTheme()) });
        }
    }
    ta.value = body;
    ta.dataset.pristine = body;
    ta.classList.remove('config-yaml-dirty');
    view.dom.classList.remove('config-yaml-dirty');
    _setYamlStatus(which, 'synced');
}

export function _currentCmTheme() {
    var theme = document.documentElement.getAttribute('data-theme') || 'light';
    return theme === 'dark' ? window.CondashCM.oneDark : [];
}

function _setYamlStatus(which, label) {
    var badge = document.querySelector('[data-yaml-status="' + which + '"]');
    if (badge) badge.textContent = label;
}

export function _getDirtyYamlFile() {
    var dirtyTa = document.querySelector('#config-form textarea.config-yaml-editor.config-yaml-dirty');
    if (!dirtyTa) return null;
    return {
        file: dirtyTa.getAttribute('data-yaml-file'),
        body: dirtyTa.value,
    };
}

export function closeConfigModal() {
    document.getElementById('config-modal').style.display = 'none';
}

export async function saveConfig(ev) {
    ev.preventDefault();
    var ta = document.getElementById('config-yaml');
    var errEl = document.getElementById('config-error');
    var okEl = document.getElementById('config-saved');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    try {
        var res = await fetch('/configuration', {
            method: 'POST',
            headers: {'Content-Type': 'text/yaml; charset=utf-8'},
            body: ta.value,
        });
        if (res.ok) {
            okEl.textContent = 'Saved. Close and reopen condash for changes to take effect.';
            okEl.style.display = 'block';
        } else {
            var msg = await res.text();
            errEl.textContent = 'Save rejected (' + res.status + '): ' + msg;
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = 'Save failed: ' + e;
        errEl.style.display = 'block';
    }
}

/* Delegated click dispatch for server-rendered markup.

   Server-rendered HTML uses `data-action="<name>"` + optional `data-*`
   attributes to declare clickable behaviour. A single document-level
   click listener reads `target.closest('[data-action]')` and routes to
   a registered handler. This removes the need to park every handler on
   `window` for inline `onclick="..."` attributes to reach it — those
   attrs are gone entirely as of this module.

   Handler signature: `handler(event, el, dataset)` where `el` is the
   element carrying `data-action` and `dataset` is `el.dataset` (read-
   only copy of the data-* attrs). Return value is ignored.

   Attribute modifiers on the click source:
   - `data-stop="1"`  → call `event.stopPropagation()` before dispatch.
   - `data-prevent="1"` → call `event.preventDefault()` before dispatch.

   Registration is one-time and uses the exported `registerAction(name,
   handler)`. Double-registration throws so a typo or collision surfaces
   at boot rather than becoming a silent override. */

const _actions = new Map();

export function registerAction(name, handler) {
    if (typeof name !== 'string' || !name) {
        throw new Error('registerAction: name must be a non-empty string');
    }
    if (typeof handler !== 'function') {
        throw new Error(`registerAction(${name}): handler must be a function`);
    }
    if (_actions.has(name)) {
        throw new Error(`registerAction(${name}): already registered`);
    }
    _actions.set(name, handler);
}

export function initActionDispatch() {
    document.addEventListener('click', function(event) {
        const el = event.target.closest('[data-action]');
        if (!el) return;
        const name = el.dataset.action;
        const handler = _actions.get(name);
        if (!handler) return;
        if (el.dataset.stop === '1') event.stopPropagation();
        if (el.dataset.prevent === '1') event.preventDefault();
        handler(event, el, el.dataset);
    });
}

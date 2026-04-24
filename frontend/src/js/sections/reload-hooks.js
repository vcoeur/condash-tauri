/* Post-reload hook registry.

   Subsystems that need to reattach to freshly-inserted DOM after a
   global or fragment swap register via `onPostReload(fn)`. The two
   DOM-swap entry points (`_reloadInPlace` in dashboard-main.js and
   `reloadNode` in stale-poll.js) call `firePostReloadHooks()` once
   the new markup is in place.

   This replaces the pre-ESM `window._reloadInPlace = wrappedFn` trick,
   which silently stopped working under bundled ESM: module-scope
   callers resolve `_reloadInPlace` against the ESM import binding, not
   the window property, so the wrapper never ran. */

const _hooks = [];

export function onPostReload(fn) {
    if (typeof fn !== 'function') return;
    _hooks.push(fn);
}

export function firePostReloadHooks() {
    for (var i = 0; i < _hooks.length; i++) {
        try { _hooks[i](); } catch (e) {}
    }
}

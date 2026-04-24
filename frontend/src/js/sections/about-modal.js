/* About modal — open/close + the "links open in host browser" shim.
   Static content (version baked in at render time, links hit the host
   browser via /open-external because pywebview swallows target=_blank).

   Extracted from dashboard-main.js on 2026-04-24 (P-08 of
   conception/projects/2026-04-23-condash-frontend-extraction). No
   cross-module references — the document-level click listener is
   registered from initAboutModalSideEffects(), called from
   dashboard-main.js's tail. */

function openAboutModal() {
    document.getElementById('about-modal').style.display = 'flex';
}

function closeAboutModal() {
    document.getElementById('about-modal').style.display = 'none';
}

function initAboutModalSideEffects() {
    document.addEventListener('click', function(ev) {
        var a = ev.target.closest && ev.target.closest('#about-modal a[data-about-link]');
        if (!a) return;
        ev.preventDefault();
        fetch('/open-external', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: a.getAttribute('href')}),
        });
    });
}

export { openAboutModal, closeAboutModal, initAboutModalSideEffects };

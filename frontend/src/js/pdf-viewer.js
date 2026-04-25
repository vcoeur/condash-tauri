/* PDF.js viewer bootstrap.
   Loads the vendored pdfjs-dist library (under /vendor/pdfjs/ — served
   by the axum host's `/vendor/{*path}` route) and exposes
   `window.__pdfjs = { mount(host), ready, error? }`. The note-preview
   module's `_mountPdfsIn(container)` walks every `.note-pdf-host` it
   finds and either calls `mount()` immediately when this module has
   resolved or marks the host with `data-pdf-pending="1"` so the IIFE
   below can flush it once ready.

   Why a custom viewer instead of stock pdfjs-dist web/viewer.html:
   * condash theme (toolbar uses --bg-card, --border, --accent, …);
   * no ~10 MB of unused viewer assets (locale strings, thumbnail panel,
     annotation editor UI, print preview);
   * direct access to the rendering loop for the modal's
     note-search-bar (Find in PDF). */
(async function() {
    const COMMON = {
        cMapUrl: '/vendor/pdfjs/cmaps/',
        cMapPacked: true,
        standardFontDataUrl: '/vendor/pdfjs/standard_fonts/',
        wasmUrl: '/vendor/pdfjs/wasm/',
        iccUrl: '/vendor/pdfjs/iccs/',
    };
    const ZOOM_STOPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];
    const FIT_WIDTH = 'fit-width';
    const FIT_PAGE = 'fit-page';
    const ACTUAL = 'actual';

    let pdfjsLib;
    try {
        pdfjsLib = await import('/vendor/pdfjs/build/pdf.mjs');
        pdfjsLib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/build/pdf.worker.mjs';
    } catch (err) {
        console.warn('[condash] PDF.js failed to load:', err);
        window.__pdfjs = { ready: false, error: err };
        const pending = document.querySelectorAll('.note-pdf-host[data-pdf-pending="1"]');
        pending.forEach(function(h) {
            delete h.dataset.pdfPending;
            h.innerHTML = '<div class="pdf-error">PDF viewer failed to load.</div>';
        });
        return;
    }

    /* Render the toolbar + lazy-rendered pages into `host`. Idempotent —
       guarded by host.dataset.mounted. Pages are sized up-front so
       scrolling works immediately; each page's canvas + text layer are
       drawn on first intersection with the viewport. */
    async function mount(host) {
        if (host.dataset.mounted === '1') return;
        host.dataset.mounted = '1';
        const src = host.dataset.pdfSrc;
        const filename = host.dataset.pdfFilename || 'document.pdf';
        host.innerHTML = '';

        // --- Toolbar ---
        const tb = document.createElement('div');
        tb.className = 'pdf-toolbar';
        const safeName = filename.replace(/"/g, '&quot;');
        tb.innerHTML = [
            '<button class="pdf-thumbs" title="Toggle thumbnails (T)" aria-label="Toggle thumbnails">\u25A4</button>',
            '<div class="pdf-toolbar-spacer" style="flex:0 0 0.5rem"></div>',
            '<button class="pdf-prev" title="Previous page (\u2190, PgUp)" aria-label="Previous page">\u2190</button>',
            '<span class="pdf-pageinfo">',
            '  <span class="pdf-page-label">Page</span>',
            '  <input class="pdf-page-input" type="number" min="1" value="1" aria-label="Page number">',
            '  <span class="pdf-total">/ ?</span>',
            '</span>',
            '<button class="pdf-next" title="Next page (\u2192, PgDn)" aria-label="Next page">\u2192</button>',
            '<span class="pdf-goto-hint" aria-live="polite"></span>',
            '<div class="pdf-toolbar-spacer"></div>',
            '<button class="pdf-fit" data-fit="fit-width" title="Fit width (W)" aria-label="Fit width">Width</button>',
            '<button class="pdf-fit" data-fit="fit-page" title="Fit page (P)" aria-label="Fit page">Page</button>',
            '<button class="pdf-fit" data-fit="actual" title="Actual size (1)" aria-label="Actual size">1:1</button>',
            '<div class="pdf-toolbar-spacer" style="flex:0 0 0.5rem"></div>',
            '<button class="pdf-zoom-out" title="Zoom out (\u2212)" aria-label="Zoom out">\u2212</button>',
            '<span class="pdf-zoom-label">\u2014</span>',
            '<button class="pdf-zoom-in" title="Zoom in (+)" aria-label="Zoom in">+</button>',
            '<div class="pdf-toolbar-spacer" style="flex:0 0 0.5rem"></div>',
            '<a class="pdf-dl" href="' + src + '" download="' + safeName + '" title="Download" aria-label="Download">\u2193</a>',
        ].join('');
        host.appendChild(tb);

        // --- Body: optional thumbnail sidebar + main pages area ---
        const body = document.createElement('div');
        body.className = 'pdf-body';
        host.appendChild(body);

        const sidebar = document.createElement('aside');
        sidebar.className = 'pdf-sidebar';
        sidebar.hidden = true;
        body.appendChild(sidebar);

        const pagesEl = document.createElement('div');
        pagesEl.className = 'pdf-pages';
        pagesEl.tabIndex = 0;
        pagesEl.innerHTML = '<div class="pdf-loading">Loading PDF\u2026</div>';
        body.appendChild(pagesEl);

        let pdf;
        try {
            pdf = await pdfjsLib.getDocument(Object.assign({ url: src }, COMMON)).promise;
        } catch (e) {
            const err = document.createElement('div');
            err.className = 'pdf-error';
            err.textContent = 'Failed to load PDF: ' + (e && e.message ? e.message : String(e));
            pagesEl.replaceChildren(err);
            return;
        }

        let currentScale = FIT_WIDTH;
        let pageWrappers = [];
        let thumbWrappers = [];
        let renderSeq = 0;           // cancels stale renders when scale changes
        let findSeq = 0;             // cancels stale find runs
        let pageIo = null;
        let lazyIo = null;
        let thumbIo = null;
        const findState = { query: '', matches: [], idx: -1 };

        function destroyObservers() {
            if (lazyIo) lazyIo.disconnect();
            if (pageIo) pageIo.disconnect();
            lazyIo = null; pageIo = null;
        }

        /* Resolve a scale mode to a concrete number using page 1's natural
           size at scale=1. */
        function resolveScale(mode, vp1) {
            if (typeof mode === 'number') return mode;
            if (mode === ACTUAL) return 1;
            if (mode === FIT_PAGE) {
                const availW = Math.max(200, pagesEl.clientWidth - 32);
                const availH = Math.max(200, pagesEl.clientHeight - 32);
                return Math.min(availW / vp1.width, availH / vp1.height);
            }
            // FIT_WIDTH (default)
            const avail = Math.max(200, pagesEl.clientWidth - 32);
            return avail / vp1.width;
        }

        function updateFitButtons() {
            tb.querySelectorAll('.pdf-fit').forEach(function(b) {
                b.classList.toggle('is-active',
                    typeof currentScale === 'string' && b.dataset.fit === currentScale);
            });
        }

        async function renderAll() {
            const seq = ++renderSeq;
            destroyObservers();
            const p1 = await pdf.getPage(1);
            const vp1 = p1.getViewport({ scale: 1 });
            const scale = resolveScale(currentScale, vp1);
            tb.querySelector('.pdf-zoom-label').textContent = Math.round(scale * 100) + '%';
            tb.querySelector('.pdf-total').textContent = '/ ' + pdf.numPages;
            tb.querySelector('.pdf-page-input').max = String(pdf.numPages);
            updateFitButtons();

            pagesEl.innerHTML = '';
            pageWrappers = [];
            for (let i = 1; i <= pdf.numPages; i++) {
                const wrap = document.createElement('div');
                wrap.className = 'pdf-page';
                wrap.dataset.page = String(i);
                pagesEl.appendChild(wrap);
                pageWrappers.push(wrap);
            }

            // Pre-size every wrapper so the scrollbar reflects the full doc.
            for (let i = 1; i <= pdf.numPages; i++) {
                const p = await pdf.getPage(i);
                if (seq !== renderSeq) return;
                const vp = p.getViewport({ scale });
                const w = pageWrappers[i - 1];
                w.style.width = vp.width + 'px';
                w.style.height = vp.height + 'px';
            }

            // Lazy-render canvases on first intersection.
            lazyIo = new IntersectionObserver(function(entries) {
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue;
                    const w = entry.target;
                    if (w.dataset.rendered === '1' || w.dataset.rendering === '1') continue;
                    w.dataset.rendering = '1';
                    const i = Number(w.dataset.page);
                    renderPage(seq, i, w, scale).catch(function(err) {
                        console.warn('[pdfjs] page', i, 'render failed:', err);
                    });
                }
            }, { root: pagesEl, rootMargin: '400px' });
            pageWrappers.forEach(function(w) { lazyIo.observe(w); });

            // Track which page is most visible to drive the page input +
            // active thumbnail.
            const inp = tb.querySelector('.pdf-page-input');
            pageIo = new IntersectionObserver(function(entries) {
                let best = null, bestRatio = 0;
                for (const e of entries) {
                    if (e.intersectionRatio > bestRatio) {
                        bestRatio = e.intersectionRatio;
                        best = e.target;
                    }
                }
                if (best) {
                    const n = Number(best.dataset.page);
                    if (document.activeElement !== inp) inp.value = String(n);
                    setActiveThumb(n);
                }
            }, { root: pagesEl, threshold: [0.25, 0.5, 0.75] });
            pageWrappers.forEach(function(w) { pageIo.observe(w); });
        }

        async function renderPage(seq, i, wrap, scale) {
            const page = await pdf.getPage(i);
            if (seq !== renderSeq) return;
            const vp = page.getViewport({ scale });
            const canvas = document.createElement('canvas');
            const dpr = window.devicePixelRatio || 1;
            canvas.width = Math.floor(vp.width * dpr);
            canvas.height = Math.floor(vp.height * dpr);
            canvas.style.width = vp.width + 'px';
            canvas.style.height = vp.height + 'px';
            wrap.appendChild(canvas);
            const ctx = canvas.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            await page.render({ canvasContext: ctx, viewport: vp }).promise;
            if (seq !== renderSeq) return;
            // Text layer — enables selection + per-layer search marks.
            try {
                const txt = await page.getTextContent();
                if (seq !== renderSeq) return;
                const layer = document.createElement('div');
                layer.className = 'textLayer';
                layer.style.width = vp.width + 'px';
                layer.style.height = vp.height + 'px';
                wrap.appendChild(layer);
                if (pdfjsLib.TextLayer) {
                    const tl = new pdfjsLib.TextLayer({
                        textContentSource: txt, container: layer, viewport: vp,
                    });
                    await tl.render();
                }
                // Re-apply active search marks to this page's fresh text layer.
                if (findState.query) {
                    markInSubtree(layer, findState.query, findState.matches);
                }
            } catch (e) { /* text layer is best-effort */ }
            wrap.dataset.rendered = '1';
            delete wrap.dataset.rendering;
        }

        // --- Sidebar thumbnails ---
        function buildThumbs() {
            if (thumbWrappers.length === pdf.numPages) return;
            sidebar.innerHTML = '';
            thumbWrappers = [];
            for (let i = 1; i <= pdf.numPages; i++) {
                const tw = document.createElement('div');
                tw.className = 'pdf-thumb';
                tw.dataset.page = String(i);
                tw.style.width = '120px'; tw.style.height = '160px';
                const lbl = document.createElement('span');
                lbl.className = 'pdf-thumb-label';
                lbl.textContent = String(i);
                tw.appendChild(lbl);
                tw.addEventListener('click', function() { gotoPage(i); });
                sidebar.appendChild(tw);
                thumbWrappers.push(tw);
            }
            if (thumbIo) thumbIo.disconnect();
            thumbIo = new IntersectionObserver(function(entries) {
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue;
                    const tw = entry.target;
                    if (tw.dataset.rendered === '1' || tw.dataset.rendering === '1') continue;
                    tw.dataset.rendering = '1';
                    const i = Number(tw.dataset.page);
                    renderThumb(i, tw).catch(function(err) {
                        console.warn('[pdfjs] thumb', i, 'render failed:', err);
                    });
                }
            }, { root: sidebar, rootMargin: '200px' });
            thumbWrappers.forEach(function(tw) { thumbIo.observe(tw); });
            // Reflect the current page immediately.
            setActiveThumb(Number(tb.querySelector('.pdf-page-input').value) || 1);
        }

        async function renderThumb(i, tw) {
            const page = await pdf.getPage(i);
            const vp0 = page.getViewport({ scale: 1 });
            const scale = 120 / vp0.width;
            const vp = page.getViewport({ scale });
            const canvas = document.createElement('canvas');
            const dpr = window.devicePixelRatio || 1;
            canvas.width = Math.floor(vp.width * dpr);
            canvas.height = Math.floor(vp.height * dpr);
            canvas.style.width = vp.width + 'px';
            canvas.style.height = vp.height + 'px';
            const ctx = canvas.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            await page.render({ canvasContext: ctx, viewport: vp }).promise;
            tw.style.width = vp.width + 'px';
            tw.style.height = vp.height + 'px';
            tw.insertBefore(canvas, tw.firstChild);
            tw.dataset.rendered = '1';
            delete tw.dataset.rendering;
        }

        function setActiveThumb(n) {
            if (!thumbWrappers.length) return;
            thumbWrappers.forEach(function(tw) {
                const isActive = Number(tw.dataset.page) === n;
                tw.classList.toggle('is-active', isActive);
                if (isActive && !sidebar.hidden) {
                    tw.scrollIntoView({ block: 'nearest' });
                }
            });
        }

        function toggleSidebar() {
            sidebar.hidden = !sidebar.hidden;
            tb.querySelector('.pdf-thumbs').classList.toggle('is-active', !sidebar.hidden);
            if (!sidebar.hidden) buildThumbs();
        }

        await renderAll();

        // --- Controls ---
        const inp = tb.querySelector('.pdf-page-input');
        function gotoPage(n) {
            n = Math.max(1, Math.min(pdf.numPages, n | 0));
            inp.value = String(n);
            pageWrappers[n - 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
            setActiveThumb(n);
        }
        function setFit(mode) { currentScale = mode; renderAll(); }
        function zoomStep(dir) {
            const cur = parseFloat(tb.querySelector('.pdf-zoom-label').textContent) / 100;
            if (dir > 0) {
                currentScale = ZOOM_STOPS.find(function(s) { return s > cur + 0.001; })
                             || ZOOM_STOPS[ZOOM_STOPS.length - 1];
            } else {
                let next = ZOOM_STOPS[0];
                for (const s of ZOOM_STOPS) { if (s < cur - 0.001) next = s; }
                currentScale = next;
            }
            renderAll();
        }

        inp.addEventListener('change', function() { gotoPage(Number(inp.value) || 1); });
        tb.querySelector('.pdf-prev').addEventListener('click', function() {
            gotoPage((Number(inp.value) || 1) - 1);
        });
        tb.querySelector('.pdf-next').addEventListener('click', function() {
            gotoPage((Number(inp.value) || 1) + 1);
        });
        tb.querySelector('.pdf-zoom-in').addEventListener('click', function() { zoomStep(+1); });
        tb.querySelector('.pdf-zoom-out').addEventListener('click', function() { zoomStep(-1); });
        tb.querySelectorAll('.pdf-fit').forEach(function(b) {
            b.addEventListener('click', function() { setFit(b.dataset.fit); });
        });
        tb.querySelector('.pdf-thumbs').addEventListener('click', toggleSidebar);

        // Vim-style `g<N>` page jump. Active while a digit is being typed;
        // commits on Enter / timeout, cancels on Escape / any other key.
        const gotoHint = tb.querySelector('.pdf-goto-hint');
        const gotoBuf = {
            active: false, digits: '', timer: null,
            start: function() { this.active = true; this.digits = ''; this._render(); this._arm(); },
            push: function(d) { this.digits += d; this._render(); this._arm(); },
            commit: function() {
                if (this.digits) gotoPage(parseInt(this.digits, 10));
                this.cancel();
            },
            cancel: function() {
                clearTimeout(this.timer); this.timer = null;
                this.active = false; this.digits = ''; this._render();
            },
            _arm: function() {
                clearTimeout(this.timer);
                const self = this;
                this.timer = setTimeout(function() { self.commit(); }, 1500);
            },
            _render: function() {
                gotoHint.textContent = this.active ? ('goto ' + (this.digits || '\u2026')) : '';
            },
        };

        pagesEl.addEventListener('keydown', function(ev) {
            if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
            const key = ev.key;
            if (gotoBuf.active) {
                if (/^[0-9]$/.test(key)) { ev.preventDefault(); gotoBuf.push(key); return; }
                if (key === 'Enter') { ev.preventDefault(); gotoBuf.commit(); return; }
                if (key === 'Escape') { ev.preventDefault(); gotoBuf.cancel(); return; }
                gotoBuf.cancel();  // fall through and handle as normal
            }
            const cur = Number(inp.value) || 1;
            if (key === '+' || key === '=') { ev.preventDefault(); zoomStep(+1); }
            else if (key === '-' || key === '_') { ev.preventDefault(); zoomStep(-1); }
            else if (key === '0') { ev.preventDefault(); setFit(FIT_WIDTH); }
            else if (key === 'w' || key === 'W') { ev.preventDefault(); setFit(FIT_WIDTH); }
            else if (key === 'p' || key === 'P') { ev.preventDefault(); setFit(FIT_PAGE); }
            else if (key === '1') { ev.preventDefault(); setFit(ACTUAL); }
            else if (key === 'PageDown' || key === 'ArrowRight') { ev.preventDefault(); gotoPage(cur + 1); }
            else if (key === 'PageUp' || key === 'ArrowLeft') { ev.preventDefault(); gotoPage(cur - 1); }
            else if (key === 'Home') { ev.preventDefault(); gotoPage(1); }
            else if (key === 'End') { ev.preventDefault(); gotoPage(pdf.numPages); }
            else if (key === 't' || key === 'T') { ev.preventDefault(); toggleSidebar(); }
            else if (key === 'g' || key === 'G') { ev.preventDefault(); gotoBuf.start(); }
        });

        // Re-fit when the viewport resizes (only relevant for symbolic fits).
        if (typeof ResizeObserver !== 'undefined') {
            let t;
            const ro = new ResizeObserver(function() {
                if (typeof currentScale === 'number') return;
                clearTimeout(t);
                t = setTimeout(function() { renderAll(); }, 150);
            });
            ro.observe(pagesEl);
        }

        /* --- Find in PDF ---
           Exposed on host.__pdfFind so the dashboard's note-search-bar can
           reach it when the modal contains a PDF. Strategy: run the same
           text-walker used for the note view pane over every page's
           textLayer. Any page that hasn't been lazy-rendered yet is forced
           to render first so marks have somewhere to land. */
        function markInSubtree(root, q, collected) {
            const qLow = q.toLowerCase();
            const qLen = q.length;
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
                acceptNode: function(n) {
                    const tag = n.parentNode && n.parentNode.nodeName;
                    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK') {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return NodeFilter.FILTER_ACCEPT;
                }
            });
            const textNodes = [];
            let node;
            while ((node = walker.nextNode())) textNodes.push(node);
            textNodes.forEach(function(n) {
                const low = n.nodeValue.toLowerCase();
                const positions = [];
                let pos = 0;
                while ((pos = low.indexOf(qLow, pos)) !== -1) {
                    positions.push(pos); pos += qLen;
                }
                for (let i = positions.length - 1; i >= 0; i--) {
                    const start = positions[i];
                    const matchNode = n.splitText(start);
                    matchNode.splitText(qLen);
                    const mark = document.createElement('mark');
                    mark.className = 'note-match';
                    matchNode.parentNode.replaceChild(mark, matchNode);
                    mark.appendChild(matchNode);
                    collected.push(mark);
                }
            });
        }

        async function ensureAllRendered() {
            const p1 = await pdf.getPage(1);
            const vp1 = p1.getViewport({ scale: 1 });
            const scale = resolveScale(currentScale, vp1);
            const tasks = [];
            for (let i = 0; i < pageWrappers.length; i++) {
                const w = pageWrappers[i];
                if (w.dataset.rendered !== '1' && w.dataset.rendering !== '1') {
                    w.dataset.rendering = '1';
                    tasks.push(renderPage(renderSeq, Number(w.dataset.page), w, scale));
                }
            }
            if (tasks.length) await Promise.allSettled(tasks);
        }

        function clearFindMarks() {
            pagesEl.querySelectorAll('mark.note-match').forEach(function(m) {
                const parent = m.parentNode;
                while (m.firstChild) parent.insertBefore(m.firstChild, m);
                parent.removeChild(m);
            });
            pagesEl.querySelectorAll('.textLayer').forEach(function(l) { l.normalize(); });
        }

        async function findRun(query) {
            const seq = ++findSeq;
            findState.query = query || '';
            clearFindMarks();
            findState.matches = [];
            findState.idx = -1;
            if (!findState.query) return findState;
            await ensureAllRendered();
            if (seq !== findSeq) return findState;
            // Walk pages in order so matches come out sorted.
            for (let i = 0; i < pageWrappers.length; i++) {
                if (seq !== findSeq) return findState;
                const layer = pageWrappers[i].querySelector('.textLayer');
                if (layer) markInSubtree(layer, findState.query, findState.matches);
            }
            if (findState.matches.length) {
                findState.idx = 0;
                const m = findState.matches[0];
                m.classList.add('active');
                scrollMatchIntoView(m);
            }
            return findState;
        }

        function findStep(dir) {
            const n = findState.matches.length;
            if (!n) return findState;
            if (findState.idx >= 0) findState.matches[findState.idx].classList.remove('active');
            findState.idx = (findState.idx + dir + n) % n;
            const m = findState.matches[findState.idx];
            m.classList.add('active');
            scrollMatchIntoView(m);
            return findState;
        }

        function scrollMatchIntoView(m) {
            // Scroll the match's page into view first (it might be outside
            // the pagesEl viewport) before centring on the mark.
            const wrap = m.closest('.pdf-page');
            if (wrap) {
                const n = Number(wrap.dataset.page);
                inp.value = String(n);
                setActiveThumb(n);
            }
            m.scrollIntoView({ block: 'center' });
        }

        function findClose() {
            findState.query = '';
            clearFindMarks();
            findState.matches = [];
            findState.idx = -1;
        }

        host.__pdfFind = {
            run: findRun, step: findStep, close: findClose, state: findState,
        };

        pagesEl.focus();
    }

    window.__pdfjs = { mount: mount, ready: true };

    // Flush any hosts that were marked pending before we finished loading.
    const pending = document.querySelectorAll('.note-pdf-host[data-pdf-pending="1"]');
    pending.forEach(function(h) {
        delete h.dataset.pdfPending;
        h.innerHTML = '';
        mount(h);
    });
})();

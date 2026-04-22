"""Guard against post-split ReferenceError regressions on inline onclick handlers.

The v0.20.0 frontend split moved ``dashboard-main.js`` into an esbuild IIFE
bundle (``--format=iife --global-name=Condash``), so top-level ``function``
declarations are scoped to the IIFE and no longer leak onto ``window``.
Inline ``onclick="foo(...)"`` attributes emitted from ``render.py``, Jinja
templates, or ``dashboard.html`` are resolved against ``window`` at click
time, so every such handler must be re-exported by the explicit
``Object.assign(window, { ... })`` block at the bottom of
``dashboard-main.js``.

Two regressions of this exact shape shipped on the same day (v0.20.1
restored ``runnerStart``/``runnerStop``/``runnerSwitch``; v0.20.2 restored
``openPath``) — both because the manual re-export list drifted out of sync
with the set of inline handlers. This test fails fast when that happens.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "condash" / "assets"
TEMPLATES = ROOT / "src" / "condash" / "templates"
RENDER_PY = ROOT / "src" / "condash" / "render.py"
DASHBOARD_HTML = ASSETS / "dashboard.html"
DASHBOARD_MAIN_JS = ASSETS / "src" / "js" / "dashboard-main.js"

ONCLICK_RE = re.compile(r'onclick=\\?"([A-Za-z_][A-Za-z0-9_]*)\(')
# JS reserved words that can legitimately appear as the first token of an
# inline onclick body (e.g. `onclick="if(event.target===this)close()"`).
# These are control flow, not handler names.
JS_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "return", "throw", "new", "typeof",
    "void", "delete", "do", "try", "function", "var", "let", "const",
})
EXPORT_BLOCK_RE = re.compile(
    r"Object\.assign\(\s*window\s*,\s*\{(?P<body>.*?)\}\s*\)\s*;",
    re.DOTALL,
)
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _collect_onclick_handlers() -> dict[str, list[Path]]:
    sources: list[Path] = [RENDER_PY, DASHBOARD_HTML, *sorted(TEMPLATES.glob("*.j2"))]
    found: dict[str, list[Path]] = {}
    for path in sources:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for name in ONCLICK_RE.findall(text):
            if name in JS_KEYWORDS:
                continue
            found.setdefault(name, []).append(path)
    return found


def _collect_window_exports() -> set[str]:
    text = DASHBOARD_MAIN_JS.read_text(encoding="utf-8")
    blocks = EXPORT_BLOCK_RE.findall(text)
    assert blocks, (
        f"No `Object.assign(window, {{ ... }})` block found in {DASHBOARD_MAIN_JS}. "
        "The inline-onclick re-export site was removed or renamed — update this test."
    )
    exported: set[str] = set()
    for body in blocks:
        stripped = re.sub(r"//.*", "", body)
        stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
        exported.update(IDENT_RE.findall(stripped))
    return exported


def test_every_inline_onclick_handler_is_exported_on_window():
    handlers = _collect_onclick_handlers()
    assert handlers, (
        "Expected at least one inline `onclick=\"<name>(` in render.py / templates / "
        "dashboard.html — the collector regex is probably broken."
    )
    exported = _collect_window_exports()
    missing = {name: paths for name, paths in handlers.items() if name not in exported}
    if missing:
        lines = ["Inline onclick handlers missing from `Object.assign(window, { ... })` in dashboard-main.js:"]
        for name, paths in sorted(missing.items()):
            rels = ", ".join(str(p.relative_to(ROOT)) for p in paths)
            lines.append(f"  - {name}  (used in: {rels})")
        lines.append(
            "Add each missing name to the re-export list at the bottom of "
            "src/condash/assets/src/js/dashboard-main.js, then rebuild the bundle "
            "with `make frontend`. See v0.20.1 / v0.20.2 fixes for prior art."
        )
        raise AssertionError("\n".join(lines))

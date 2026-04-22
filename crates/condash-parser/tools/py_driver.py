"""Python driver for the parser diff harness.

Invoked by ``parser-diff`` (the Rust bin in the same crate) in two modes:

1. **per-README mode** (default): read README paths from stdin one per
   line, call :func:`condash.parser.parse_readme` for each, emit
   ``{path, data}`` JSON lines on stdout.

2. **collect mode** (``--mode=collect``): ignore stdin, call
   :func:`condash.parser.collect_items` and :func:`collect_knowledge`
   once, emit a single JSON document on stdout — keyed ``{items,
   knowledge}``.

Stdout is newline-delimited JSON for per-README mode so the Rust
consumer can stream-parse. Stderr carries warnings and summary lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_ctx(condash_src: str, base_dir: Path):
    """Import condash from ``condash_src`` and return a minimal RenderCtx."""
    sys.path.insert(0, condash_src)
    from condash.context import RenderCtx  # noqa: E402

    return RenderCtx(
        base_dir=base_dir,
        workspace=None,
        worktrees=None,
        repo_structure=[],
    )


def _run_per_readme(condash_src: str, base_dir: Path) -> int:
    ctx = _build_ctx(condash_src, base_dir)
    from condash.parser import parse_readme  # noqa: E402

    count = 0
    for raw in sys.stdin:
        path_str = raw.strip()
        if not path_str:
            continue
        path = Path(path_str).resolve()
        try:
            result = parse_readme(ctx, path)
        except Exception as exc:  # noqa: BLE001 — driver surface only
            print(f"driver: error parsing {path}: {exc}", file=sys.stderr)
            result = None
        rel = str(path.relative_to(base_dir))
        sys.stdout.write(json.dumps({"path": rel, "data": result}, ensure_ascii=False))
        sys.stdout.write("\n")
        sys.stdout.flush()
        count += 1

    print(f"driver: parsed {count} READMEs", file=sys.stderr)
    return 0


def _run_collect(condash_src: str, base_dir: Path) -> int:
    ctx = _build_ctx(condash_src, base_dir)
    from condash.parser import collect_items, collect_knowledge  # noqa: E402

    items = collect_items(ctx)
    knowledge = collect_knowledge(ctx)
    out = {"items": items, "knowledge": knowledge}
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()
    print(
        f"driver: collect items={len(items)} knowledge={'present' if knowledge else 'absent'}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condash-src", required=True, help="path to condash's src/ directory")
    ap.add_argument("--base-dir", required=True, help="conception base_dir for RenderCtx")
    ap.add_argument(
        "--mode",
        choices=("per-readme", "collect"),
        default="per-readme",
        help="per-readme = stream one {path,data} per line; collect = emit a single {items,knowledge} doc",
    )
    args = ap.parse_args()

    base_dir = Path(args.base_dir).resolve()
    if args.mode == "collect":
        return _run_collect(args.condash_src, base_dir)
    return _run_per_readme(args.condash_src, base_dir)


if __name__ == "__main__":
    raise SystemExit(main())

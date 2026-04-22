"""Python driver for the mutation-diff harness.

Reads one JSON command per line on stdin, applies the corresponding
``mutations._*`` helper in a per-case tempfile, and emits one JSON line
on stdout with the return value and the post-mutation bytes.

Command shape (stdin):

    {"id": "case-7",
     "op": "toggle",            // set_priority|toggle|remove|edit|add|reorder
     "initial": "…markdown…",
     "args": {...}}

Response shape (stdout):

    {"id": "case-7",
     "return": <json-encodable>,
     "final": "…markdown after mutation…"}

Both sides of the diff drive the same sequence of cases — Rust generates
the case list, sends it here, and also runs each op locally. The Rust
binary is responsible for comparing ``return`` + ``final`` byte-for-byte.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _dispatch(condash_src: str):
    sys.path.insert(0, condash_src)
    from condash import mutations as m  # noqa: E402

    def run(op: str, path: Path, args: dict):
        if op == "set_priority":
            return m._set_priority(path, args["priority"])
        if op == "toggle":
            return m._toggle_checkbox(path, args["line"])
        if op == "remove":
            return m._remove_step(path, args["line"])
        if op == "edit":
            return m._edit_step(path, args["line"], args["text"])
        if op == "add":
            return m._add_step(path, args["text"], args.get("section"))
        if op == "reorder":
            return m._reorder_all(path, args["order"])
        raise ValueError(f"unknown op: {op}")

    return run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condash-src", required=True)
    ns = ap.parse_args()

    run = _dispatch(ns.condash_src)

    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            cmd = json.loads(raw)
            case_id = cmd["id"]
            op = cmd["op"]
            initial = cmd["initial"]
            args = cmd.get("args") or {}

            path = tmp_dir / f"{case_id}.md"
            path.write_text(initial, encoding="utf-8")
            try:
                ret = run(op, path, args)
            except Exception as exc:  # noqa: BLE001 — driver surface only
                print(f"driver: {case_id} raised: {exc}", file=sys.stderr)
                ret = {"__error__": str(exc)}
            final = path.read_text(encoding="utf-8")
            out = {"id": case_id, "return": ret, "final": final}
            sys.stdout.write(json.dumps(out, ensure_ascii=False))
            sys.stdout.write("\n")
            sys.stdout.flush()
            count += 1

    print(f"driver: processed {count} mutation cases", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

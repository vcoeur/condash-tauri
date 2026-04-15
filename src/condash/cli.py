"""Command-line entry point for condash."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="condash",
        description="Standalone desktop dashboard for markdown-based conception items.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"condash {__version__}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file (default: ~/.config/condash/config.toml)",
    )
    parser.add_argument(
        "--conception-path",
        type=Path,
        default=None,
        help="One-shot override of the conception directory (does not touch config).",
    )
    parser.add_argument(
        "--tidy",
        action="store_true",
        help="Move done items into YYYY-MM/ archive dirs and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cfg = load(path=args.config, conception_override=args.conception_path)

    if not cfg.conception_path.is_dir():
        print(
            f"condash: error: conception directory does not exist: {cfg.conception_path}",
            file=sys.stderr,
        )
        return 2

    from . import legacy

    legacy.init(cfg)

    if args.tidy:
        moves = legacy.run_tidy()
        if moves:
            for old, new in moves:
                print(f"  {old} \u2192 {new}")
            print(f"{len(moves)} item(s) moved.")
        else:
            print("Nothing to move.")
        return 0

    from . import app

    app.run(cfg)
    return 0

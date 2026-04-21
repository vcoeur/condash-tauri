"""Shared helpers used across the route subpackage.

Lives in its own module so submodules can import from it without
re-entering the package ``__init__`` (which itself imports each
submodule, and would deadlock).
"""

from __future__ import annotations

from fastapi.responses import JSONResponse


def error(status: int, message: str) -> JSONResponse:
    """Shared 4xx/5xx envelope: ``{"error": <message>}`` with ``status``."""
    return JSONResponse(status_code=status, content={"error": message})

"""Configuration read + write routes (form + raw-YAML paths).

The dashboard's gear modal POSTs ``/config`` with a structured payload;
the split-pane YAML view POSTs ``/config/yaml`` with a raw body.
Both end up running ``config_mod.save`` against an updated
:class:`CondashConfig` and rebuilding the live ``RenderCtx`` so paths,
repos, and ``open_with`` slots take effect on the next request.

Self-write stamping (:meth:`AppState.stamp_config_self_write`) suppresses
the watchdog's echo of this process's own save back through the reload
callback.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml
from fastapi import APIRouter, Request

from .. import config as config_mod
from ..config import (
    OPEN_WITH_SLOT_KEYS,
    CondashConfig,
    OpenWithSlot,
    RepoRunCommand,
)
from ..context import build_ctx
from ..pty import resolve_terminal_shell
from ..state import AppState
from ._common import error


def _repo_entries(
    names: list[str],
    submodules: dict[str, list[str]],
    repo_run: dict[str, RepoRunCommand] | None = None,
) -> list[dict]:
    """Shape a repo-name list for the /config JSON payload: one object per
    repo with its submodule paths attached and — when configured — the
    inline-runner template for the repo and for each sub-repo.
    """
    runs = repo_run or {}
    out: list[dict] = []
    for name in names:
        subs = list(submodules.get(name) or [])
        sub_objs = [
            {"name": sub, "run": runs[f"{name}--{sub}"].template}
            if f"{name}--{sub}" in runs
            else {"name": sub}
            for sub in subs
        ]
        entry: dict = {
            "name": name,
            "submodules": subs,
            "submodule_entries": sub_objs,
        }
        top_run = runs.get(name)
        if top_run is not None:
            entry["run"] = top_run.template
        out.append(entry)
    return out


def _read_yaml_body(target: Path | None) -> str:
    """Read the raw bytes of a YAML file for the modal's split-pane view."""
    if target is None:
        return ""
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return ""


def config_to_payload(cfg: CondashConfig) -> dict:
    """Serialise the live config to JSON for ``GET /config``."""
    repos_yaml_target = config_mod.repositories_yaml_path(cfg.conception_path)
    prefs_yaml_target = config_mod.preferences_yaml_path(cfg.conception_path)
    return {
        "conception_path": str(cfg.conception_path) if cfg.conception_path else "",
        "workspace_path": str(cfg.workspace_path) if cfg.workspace_path else "",
        "worktrees_path": str(cfg.worktrees_path) if cfg.worktrees_path else "",
        "port": int(cfg.port),
        "native": bool(cfg.native),
        "repositories_primary": _repo_entries(
            cfg.repositories_primary, cfg.repo_submodules, cfg.repo_run
        ),
        "repositories_secondary": _repo_entries(
            cfg.repositories_secondary, cfg.repo_submodules, cfg.repo_run
        ),
        "repositories_yaml_source": str(cfg.yaml_source) if cfg.yaml_source else "",
        "repositories_yaml_expected_path": (str(repos_yaml_target) if repos_yaml_target else ""),
        "repositories_yaml_body": _read_yaml_body(cfg.yaml_source or repos_yaml_target),
        "preferences_yaml_source": (str(cfg.preferences_source) if cfg.preferences_source else ""),
        "preferences_yaml_expected_path": (str(prefs_yaml_target) if prefs_yaml_target else ""),
        "preferences_yaml_body": _read_yaml_body(cfg.preferences_source or prefs_yaml_target),
        "terminal": {
            "shell": cfg.terminal.shell or "",
            "shortcut": cfg.terminal.shortcut,
            "resolved_shell": resolve_terminal_shell(cfg),
            "screenshot_dir": cfg.terminal.screenshot_dir or "",
            "resolved_screenshot_dir": str(cfg.terminal.resolved_screenshot_dir()),
            "screenshot_paste_shortcut": cfg.terminal.screenshot_paste_shortcut,
            "launcher_command": cfg.terminal.launcher_command,
            "move_tab_left_shortcut": cfg.terminal.move_tab_left_shortcut,
            "move_tab_right_shortcut": cfg.terminal.move_tab_right_shortcut,
        },
        "open_with": {
            slot_key: {
                "label": cfg.open_with[slot_key].label,
                "commands": list(cfg.open_with[slot_key].commands),
            }
            for slot_key in OPEN_WITH_SLOT_KEYS
            if slot_key in cfg.open_with
        },
        "pdf_viewer": list(cfg.pdf_viewer),
    }


def _parse_repo_entries(
    raw: object, key: str
) -> tuple[list[str], dict[str, list[str]], dict[str, RepoRunCommand]]:
    """Parse a `repositories_primary` / `_secondary` payload entry.

    Accepts either a list of strings (legacy) or a list of
    ``{name, submodules, run, submodule_entries}`` objects.
    """
    if raw is None:
        return [], {}, {}
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    names: list[str] = []
    subs: dict[str, list[str]] = {}
    runs: dict[str, RepoRunCommand] = {}
    for entry in raw:
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                names.append(name)
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{key} entries must be strings or objects")
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        names.append(name)
        sub_entries_raw = entry.get("submodule_entries")
        if isinstance(sub_entries_raw, list):
            cleaned: list[str] = []
            for sub_entry in sub_entries_raw:
                if isinstance(sub_entry, str):
                    s = sub_entry.strip()
                    if s:
                        cleaned.append(s)
                    continue
                if not isinstance(sub_entry, dict):
                    raise ValueError(f"{key}[].submodule_entries must be strings or objects")
                sub_name = str(sub_entry.get("name") or "").strip()
                if not sub_name:
                    continue
                cleaned.append(sub_name)
                sub_run_raw = sub_entry.get("run")
                if sub_run_raw is None:
                    continue
                sub_run = str(sub_run_raw).strip()
                if sub_run:
                    runs[f"{name}--{sub_name}"] = RepoRunCommand(template=sub_run)
            if cleaned:
                subs[name] = cleaned
        else:
            sub_raw = entry.get("submodules") or []
            if not isinstance(sub_raw, list):
                raise ValueError(f"{key}[].submodules must be a list")
            cleaned = [str(s).strip() for s in sub_raw if str(s).strip()]
            if cleaned:
                subs[name] = cleaned
        run_raw = entry.get("run")
        if run_raw is None:
            continue
        run_str = str(run_raw).strip()
        if run_str:
            runs[name] = RepoRunCommand(template=run_str)
    return names, subs, runs


def payload_to_config(data: dict) -> CondashConfig:
    """Build a validated CondashConfig from the in-app editor's JSON payload."""
    if not isinstance(data, dict):
        raise ValueError("payload must be an object")
    conception_raw = (data.get("conception_path") or "").strip()
    conception = Path(conception_raw).expanduser() if conception_raw else None

    workspace_raw = (data.get("workspace_path") or "").strip()
    workspace = Path(workspace_raw).expanduser() if workspace_raw else None
    worktrees_raw = (data.get("worktrees_path") or "").strip()
    worktrees = Path(worktrees_raw).expanduser() if worktrees_raw else None

    port_raw = data.get("port", 0)
    if isinstance(port_raw, str):
        port_raw = int(port_raw or 0)
    if not isinstance(port_raw, int) or not 0 <= port_raw <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")

    native_raw = data.get("native", True)
    if not isinstance(native_raw, bool):
        raise ValueError("native must be a boolean")

    primary, primary_subs, primary_runs = _parse_repo_entries(
        data.get("repositories_primary"), "repositories_primary"
    )
    secondary, secondary_subs, secondary_runs = _parse_repo_entries(
        data.get("repositories_secondary"), "repositories_secondary"
    )
    repo_submodules: dict[str, list[str]] = {**primary_subs, **secondary_subs}
    repo_run: dict[str, RepoRunCommand] = {**primary_runs, **secondary_runs}

    open_with_raw = data.get("open_with") or {}
    if not isinstance(open_with_raw, dict):
        raise ValueError("open_with must be an object")
    open_with: dict[str, OpenWithSlot] = {}
    for slot_key in OPEN_WITH_SLOT_KEYS:
        defaults = config_mod.DEFAULT_OPEN_WITH[slot_key]
        slot_data = open_with_raw.get(slot_key) or {}
        if not isinstance(slot_data, dict):
            raise ValueError(f"open_with.{slot_key} must be an object")
        label = str(slot_data.get("label") or defaults["label"])
        commands_raw = slot_data.get("commands")
        if commands_raw is None:
            commands = list(defaults["commands"])
        elif isinstance(commands_raw, list):
            commands = [str(c) for c in commands_raw if str(c).strip()]
        else:
            raise ValueError(f"open_with.{slot_key}.commands must be a list")
        open_with[slot_key] = OpenWithSlot(label=label, commands=commands)

    pdf_viewer_raw = data.get("pdf_viewer", [])
    if pdf_viewer_raw is None:
        pdf_viewer: list[str] = []
    elif isinstance(pdf_viewer_raw, list):
        pdf_viewer = [str(c).strip() for c in pdf_viewer_raw if str(c).strip()]
    else:
        raise ValueError("pdf_viewer must be a list of command strings")

    term_raw = data.get("terminal") or {}
    if not isinstance(term_raw, dict):
        raise ValueError("terminal must be an object")
    shell_in = str(term_raw.get("shell") or "").strip() or None
    shortcut_in = (
        str(term_raw.get("shortcut") or "").strip() or config_mod.DEFAULT_TERMINAL_SHORTCUT
    )
    screenshot_dir_in = str(term_raw.get("screenshot_dir") or "").strip() or None
    paste_shortcut_in = (
        str(term_raw.get("screenshot_paste_shortcut") or "").strip()
        or config_mod.DEFAULT_SCREENSHOT_PASTE_SHORTCUT
    )
    launcher_command_in = str(term_raw.get("launcher_command", config_mod.DEFAULT_LAUNCHER_COMMAND))
    move_left_in = (
        str(term_raw.get("move_tab_left_shortcut") or "").strip()
        or config_mod.DEFAULT_MOVE_TAB_LEFT_SHORTCUT
    )
    move_right_in = (
        str(term_raw.get("move_tab_right_shortcut") or "").strip()
        or config_mod.DEFAULT_MOVE_TAB_RIGHT_SHORTCUT
    )
    terminal = config_mod.TerminalConfig(
        shell=shell_in,
        shortcut=shortcut_in,
        screenshot_dir=screenshot_dir_in,
        screenshot_paste_shortcut=paste_shortcut_in,
        launcher_command=launcher_command_in.strip(),
        move_tab_left_shortcut=move_left_in,
        move_tab_right_shortcut=move_right_in,
    )

    return CondashConfig(
        conception_path=conception,
        workspace_path=workspace,
        worktrees_path=worktrees,
        repositories_primary=primary,
        repositories_secondary=secondary,
        repo_submodules=repo_submodules,
        terminal=terminal,
        port=port_raw,
        native=native_raw,
        open_with=open_with,
        pdf_viewer=pdf_viewer,
        repo_run=repo_run,
    )


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/config")
    def get_config():
        cfg = state.cfg
        if cfg is None:
            return error(500, "config not initialised")
        return config_to_payload(cfg)

    @router.post("/config")
    async def post_config(req: Request):
        if state.cfg is None:
            return error(500, "config not initialised")
        data = await req.json()
        try:
            new_cfg = payload_to_config(data)
        except (ValueError, KeyError, TypeError) as exc:
            return error(400, f"invalid config: {exc}")
        # Stamp self-writes so the filesystem watcher doesn't echo our
        # own save back as an external reload event.
        state.stamp_config_self_write("repositories.yml", "preferences.yml")
        config_mod.save(new_cfg)
        # Rebuild the RenderCtx so paths / repos / open-with changes take
        # effect on the next request without needing a process restart.
        state.ctx = build_ctx(new_cfg)
        # Surface which fields require a restart to actually take effect.
        restart_required = []
        old = state.cfg
        if old.port != new_cfg.port:
            restart_required.append("port")
        if old.native != new_cfg.native:
            restart_required.append("native")
        state.cfg = new_cfg
        return {
            "ok": True,
            "restart_required": restart_required,
            "config": config_to_payload(new_cfg),
        }

    @router.post("/config/yaml")
    async def post_config_yaml(req: Request):
        """Save a single YAML file verbatim (split-pane modal write path).

        Payload ``{"file": "repositories" | "preferences", "body": <yaml>}``.
        Parses the YAML, overlays it onto the live config, then runs through
        the same :func:`config_mod.save` + ``build_ctx`` path as the
        form-based ``POST /config`` so the on-disk state and runtime state
        stay in lockstep.
        """
        if state.cfg is None:
            return error(500, "config not initialised")
        try:
            data = await req.json()
        except ValueError:
            return error(400, "bad JSON")
        if not isinstance(data, dict):
            return error(400, "payload must be an object")
        which = str(data.get("file") or "").strip()
        body = data.get("body")
        if which not in ("repositories", "preferences"):
            return error(400, "file must be 'repositories' or 'preferences'")
        if not isinstance(body, str):
            return error(400, "body must be a string")
        if state.cfg.conception_path is None:
            return error(400, "conception_path is unset — set it in General first")
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return error(400, f"malformed YAML: {exc}")
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            return error(400, "top-level YAML must be a mapping")
        # Clone the current config so a bad payload can't leave it
        # half-applied if _apply_* raises deep into the parse.
        draft = copy.deepcopy(state.cfg)
        try:
            if which == "repositories":
                target = config_mod.repositories_yaml_path(draft.conception_path)
                config_mod._apply_repositories_yaml(draft, parsed, target)  # noqa: SLF001
            else:
                target = config_mod.preferences_yaml_path(draft.conception_path)
                config_mod._apply_preferences_yaml(draft, parsed, target)  # noqa: SLF001
        except config_mod.ConfigIncompleteError as exc:
            return error(400, str(exc))
        # Stamp self-writes so the file watcher doesn't echo back.
        state.stamp_config_self_write("repositories.yml", "preferences.yml")
        config_mod.save(draft)
        state.ctx = build_ctx(draft)
        state.cfg = draft
        return {"ok": True, "config": config_to_payload(draft)}

    return router

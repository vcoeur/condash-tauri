"""Git repo discovery and status for the dashboard's repo strip.

Scans the configured ``workspace_path`` for git repositories, bundles them
into the ``primary`` / ``secondary`` / ``Others`` groups per ``CondashConfig``,
and attaches dirty-file counts + worktree listings. A 30-second fingerprint
cache (keyed off ``HEAD`` + porcelain status) drives the ``/check-updates``
long-poll so the dashboard only re-renders when something actually changed.

``_git_cache`` is a module-level cache keyed by nothing — assumes a single
active ``RenderCtx`` per process, which is condash's invariant (one window,
one user).
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import time
from pathlib import Path

from .context import RenderCtx

_git_cache = {"fingerprint": None, "timestamp": 0.0}


def _is_sandbox_stub(repo_path: Path, status: str, rel: str) -> bool:
    """Return True for harness-synthesized stub files that should not count
    as real repo changes.

    When condash runs inside a sandbox (e.g. Claude Code's bwrap harness),
    the runtime binds zero-byte read-only copies of the user's home
    dotfiles (``.bashrc``, ``.gitconfig``, ``.mcp.json``, …) into every
    working directory so programs don't crash on missing config. These
    show up as untracked files in ``git status`` but they are not real
    changes, and the commit skill already filters them with the same
    logic — we want condash's dirty-badge to agree.
    """
    if "D" in status:
        return False
    try:
        st = (Path(repo_path) / rel).lstat()
    except OSError:
        return False
    if stat.S_ISCHR(st.st_mode):
        return True
    if stat.S_ISLNK(st.st_mode):
        try:
            return os.readlink(str(Path(repo_path) / rel)) == "/dev/null"
        except OSError:
            return False
    if status != "??":
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size != 0:
        return False
    if st.st_mode & 0o222:
        return False
    return True


def _git_status(path):
    try:
        branch = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status_out = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "?", False, 0, []
    changed_files = []
    for ln in status_out.splitlines():
        if len(ln) < 4:
            continue
        status = ln[:2]
        rest = ln[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        if _is_sandbox_stub(path, status, rest):
            continue
        changed_files.append(rest)
    return branch, bool(changed_files), len(changed_files), changed_files


def _git_worktrees(repo_path):
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    main = str(Path(repo_path).resolve())
    worktrees = []
    current = {}
    for line in out.splitlines() + [""]:
        if not line:
            if current.get("path") and current["path"] != main:
                wt_path = Path(current["path"])
                key = (
                    wt_path.parent.name
                    if wt_path.parent.parent.name == "worktrees"
                    else wt_path.name
                )
                branch, dirty, changed, changed_files = _git_status(wt_path)
                worktrees.append(
                    {
                        "key": key,
                        "path": current["path"],
                        "branch": branch or current.get("branch", ""),
                        "dirty": dirty,
                        "changed": changed,
                        "changed_files": changed_files,
                    }
                )
            current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree ") :]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].replace("refs/heads/", "")
    return worktrees


def _load_repository_structure(ctx: RenderCtx):
    """Return configured primary/secondary repo buckets."""
    return list(ctx.repo_structure)


def _scan_repo(found: dict, repo_dir: Path, display_name: str) -> None:
    """Probe ``repo_dir`` and record the result under ``display_name`` in
    ``found``. Caller has already confirmed ``repo_dir/.git`` exists.
    """
    branch, dirty, changed, changed_files = _git_status(repo_dir)
    found[display_name] = {
        "name": display_name,
        "path": str(repo_dir.resolve()),
        "branch": branch,
        "dirty": dirty,
        "changed": changed,
        "changed_files": changed_files,
        "worktrees": _git_worktrees(repo_dir),
    }


def _subrepo_member(parent: dict, sub_name: str) -> dict:
    """Build a top-level repo entry for a subrepo declared under ``parent``.

    The subrepo's worktrees mirror the parent's: each parent worktree gets a
    matching subrepo entry pointing at ``<wt>/<sub_name>``. When the
    subdirectory is absent in a given worktree, the entry is emitted with
    ``missing=True`` so the UI can flag it.
    """
    parent_path = Path(parent["path"])
    sub_path = parent_path / sub_name
    parent_changed = parent.get("changed_files") or []
    prefix = sub_name.rstrip("/") + "/"
    sub_changed_files = [f[len(prefix) :] for f in parent_changed if f.startswith(prefix)]
    member = {
        "name": sub_name,
        "is_subrepo": True,
        "path": str(sub_path.resolve()) if sub_path.is_dir() else str(sub_path),
        "branch": "",
        "dirty": bool(sub_changed_files),
        "changed": len(sub_changed_files),
        "changed_files": sub_changed_files,
        "missing": not sub_path.is_dir(),
        "worktrees": [],
    }
    for wt in parent.get("worktrees") or []:
        wt_sub_path = Path(wt["path"]) / sub_name
        wt_changed_files = [
            f[len(prefix) :] for f in (wt.get("changed_files") or []) if f.startswith(prefix)
        ]
        member["worktrees"].append(
            {
                "key": wt["key"],
                "path": str(wt_sub_path.resolve()) if wt_sub_path.is_dir() else str(wt_sub_path),
                "branch": wt.get("branch", "") if wt_sub_path.is_dir() else "",
                "dirty": bool(wt_changed_files),
                "changed": len(wt_changed_files),
                "changed_files": wt_changed_files,
                "missing": not wt_sub_path.is_dir(),
            }
        )
    return member


def _parent_member(repo: dict) -> dict:
    """Promote a scanned repo into the parent member of a family."""
    return {
        "name": repo["name"],
        "is_subrepo": False,
        "path": repo["path"],
        "branch": repo["branch"],
        "dirty": repo["dirty"],
        "changed": repo["changed"],
        "changed_files": repo["changed_files"],
        "missing": False,
        "worktrees": [
            {
                "key": wt["key"],
                "path": wt["path"],
                "branch": wt["branch"],
                "dirty": wt["dirty"],
                "changed": wt["changed"],
                "changed_files": wt.get("changed_files") or [],
                "missing": False,
            }
            for wt in repo.get("worktrees") or []
        ],
    }


def _collect_git_repos(ctx: RenderCtx):
    """Find git repos under the configured workspace and group them.

    Returns ``[]`` (no repo strip) when ``workspace_path`` is unset.

    Scan depth:

    - **Depth 1** — direct children of ``workspace_path``. If a child has
      its own ``.git/`` it's a repo; display name = child directory name.
    - **Depth 2** — when a direct child has no ``.git/`` but is itself a
      directory, descend one level. Each grandchild with a ``.git/``
      becomes a repo with display name ``<org>/<repo>``. This supports
      workspaces where ``workspace_path`` is a parent of org folders
      (e.g. ``~/src`` containing ``myorg/`` and ``vcoeur/``).

    Depth is capped at 2 — no deeper recursion, no symlink chasing.
    """
    if ctx.workspace is None:
        return []
    workspace = ctx.workspace
    found = {}
    if workspace.is_dir():
        for child in sorted(workspace.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / ".git").exists():
                _scan_repo(found, child, child.name)
                continue
            # Depth 2 — the child is an org-style grouping directory.
            try:
                grandchildren = sorted(child.iterdir())
            except OSError:
                continue
            for grand in grandchildren:
                if not grand.is_dir() or grand.name.startswith("."):
                    continue
                if not (grand / ".git").exists():
                    continue
                _scan_repo(found, grand, f"{child.name}/{grand.name}")

    structure = _load_repository_structure(ctx)
    submodule_map = {name: subs for _, entries in structure for name, subs in entries}

    def _build_family(repo_name: str) -> dict:
        repo = found[repo_name]
        members = [_parent_member(repo)]
        for sub_name in submodule_map.get(repo_name) or []:
            members.append(_subrepo_member(repo, sub_name))
        return {
            "name": repo_name,
            "has_subrepos": len(members) > 1,
            "members": members,
        }

    groups = []
    placed = set()
    for label, entries in structure:
        bucket = [_build_family(n) for n, _ in entries if n in found]
        placed.update(n for n, _ in entries if n in found)
        if bucket:
            groups.append((label, bucket))

    others = [_build_family(n) for n in sorted(found) if n not in placed]
    if others:
        groups.append(("Others", others))
    return groups


def _runner_tokens_for(ctx: RenderCtx, repo_name: str, sub_name: str | None = None) -> str:
    """Return a fingerprint fragment for the runner keys anchored at a row.

    Late-imports :mod:`condash.runners` to avoid import cycles at module
    load (render/git_scan are loaded before the FastAPI routes run).
    """
    from . import runners as runners_mod

    if sub_name is None:
        key = repo_name
    else:
        key = f"{repo_name}--{sub_name}"
    if key not in ctx.repo_run:
        return ""
    return f"|run:{runners_mod.fingerprint_token(key)}"


def compute_git_node_fingerprints(ctx: RenderCtx) -> dict[str, str]:
    """Return ``{node_id: hash}`` for the Code tab hierarchy.

    Node-id scheme:

      - ``code`` — whole Code tab.
      - ``code/<group-label>`` — primary / secondary / Others bucket.
      - ``code/<group-label>/<family>`` — a repo family (parent + subrepos).
      - ``code/<group-label>/<family>/m:<name>`` — a member (parent or
        subrepo). The parent uses its own name; subrepos use the subrepo
        name.
      - ``code/<group-label>/<family>/m:<name>/wt:<key>`` — a worktree of
        that member.

    Leaf hashes cover branch + dirty count + change-file signature. Group /
    family / member hashes mix their own state with the set of direct child
    ids so adds/removes are detectable but in-place edits don't bubble.
    """
    out: dict[str, str] = {}
    groups = _collect_git_repos(ctx)

    def leaf_hash(node: dict) -> str:
        files = tuple(sorted(node.get("changed_files") or []))
        return _hash(
            (
                "leaf",
                node.get("branch", ""),
                node.get("changed", 0),
                bool(node.get("dirty")),
                bool(node.get("missing")),
                files,
            )
        )

    top_child_ids: list[str] = []
    for label, families in groups:
        group_id = f"code/{label}"
        family_ids: list[str] = []
        for family in families:
            family_id = f"{group_id}/{family['name']}"
            member_ids: list[str] = []
            for member in family["members"]:
                member_id = f"{family_id}/m:{member['name']}"
                wt_ids: list[str] = []
                for wt in member.get("worktrees") or []:
                    wt_id = f"{member_id}/wt:{wt['key']}"
                    out[wt_id] = leaf_hash(wt)
                    wt_ids.append(wt_id)
                # Mix the runner key into the member hash so a runner
                # start/exit repaints this row (the inline terminal mount
                # lives on the member row, not on its worktrees).
                runner_token = (
                    _runner_tokens_for(ctx, family["name"], member["name"])
                    if member.get("is_subrepo")
                    else _runner_tokens_for(ctx, family["name"])
                )
                out[member_id] = _hash(
                    ("member", leaf_hash(member), tuple(sorted(wt_ids)), runner_token)
                )
                member_ids.append(member_id)
            # Family hash mixes each member's hash so a runner start/exit
            # (or any leaf-state edit) on a member bubbles to the family —
            # the /fragment endpoint reloads at the family level.
            out[family_id] = _hash(("family", tuple((mid, out[mid]) for mid in member_ids)))
            family_ids.append(family_id)
        out[group_id] = _hash(("group", label, tuple(sorted(family_ids))))
        top_child_ids.append(group_id)

    out["code"] = _hash(("tab", "code", tuple(sorted(top_child_ids))))
    return out


def _hash(data) -> str:
    """MD5 of ``repr(data)`` truncated — mirrors parser.py so both modules
    stay consistent. Re-exported intentionally instead of importing to keep
    this module independent of parser.py."""
    return hashlib.md5(repr(data).encode()).hexdigest()[:16]


def _git_fingerprint(ctx: RenderCtx):
    now = time.monotonic()
    if _git_cache["fingerprint"] and now - _git_cache["timestamp"] < 30:
        return _git_cache["fingerprint"]

    if ctx.workspace is None:
        _git_cache["fingerprint"] = "no-workspace"
        _git_cache["timestamp"] = now
        return _git_cache["fingerprint"]

    workspace = ctx.workspace
    parts = []
    if workspace.is_dir():
        for child in sorted(workspace.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / ".git").exists():
                continue
            try:
                head = subprocess.run(
                    ["git", "-C", str(child), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                status = subprocess.run(
                    ["git", "-C", str(child), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
                parts.append(f"{child.name}:{head}:{status}")
            except (OSError, subprocess.SubprocessError):
                parts.append(f"{child.name}:error")

    fp = hashlib.md5("".join(parts).encode()).hexdigest()[:16]
    _git_cache["fingerprint"] = fp
    _git_cache["timestamp"] = now
    return fp

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


def _resolve_submodules(base_path, submodule_names):
    out = []
    base = Path(base_path)
    for name in submodule_names:
        sub = base / name
        if sub.is_dir():
            out.append({"name": name, "path": str(sub.resolve())})
    return out


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
        "submodules": [],
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

    def _attach_counts(container):
        changed_files = container.get("changed_files") or []
        for sub in container.get("submodules") or []:
            prefix = sub["name"] + "/"
            sub["changed"] = sum(1 for f in changed_files if f.startswith(prefix))
            sub["dirty"] = sub["changed"] > 0

    for repo_name, repo in found.items():
        subs = submodule_map.get(repo_name) or []
        if not subs:
            continue
        repo["submodules"] = _resolve_submodules(repo["path"], subs)
        _attach_counts(repo)
        for wt in repo["worktrees"]:
            wt["submodules"] = _resolve_submodules(wt["path"], subs)
            _attach_counts(wt)

    groups = []
    placed = set()
    for label, entries in structure:
        bucket = [found[n] for n, _ in entries if n in found]
        placed.update(n for n, _ in entries if n in found)
        if bucket:
            groups.append((label, bucket))

    others = [found[n] for n in sorted(found) if n not in placed]
    if others:
        groups.append(("Others", others))
    return groups


def compute_git_node_fingerprints(ctx: RenderCtx) -> dict[str, str]:
    """Return ``{node_id: hash}`` for the Code tab hierarchy.

    Node-id scheme:

      - ``code`` — whole Code tab.
      - ``code/<group-label>`` — primary / secondary / Others bucket.
      - ``code/<group-label>/<repo>`` — a repo.
      - ``code/<group-label>/<repo>/sub:<name>`` — a submodule under the repo.
      - ``code/<group-label>/<repo>/wt:<key>`` — a worktree under the repo.
      - ``code/<group-label>/<repo>/wt:<key>/sub:<name>`` — a submodule
        inside a worktree.

    Leaf hashes cover branch + dirty count + change-file signature. Group
    hashes depend only on the set of direct child ids so edits at a repo
    don't dirty-mark the enclosing group; only add/remove does.
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
                files,
            )
        )

    top_child_ids: list[str] = []
    for label, repos in groups:
        group_id = f"code/{label}"
        repo_ids: list[str] = []
        for repo in repos:
            repo_id = f"{group_id}/{repo['name']}"
            repo_child_ids: list[str] = []

            for sub in repo.get("submodules") or []:
                sub_id = f"{repo_id}/sub:{sub['name']}"
                out[sub_id] = leaf_hash(sub)
                repo_child_ids.append(sub_id)

            for wt in repo.get("worktrees", []) or []:
                wt_id = f"{repo_id}/wt:{wt['key']}"
                wt_child_ids: list[str] = []
                for sub in wt.get("submodules") or []:
                    sub_id = f"{wt_id}/sub:{sub['name']}"
                    out[sub_id] = leaf_hash(sub)
                    wt_child_ids.append(sub_id)
                # Worktree hash mixes its own state with its children — it's
                # still a leaf-ish node (has branch/dirty of its own) but we
                # track its children so adds/removes are detectable.
                out[wt_id] = _hash(("wt", leaf_hash(wt), tuple(sorted(wt_child_ids))))
                repo_child_ids.append(wt_id)

            # Repo hash mixes leaf state + direct children membership.
            out[repo_id] = _hash(("repo", leaf_hash(repo), tuple(sorted(repo_child_ids))))
            repo_ids.append(repo_id)

        out[group_id] = _hash(("group", label, tuple(sorted(repo_ids))))
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

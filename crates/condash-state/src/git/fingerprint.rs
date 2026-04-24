//! Git fingerprints for `/check-updates` hints and per-node scoped
//! reloads. Split from the scan path in
//! `2026-04-24-condash-simplify-perf-audit`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::time::Instant;

use condash_parser::PyValue;
use md5::{Digest, Md5};

use crate::RenderCtx;

use super::scan::collect_git_repos;

/// `/check-updates` hint fingerprint. 30-second process-wide cache
/// keyed by nothing (assumes one active ctx per process — condash's
/// invariant). Port of `_git_fingerprint`.
pub fn git_fingerprint(ctx: &RenderCtx) -> String {
    static CACHE: Mutex<Option<(String, Instant)>> = Mutex::new(None);

    if let Ok(mut guard) = CACHE.lock() {
        if let Some((ref fp, ts)) = *guard {
            if ts.elapsed().as_secs() < 30 {
                return fp.clone();
            }
        }
        let fp = compute_git_fingerprint(ctx);
        *guard = Some((fp.clone(), Instant::now()));
        return fp;
    }
    compute_git_fingerprint(ctx)
}

fn compute_git_fingerprint(ctx: &RenderCtx) -> String {
    let Some(workspace) = ctx.workspace.as_deref() else {
        return "no-workspace".into();
    };
    if !workspace.is_dir() {
        return md5_16(b"");
    }

    let mut children: Vec<PathBuf> = match std::fs::read_dir(workspace) {
        Ok(it) => it.flatten().map(|e| e.path()).collect(),
        Err(_) => Vec::new(),
    };
    children.sort();

    let mut parts = String::new();
    for child in &children {
        let name = match child.file_name().and_then(|n| n.to_str()) {
            Some(n) => n,
            None => continue,
        };
        if !child.is_dir() || name.starts_with('.') {
            continue;
        }
        if !child.join(".git").exists() {
            continue;
        }
        let head = Command::new("git")
            .arg("-C")
            .arg(child)
            .args(["rev-parse", "HEAD"])
            .output();
        let status = Command::new("git")
            .arg("-C")
            .arg(child)
            .args(["status", "--porcelain"])
            .output();
        match (head, status) {
            (Ok(h), Ok(s)) => {
                let head_text = String::from_utf8_lossy(&h.stdout).trim().to_string();
                let status_text = String::from_utf8_lossy(&s.stdout).into_owned();
                parts.push_str(&format!("{name}:{head_text}:{status_text}"));
            }
            _ => parts.push_str(&format!("{name}:error")),
        }
    }

    md5_16(parts.as_bytes())
}

/// MD5-truncated-to-16 of the bytes passed in. Shared helper used
/// throughout the node-fingerprint walk since Python's `_hash` lives
/// on `repr()` strings.
fn md5_16(bytes: &[u8]) -> String {
    let digest = Md5::digest(bytes);
    format!("{digest:x}")[..16].to_string()
}

/// Per-leaf hash — matches Python's `leaf_hash` closure. Written
/// inline (rather than via `PyValue::Tuple`) so we can emit the
/// bare-word `True` / `False` that Python's `repr(bool)` produces
/// without teaching `PyValue` a new variant.
fn leaf_hash(branch: &str, changed: usize, dirty: bool, missing: bool, files: &[String]) -> String {
    // Build the tuple's repr() manually since PyValue only models
    // strings/ints/tuples/lists. Python's tuple repr for
    // ("leaf", branch, changed, dirty, missing, files_tuple) is:
    //   ('leaf', 'branch', 3, True, False, ('a', 'b'))
    let mut sorted: Vec<String> = files.to_vec();
    sorted.sort();
    let files_tuple_repr = {
        let mut s = String::from("(");
        for (i, f) in sorted.iter().enumerate() {
            if i > 0 {
                s.push_str(", ");
            }
            s.push_str(&PyValue::Str(f.clone()).repr());
        }
        if sorted.len() == 1 {
            s.push(',');
        }
        s.push(')');
        s
    };
    let repr = format!(
        "('leaf', {}, {}, {}, {}, {})",
        PyValue::Str(branch.to_string()).repr(),
        changed,
        if dirty { "True" } else { "False" },
        if missing { "True" } else { "False" },
        files_tuple_repr,
    );
    md5_16(repr.as_bytes())
}

/// Per-node fingerprints for the Code tab hierarchy. Port of
/// `compute_git_node_fingerprints`.
pub fn compute_git_node_fingerprints(ctx: &RenderCtx) -> HashMap<String, String> {
    let mut out: HashMap<String, String> = HashMap::new();
    let groups = collect_git_repos(ctx);

    let mut top_child_ids: Vec<String> = Vec::new();
    for group in &groups {
        let group_id = format!("code/{}", group.label);
        let mut family_ids: Vec<String> = Vec::new();
        for family in &group.families {
            let family_id = format!("{group_id}/{}", family.name);
            let mut member_ids: Vec<String> = Vec::new();
            for member in &family.members {
                let member_id = format!("{family_id}/m:{}", member.name);
                let mut wt_ids: Vec<String> = Vec::new();
                for wt in &member.worktrees {
                    let wt_id = format!("{member_id}/wt:{}", wt.key);
                    out.insert(
                        wt_id.clone(),
                        leaf_hash(
                            &wt.branch,
                            wt.changed,
                            wt.dirty,
                            wt.missing,
                            &wt.changed_files,
                        ),
                    );
                    wt_ids.push(wt_id);
                }
                wt_ids.sort();
                // Runner session state is Phase 4 territory (nothing starts
                // runners yet), but the fingerprint still has to agree
                // with Python. Python's `_runner_tokens_for` returns
                // `""` when the key isn't configured, and `|run:off`
                // when it is but no session is live — which is every
                // row in Phase 2. Mirror that exactly.
                let runner_key = if member.is_subrepo {
                    format!("{}--{}", family.name, member.name)
                } else {
                    family.name.clone()
                };
                let runner_token = if ctx.repo_run_keys.contains(&runner_key) {
                    "|run:off".to_string()
                } else {
                    String::new()
                };
                let member_leaf = leaf_hash(
                    &member.branch,
                    member.changed,
                    member.dirty,
                    member.missing,
                    &member.changed_files,
                );
                let member_data = {
                    // Python: ("member", leaf_hash(member), tuple(sorted(wt_ids)), runner_token)
                    let wt_tuple_repr = {
                        let mut s = String::from("(");
                        for (i, wid) in wt_ids.iter().enumerate() {
                            if i > 0 {
                                s.push_str(", ");
                            }
                            s.push_str(&PyValue::Str(wid.clone()).repr());
                        }
                        if wt_ids.len() == 1 {
                            s.push(',');
                        }
                        s.push(')');
                        s
                    };
                    format!(
                        "('member', {}, {}, {})",
                        PyValue::Str(member_leaf).repr(),
                        wt_tuple_repr,
                        PyValue::Str(runner_token.clone()).repr(),
                    )
                };
                out.insert(member_id.clone(), md5_16(member_data.as_bytes()));
                member_ids.push(member_id);
            }
            // Family hash mixes each member's hash.
            let family_data = {
                let mut s = String::from("('family', (");
                for (i, mid) in member_ids.iter().enumerate() {
                    if i > 0 {
                        s.push_str(", ");
                    }
                    s.push_str(&format!(
                        "({}, {})",
                        PyValue::Str(mid.clone()).repr(),
                        PyValue::Str(out[mid].clone()).repr(),
                    ));
                }
                if member_ids.len() == 1 {
                    s.push(',');
                }
                s.push_str("))");
                s
            };
            out.insert(family_id.clone(), md5_16(family_data.as_bytes()));
            family_ids.push(family_id);
        }
        family_ids.sort();
        let group_data = {
            let mut s = format!("('group', {}, (", PyValue::Str(group.label.clone()).repr());
            for (i, fid) in family_ids.iter().enumerate() {
                if i > 0 {
                    s.push_str(", ");
                }
                s.push_str(&PyValue::Str(fid.clone()).repr());
            }
            if family_ids.len() == 1 {
                s.push(',');
            }
            s.push_str("))");
            s
        };
        out.insert(group_id.clone(), md5_16(group_data.as_bytes()));
        top_child_ids.push(group_id);
    }

    top_child_ids.sort();
    let tab_data = {
        let mut s = String::from("('tab', 'code', (");
        for (i, gid) in top_child_ids.iter().enumerate() {
            if i > 0 {
                s.push_str(", ");
            }
            s.push_str(&PyValue::Str(gid.clone()).repr());
        }
        if top_child_ids.len() == 1 {
            s.push(',');
        }
        s.push_str("))");
        s
    };
    out.insert("code".to_string(), md5_16(tab_data.as_bytes()));

    out
}

//! Phase 2 slice 4 diff harness: run `collect_git_repos`,
//! `git_fingerprint`, and `compute_git_node_fingerprints` (plus
//! `search_items` once that module lands) in Rust *and* Python,
//! compare outputs byte-for-byte.
//!
//! The Python driver is the source of truth for the ctx used by both
//! sides — it loads condash's config, builds the `RenderCtx`, and
//! echoes the resolved `workspace` + `repo_structure` in its JSON
//! output. The Rust side rebuilds an equivalent ctx from that echo
//! (no YAML parser needed on this side).

use std::path::PathBuf;
use std::process::{Command, Stdio};

use condash_parser::collect_items;
use condash_state::{
    collect_git_repos, compute_git_node_fingerprints, ctx::RepoEntry, ctx::RepoSection,
    git_fingerprint, search_items, RenderCtx,
};
use serde_json::Value;

#[derive(Debug)]
struct Args {
    conception: PathBuf,
    condash_src: PathBuf,
    python: String,
    driver: PathBuf,
    mode: Mode,
    query: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Git,
    Search,
    All,
}

fn parse_args() -> Args {
    let mut conception = None;
    let mut condash_src = None;
    let mut python = None;
    let mut driver = None;
    let mut mode = Mode::All;
    let mut query = String::new();
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--conception" => conception = Some(it.next().expect("--conception VALUE").into()),
            "--condash-src" => condash_src = Some(it.next().expect("--condash-src VALUE").into()),
            "--python" => python = Some(it.next().expect("--python VALUE")),
            "--driver" => driver = Some(it.next().expect("--driver VALUE").into()),
            "--mode" => {
                let v = it.next().expect("--mode VALUE");
                mode = match v.as_str() {
                    "git" => Mode::Git,
                    "search" => Mode::Search,
                    "all" => Mode::All,
                    _ => {
                        eprintln!("unknown mode: {v}");
                        std::process::exit(2);
                    }
                };
            }
            "--query" => query = it.next().expect("--query VALUE"),
            "-h" | "--help" => {
                eprintln!(
                    "usage: state-diff \\\n  --conception <base>  \\\n  --condash-src <condash/src>  \\\n  --driver <path-to-py_driver.py>  \\\n  [--python <python-exe>]  \\\n  [--mode git|search|all] [--query Q]"
                );
                std::process::exit(0);
            }
            other => {
                eprintln!("unknown arg: {other}");
                std::process::exit(2);
            }
        }
    }
    Args {
        conception: conception.expect("--conception required"),
        condash_src: condash_src.expect("--condash-src required"),
        python: python.unwrap_or_else(|| "python3".into()),
        driver: driver.expect("--driver required"),
        mode,
        query,
    }
}

fn run_python(args: &Args, mode: &str, extra: &[&str]) -> std::io::Result<Value> {
    let mut cmd = Command::new(&args.python);
    cmd.arg(&args.driver)
        .arg("--condash-src")
        .arg(&args.condash_src)
        .arg("--base-dir")
        .arg(&args.conception)
        .arg("--mode")
        .arg(mode);
    for a in extra {
        cmd.arg(a);
    }
    let output = cmd.stderr(Stdio::inherit()).output()?;
    if !output.status.success() {
        return Err(std::io::Error::other(format!(
            "python driver exited with {}",
            output.status
        )));
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|e| std::io::Error::other(format!("driver emitted malformed JSON: {e}")))
}

fn build_ctx_from_py(ctx_json: &Value) -> RenderCtx {
    let workspace = ctx_json
        .get("workspace")
        .and_then(|v| v.as_str())
        .map(PathBuf::from);
    let worktrees = ctx_json
        .get("worktrees")
        .and_then(|v| v.as_str())
        .map(PathBuf::from);
    let repo_run_keys: std::collections::HashSet<String> = ctx_json
        .get("repo_run_keys")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let repo_structure = ctx_json
        .get("repo_structure")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|section| {
                    let label = section.get("label").and_then(|v| v.as_str())?.to_string();
                    let repos = section
                        .get("repos")?
                        .as_array()?
                        .iter()
                        .filter_map(|e| {
                            let name = e.get("name").and_then(|v| v.as_str())?.to_string();
                            let submodules = e
                                .get("submodules")
                                .and_then(|v| v.as_array())
                                .map(|a| {
                                    a.iter()
                                        .filter_map(|s| s.as_str().map(String::from))
                                        .collect()
                                })
                                .unwrap_or_default();
                            Some(RepoEntry { name, submodules })
                        })
                        .collect();
                    Some(RepoSection { label, repos })
                })
                .collect()
        })
        .unwrap_or_default();
    RenderCtx {
        base_dir: PathBuf::new(),
        workspace,
        worktrees,
        repo_structure,
        open_with: Default::default(),
        repo_run_keys,
        repo_run_templates: Default::default(),
        repo_force_stop_templates: Default::default(),
        pdf_viewer: Vec::new(),
        terminal: Default::default(),
        template: String::new(),
    }
}

fn run_git(args: &Args) -> bool {
    eprintln!("diff(git): running collect_git_repos + fingerprints");
    let py = run_python(args, "git", &[]).expect("python driver failed");

    let ctx = build_ctx_from_py(py.get("ctx").unwrap_or(&Value::Null));
    let rs_groups = collect_git_repos(&ctx);
    let rs_fp = git_fingerprint(&ctx);
    let rs_node_fps = compute_git_node_fingerprints(&ctx);

    let mut ok = true;

    // Compare groups as JSON. Python serialises Group as {label, families}
    // after the driver's normalisation; Rust's Group has the same shape
    // with #[derive(Serialize)] — round-trip as serde_json::Value so the
    // equality is structural (key order doesn't matter).
    let rs_groups_json = serde_json::to_value(&rs_groups).expect("serialise groups");
    let py_groups = py.get("groups").unwrap_or(&Value::Null);
    if py_groups != &rs_groups_json {
        ok = false;
        report_groups_mismatch(py_groups, &rs_groups_json);
    } else {
        let n = rs_groups.len();
        let families: usize = rs_groups.iter().map(|g| g.families.len()).sum();
        eprintln!("  groups: OK ({n} groups, {families} families)");
    }

    let py_fp = py.get("fingerprint").and_then(|v| v.as_str()).unwrap_or("");
    if py_fp == rs_fp {
        eprintln!("  fingerprint: OK ({rs_fp})");
    } else {
        ok = false;
        eprintln!("  fingerprint: MISMATCH py={py_fp} rs={rs_fp}");
    }

    let empty = serde_json::Map::new();
    let py_node = py
        .get("node_fingerprints")
        .and_then(|v| v.as_object())
        .unwrap_or(&empty);
    let mut mismatches = 0usize;
    let mut only_py = 0usize;
    let mut only_rs = 0usize;
    for (k, v) in &rs_node_fps {
        match py_node.get(k).and_then(|pv| pv.as_str()) {
            Some(pv) if pv == v => {}
            Some(pv) => {
                mismatches += 1;
                eprintln!("    node_fingerprints[{k}]: MISMATCH py={pv} rs={v}");
            }
            None => {
                only_rs += 1;
                eprintln!("    node_fingerprints[{k}]: ONLY-RS rs={v}");
            }
        }
    }
    for k in py_node.keys() {
        if !rs_node_fps.contains_key(k) {
            only_py += 1;
            eprintln!(
                "    node_fingerprints[{k}]: ONLY-PY py={}",
                py_node.get(k).and_then(|v| v.as_str()).unwrap_or("?")
            );
        }
    }
    if mismatches == 0 && only_py == 0 && only_rs == 0 {
        eprintln!("  node_fingerprints: OK ({} entries)", rs_node_fps.len());
    } else {
        ok = false;
    }

    ok
}

fn report_groups_mismatch(py: &Value, rs: &Value) {
    eprintln!("  groups: MISMATCH");
    let py_obj = py.as_array();
    let rs_obj = rs.as_array();
    match (py_obj, rs_obj) {
        (Some(p), Some(r)) => {
            if p.len() != r.len() {
                eprintln!("    group count differs py={} rs={}", p.len(), r.len());
            }
            for (i, (a, b)) in p.iter().zip(r.iter()).enumerate() {
                if a != b {
                    let label = a.get("label").and_then(|v| v.as_str()).unwrap_or("?");
                    eprintln!("    group[{i}] (label={label}) differs");
                    compare_objects(a, b, 3);
                }
            }
        }
        _ => eprintln!("    (non-array values)"),
    }
}

fn compare_objects(a: &Value, b: &Value, depth: usize) {
    let indent = "  ".repeat(depth);
    let ao = a.as_object();
    let bo = b.as_object();
    if let (Some(ao), Some(bo)) = (ao, bo) {
        let mut keys: Vec<_> = ao
            .keys()
            .chain(bo.keys())
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect();
        keys.sort();
        for k in keys {
            let av = ao.get(k);
            let bv = bo.get(k);
            if av != bv {
                eprintln!("{indent}key {k}:");
                eprintln!("{indent}  py: {}", truncate(&format!("{:?}", av)));
                eprintln!("{indent}  rs: {}", truncate(&format!("{:?}", bv)));
            }
        }
    } else {
        eprintln!("{indent}(non-object values)");
    }
}

fn truncate(s: &str) -> String {
    let max = 300;
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let head: String = s.chars().take(max).collect();
        format!("{head}…")
    }
}

fn run_search(args: &Args) -> bool {
    // Use a built-in query when none supplied — picks up tokens that
    // hit every source type (title, readme body, notes, filenames) on
    // the live corpus.
    let default_queries: &[&str] = &["condash", "render tauri", "phase 2", "evaluation"];
    let queries: Vec<String> = if args.query.is_empty() {
        default_queries.iter().map(|s| s.to_string()).collect()
    } else {
        vec![args.query.clone()]
    };

    let mut all_ok = true;
    for q in &queries {
        eprintln!("diff(search): query = {q:?}");
        let py = run_python(args, "search", &["--query", q]).expect("python driver failed");
        let py_results = py
            .get("results")
            .cloned()
            .unwrap_or(Value::Array(Vec::new()));

        // Rust ctx needs the same base_dir as Python. Ask the driver
        // in `git` mode — reusing it is cheaper than loading YAML here.
        // (The Python `search` mode's ctx has the same conception
        // path, so we just need to set base_dir ourselves.)
        let ctx = RenderCtx {
            base_dir: args.conception.clone(),
            ..Default::default()
        };
        let items = collect_items(&args.conception);
        let rs = search_items(&ctx, &items, q);
        let rs_json = serde_json::to_value(&rs).expect("serialise search results");

        if py_results == rs_json {
            eprintln!("  OK (query={q:?}, {} matched projects)", rs.len());
        } else {
            all_ok = false;
            report_search_mismatch(q, &py_results, &rs_json);
        }
    }
    all_ok
}

fn report_search_mismatch(query: &str, py: &Value, rs: &Value) {
    let py_arr = py.as_array();
    let rs_arr = rs.as_array();
    match (py_arr, rs_arr) {
        (Some(p), Some(r)) => {
            eprintln!(
                "  MISMATCH (query={query:?}): py_results={} rs_results={}",
                p.len(),
                r.len()
            );
            let n = p.len().max(r.len());
            for i in 0..n {
                let a = p.get(i);
                let b = r.get(i);
                if a != b {
                    let slug_a = a
                        .and_then(|v| v.get("slug"))
                        .and_then(|v| v.as_str())
                        .unwrap_or("?");
                    let slug_b = b
                        .and_then(|v| v.get("slug"))
                        .and_then(|v| v.as_str())
                        .unwrap_or("?");
                    eprintln!("    result[{i}]: py.slug={slug_a} rs.slug={slug_b}");
                    if let (Some(a), Some(b)) = (a, b) {
                        if a != b {
                            compare_objects(a, b, 3);
                        }
                    }
                }
            }
        }
        _ => eprintln!("  MISMATCH: non-array on one side"),
    }
}

fn main() {
    let args = parse_args();
    let ok = match args.mode {
        Mode::Git => run_git(&args),
        Mode::Search => run_search(&args),
        Mode::All => run_git(&args) && run_search(&args),
    };
    std::process::exit(if ok { 0 } else { 1 });
}

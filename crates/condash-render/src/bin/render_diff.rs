//! Phase 2 slice 3 diff harness: render every card + knowledge fragment
//! in Rust *and* Python, compare HTML byte-for-byte.
//!
//! Exit 0 = every fragment matches; exit 1 = at least one mismatch.
//! Like `parser-diff`, this is a workspace-local dev tool that exists
//! to guard the Rust port against Jinja2 ↔ minijinja drift as the
//! template surface grows.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use condash_parser::{collect_items, collect_knowledge, KnowledgeNode};
use condash_render::git_render::{render_git_repo_fragment, render_git_repos};
use condash_render::{
    render_card_fragment, render_history, render_knowledge, render_knowledge_card_fragment,
    render_knowledge_group_fragment,
};
use condash_state::{
    collect_git_repos, ctx::OpenWithSlot, ctx::RepoEntry, ctx::RepoSection, RenderCtx,
};
use serde_json::Value;

#[derive(Debug)]
struct Args {
    conception: PathBuf,
    condash_src: PathBuf,
    python: String,
    driver: PathBuf,
}

fn parse_args() -> Args {
    let mut conception = None;
    let mut condash_src = None;
    let mut python = None;
    let mut driver = None;
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--conception" => conception = Some(it.next().expect("--conception VALUE").into()),
            "--condash-src" => condash_src = Some(it.next().expect("--condash-src VALUE").into()),
            "--python" => python = Some(it.next().expect("--python VALUE")),
            "--driver" => driver = Some(it.next().expect("--driver VALUE").into()),
            "-h" | "--help" => {
                eprintln!(
                    "usage: render-diff \\\n  --conception <base>  \\\n  --condash-src <condash/src>  \\\n  --driver <path-to-py_driver.py>  \\\n  [--python <python-exe>]"
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
    }
}

fn run_python(args: &Args) -> std::io::Result<Value> {
    let output = Command::new(&args.python)
        .arg(&args.driver)
        .arg("--condash-src")
        .arg(&args.condash_src)
        .arg("--base-dir")
        .arg(&args.conception)
        .arg("--mode")
        .arg("render")
        .stderr(Stdio::inherit())
        .output()?;
    if !output.status.success() {
        return Err(std::io::Error::other(format!(
            "python driver exited with {}",
            output.status
        )));
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|e| std::io::Error::other(format!("driver emitted malformed JSON: {e}")))
}

fn walk_knowledge(
    node: &KnowledgeNode,
    groups: &mut HashMap<String, String>,
    cards: &mut HashMap<String, String>,
) {
    groups.insert(node.rel_dir.clone(), render_knowledge_group_fragment(node));
    if let Some(idx) = node.index.as_ref() {
        cards.insert(idx.path.clone(), render_knowledge_card_fragment(idx));
    }
    for entry in &node.body {
        cards.insert(entry.path.clone(), render_knowledge_card_fragment(entry));
    }
    for child in &node.children {
        walk_knowledge(child, groups, cards);
    }
}

fn build_ctx_from_py(ctx_json: &Value, base: &Path) -> RenderCtx {
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
    let open_with: std::collections::HashMap<String, OpenWithSlot> = ctx_json
        .get("open_with")
        .and_then(|v| v.as_object())
        .map(|obj| {
            obj.iter()
                .map(|(k, v)| {
                    let label = v
                        .get("label")
                        .and_then(|l| l.as_str())
                        .unwrap_or(k.as_str())
                        .to_string();
                    (
                        k.clone(),
                        OpenWithSlot {
                            label,
                            commands: Vec::new(),
                        },
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    RenderCtx {
        base_dir: base.to_path_buf(),
        workspace,
        worktrees,
        repo_structure,
        open_with,
        repo_run_keys,
        repo_run_templates: Default::default(),
        pdf_viewer: Vec::new(),
        terminal: Default::default(),
        template: String::new(),
    }
}

fn render_rust(
    ctx: &RenderCtx,
) -> (
    HashMap<String, String>,
    HashMap<String, String>,
    HashMap<String, String>,
    String,
    HashMap<String, String>,
) {
    let items = collect_items(&ctx.base_dir);
    let mut cards: HashMap<String, String> = HashMap::new();
    for item in &items {
        cards.insert(item.readme.slug.clone(), render_card_fragment(item));
    }
    let knowledge = collect_knowledge(&ctx.base_dir);
    let mut groups: HashMap<String, String> = HashMap::new();
    let mut k_cards: HashMap<String, String> = HashMap::new();
    if let Some(root) = knowledge.as_ref() {
        walk_knowledge(root, &mut groups, &mut k_cards);
    }

    let git_groups = collect_git_repos(ctx);
    // The diff harness only compares rendered HTML shapes; runners are a
    // per-process-state concern the harness doesn't model. Pass an
    // empty live map so both builds render the "no session" branch.
    let live_runners: condash_render::git_render::LiveRunners = Default::default();
    let git_html = render_git_repos(ctx, &git_groups, &live_runners);
    let mut git_fragments: HashMap<String, String> = HashMap::new();
    for group in &git_groups {
        let group_id = format!("code/{}", group.label);
        for family in &group.families {
            let node_id = format!("{group_id}/{}", family.name);
            if let Some(html) = render_git_repo_fragment(ctx, &git_groups, &node_id, &live_runners)
            {
                git_fragments.insert(node_id, html);
            }
        }
    }
    (cards, groups, k_cards, git_html, git_fragments)
}

fn compare_map(
    label: &str,
    py: &HashMap<String, String>,
    rs: &HashMap<String, String>,
) -> (usize, usize, usize, usize) {
    let mut matched = 0usize;
    let mut mismatched = 0usize;
    let mut only_py = 0usize;
    let mut only_rs = 0usize;

    for (k, v) in rs {
        match py.get(k) {
            Some(pv) if pv == v => matched += 1,
            Some(pv) => {
                mismatched += 1;
                report_string_diff(&format!("{label}[{k}]"), pv, v);
            }
            None => {
                only_rs += 1;
                eprintln!("  {label}[{k}]: ONLY-RS");
            }
        }
    }
    for k in py.keys() {
        if !rs.contains_key(k) {
            only_py += 1;
            eprintln!("  {label}[{k}]: ONLY-PY");
        }
    }
    (matched, mismatched, only_py, only_rs)
}

fn report_string_diff(label: &str, py: &str, rs: &str) {
    eprintln!("  {label}: MISMATCH ({} vs {} bytes)", py.len(), rs.len());
    // Find the first differing byte and print a short context window.
    let diff_at = py
        .bytes()
        .zip(rs.bytes())
        .position(|(a, b)| a != b)
        .unwrap_or(py.len().min(rs.len()));
    let start = diff_at.saturating_sub(60);
    let end_py = (diff_at + 80).min(py.len());
    let end_rs = (diff_at + 80).min(rs.len());
    eprintln!("    diff at byte {diff_at}:");
    eprintln!("    py: …{}…", safe_slice(py, start, end_py));
    eprintln!("    rs: …{}…", safe_slice(rs, start, end_rs));
}

fn safe_slice(s: &str, start: usize, end: usize) -> String {
    let bytes = s.as_bytes();
    let end = end.min(bytes.len());
    let start = start.min(end);
    let snippet = &bytes[start..end];
    String::from_utf8_lossy(snippet).replace('\n', "\\n")
}

fn parse_map(value: Option<&Value>) -> HashMap<String, String> {
    let Some(Value::Object(map)) = value else {
        return HashMap::new();
    };
    map.iter()
        .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
        .collect()
}

fn compare_single(label: &str, py: Option<&str>, rs: &str) -> bool {
    match py {
        Some(pv) if pv == rs => {
            eprintln!("  {label}: OK ({} bytes)", rs.len());
            true
        }
        Some(pv) => {
            report_string_diff(label, pv, rs);
            false
        }
        None => {
            eprintln!("  {label}: missing from Python output");
            false
        }
    }
}

fn main() {
    let args = parse_args();

    eprintln!("diff(render): running card + knowledge fragment rendering");
    let py = run_python(&args).expect("python driver failed");

    let py_cards = parse_map(py.get("cards"));
    let py_groups = parse_map(py.get("knowledge_groups"));
    let py_cards_k = parse_map(py.get("knowledge_cards"));
    let py_history = py.get("history").and_then(|v| v.as_str()).unwrap_or("");
    let py_knowledge_tree = py
        .get("knowledge_tree")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let py_git_repos = py.get("git_repos").and_then(|v| v.as_str()).unwrap_or("");
    let py_git_fragments = parse_map(py.get("git_fragments"));

    let ctx = build_ctx_from_py(py.get("ctx").unwrap_or(&Value::Null), &args.conception);
    let (rs_cards, rs_groups, rs_cards_k, rs_git_repos, rs_git_fragments) = render_rust(&ctx);

    let (m1, x1, py_only_1, rs_only_1) = compare_map("cards", &py_cards, &rs_cards);
    let (m2, x2, py_only_2, rs_only_2) = compare_map("knowledge_groups", &py_groups, &rs_groups);
    let (m3, x3, py_only_3, rs_only_3) = compare_map("knowledge_cards", &py_cards_k, &rs_cards_k);

    let items = collect_items(&ctx.base_dir);
    let rs_history = render_history(&ctx, &items);
    let rs_knowledge_tree = render_knowledge(collect_knowledge(&ctx.base_dir).as_ref());
    let ok_hist = compare_single("history", Some(py_history), &rs_history);
    let ok_ktree = compare_single(
        "knowledge_tree",
        Some(py_knowledge_tree),
        &rs_knowledge_tree,
    );
    let ok_git = compare_single("git_repos", Some(py_git_repos), &rs_git_repos);
    let (gf_m, gf_x, gf_py, gf_rs) =
        compare_map("git_fragments", &py_git_fragments, &rs_git_fragments);

    eprintln!("  cards: matched={m1} mismatched={x1} only_py={py_only_1} only_rs={rs_only_1}");
    eprintln!(
        "  knowledge_groups: matched={m2} mismatched={x2} only_py={py_only_2} only_rs={rs_only_2}"
    );
    eprintln!(
        "  knowledge_cards: matched={m3} mismatched={x3} only_py={py_only_3} only_rs={rs_only_3}"
    );
    eprintln!("  git_fragments: matched={gf_m} mismatched={gf_x} only_py={gf_py} only_rs={gf_rs}");

    let failed = x1
        + x2
        + x3
        + py_only_1
        + py_only_2
        + py_only_3
        + rs_only_1
        + rs_only_2
        + rs_only_3
        + gf_x
        + gf_py
        + gf_rs
        > 0
        || !ok_hist
        || !ok_ktree
        || !ok_git;
    std::process::exit(if failed { 1 } else { 0 });
}

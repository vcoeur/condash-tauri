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
use condash_render::{
    render_card_fragment, render_history, render_knowledge, render_knowledge_card_fragment,
    render_knowledge_group_fragment,
};
use condash_state::RenderCtx;
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

fn render_rust(
    base: &Path,
) -> (
    HashMap<String, String>,
    HashMap<String, String>,
    HashMap<String, String>,
) {
    let items = collect_items(base);
    let mut cards: HashMap<String, String> = HashMap::new();
    for item in &items {
        cards.insert(item.readme.slug.clone(), render_card_fragment(item));
    }
    let knowledge = collect_knowledge(base);
    let mut groups: HashMap<String, String> = HashMap::new();
    let mut k_cards: HashMap<String, String> = HashMap::new();
    if let Some(root) = knowledge.as_ref() {
        walk_knowledge(root, &mut groups, &mut k_cards);
    }
    (cards, groups, k_cards)
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

    let (rs_cards, rs_groups, rs_cards_k) = render_rust(&args.conception);

    let (m1, x1, py_only_1, rs_only_1) = compare_map("cards", &py_cards, &rs_cards);
    let (m2, x2, py_only_2, rs_only_2) = compare_map("knowledge_groups", &py_groups, &rs_groups);
    let (m3, x3, py_only_3, rs_only_3) = compare_map("knowledge_cards", &py_cards_k, &rs_cards_k);

    // history + knowledge_tree are single HTML strings — compare directly.
    let ctx = RenderCtx::with_base_dir(&args.conception);
    let items = collect_items(&args.conception);
    let rs_history = render_history(&ctx, &items);
    let rs_knowledge_tree = render_knowledge(collect_knowledge(&args.conception).as_ref());
    let ok_hist = compare_single("history", Some(py_history), &rs_history);
    let ok_ktree = compare_single("knowledge_tree", Some(py_knowledge_tree), &rs_knowledge_tree);

    eprintln!("  cards: matched={m1} mismatched={x1} only_py={py_only_1} only_rs={rs_only_1}");
    eprintln!(
        "  knowledge_groups: matched={m2} mismatched={x2} only_py={py_only_2} only_rs={rs_only_2}"
    );
    eprintln!(
        "  knowledge_cards: matched={m3} mismatched={x3} only_py={py_only_3} only_rs={rs_only_3}"
    );

    let failed = x1
        + x2
        + x3
        + py_only_1
        + py_only_2
        + py_only_3
        + rs_only_1
        + rs_only_2
        + rs_only_3
        > 0
        || !ok_hist
        || !ok_ktree;
    std::process::exit(if failed { 1 } else { 0 });
}

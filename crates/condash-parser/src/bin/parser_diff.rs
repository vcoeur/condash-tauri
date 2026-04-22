//! Phase 1 + Phase 2 diff harness: parse every README under
//! `<conception>/projects/` in Rust *and* Python, drop into a cross-
//! language equality check. Phase 2 extended it with a `collect` mode
//! that diffs `collect_items` + `collect_knowledge` as whole documents.
//!
//! Exit 0 = byte-identical JSON for every document; exit 1 = at least
//! one mismatch. The binary is a workspace-local dev tool, not something
//! the condash end-user runs — it exists to guard the Rust port as
//! phases 2-4 build on top of it.

use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use condash_parser::{
    collect_items, collect_knowledge, compute_fingerprint, compute_knowledge_node_fingerprints,
    compute_project_node_fingerprints, parse_readme,
};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug)]
struct Args {
    conception: PathBuf,
    condash_src: PathBuf,
    python: String,
    driver: PathBuf,
    mode: Mode,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    PerReadme,
    Collect,
    Fingerprints,
}

fn parse_args() -> Args {
    let mut conception = None;
    let mut condash_src = None;
    let mut python = None;
    let mut driver = None;
    let mut mode = Mode::PerReadme;
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
                    "per-readme" => Mode::PerReadme,
                    "collect" => Mode::Collect,
                    "fingerprints" => Mode::Fingerprints,
                    _ => {
                        eprintln!("unknown mode: {v}");
                        std::process::exit(2);
                    }
                };
            }
            "-h" | "--help" => {
                eprintln!(
                    "usage: parser-diff \\\n  --conception <base>  \\\n  --condash-src <condash/src>  \\\n  --driver <path-to-py_driver.py>  \\\n  [--python <python-exe>]  \\\n  [--mode per-readme|collect]"
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
    }
}

/// Collect every `README.md` under `root`, sorted, skipping dot-dirs.
fn collect_readmes(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    walk(root, &mut out);
    out.sort();
    out
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if path.is_dir() {
            if name.starts_with('.') {
                continue;
            }
            walk(&path, out);
        } else if name == "README.md" {
            out.push(path);
        }
    }
}

#[derive(Deserialize)]
struct DriverLine {
    path: String,
    data: Option<Value>,
}

/// Spawn the Python driver in per-README mode, stream READMEs to it,
/// collect JSON back keyed by relative path.
fn run_python_per_readme(
    python: &str,
    driver: &Path,
    condash_src: &Path,
    base_dir: &Path,
    readmes: &[PathBuf],
) -> std::io::Result<HashMap<String, Option<Value>>> {
    let mut child = Command::new(python)
        .arg(driver)
        .arg("--condash-src")
        .arg(condash_src)
        .arg("--base-dir")
        .arg(base_dir)
        .arg("--mode")
        .arg("per-readme")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;

    {
        // `take()` moves the ChildStdin out of the Child, so dropping it
        // actually closes the pipe and the Python driver sees EOF on
        // stdin. Using `as_mut()` only borrows — the handle stays alive
        // and the driver blocks forever. Ask me how I know.
        let mut stdin = child.stdin.take().expect("piped stdin");
        for p in readmes {
            writeln!(stdin, "{}", p.display())?;
        }
    } // drop stdin → EOF

    let stdout = child.stdout.take().expect("piped stdout");
    let reader = BufReader::new(stdout);
    let mut map = HashMap::with_capacity(readmes.len());
    for line in reader.lines() {
        let line = line?;
        if line.is_empty() {
            continue;
        }
        let parsed: DriverLine = serde_json::from_str(&line)
            .unwrap_or_else(|e| panic!("driver emitted malformed JSON {line:?}: {e}"));
        map.insert(parsed.path, parsed.data);
    }

    let status = child.wait()?;
    if !status.success() {
        return Err(std::io::Error::other(format!(
            "python driver exited with {status}"
        )));
    }
    Ok(map)
}

fn parse_in_rust(path: &Path, base_dir: &Path) -> (String, Option<Value>) {
    let rel = path
        .strip_prefix(base_dir)
        .map(|r| r.to_string_lossy().replace('\\', "/"))
        .unwrap_or_else(|_| path.to_string_lossy().into_owned());
    let parsed = parse_readme(base_dir, path, None).and_then(|r| serde_json::to_value(&r).ok());
    (rel, parsed)
}

fn run_per_readme(args: &Args) -> i32 {
    let projects = args.conception.join("projects");
    let readmes = collect_readmes(&projects);
    eprintln!(
        "diff(per-readme): found {} READMEs under {}",
        readmes.len(),
        projects.display()
    );

    let py = run_python_per_readme(
        &args.python,
        &args.driver,
        &args.condash_src,
        &args.conception,
        &readmes,
    )
    .expect("python driver failed");

    let mut matched = 0usize;
    let mut mismatched = 0usize;
    let mut missing_py = 0usize;

    for path in &readmes {
        let (rel, rust_value) = parse_in_rust(path, &args.conception);
        let py_value = match py.get(&rel) {
            Some(v) => v,
            None => {
                eprintln!("[MISSING-PY] {rel}");
                missing_py += 1;
                continue;
            }
        };
        if py_value == &rust_value {
            matched += 1;
        } else {
            mismatched += 1;
            report_item_mismatch(&rel, py_value, &rust_value);
        }
    }

    eprintln!(
        "diff(per-readme): matched={} mismatched={} missing_py={} total={}",
        matched,
        mismatched,
        missing_py,
        readmes.len()
    );

    if mismatched > 0 || missing_py > 0 {
        1
    } else {
        0
    }
}

fn run_collect(args: &Args) -> i32 {
    eprintln!("diff(collect): running collect_items + collect_knowledge");

    let py = run_python_single_mode(
        &args.python,
        &args.driver,
        &args.condash_src,
        &args.conception,
        "collect",
    )
    .expect("python driver failed");

    let items_rust: Vec<_> = collect_items(&args.conception);
    let items_rust_value = serde_json::to_value(&items_rust).expect("serialise rust items");
    let knowledge_rust = collect_knowledge(&args.conception);
    let knowledge_rust_value =
        serde_json::to_value(&knowledge_rust).expect("serialise rust knowledge");

    let mut failed = false;

    match py.get("items") {
        Some(py_items) if py_items == &items_rust_value => {
            let n = py_items.as_array().map(|a| a.len()).unwrap_or(0);
            eprintln!("  items: OK ({} items match)", n);
        }
        Some(py_items) => {
            failed = true;
            report_items_mismatch(py_items, &items_rust_value);
        }
        None => {
            failed = true;
            eprintln!("  items: MISSING from Python output");
        }
    }

    match py.get("knowledge") {
        Some(py_k) if py_k == &knowledge_rust_value => {
            eprintln!("  knowledge: OK");
        }
        Some(py_k) => {
            failed = true;
            report_knowledge_mismatch(py_k, &knowledge_rust_value);
        }
        None => {
            failed = true;
            eprintln!("  knowledge: MISSING from Python output");
        }
    }

    if failed {
        1
    } else {
        0
    }
}

fn run_python_single_mode(
    python: &str,
    driver: &Path,
    condash_src: &Path,
    base_dir: &Path,
    mode: &str,
) -> std::io::Result<Value> {
    let output = Command::new(python)
        .arg(driver)
        .arg("--condash-src")
        .arg(condash_src)
        .arg("--base-dir")
        .arg(base_dir)
        .arg("--mode")
        .arg(mode)
        .stderr(Stdio::inherit())
        .output()?;
    if !output.status.success() {
        return Err(std::io::Error::other(format!(
            "python driver exited with {}",
            output.status
        )));
    }
    let parsed: Value = serde_json::from_slice(&output.stdout)
        .unwrap_or_else(|e| panic!("driver emitted malformed JSON: {e}"));
    Ok(parsed)
}

fn run_fingerprints(args: &Args) -> i32 {
    eprintln!("diff(fingerprints): running compute_fingerprint + compute_*_node_fingerprints");

    let py = run_python_single_mode(
        &args.python,
        &args.driver,
        &args.condash_src,
        &args.conception,
        "fingerprints",
    )
    .expect("python driver failed");

    let items = collect_items(&args.conception);
    let knowledge = collect_knowledge(&args.conception);
    let overall = compute_fingerprint(&items);
    let project_nodes = compute_project_node_fingerprints(&items);
    let knowledge_nodes = compute_knowledge_node_fingerprints(knowledge.as_ref());

    let mut failed = false;

    match py.get("overall").and_then(|v| v.as_str()) {
        Some(py_overall) if py_overall == overall => {
            eprintln!("  overall: OK ({overall})");
        }
        Some(py_overall) => {
            failed = true;
            eprintln!("  overall: MISMATCH — py={py_overall} rs={overall}");
        }
        None => {
            failed = true;
            eprintln!("  overall: missing from Python output");
        }
    }

    let py_project = py
        .get("project_nodes")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let mut project_mismatches = 0usize;
    let mut project_only_rs = 0usize;
    for (k, v) in &project_nodes {
        match py_project.get(k).and_then(|pv| pv.as_str()) {
            Some(pv) if pv == v => {}
            Some(pv) => {
                project_mismatches += 1;
                eprintln!("    project_nodes[{k}]: MISMATCH py={pv} rs={v}");
            }
            None => {
                project_only_rs += 1;
                eprintln!("    project_nodes[{k}]: ONLY-RS rs={v}");
            }
        }
    }
    let mut project_only_py = 0usize;
    for k in py_project.keys() {
        if !project_nodes.contains_key(k) {
            project_only_py += 1;
            eprintln!(
                "    project_nodes[{k}]: ONLY-PY py={}",
                py_project.get(k).and_then(|v| v.as_str()).unwrap_or("?")
            );
        }
    }
    if project_mismatches == 0 && project_only_rs == 0 && project_only_py == 0 {
        eprintln!(
            "  project_nodes: OK ({} entries match)",
            project_nodes.len()
        );
    } else {
        failed = true;
    }

    let py_knowledge = py
        .get("knowledge_nodes")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let mut k_mismatches = 0usize;
    let mut k_only_rs = 0usize;
    for (k, v) in &knowledge_nodes {
        match py_knowledge.get(k).and_then(|pv| pv.as_str()) {
            Some(pv) if pv == v => {}
            Some(pv) => {
                k_mismatches += 1;
                eprintln!("    knowledge_nodes[{k}]: MISMATCH py={pv} rs={v}");
            }
            None => {
                k_only_rs += 1;
                eprintln!("    knowledge_nodes[{k}]: ONLY-RS rs={v}");
            }
        }
    }
    let mut k_only_py = 0usize;
    for k in py_knowledge.keys() {
        if !knowledge_nodes.contains_key(k) {
            k_only_py += 1;
            eprintln!(
                "    knowledge_nodes[{k}]: ONLY-PY py={}",
                py_knowledge.get(k).and_then(|v| v.as_str()).unwrap_or("?")
            );
        }
    }
    if k_mismatches == 0 && k_only_rs == 0 && k_only_py == 0 {
        eprintln!(
            "  knowledge_nodes: OK ({} entries match)",
            knowledge_nodes.len()
        );
    } else {
        failed = true;
    }

    if failed {
        1
    } else {
        0
    }
}

fn main() {
    let args = parse_args();
    let code = match args.mode {
        Mode::PerReadme => run_per_readme(&args),
        Mode::Collect => run_collect(&args),
        Mode::Fingerprints => run_fingerprints(&args),
    };
    std::process::exit(code);
}

/// Print the first few differing fields for an item. We don't dump the
/// full JSON — it's thousands of lines for big READMEs — just identify
/// the keys that differ so the next triage pass is cheap.
fn report_item_mismatch(rel: &str, py: &Option<Value>, rust: &Option<Value>) {
    eprintln!("[MISMATCH] {rel}");
    match (py, rust) {
        (None, None) => unreachable!("equality already checked"),
        (None, Some(_)) => eprintln!("  python: None  rust: Some(…)"),
        (Some(_), None) => eprintln!("  python: Some(…)  rust: None"),
        (Some(py), Some(rust)) => diff_objects(py, rust, 1),
    }
}

fn report_items_mismatch(py: &Value, rust: &Value) {
    let py_items = py.as_array();
    let rust_items = rust.as_array();
    match (py_items, rust_items) {
        (Some(p), Some(r)) => {
            if p.len() != r.len() {
                eprintln!(
                    "  items: length mismatch — python={} rust={}",
                    p.len(),
                    r.len()
                );
                let py_slugs: Vec<_> = p.iter().filter_map(|v| v.get("slug")).collect();
                let rust_slugs: Vec<_> = r.iter().filter_map(|v| v.get("slug")).collect();
                eprintln!("    py slugs: {:?}", py_slugs);
                eprintln!("    rs slugs: {:?}", rust_slugs);
                return;
            }
            for (i, (a, b)) in p.iter().zip(r.iter()).enumerate() {
                if a != b {
                    let slug = a
                        .get("slug")
                        .and_then(|v| v.as_str())
                        .unwrap_or("<no slug>");
                    eprintln!("  items[{}] (slug={}) differs:", i, slug);
                    diff_objects(a, b, 2);
                }
            }
        }
        _ => eprintln!("  items: non-array value on one side"),
    }
}

fn report_knowledge_mismatch(py: &Value, rust: &Value) {
    eprintln!("  knowledge: trees differ");
    diff_knowledge_nodes(py, rust, 1);
}

fn diff_knowledge_nodes(py: &Value, rust: &Value, depth: usize) {
    let indent = "  ".repeat(depth);
    if py == rust {
        return;
    }
    let py_obj = py.as_object();
    let rust_obj = rust.as_object();
    if let (Some(p), Some(r)) = (py_obj, rust_obj) {
        let rel_dir = p
            .get("rel_dir")
            .and_then(|v| v.as_str())
            .unwrap_or("<no rel_dir>");
        for key in ["name", "label", "rel_dir", "count"] {
            if p.get(key) != r.get(key) {
                eprintln!(
                    "{indent}{rel_dir}: key {key}: py={:?} rs={:?}",
                    p.get(key),
                    r.get(key)
                );
            }
        }
        if p.get("index") != r.get("index") {
            eprintln!("{indent}{rel_dir}: index differs");
        }
        if p.get("body") != r.get("body") {
            let p_body = p.get("body").and_then(|v| v.as_array());
            let r_body = r.get("body").and_then(|v| v.as_array());
            let pl = p_body.map(|a| a.len()).unwrap_or(0);
            let rl = r_body.map(|a| a.len()).unwrap_or(0);
            eprintln!(
                "{indent}{rel_dir}: body differs (py_len={} rs_len={})",
                pl, rl
            );
            if let (Some(pb), Some(rb)) = (p_body, r_body) {
                for (i, (a, b)) in pb.iter().zip(rb.iter()).enumerate() {
                    if a != b {
                        eprintln!("{indent}  body[{i}]: py={:?} rs={:?}", a, b);
                    }
                }
            }
        }
        let p_children = p.get("children").and_then(|v| v.as_array());
        let r_children = r.get("children").and_then(|v| v.as_array());
        if let (Some(pc), Some(rc)) = (p_children, r_children) {
            if pc.len() != rc.len() {
                eprintln!(
                    "{indent}{rel_dir}: child count differs py={} rs={}",
                    pc.len(),
                    rc.len()
                );
            }
            for (a, b) in pc.iter().zip(rc.iter()) {
                diff_knowledge_nodes(a, b, depth + 1);
            }
        }
    }
}

fn diff_objects(py: &Value, rust: &Value, depth: usize) {
    let indent = "  ".repeat(depth);
    let py_obj = py.as_object();
    let rust_obj = rust.as_object();
    if let (Some(py_obj), Some(rust_obj)) = (py_obj, rust_obj) {
        let mut keys: Vec<_> = py_obj
            .keys()
            .chain(rust_obj.keys())
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect();
        keys.sort();
        for k in keys {
            let p = py_obj.get(k);
            let r = rust_obj.get(k);
            if p != r {
                eprintln!("{indent}key {k}:");
                eprintln!("{indent}  python: {}", truncate(&format!("{:?}", p)));
                eprintln!("{indent}  rust:   {}", truncate(&format!("{:?}", r)));
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

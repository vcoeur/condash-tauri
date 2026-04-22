//! Phase 3 slice 1 diff harness: for every synthetic + live-corpus
//! mutation case, apply the mutation in both Rust and Python, and
//! compare both the return value and the post-mutation file bytes.
//!
//! Exit 0 = every case matched (return + bytes); exit 1 = at least one
//! mismatch. Pattern mirrors `condash-parser/src/bin/parser_diff.rs`.
//!
//! The *same* case list drives both sides — Rust enumerates cases,
//! sends each one over stdin to the Python driver, then locally runs
//! the corresponding Rust helper on a fresh tempfile seeded with the
//! same initial bytes. Python and Rust never see each other's tempfile
//! (no shared state, no race).

use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use condash_mutations::{
    add_step, edit_step, remove_step, reorder_all, set_priority, toggle_checkbox,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tempfile::TempDir;

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
                    "usage: mutation-diff \\\n  --conception <base>  \\\n  --condash-src <condash/src>  \\\n  --driver <path-to-py_driver.py>  \\\n  [--python <python-exe>]"
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

#[derive(Debug, Clone, Serialize)]
struct Case {
    id: String,
    op: String,
    initial: String,
    args: Value,
}

#[derive(Debug, Deserialize)]
struct DriverLine {
    id: String,
    #[serde(rename = "return")]
    ret: Value,
    #[serde(rename = "final")]
    finalc: String,
}

fn case(id: &str, op: &str, initial: &str, args: Value) -> Case {
    Case {
        id: id.to_string(),
        op: op.to_string(),
        initial: initial.to_string(),
        args,
    }
}

/// Synthetic cases chosen to exercise every branch in the six helpers.
/// Kept close to the unit-test corpus so an accidental divergence gets
/// spotted by both suites.
fn synthetic_cases() -> Vec<Case> {
    let mut out: Vec<Case> = Vec::new();

    // ---- set_priority
    out.push(case(
        "sp-rewrite-existing",
        "set_priority",
        "# T\n\n**Date**: 2026-04-22\n**Status**: now\n",
        json!({"priority": "soon"}),
    ));
    out.push(case(
        "sp-rewrite-space-colon",
        "set_priority",
        "# T\n\n**Date** : 2026-04-22\n**Status** : now\n",
        json!({"priority": "done"}),
    ));
    out.push(case(
        "sp-insert-missing-colon-style",
        "set_priority",
        "# T\n\n**Date**: 2026-04-22\n**Apps**: `x`\n\n## Goal\n\nbody.\n",
        json!({"priority": "now"}),
    ));
    out.push(case(
        "sp-insert-missing-space-style",
        "set_priority",
        "# T\n\n**Date** : 2026-04-22\n\n## Goal\n",
        json!({"priority": "soon"}),
    ));
    out.push(case(
        "sp-reject-unknown",
        "set_priority",
        "# T\n\n**Status**: now\n",
        json!({"priority": "urgent"}),
    ));

    // ---- toggle
    // Start at each of the five states and flip once.
    for (id, init, line) in [
        ("tg-open-to-done", "- [ ] x\n", 0),
        ("tg-done-to-progress", "- [x] x\n", 0),
        ("tg-capital-x", "- [X] x\n", 0),
        ("tg-progress-to-abandoned", "- [~] x\n", 0),
        ("tg-abandoned-to-open", "- [-] x\n", 0),
        ("tg-non-checkbox", "not a box\n", 0),
        ("tg-oob", "- [ ] only\n", 99),
    ] {
        out.push(case(id, "toggle", init, json!({"line": line})));
    }

    // ---- remove
    out.push(case(
        "rm-middle",
        "remove",
        "- [ ] a\n- [ ] b\n- [ ] c\n",
        json!({"line": 1}),
    ));
    out.push(case(
        "rm-non-checkbox",
        "remove",
        "heading\n- [ ] a\n",
        json!({"line": 0}),
    ));
    out.push(case("rm-oob", "remove", "- [ ] only\n", json!({"line": 5})));

    // ---- edit
    out.push(case(
        "ed-rewrite-keep-status",
        "edit",
        "- [x] old text\n",
        json!({"line": 0, "text": "new text"}),
    ));
    out.push(case(
        "ed-strip-newlines",
        "edit",
        "- [ ] old\n",
        json!({"line": 0, "text": "line1\nline2\rdone"}),
    ));
    out.push(case(
        "ed-preserve-indent",
        "edit",
        "    - [~] nested\n",
        json!({"line": 0, "text": "new"}),
    ));
    out.push(case(
        "ed-non-checkbox",
        "edit",
        "plain\n",
        json!({"line": 0, "text": "x"}),
    ));
    out.push(case(
        "ed-non-ascii",
        "edit",
        "- [ ] old\n",
        json!({"line": 0, "text": "é à ù — ok"}),
    ));

    // ---- add
    out.push(case(
        "add-create-before-notes",
        "add",
        "# Title\n\n## Goal\n\nbody.\n\n## Notes\n\nn.\n",
        json!({"text": "first"}),
    ));
    out.push(case(
        "add-create-no-notes",
        "add",
        "# Title\n\n## Goal\n\nbody.\n",
        json!({"text": "first"}),
    ));
    out.push(case(
        "add-append-existing",
        "add",
        "# T\n\n## Steps\n\n- [ ] one\n- [x] two\n\n## Notes\n\nn.\n",
        json!({"text": "three"}),
    ));
    out.push(case(
        "add-before-h3",
        "add",
        "# T\n\n## Steps\n\n- [ ] one\n\n### Subsection\n\n- [ ] nested\n\n## Notes\n",
        json!({"text": "sibling"}),
    ));
    out.push(case(
        "add-explicit-section",
        "add",
        "# T\n\n## Scope\n\nstuff.\n\n## Steps\n\n- [ ] s1\n\n## Notes\n",
        json!({"text": "scoped", "section": "Scope"}),
    ));
    out.push(case(
        "add-heading-missing-fallthrough",
        "add",
        "# T\n\n## Steps\n\n- [ ] s1\n\n## Notes\n",
        json!({"text": "new", "section": "Nonexistent"}),
    ));
    out.push(case(
        "add-strip-newlines",
        "add",
        "# T\n\n## Steps\n\n- [ ] old\n",
        json!({"text": "a\nb\rc"}),
    ));
    out.push(case(
        "add-case-insensitive-steps",
        "add",
        "# T\n\n## STEPS (ongoing)\n\n- [ ] one\n",
        json!({"text": "case"}),
    ));
    out.push(case(
        "add-with-chronologie",
        "add",
        "# T\n\n## Goal\n\ng.\n\n## Chronologie\n\nc.\n",
        json!({"text": "fr"}),
    ));

    // ---- reorder
    out.push(case(
        "rx-shuffle",
        "reorder",
        "## Steps\n\n- [ ] a\n- [x] b\n- [~] c\n",
        json!({"order": [4, 2, 3]}),
    ));
    out.push(case(
        "rx-reject-non-checkbox",
        "reorder",
        "heading\n- [ ] a\n- [ ] b\n",
        json!({"order": [0, 1, 2]}),
    ));
    out.push(case(
        "rx-reject-oob",
        "reorder",
        "- [ ] a\n- [ ] b\n",
        json!({"order": [0, 99]}),
    ));
    out.push(case(
        "rx-identity",
        "reorder",
        "- [ ] a\n- [x] b\n- [~] c\n",
        json!({"order": [0, 1, 2]}),
    ));

    out
}

/// Extra cases built from live-corpus READMEs: for each README with at
/// least one checkbox, exercise toggle + add + set_priority on real
/// content. We only *read* the live file, never mutate it — each case
/// copies the bytes into an isolated tempfile.
fn live_cases(base_dir: &Path) -> Vec<Case> {
    let mut out = Vec::new();
    let projects = base_dir.join("projects");
    let mut readmes: Vec<PathBuf> = Vec::new();
    walk_readmes(&projects, &mut readmes);
    readmes.sort();

    // Cap the live corpus count so the diff stays fast (still covers
    // every parser/render branch we hit in practice).
    for path in readmes.iter().take(30) {
        let Ok(content) = fs::read_to_string(path) else {
            continue;
        };
        let rel = path
            .strip_prefix(base_dir)
            .map(|p| p.to_string_lossy().replace('/', "_"))
            .unwrap_or_else(|_| path.file_name().unwrap().to_string_lossy().into_owned());
        let rel = rel.replace(".md", "");

        out.push(case(
            &format!("live-sp-{rel}"),
            "set_priority",
            &content,
            json!({"priority": "soon"}),
        ));
        out.push(case(
            &format!("live-add-{rel}"),
            "add",
            &content,
            json!({"text": "diff-harness-added-step"}),
        ));
        // Find the first checkbox line and toggle it.
        if let Some((idx, _)) = content
            .split('\n')
            .enumerate()
            .find(|(_, l)| l.contains("- [ ]") || l.contains("- [x]") || l.contains("- [X]"))
        {
            out.push(case(
                &format!("live-tg-{rel}"),
                "toggle",
                &content,
                json!({"line": idx}),
            ));
        }
    }
    out
}

fn walk_readmes(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for e in entries.flatten() {
        let p = e.path();
        let n = e.file_name();
        let n = n.to_string_lossy();
        if p.is_dir() {
            if n.starts_with('.') {
                continue;
            }
            walk_readmes(&p, out);
        } else if n == "README.md" {
            out.push(p);
        }
    }
}

fn apply_rust(tmp: &Path, c: &Case) -> (Value, String) {
    let path = tmp.join(format!("{}.md", c.id));
    fs::write(&path, &c.initial).expect("seed tempfile");

    let ret: Value = match c.op.as_str() {
        "set_priority" => {
            let p = c.args["priority"].as_str().unwrap_or("");
            json!(set_priority(&path, p).expect("set_priority"))
        }
        "toggle" => {
            let line = c.args["line"].as_u64().unwrap_or(0) as usize;
            let r = toggle_checkbox(&path, line).expect("toggle");
            match r {
                Some(s) => serde_json::to_value(s).unwrap(),
                None => Value::Null,
            }
        }
        "remove" => {
            let line = c.args["line"].as_u64().unwrap_or(0) as usize;
            json!(remove_step(&path, line).expect("remove"))
        }
        "edit" => {
            let line = c.args["line"].as_u64().unwrap_or(0) as usize;
            let t = c.args["text"].as_str().unwrap_or("");
            json!(edit_step(&path, line, t).expect("edit"))
        }
        "add" => {
            let t = c.args["text"].as_str().unwrap_or("");
            let s = c.args.get("section").and_then(|v| v.as_str());
            json!(add_step(&path, t, s).expect("add"))
        }
        "reorder" => {
            let order: Vec<usize> = c.args["order"]
                .as_array()
                .map(|a| a.iter().map(|v| v.as_u64().unwrap_or(0) as usize).collect())
                .unwrap_or_default();
            json!(reorder_all(&path, &order).expect("reorder"))
        }
        other => panic!("unknown op: {other}"),
    };
    let final_bytes = fs::read_to_string(&path).expect("read back");
    (ret, final_bytes)
}

fn run_python(
    python: &str,
    driver: &Path,
    condash_src: &Path,
    cases: &[Case],
) -> std::io::Result<HashMap<String, DriverLine>> {
    let mut child = Command::new(python)
        .arg(driver)
        .arg("--condash-src")
        .arg(condash_src)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;

    // Writer runs on its own thread so stdin and stdout drain in
    // parallel — otherwise, with ~120 cases each carrying full
    // README bytes, Python's stdout pipe fills before we start
    // reading here, Python blocks on write, stops reading stdin,
    // and the main thread blocks forever on its own write. Classic
    // pipe deadlock. Separate writer thread is the standard fix.
    let stdin = child.stdin.take().expect("piped stdin");
    let serialised: Vec<String> = cases
        .iter()
        .map(|c| serde_json::to_string(c).expect("serialise case"))
        .collect();
    let writer = std::thread::spawn(move || -> std::io::Result<()> {
        let mut stdin = stdin;
        for line in serialised {
            writeln!(stdin, "{line}")?;
        }
        Ok(()) // stdin dropped here → EOF reaches Python.
    });

    let stdout = child.stdout.take().expect("piped stdout");
    let reader = BufReader::new(stdout);
    let mut map = HashMap::with_capacity(cases.len());
    for line in reader.lines() {
        let line = line?;
        if line.is_empty() {
            continue;
        }
        let parsed: DriverLine = serde_json::from_str(&line)
            .unwrap_or_else(|e| panic!("driver emitted malformed JSON {line:?}: {e}"));
        map.insert(parsed.id.clone(), parsed);
    }

    writer.join().expect("writer thread panicked")?;

    let status = child.wait()?;
    if !status.success() {
        return Err(std::io::Error::other(format!(
            "python driver exited with {status}"
        )));
    }
    Ok(map)
}

fn main() {
    let args = parse_args();

    let mut cases = synthetic_cases();
    cases.extend(live_cases(&args.conception));
    eprintln!("diff(mutations): {} synthetic + live cases", cases.len());

    let py = run_python(&args.python, &args.driver, &args.condash_src, &cases)
        .expect("python driver failed");

    let tmp = TempDir::new().expect("tempdir");

    let mut matched = 0usize;
    let mut ret_mismatch = 0usize;
    let mut bytes_mismatch = 0usize;
    let mut missing_py = 0usize;

    for c in &cases {
        let (rust_ret, rust_final) = apply_rust(tmp.path(), c);
        let Some(py_row) = py.get(&c.id) else {
            eprintln!("[MISSING-PY] {}", c.id);
            missing_py += 1;
            continue;
        };
        let ret_ok = py_row.ret == rust_ret;
        let bytes_ok = py_row.finalc == rust_final;
        if ret_ok && bytes_ok {
            matched += 1;
            continue;
        }
        if !ret_ok {
            ret_mismatch += 1;
            eprintln!(
                "[RET MISMATCH] {}: py={} rust={}",
                c.id, py_row.ret, rust_ret
            );
        }
        if !bytes_ok {
            bytes_mismatch += 1;
            eprintln!(
                "[BYTES MISMATCH] {}\n  py   = {:?}\n  rust = {:?}",
                c.id, py_row.finalc, rust_final
            );
        }
    }

    eprintln!(
        "diff(mutations): matched={matched} ret-mismatch={ret_mismatch} bytes-mismatch={bytes_mismatch} missing-py={missing_py} total={}",
        cases.len()
    );

    if ret_mismatch > 0 || bytes_mismatch > 0 || missing_py > 0 {
        std::process::exit(1);
    }
}

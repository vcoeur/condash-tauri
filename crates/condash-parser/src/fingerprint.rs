//! Cheap content hashes that drive `/check-updates`.
//!
//! Rust port of the fingerprint helpers in `src/condash/parser.py`:
//! `_compute_fingerprint`, `_hash`, `_card_content_data`,
//! `compute_project_node_fingerprints`, `_knowledge_card_content`,
//! `_walk_knowledge_nodes`, `compute_knowledge_node_fingerprints`.
//!
//! Python builds a nested tuple of the content that should dirty-mark
//! a card or group, calls `repr()` on it, and hashes the UTF-8 bytes
//! with MD5, truncating to 16 hex chars. We reproduce Python's `repr`
//! output for tuples, lists, strings, and ints so the Rust build and
//! the Python build compute byte-identical fingerprints against the
//! same parsed items. This matters while both builds dogfood in
//! parallel (Phase 6) — without it the dashboard's cache-bust logic
//! would thrash every time the user hopped between the two.

use std::collections::{BTreeMap, HashMap};

use md5::{Digest, Md5};

use crate::knowledge::{KnowledgeCard, KnowledgeNode};
use crate::readme::ItemReadme;
use crate::tree::{flatten_tree_paths, ItemTree};
use crate::Item;

/// A subset of Python's value universe — just what our fingerprint
/// data actually contains. `PyValue::repr` reproduces Python's
/// `repr()` output for these shapes byte-identically.
#[derive(Debug, Clone)]
pub enum PyValue {
    Str(String),
    Int(i64),
    /// Python tuple: renders as `(a, b, c)`; single-element is `(x,)`.
    Tuple(Vec<PyValue>),
    /// Python list: renders as `[a, b, c]`. No trailing-comma quirk.
    List(Vec<PyValue>),
}

impl PyValue {
    /// Render this value the way CPython's `repr()` would.
    ///
    /// Strings: single-quote preferred; switches to double-quote when
    /// the string contains a single quote but no double quote. Escapes
    /// `\\`, the chosen quote, `\n`, `\r`, `\t`, and control chars in
    /// the `\x00`-`\x1f` + `\x7f` range. Non-ASCII chars pass through
    /// verbatim (Python 3 `repr` leaves them unescaped).
    pub fn repr(&self) -> String {
        let mut out = String::new();
        self.repr_into(&mut out);
        out
    }

    fn repr_into(&self, out: &mut String) {
        match self {
            PyValue::Str(s) => repr_str(s, out),
            PyValue::Int(i) => out.push_str(&i.to_string()),
            PyValue::Tuple(items) => {
                out.push('(');
                for (i, v) in items.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    v.repr_into(out);
                }
                // `(x,)` trailing comma for single-element tuples.
                if items.len() == 1 {
                    out.push(',');
                }
                out.push(')');
            }
            PyValue::List(items) => {
                out.push('[');
                for (i, v) in items.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    v.repr_into(out);
                }
                out.push(']');
            }
        }
    }
}

fn repr_str(s: &str, out: &mut String) {
    let has_single = s.contains('\'');
    let has_double = s.contains('"');
    let quote = if has_single && !has_double { '"' } else { '\'' };
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || (c as u32) == 0x7F => {
                // Python uses `\x%02x` for 0..0x20 except the named
                // escapes handled above, and for 0x7F.
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
}

/// MD5 of `py_repr(data)` truncated to 16 hex chars — Python's
/// `hashlib.md5(repr(data).encode()).hexdigest()[:16]`.
pub fn hash(data: &PyValue) -> String {
    let repr = data.repr();
    let digest = Md5::digest(repr.as_bytes());
    let hex = format!("{digest:x}");
    hex[..16].to_string()
}

/// Overall fingerprint across every parsed item. Sorted by slug so
/// ordering on disk doesn't influence the hash.
pub fn compute_fingerprint(items: &[Item]) -> String {
    let mut sorted: Vec<&Item> = items.iter().collect();
    sorted.sort_by(|a, b| a.readme.slug.cmp(&b.readme.slug));
    let list = PyValue::List(
        sorted
            .into_iter()
            .map(|item| item_fingerprint_tuple(&item.readme, &item.files))
            .collect(),
    );
    hash(&list)
}

/// Per-item nine-tuple matching Python's `_compute_fingerprint` append:
/// (slug, title, priority, kind, apps, summary, sections, deliverables, files).
fn item_fingerprint_tuple(readme: &ItemReadme, files: &ItemTree) -> PyValue {
    PyValue::Tuple(vec![
        PyValue::Str(readme.slug.clone()),
        PyValue::Str(readme.title.clone()),
        PyValue::Str(readme.priority.clone()),
        PyValue::Str(readme.kind.clone()),
        apps_tuple(&readme.apps),
        PyValue::Str(readme.summary.clone()),
        sections_tuple(readme),
        deliverables_tuple(readme),
        files_tuple(files),
    ])
}

/// Card-content eight-tuple used by per-node project fingerprints.
/// Mirrors Python's `_card_content_data` — intentionally omits
/// `priority` so a priority change only re-keys the id (card moves
/// groups), it doesn't content-dirty the card itself.
fn card_content_data(readme: &ItemReadme, files: &ItemTree) -> PyValue {
    PyValue::Tuple(vec![
        PyValue::Str(readme.slug.clone()),
        PyValue::Str(readme.title.clone()),
        PyValue::Str(readme.kind.clone()),
        apps_tuple(&readme.apps),
        PyValue::Str(readme.summary.clone()),
        sections_tuple(readme),
        deliverables_tuple(readme),
        files_tuple(files),
    ])
}

fn apps_tuple(apps: &[String]) -> PyValue {
    PyValue::Tuple(apps.iter().cloned().map(PyValue::Str).collect())
}

fn sections_tuple(readme: &ItemReadme) -> PyValue {
    let sections = readme
        .sections
        .iter()
        .map(|s| {
            let items = PyValue::Tuple(
                s.items
                    .iter()
                    .map(|it| {
                        PyValue::Tuple(vec![
                            PyValue::Str(it.text.clone()),
                            PyValue::Str(checkbox_status_str(it.status).to_string()),
                        ])
                    })
                    .collect(),
            );
            PyValue::Tuple(vec![PyValue::Str(s.heading.clone()), items])
        })
        .collect();
    PyValue::Tuple(sections)
}

fn deliverables_tuple(readme: &ItemReadme) -> PyValue {
    PyValue::Tuple(
        readme
            .deliverables
            .iter()
            .map(|d| {
                PyValue::Tuple(vec![
                    PyValue::Str(d.label.clone()),
                    PyValue::Str(d.path.clone()),
                ])
            })
            .collect(),
    )
}

fn files_tuple(files: &ItemTree) -> PyValue {
    PyValue::Tuple(
        flatten_tree_paths(files)
            .into_iter()
            .map(PyValue::Str)
            .collect(),
    )
}

fn checkbox_status_str(status: crate::sections::CheckboxStatus) -> &'static str {
    use crate::sections::CheckboxStatus::*;
    match status {
        Open => "open",
        Done => "done",
        Progress => "progress",
        Abandoned => "abandoned",
    }
}

/// Return `{node_id: hash}` for the Projects tab hierarchy.
///
/// See Python's `compute_project_node_fingerprints` docstring for the
/// scheme; the core idea is that group hashes depend only on slug
/// membership (not child content), so a card edit dirty-marks the card
/// and nothing above it.
pub fn compute_project_node_fingerprints(items: &[Item]) -> HashMap<String, String> {
    let mut out: HashMap<String, String> = HashMap::new();

    // Per-card hashes.
    for item in items {
        let id = format!("projects/{}/{}", item.readme.priority, item.readme.slug);
        out.insert(id, hash(&card_content_data(&item.readme, &item.files)));
    }

    // Per-priority group hashes. Use BTreeMap so iteration is
    // deterministic — helps debugging but doesn't affect the hash
    // (each group is hashed independently).
    let mut by_priority: BTreeMap<&str, Vec<&Item>> = BTreeMap::new();
    for item in items {
        by_priority
            .entry(item.readme.priority.as_str())
            .or_default()
            .push(item);
    }
    for (priority, group) in &by_priority {
        let mut slugs: Vec<String> = group.iter().map(|i| i.readme.slug.clone()).collect();
        slugs.sort();
        let slug_tuple = PyValue::Tuple(slugs.into_iter().map(PyValue::Str).collect());
        let data = PyValue::Tuple(vec![
            PyValue::Str("group".into()),
            PyValue::Str((*priority).to_string()),
            slug_tuple,
        ]);
        out.insert(format!("projects/{}", priority), hash(&data));
    }

    // Whole-tab membership hash.
    let mut tab_pairs: Vec<(String, String)> = items
        .iter()
        .map(|i| (i.readme.priority.clone(), i.readme.slug.clone()))
        .collect();
    tab_pairs.sort();
    let tab_tuple = PyValue::Tuple(
        tab_pairs
            .into_iter()
            .map(|(p, s)| PyValue::Tuple(vec![PyValue::Str(p), PyValue::Str(s)]))
            .collect(),
    );
    let tab_data = PyValue::Tuple(vec![
        PyValue::Str("tab".into()),
        PyValue::Str("projects".into()),
        tab_tuple,
    ]);
    out.insert("projects".into(), hash(&tab_data));

    out
}

/// Return `{node_id: hash}` for the Knowledge tree.
///
/// Directory hashes depend only on the set of direct child ids, so a
/// card edit dirty-marks only that card. Adds/removes at a directory
/// level dirty-mark just that directory.
pub fn compute_knowledge_node_fingerprints(
    tree: Option<&KnowledgeNode>,
) -> HashMap<String, String> {
    let mut out: HashMap<String, String> = HashMap::new();
    if let Some(root) = tree {
        walk_nodes(root, &mut out);
    }
    out
}

fn walk_nodes(node: &KnowledgeNode, out: &mut HashMap<String, String>) -> String {
    let node_id = node.rel_dir.clone();
    let mut child_ids: Vec<String> = Vec::new();

    if let Some(idx) = node.index.as_ref() {
        let card_id = idx.path.clone();
        out.insert(card_id.clone(), hash(&knowledge_card_content(idx)));
        child_ids.push(card_id);
    }
    for entry in &node.body {
        let card_id = entry.path.clone();
        out.insert(card_id.clone(), hash(&knowledge_card_content(entry)));
        child_ids.push(card_id);
    }
    for child in &node.children {
        let child_id = walk_nodes(child, out);
        child_ids.push(child_id);
    }

    let mut sorted = child_ids.clone();
    sorted.sort();
    let data = PyValue::Tuple(vec![
        PyValue::Str("dir".into()),
        PyValue::Str(node_id.clone()),
        PyValue::Tuple(sorted.into_iter().map(PyValue::Str).collect()),
    ]);
    out.insert(node_id.clone(), hash(&data));
    node_id
}

fn knowledge_card_content(card: &KnowledgeCard) -> PyValue {
    PyValue::Tuple(vec![
        PyValue::Str(card.path.clone()),
        PyValue::Str(card.title.clone()),
        PyValue::Str(card.desc.clone()),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn py_repr_strings_prefer_single_quote() {
        assert_eq!(PyValue::Str("hello".into()).repr(), "'hello'");
        assert_eq!(PyValue::Str("".into()).repr(), "''");
    }

    #[test]
    fn py_repr_switches_to_double_quote_when_string_contains_single() {
        assert_eq!(PyValue::Str("it's".into()).repr(), "\"it's\"");
    }

    #[test]
    fn py_repr_escapes_single_quote_when_string_has_both() {
        assert_eq!(PyValue::Str("a'b\"c".into()).repr(), "'a\\'b\"c'");
    }

    #[test]
    fn py_repr_named_escapes() {
        assert_eq!(PyValue::Str("\n\t\r\\".into()).repr(), "'\\n\\t\\r\\\\'");
    }

    #[test]
    fn py_repr_control_chars_as_hex() {
        assert_eq!(
            PyValue::Str("\x01\x1f\x7f".into()).repr(),
            "'\\x01\\x1f\\x7f'"
        );
    }

    #[test]
    fn py_repr_non_ascii_passes_through() {
        // Python 3 repr does not escape Latin-1 or BMP chars.
        assert_eq!(PyValue::Str("éà中".into()).repr(), "'éà中'");
    }

    #[test]
    fn py_repr_tuple_trailing_comma_for_single_element() {
        assert_eq!(
            PyValue::Tuple(vec![PyValue::Str("a".into())]).repr(),
            "('a',)"
        );
        assert_eq!(
            PyValue::Tuple(vec![PyValue::Str("a".into()), PyValue::Str("b".into())]).repr(),
            "('a', 'b')"
        );
        assert_eq!(PyValue::Tuple(vec![]).repr(), "()");
    }

    #[test]
    fn py_repr_list_no_trailing_comma() {
        assert_eq!(
            PyValue::List(vec![PyValue::Str("a".into())]).repr(),
            "['a']"
        );
        assert_eq!(PyValue::List(vec![]).repr(), "[]");
    }

    #[test]
    fn py_repr_nested() {
        let v = PyValue::Tuple(vec![
            PyValue::Str("dir".into()),
            PyValue::Str("knowledge/topics".into()),
            PyValue::Tuple(vec![
                PyValue::Str("knowledge/topics/a.md".into()),
                PyValue::Str("knowledge/topics/b.md".into()),
            ]),
        ]);
        assert_eq!(
            v.repr(),
            "('dir', 'knowledge/topics', ('knowledge/topics/a.md', 'knowledge/topics/b.md'))"
        );
    }

    #[test]
    fn py_repr_ints() {
        assert_eq!(PyValue::Int(0).repr(), "0");
        assert_eq!(PyValue::Int(-42).repr(), "-42");
        assert_eq!(
            PyValue::Tuple(vec![PyValue::Int(1), PyValue::Int(2)]).repr(),
            "(1, 2)"
        );
    }

    #[test]
    fn hash_truncates_md5_to_16_chars() {
        // Baseline from Python: md5("'hello'") hex digest.
        let got = hash(&PyValue::Str("hello".into()));
        assert_eq!(got.len(), 16);
        // Not asserting the exact bytes — we diff against Python on the
        // live corpus in parser-diff. Here we only check the shape.
    }

    #[test]
    fn fingerprint_is_stable_for_equal_items() {
        use crate::sections::{CheckboxStatus, Section, SectionItem};
        let make = || Item {
            readme: ItemReadme {
                slug: "foo".into(),
                title: "Foo".into(),
                date: "".into(),
                priority: "now".into(),
                invalid_status: None,
                apps: vec![],
                severity: None,
                summary: "".into(),
                sections: vec![Section {
                    heading: "Steps".into(),
                    items: vec![SectionItem {
                        text: "one".into(),
                        done: true,
                        status: CheckboxStatus::Done,
                        line: 0,
                    }],
                }],
                deliverables: vec![],
                done: 1,
                total: 1,
                path: "x".into(),
                kind: "project".into(),
            },
            files: ItemTree::default(),
        };
        let a = compute_fingerprint(&[make()]);
        let b = compute_fingerprint(&[make()]);
        assert_eq!(a, b);
    }
}

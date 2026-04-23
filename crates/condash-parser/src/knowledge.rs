//! Knowledge-tree walker shared by the knowledge and code explorer
//! tabs. Builds a recursive `{name, label, rel_dir, index, body,
//! children, count}` node shape from the on-disk `knowledge/` tree;
//! the render layer and fingerprint hasher both consume this shape
//! directly.

use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};

const DESC_MAX: usize = 220;

/// One file card — title + short description + path-relative-to-base.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KnowledgeCard {
    pub path: String,
    pub title: String,
    pub desc: String,
}

/// One directory node in the knowledge tree.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KnowledgeNode {
    pub name: String,
    pub label: String,
    pub rel_dir: String,
    /// Present when the directory carries an `index.md` badge.
    pub index: Option<KnowledgeCard>,
    pub body: Vec<KnowledgeCard>,
    pub children: Vec<KnowledgeNode>,
    pub count: usize,
}

/// Pick a human label + short description from one `.md` file. Mirrors
/// `_knowledge_title_and_desc`: first `# heading` wins as title (or the
/// filename as fallback with `-` / `_` turned into spaces), first
/// non-blank non-heading non-frontmatter line becomes the description.
/// Description is trimmed of a trailing dot and capped at 220 *bytes*
/// to match Python's `str[:220]` slicing.
pub fn knowledge_title_and_desc(path: &Path) -> (String, String) {
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string();
    let mut title = stem.replace('-', " ").replace('_', " ");
    let mut desc = String::new();

    let bytes = match fs::read(path) {
        Ok(b) => b,
        Err(_) => return (title, desc),
    };
    // Python's `read_text(errors="replace")` maps invalid bytes to U+FFFD.
    let text = String::from_utf8_lossy(&bytes);
    let mut title_taken = false;
    for raw in text.split('\n') {
        let line = raw.trim_end_matches('\r').trim();
        if line.is_empty() {
            continue;
        }
        if !title_taken && line.starts_with('#') {
            let picked = line.trim_start_matches('#').trim();
            if !picked.is_empty() {
                title = picked.to_string();
            }
            title_taken = true;
            continue;
        }
        if line.starts_with('#') || line.starts_with("---") {
            continue;
        }
        desc = line.trim_end_matches('.').to_string();
        break;
    }
    // Python's `desc[:220]` slices by codepoint in py3 `str`, which
    // for ASCII is the same as bytes. Use chars() to stay safe with
    // non-ASCII descriptions.
    if desc.chars().count() > DESC_MAX {
        desc = desc.chars().take(DESC_MAX).collect();
    }
    (title, desc)
}

/// Scan `<base_dir>/knowledge/` recursively; returns `None` if the
/// directory is missing. Wrapper matching Python's `collect_knowledge`.
pub fn collect_knowledge(base_dir: &Path) -> Option<KnowledgeNode> {
    collect_tree(base_dir, "knowledge", "Knowledge")
}

/// Generic tree walker used by the knowledge and code explorer tabs.
/// `root_name` is the directory name under `base_dir`; `root_label` is
/// the human label used at the root node only.
pub fn collect_tree(base_dir: &Path, root_name: &str, root_label: &str) -> Option<KnowledgeNode> {
    let root = base_dir.join(root_name);
    if !root.is_dir() {
        return None;
    }
    Some(build_node(base_dir, &root, &root, root_label))
}

fn build_node(base_dir: &Path, root_dir: &Path, d: &Path, root_label: &str) -> KnowledgeNode {
    let is_root = d == root_dir;
    let label = if is_root {
        root_label.to_string()
    } else {
        title_case_segments(&file_name_str(d))
    };

    let mut index: Option<KnowledgeCard> = None;
    let mut body: Vec<KnowledgeCard> = Vec::new();
    let mut children: Vec<KnowledgeNode> = Vec::new();

    let entries = match fs::read_dir(d) {
        Ok(it) => {
            let mut v: Vec<_> = it.flatten().map(|e| e.path()).collect();
            v.sort();
            v
        }
        Err(_) => Vec::new(),
    };

    for entry in entries {
        let name = file_name_str(&entry);
        if name.starts_with('.') {
            continue;
        }
        let meta = match fs::metadata(&entry) {
            Ok(m) => m,
            Err(_) => continue,
        };
        let ft = meta.file_type();
        if ft.is_file() {
            if has_md_suffix(&name) {
                let (title, desc) = knowledge_title_and_desc(&entry);
                let card = KnowledgeCard {
                    path: rel_to(base_dir, &entry),
                    title,
                    desc,
                };
                if name == "index.md" {
                    index = Some(card);
                } else {
                    body.push(card);
                }
            }
        } else if ft.is_dir() {
            let child = build_node(base_dir, root_dir, &entry, root_label);
            if child.count > 0 {
                children.push(child);
            }
        }
    }

    let count = body.len()
        + index.as_ref().map(|_| 1).unwrap_or(0)
        + children.iter().map(|c| c.count).sum::<usize>();
    KnowledgeNode {
        name: if is_root {
            String::new()
        } else {
            file_name_str(d)
        },
        label,
        rel_dir: rel_to(base_dir, d),
        index,
        body,
        children,
        count,
    }
}

/// `name.replace('_', ' ').replace('-', ' ').title()` — Python's
/// `str.title()` uppercases the first letter of each word and lowercases
/// the rest, with word boundaries at non-letter characters.
fn title_case_segments(name: &str) -> String {
    let spaced = name.replace(['_', '-'], " ");
    let mut out = String::with_capacity(spaced.len());
    let mut boundary = true;
    for ch in spaced.chars() {
        if ch.is_alphabetic() {
            if boundary {
                out.extend(ch.to_uppercase());
            } else {
                out.extend(ch.to_lowercase());
            }
            boundary = false;
        } else {
            out.push(ch);
            boundary = true;
        }
    }
    out
}

fn file_name_str(p: &Path) -> String {
    p.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string()
}

fn has_md_suffix(name: &str) -> bool {
    name.to_ascii_lowercase().ends_with(".md")
}

fn rel_to(base: &Path, path: &Path) -> String {
    path.strip_prefix(base)
        .map(|r| r.to_string_lossy().replace('\\', "/"))
        .unwrap_or_else(|_| path.to_string_lossy().into_owned())
}

/// Return the tree node at `rel_dir` (e.g. `knowledge/topics`) or
/// `None`. Recursive; mirrors `find_knowledge_node`.
pub fn find_node<'a>(tree: Option<&'a KnowledgeNode>, rel_dir: &str) -> Option<&'a KnowledgeNode> {
    let tree = tree?;
    if tree.rel_dir == rel_dir {
        return Some(tree);
    }
    for child in &tree.children {
        if let Some(found) = find_node(Some(child), rel_dir) {
            return Some(found);
        }
    }
    None
}

/// Return the card entry (index or body) at file `path` or `None`.
pub fn find_card<'a>(tree: Option<&'a KnowledgeNode>, path: &str) -> Option<&'a KnowledgeCard> {
    let tree = tree?;
    if let Some(idx) = tree.index.as_ref() {
        if idx.path == path {
            return Some(idx);
        }
    }
    for entry in &tree.body {
        if entry.path == path {
            return Some(entry);
        }
    }
    for child in &tree.children {
        if let Some(found) = find_card(Some(child), path) {
            return Some(found);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{self, File};
    use std::io::Write;

    fn write(p: &Path, contents: &str) {
        if let Some(parent) = p.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        File::create(p)
            .unwrap()
            .write_all(contents.as_bytes())
            .unwrap();
    }

    #[test]
    fn title_from_first_heading() {
        let td = tempfile::tempdir().unwrap();
        let p = td.path().join("foo-bar.md");
        write(&p, "# My Page Title\n\nFirst line of body.\n");
        let (t, d) = knowledge_title_and_desc(&p);
        assert_eq!(t, "My Page Title");
        assert_eq!(d, "First line of body");
    }

    #[test]
    fn title_fallback_to_filename_with_dashes_replaced() {
        let td = tempfile::tempdir().unwrap();
        let p = td.path().join("some-topic_thing.md");
        write(&p, "not a heading\nbody\n");
        let (t, d) = knowledge_title_and_desc(&p);
        assert_eq!(t, "some topic thing");
        assert_eq!(d, "not a heading");
    }

    #[test]
    fn desc_strips_trailing_dot_only() {
        let td = tempfile::tempdir().unwrap();
        let p = td.path().join("x.md");
        write(&p, "# T\n\nEllipsis ok...\n");
        // Every trailing dot is stripped — `"foo."` and `"foo…"` collapse.
        let (_t, d) = knowledge_title_and_desc(&p);
        assert_eq!(d, "Ellipsis ok");
    }

    #[test]
    fn desc_skips_headings_after_title() {
        let td = tempfile::tempdir().unwrap();
        let p = td.path().join("x.md");
        // `---` lines and `#` lines are skipped; the first other non-blank
        // line wins. YAML-frontmatter keys between fences leak through on
        // purpose — the parser is intentionally cheap and doesn't model
        // frontmatter structurally.
        write(&p, "# Title\n\n## A subheading\n\nActual body line.\n");
        let (t, d) = knowledge_title_and_desc(&p);
        assert_eq!(t, "Title");
        assert_eq!(d, "Actual body line");
    }

    #[test]
    fn desc_leaks_frontmatter_body_lines() {
        let td = tempfile::tempdir().unwrap();
        let p = td.path().join("x.md");
        write(&p, "---\nmeta: here\n---\n# Title\n\nActual body.\n");
        // `---` lines skipped, `meta: here` is a plain line → taken as desc.
        let (_t, d) = knowledge_title_and_desc(&p);
        assert_eq!(d, "meta: here");
    }

    #[test]
    fn desc_capped_at_220_chars() {
        let td = tempfile::tempdir().unwrap();
        let p = td.path().join("x.md");
        let body = "a".repeat(400);
        write(&p, &format!("# T\n\n{body}\n"));
        let (_t, d) = knowledge_title_and_desc(&p);
        assert_eq!(d.chars().count(), DESC_MAX);
    }

    #[test]
    fn collect_knowledge_returns_none_when_missing() {
        let td = tempfile::tempdir().unwrap();
        assert!(collect_knowledge(td.path()).is_none());
    }

    #[test]
    fn tree_shape_matches_python_contract() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        write(
            &base.join("knowledge/index.md"),
            "# Knowledge\n\nRoot index body.\n",
        );
        write(
            &base.join("knowledge/topics/index.md"),
            "# Topics\n\nTopics index.\n",
        );
        write(
            &base.join("knowledge/topics/testing/playwright-sandbox.md"),
            "# Playwright Sandbox\n\nRecipe line.\n",
        );
        write(&base.join("knowledge/topics/testing/empty-dir-skipped"), "");
        fs::create_dir_all(base.join("knowledge/empty-subtree")).unwrap();

        let tree = collect_knowledge(base).expect("tree present");
        assert_eq!(tree.name, "");
        assert_eq!(tree.label, "Knowledge");
        assert_eq!(tree.rel_dir, "knowledge");
        assert!(tree.index.is_some());
        assert_eq!(tree.index.as_ref().unwrap().title, "Knowledge");

        // empty-subtree is pruned.
        assert_eq!(tree.children.len(), 1);
        let topics = &tree.children[0];
        assert_eq!(topics.name, "topics");
        assert_eq!(topics.label, "Topics");
        assert_eq!(topics.rel_dir, "knowledge/topics");
        assert_eq!(topics.children.len(), 1);

        let testing = &topics.children[0];
        assert_eq!(testing.label, "Testing");
        assert_eq!(testing.rel_dir, "knowledge/topics/testing");
        assert!(testing.index.is_none());
        assert_eq!(testing.body.len(), 1);
        assert_eq!(testing.body[0].title, "Playwright Sandbox");
        assert_eq!(
            testing.body[0].path,
            "knowledge/topics/testing/playwright-sandbox.md"
        );

        // Counts: root has 1 (index) + 1 (topics subtree which has 1 index + 1 body = 2) = 3.
        assert_eq!(testing.count, 1);
        assert_eq!(topics.count, 2);
        assert_eq!(tree.count, 3);
    }

    #[test]
    fn find_node_and_find_card_walk_recursively() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        write(&base.join("knowledge/index.md"), "# K\n");
        write(&base.join("knowledge/topics/index.md"), "# T\n");
        write(&base.join("knowledge/topics/leaf.md"), "# Leaf\n\nHello.\n");
        let tree = collect_knowledge(base).unwrap();

        let topics = find_node(Some(&tree), "knowledge/topics").unwrap();
        assert_eq!(topics.label, "Topics");

        let leaf = find_card(Some(&tree), "knowledge/topics/leaf.md").unwrap();
        assert_eq!(leaf.title, "Leaf");
    }

    #[test]
    fn title_case_handles_multi_word_segments() {
        assert_eq!(
            title_case_segments("cross-repo_gotchas"),
            "Cross Repo Gotchas"
        );
        assert_eq!(title_case_segments("2026-04-now"), "2026 04 Now");
    }
}

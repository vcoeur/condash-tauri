//! Note preview HTML — driven by `GET /note`. Dispatches on
//! [`condash_parser::note_kind`] and emits the markup the dashboard's
//! view pane mounts into (`_mountPdfsIn`, `_renderMermaidIn`,
//! `_wireNoteLinks` in `frontend/src/js/dashboard-main.js`).
//!
//! The markdown path uses `pulldown-cmark` for the core conversion and
//! post-processes `[[wikilink]]` / `[[target|label]]` patterns into the
//! `<a class="wikilink">` and `<a class="wikilink-missing">` shapes the
//! frontend's click handler already understands. Resolution is a simple
//! existence check against `base_dir` — conception/projects use
//! path-style links anyway, so deep wikilink parity with the old
//! Kasten-style resolver is out of scope for the note-modal port.

use std::path::Path;

use once_cell::sync::Lazy;
use pulldown_cmark::{html as md_html, Options, Parser};
use regex::Regex;

use crate::h;

/// `[[target]]` or `[[target|label]]`. Target may contain `/`, `.`, `-`,
/// `_`; label is anything non-`]`.
static WIKILINK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]").expect("wikilink regex compiles"));

/// Render a note for the view pane. `rel_path` is relative to the
/// conception tree; `full_path` is the resolved absolute path (already
/// sandbox-validated by the caller).
pub fn render_note(rel_path: &str, full_path: &Path, base_dir: &Path) -> String {
    let kind = condash_parser::note_kind(full_path);
    match kind {
        "md" => render_markdown(rel_path, full_path, base_dir),
        "pdf" => render_pdf_host(rel_path, full_path),
        "image" => render_image(rel_path, full_path),
        "text" => render_text(full_path),
        _ => format!(
            "<p class=\"note-error\">Binary file — use the Plain tab to view or download.</p>"
        ),
    }
}

fn render_markdown(rel_path: &str, full_path: &Path, base_dir: &Path) -> String {
    let raw = std::fs::read_to_string(full_path).unwrap_or_default();
    let note_dir = rel_path.rsplit_once('/').map(|(d, _)| d).unwrap_or("");
    let with_wikilinks = rewrite_wikilinks(&raw, note_dir, base_dir);

    let mut opts = Options::empty();
    opts.insert(Options::ENABLE_TABLES);
    opts.insert(Options::ENABLE_STRIKETHROUGH);
    opts.insert(Options::ENABLE_TASKLISTS);
    opts.insert(Options::ENABLE_FOOTNOTES);
    opts.insert(Options::ENABLE_HEADING_ATTRIBUTES);
    let parser = Parser::new_ext(&with_wikilinks, opts);
    let mut html = String::new();
    md_html::push_html(&mut html, parser);
    format!("<div class=\"note-md\">{html}</div>")
}

/// Rewrite `[[target]]` / `[[target|label]]` into anchors the frontend
/// recognises. Existence is checked against `base_dir` when the target
/// looks path-like; otherwise the wikilink is left as unresolved.
fn rewrite_wikilinks(src: &str, note_dir: &str, base_dir: &Path) -> String {
    WIKILINK_RE
        .replace_all(src, |caps: &regex::Captures| {
            let target = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
            let label = caps
                .get(2)
                .map(|m| m.as_str().trim())
                .filter(|s| !s.is_empty())
                .unwrap_or(target);
            if target.is_empty() {
                return format!(
                    "<a class=\"wikilink-missing\" title=\"Empty wikilink\">{}</a>",
                    h(label)
                );
            }
            let resolved = resolve_wikilink(target, note_dir, base_dir);
            match resolved {
                Some(rel) => format!(
                    "<a class=\"wikilink\" href=\"{}\">{}</a>",
                    h(&rel),
                    h(label)
                ),
                None => format!(
                    "<a class=\"wikilink-missing\" title=\"Unresolved wikilink: {}\">{}</a>",
                    h(target),
                    h(label)
                ),
            }
        })
        .into_owned()
}

fn resolve_wikilink(target: &str, note_dir: &str, base_dir: &Path) -> Option<String> {
    // Treat `target` as a conception-tree-relative path if it contains `/`
    // or ends in `.md`; otherwise resolve relative to the note's directory.
    let candidates: Vec<String> = if target.contains('/') {
        vec![target.to_string(), format!("{target}.md")]
    } else if note_dir.is_empty() {
        vec![target.to_string(), format!("{target}.md")]
    } else {
        vec![
            format!("{note_dir}/{target}"),
            format!("{note_dir}/{target}.md"),
            target.to_string(),
            format!("{target}.md"),
        ]
    };
    for cand in candidates {
        let full = base_dir.join(&cand);
        if full.is_file() {
            return Some(cand);
        }
    }
    None
}

fn render_pdf_host(rel_path: &str, full_path: &Path) -> String {
    let filename = full_path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| rel_path.to_string());
    format!(
        "<div class=\"note-pdf-host\" data-pdf-src=\"/asset/{src}\" data-pdf-filename=\"{name}\"></div>",
        src = h(rel_path),
        name = h(&filename),
    )
}

fn render_image(rel_path: &str, full_path: &Path) -> String {
    let alt = full_path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| rel_path.to_string());
    format!(
        "<div class=\"note-image\"><img src=\"/asset/{src}\" alt=\"{alt}\" loading=\"lazy\"></div>",
        src = h(rel_path),
        alt = h(&alt),
    )
}

fn render_text(full_path: &Path) -> String {
    match std::fs::read_to_string(full_path) {
        Ok(body) => format!("<pre class=\"note-text\">{}</pre>", h(&body)),
        Err(_) => "<p class=\"note-error\">Failed to read file.</p>".into(),
    }
}

/// File metadata payload returned by `GET /note-raw`. `mtime` is the
/// modified-time as epoch seconds; `kind` is the same string the view
/// renderer dispatches on.
pub fn raw_payload(full_path: &Path) -> Option<serde_json::Value> {
    let kind = condash_parser::note_kind(full_path);
    let content = match kind {
        "md" | "text" => std::fs::read_to_string(full_path).ok()?,
        _ => return None,
    };
    let mtime = full_path
        .metadata()
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    Some(serde_json::json!({
        "content": content,
        "kind": kind,
        "mtime": mtime,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(path: &Path, body: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, body).unwrap();
    }

    #[test]
    fn markdown_renders_headings_and_links() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let note = base.join("projects/2026-04/foo/notes/a.md");
        write(&note, "# Title\n\nSee [link](../README.md).\n");
        let html = render_note("projects/2026-04/foo/notes/a.md", &note, base);
        assert!(html.contains("<h1"));
        assert!(html.contains("Title"));
        assert!(html.contains("href=\"../README.md\""));
    }

    #[test]
    fn wikilinks_resolve_against_base() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let note = base.join("projects/2026-04/foo/README.md");
        write(&note, "body\n");
        let target = base.join("knowledge/conventions.md");
        write(&target, "k\n");
        let src = "See [[knowledge/conventions.md|conv]] and [[missing/thing]].";
        let out = rewrite_wikilinks(src, "projects/2026-04/foo", base);
        assert!(out.contains("class=\"wikilink\""));
        assert!(out.contains("href=\"knowledge/conventions.md\""));
        assert!(out.contains("class=\"wikilink-missing\""));
    }

    #[test]
    fn pdf_host_emits_expected_attrs() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let pdf = base.join("projects/2026-04/foo/notes/report.pdf");
        write(&pdf, "%PDF-1.4\n");
        let html = render_note("projects/2026-04/foo/notes/report.pdf", &pdf, base);
        assert!(html.contains("class=\"note-pdf-host\""));
        assert!(html.contains("data-pdf-src=\"/asset/projects/2026-04/foo/notes/report.pdf\""));
        assert!(html.contains("data-pdf-filename=\"report.pdf\""));
    }

    #[test]
    fn image_emits_asset_url() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let img = base.join("k/photo.png");
        write(&img, "PNG");
        let html = render_note("k/photo.png", &img, base);
        assert!(html.contains("<img"));
        assert!(html.contains("src=\"/asset/k/photo.png\""));
    }

    #[test]
    fn raw_payload_roundtrips_md() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let note = base.join("note.md");
        write(&note, "# hi\n");
        let v = raw_payload(&note).expect("payload");
        assert_eq!(v["kind"], "md");
        assert_eq!(v["content"], "# hi\n");
        assert!(v["mtime"].as_f64().unwrap() > 0.0);
    }

    #[test]
    fn raw_payload_none_for_binary() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        let pdf = base.join("note.pdf");
        write(&pdf, "%PDF");
        assert!(raw_payload(&pdf).is_none());
    }
}

//! History-tab search backend.
//!
//! Broadens the Projects-tab string filter: matches README bodies,
//! note + text-file content, and filenames. Returns per-project hits
//! with HTML-escaped snippets and `<mark>` wrapping, scored by source
//! (title > header > body > filename) and recency.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use condash_parser::Item;
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};

use crate::RenderCtx;

/// File extensions whose content we read + search. Filenames are
/// searched regardless of extension.
const CONTENT_EXTS: &[&str] = &[".md", ".txt", ".yml", ".yaml"];

/// Skip content-indexing files larger than this so a stray big log
/// doesn't dominate cost.
const MAX_CONTENT_BYTES: u64 = 512 * 1024;

const SNIPPET_RADIUS: usize = 60;

/// Source-weight table — a title hit outranks a body hit so the
/// ranking feels intuitive for "where did I write this?" queries.
fn source_weight(src: &str) -> i64 {
    match src {
        "title" => 4,
        "filename" => 3,
        "readme" | "note" => 2,
        _ => 1,
    }
}

fn status_to_subtab(status: &str) -> &'static str {
    match status {
        "now" | "review" => "current",
        "soon" | "later" => "next",
        "backlog" => "backlog",
        "done" => "done",
        _ => "current",
    }
}

/// One hit within a project. Matches Python's dict fields.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Hit {
    pub source: String,
    pub label: String,
    pub path: String,
    pub snippet: String,
}

/// One per-project result bundle.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SearchResult {
    pub slug: String,
    pub title: String,
    pub kind: String,
    pub status: String,
    pub subtab: String,
    pub path: String,
    pub month: String,
    pub hits: Vec<Hit>,
}

fn tokenise(q: &str) -> Vec<String> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<String> = Vec::new();
    for raw in q.split_whitespace() {
        let lower = raw.to_lowercase();
        if lower.is_empty() {
            continue;
        }
        if seen.insert(lower.clone()) {
            out.push(lower);
        }
    }
    out
}

/// HTML-escape — mirrors Python's `html.escape(quote=True)`.
fn html_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            other => out.push(other),
        }
    }
    out
}

/// Collapse any run of whitespace to a single space and strip both
/// ends. Uses `regex` so Unicode whitespace (non-breaking space, CJK
/// ideographic space, …) is handled the same as ASCII.
fn collapse_whitespace(text: &str) -> String {
    static WS_RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = WS_RE.get_or_init(|| Regex::new(r"\s+").unwrap());
    re.replace_all(text, " ").trim().to_string()
}

fn build_snippet(text: &str, tokens: &[String], radius: usize) -> String {
    if text.is_empty() || tokens.is_empty() {
        return String::new();
    }
    // All index math is done in char-space (not bytes). Rust's
    // `str::find` returns a byte offset, which is fine for ASCII but
    // slices mid-codepoint on French content with accents or em-dashes.
    let text_chars: Vec<char> = text.chars().collect();
    let hay_chars: Vec<char> = text.to_lowercase().chars().collect();
    // `to_lowercase()` can in theory change char count (rare Unicode
    // edge cases like `İ` → `i̇`). For the conception corpus this
    // doesn't happen, so we don't re-align the indices after lowercasing.

    let mut best: Option<(usize, usize)> = None;
    for tok in tokens {
        let tok_chars: Vec<char> = tok.chars().collect();
        if tok_chars.is_empty() {
            continue;
        }
        if let Some(p) = find_subseq(&hay_chars, &tok_chars) {
            if best.map_or(true, |(cur, _)| p < cur) {
                best = Some((p, tok_chars.len()));
            }
        }
    }
    let Some((pos, hit_len)) = best else {
        return String::new();
    };

    let mut start_c = pos.saturating_sub(radius);
    let mut end_c = (pos + hit_len + radius).min(text_chars.len());

    if start_c > 0 {
        // Python: ws = text.rfind(" ", 0, start)  — returns -1 on no match.
        // Then `if 0 <= start - ws < 20: start = ws + 1`. When ws is -1,
        // `start - (-1) = start + 1`, so short snippets (start < 19)
        // snap to start = 0 rather than keep the leading `…`.
        let ws_i32: i32 = text_chars[..start_c]
            .iter()
            .rposition(|&c| c == ' ')
            .map(|i| i as i32)
            .unwrap_or(-1);
        let delta = start_c as i32 - ws_i32;
        if (0..20).contains(&delta) {
            start_c = (ws_i32 + 1) as usize;
        }
    }
    if end_c < text_chars.len() {
        // Python: we = text.find(" ", end) — returns -1 on no match, in
        // which case the `if we >= 0 and we - end < 20` check is false,
        // so no snap. Rust mirrors via `None` → don't snap.
        if let Some(offset) = text_chars[end_c..].iter().position(|&c| c == ' ') {
            let we = end_c + offset;
            if we - end_c < 20 {
                end_c = we;
            }
        }
    }

    let frag: String = text_chars[start_c..end_c].iter().collect();
    let frag = collapse_whitespace(&frag);
    let escaped = html_escape(&frag);

    let pattern_body = tokens
        .iter()
        .map(|t| regex::escape(t))
        .collect::<Vec<_>>()
        .join("|");
    let pat = RegexBuilder::new(&format!("({pattern_body})"))
        .case_insensitive(true)
        .build()
        .unwrap();
    let marked = pat.replace_all(&escaped, "<mark>$1</mark>").to_string();

    let prefix = if start_c > 0 { "…" } else { "" };
    let suffix = if end_c < text_chars.len() { "…" } else { "" };
    format!("{prefix}{marked}{suffix}")
}

fn find_subseq(hay: &[char], needle: &[char]) -> Option<usize> {
    if needle.is_empty() {
        return Some(0);
    }
    if needle.len() > hay.len() {
        return None;
    }
    hay.windows(needle.len()).position(|w| w == needle)
}

fn read_text(path: &Path) -> Option<String> {
    let md = std::fs::metadata(path).ok()?;
    if md.len() > MAX_CONTENT_BYTES {
        return None;
    }
    std::fs::read_to_string(path).ok()
}

/// Everything after the first `## ` heading — the README body prose.
fn readme_body(text: &str) -> String {
    let lines: Vec<&str> = text.split('\n').collect();
    for (i, line) in lines.iter().enumerate() {
        if line.starts_with("## ") {
            return lines[i..].join("\n");
        }
    }
    String::new()
}

fn lower_ext(p: &Path) -> String {
    p.extension()
        .and_then(|e| e.to_str())
        .map(|e| format!(".{}", e.to_ascii_lowercase()))
        .unwrap_or_default()
}

/// `(rel_path, abs_path, is_content)` for each non-hidden file under
/// `item_dir`. Skips top-level `README.md` (indexed separately via
/// `readme_body`).
fn iter_item_files(item_dir: &Path) -> Vec<(PathBuf, PathBuf, bool)> {
    let mut out: Vec<(PathBuf, PathBuf, bool)> = Vec::new();
    rglob(item_dir, item_dir, &mut out);
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

fn rglob(base: &Path, cur: &Path, out: &mut Vec<(PathBuf, PathBuf, bool)>) {
    let Ok(entries) = std::fs::read_dir(cur) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        if name.starts_with('.') {
            continue;
        }
        let ft = match entry.file_type() {
            Ok(f) => f,
            Err(_) => continue,
        };
        if ft.is_dir() {
            rglob(base, &path, out);
            continue;
        }
        if !ft.is_file() {
            continue;
        }
        let rel = match path.strip_prefix(base) {
            Ok(p) => p.to_path_buf(),
            Err(_) => continue,
        };
        // Skip the top-level README.md — its body is indexed separately.
        let parts: Vec<_> = rel.components().collect();
        if parts.len() == 1 {
            if let std::path::Component::Normal(n) = parts[0] {
                if n == "README.md" {
                    continue;
                }
            }
        }
        let ext = lower_ext(&path);
        let is_content = CONTENT_EXTS.iter().any(|e| e == &ext.as_str());
        out.push((rel, path, is_content));
    }
}

fn rel_str(p: &Path) -> String {
    p.to_string_lossy().replace('\\', "/")
}

/// Port of `search_items`. Token-AND semantics, scored per-hit, sorted
/// score-DESC then slug-DESC for newest-first tie-break.
pub fn search_items(ctx: &RenderCtx, items: &[Item], query: &str) -> Vec<SearchResult> {
    let tokens = tokenise(query);
    if tokens.is_empty() {
        return Vec::new();
    }
    let base_dir = &ctx.base_dir;

    let mut scored: Vec<(i64, SearchResult)> = Vec::new();
    for item in items {
        let item_path = Path::new(&item.readme.path);
        let item_rel = item_path.parent().unwrap_or(Path::new(""));
        let item_dir = base_dir.join(item_rel);
        if !item_dir.is_dir() {
            continue;
        }

        let status = &item.readme.priority;
        let header_text = format!(
            "{} {} {} {} {}",
            item.readme.title,
            item.readme.slug,
            item.readme.kind,
            status,
            item.readme.apps.join(" "),
        );
        let header_lower = header_text.to_lowercase();

        let readme_path_abs = item_dir.join("README.md");
        let readme_body_text = if readme_path_abs.is_file() {
            read_text(&readme_path_abs)
                .map(|raw| readme_body(&raw))
                .unwrap_or_default()
        } else {
            String::new()
        };

        let files: Vec<(PathBuf, PathBuf, bool)> = iter_item_files(&item_dir);
        let per_file: Vec<(PathBuf, &'static str, Option<String>)> = files
            .into_iter()
            .map(|(rel, abs, is_content)| {
                let text = if is_content { read_text(&abs) } else { None };
                let source: &'static str = if rel.components().next().and_then(|c| match c {
                    std::path::Component::Normal(n) => n.to_str(),
                    _ => None,
                }) == Some("notes")
                {
                    "note"
                } else {
                    "file"
                };
                (rel, source, text)
            })
            .collect();

        // Token-AND filter: every token must appear somewhere.
        let mut matched: HashSet<&str> = HashSet::new();
        for t in &tokens {
            if header_lower.contains(t) {
                matched.insert(t.as_str());
            }
        }
        if !readme_body_text.is_empty() {
            let rl = readme_body_text.to_lowercase();
            for t in &tokens {
                if rl.contains(t) {
                    matched.insert(t.as_str());
                }
            }
        }
        for (rel, _src, text) in &per_file {
            let rel_lower = rel_str(rel).to_lowercase();
            for t in &tokens {
                if rel_lower.contains(t) {
                    matched.insert(t.as_str());
                }
            }
            if let Some(txt) = text.as_ref() {
                let tl = txt.to_lowercase();
                for t in &tokens {
                    if tl.contains(t) {
                        matched.insert(t.as_str());
                    }
                }
            }
        }
        if matched.len() < tokens.len() {
            continue;
        }

        let item_rel_str = rel_str(item_rel);
        let readme_rel = format!("{item_rel_str}/README.md");

        let mut hits: Vec<Hit> = Vec::new();
        let mut hit_paths_with_content: HashSet<String> = HashSet::new();

        if tokens.iter().any(|t| header_lower.contains(t)) {
            hits.push(Hit {
                source: "title".into(),
                label: "Title".into(),
                path: readme_rel.clone(),
                snippet: build_snippet(&header_text, &tokens, SNIPPET_RADIUS),
            });
        }

        if !readme_body_text.is_empty() {
            let rl = readme_body_text.to_lowercase();
            if tokens.iter().any(|t| rl.contains(t)) {
                let snippet = build_snippet(&readme_body_text, &tokens, SNIPPET_RADIUS);
                if !snippet.is_empty() {
                    hits.push(Hit {
                        source: "readme".into(),
                        label: "README".into(),
                        path: readme_rel.clone(),
                        snippet,
                    });
                    hit_paths_with_content.insert(readme_rel.clone());
                }
            }
        }

        for (rel, source, text) in &per_file {
            let Some(txt) = text.as_ref() else { continue };
            let tl = txt.to_lowercase();
            if !tokens.iter().any(|t| tl.contains(t)) {
                continue;
            }
            let rel_s = rel_str(rel);
            let file_rel = format!("{item_rel_str}/{rel_s}");
            hits.push(Hit {
                source: (*source).to_string(),
                label: rel_s.clone(),
                path: file_rel.clone(),
                snippet: build_snippet(txt, &tokens, SNIPPET_RADIUS),
            });
            hit_paths_with_content.insert(file_rel);
        }

        // Filename-only hits — skip when same file already has content hit.
        for (rel, _src, _text) in &per_file {
            let rel_s = rel_str(rel);
            let file_rel = format!("{item_rel_str}/{rel_s}");
            if hit_paths_with_content.contains(&file_rel) {
                continue;
            }
            let rel_lower = rel_s.to_lowercase();
            if !tokens.iter().any(|t| rel_lower.contains(t)) {
                continue;
            }
            hits.push(Hit {
                source: "filename".into(),
                label: rel_s.clone(),
                path: file_rel,
                snippet: build_snippet(&rel_s, &tokens, SNIPPET_RADIUS),
            });
        }

        if hits.is_empty() {
            continue;
        }

        let mut score: i64 = 0;
        for hit in &hits {
            let hay = format!("{} {}", hit.snippet, hit.label).to_lowercase();
            let token_count: i64 = tokens
                .iter()
                .map(|t| hay.matches(t.as_str()).count() as i64)
                .sum();
            score += source_weight(&hit.source) * token_count.max(1);
        }

        let parts: Vec<&str> = item.readme.path.split('/').collect();
        let month = if parts.len() >= 2 {
            parts[1].to_string()
        } else {
            String::new()
        };

        scored.push((
            score,
            SearchResult {
                slug: item.readme.slug.clone(),
                title: item.readme.title.clone(),
                kind: item.readme.kind.clone(),
                status: status.clone(),
                subtab: status_to_subtab(status).into(),
                path: item.readme.path.clone(),
                month,
                hits,
            },
        ));
    }

    // Score DESC, then slug DESC.
    scored.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| b.1.slug.cmp(&a.1.slug)));
    scored.into_iter().map(|(_, r)| r).collect()
}

//! `parse_readme_content` — the pure parsing step.
//!
//! This module takes the README body as a string and produces an
//! [`ItemReadme`]. The filesystem reads (loading the file, walking the
//! item directory for the `files` field) live one layer up in
//! [`crate::collect`], which makes this function trivial to exercise
//! from unit tests without touching the disk.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::deliverables::{parse_deliverables, Deliverable};
use crate::regexes::{HEADING2_RE, HEADING3_RE, METADATA_RE};
use crate::sections::{parse_sections, Section};
use crate::Priority;

/// Maximum summary length in *codepoints* (count user-visible glyphs,
/// not bytes). When exceeded, the summary is truncated to
/// `SUMMARY_MAX - 3` codepoints and `...` is appended, so the final
/// string is exactly `SUMMARY_MAX`.
const SUMMARY_MAX: usize = 300;
const SUMMARY_HEAD: usize = 297;

/// Parsed item README. The `files` field is filled in by the collector
/// one layer up — it lives on this struct for ergonomic template
/// rendering but isn't populated by the pure parse step.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ItemReadme {
    pub slug: String,
    pub title: String,
    pub date: String,
    pub priority: String,
    pub invalid_status: Option<String>,
    pub apps: Vec<String>,
    pub severity: Option<String>,
    pub summary: String,
    pub sections: Vec<Section>,
    pub deliverables: Vec<Deliverable>,
    pub done: usize,
    pub total: usize,
    pub path: String,
    pub kind: String,
}

/// Parse one item's README content into an [`ItemReadme`].
///
/// `content` is the raw UTF-8 text of the file. `slug` is the item
/// folder name. `rel_path` is the README path relative to
/// `ctx.base_dir`; `item_dir` is the same minus the trailing
/// `/README.md`. `fallback_kind` is used only when the README has no
/// `**Kind**:` header.
///
/// Returns `None` when `content` is empty.
pub fn parse_readme_content(
    content: &str,
    slug: &str,
    rel_path: &str,
    item_dir: &str,
    fallback_kind: Option<&str>,
) -> Option<ItemReadme> {
    let lines: Vec<&str> = content.split('\n').collect();
    if lines.is_empty() {
        return None;
    }

    let title = lines[0].trim_start_matches('#').trim().to_string();

    let (meta, first_section_idx) = parse_header(&lines);

    let date = meta.get("date").cloned().unwrap_or_default();

    let apps_raw = meta
        .get("apps")
        .or_else(|| meta.get("composant"))
        .cloned()
        .unwrap_or_default();
    let apps = split_apps(&apps_raw);

    let severity = meta
        .get("sévérité")
        .or_else(|| meta.get("severity"))
        .cloned();

    let summary = extract_summary(&lines, first_section_idx);

    let mut sections = parse_sections(&lines);
    if !sections
        .iter()
        .any(|s| s.heading.eq_ignore_ascii_case("steps"))
    {
        sections.insert(
            0,
            Section {
                heading: "Steps".to_string(),
                items: Vec::new(),
            },
        );
    }

    let mut deliverables = parse_deliverables(&lines);
    for d in deliverables.iter_mut() {
        d.full_path = Some(format!("{}/{}", item_dir, d.path));
    }

    let done: usize = sections
        .iter()
        .flat_map(|s| s.items.iter())
        .filter(|it| it.done)
        .count();
    let total: usize = sections.iter().map(|s| s.items.len()).sum();

    let (priority, invalid_status) = resolve_status(meta.get("status").map(|s| s.as_str()));

    let kind = resolve_kind(meta.get("kind").map(|s| s.as_str()), fallback_kind);

    Some(ItemReadme {
        slug: slug.to_string(),
        title,
        date,
        priority,
        invalid_status,
        apps,
        severity,
        summary,
        sections,
        deliverables,
        done,
        total,
        path: rel_path.to_string(),
        kind,
    })
}

/// Walk the lines after the title and collect `**Key**: value` pairs until
/// the first `## heading`. Returns the header metadata (keys lowercased,
/// values trimmed) and the index of that first H2 if one exists.
fn parse_header(lines: &[&str]) -> (HashMap<String, String>, Option<usize>) {
    let mut meta: HashMap<String, String> = HashMap::new();
    let mut first_section_idx = None;

    for (i, line) in lines.iter().enumerate().skip(1) {
        if HEADING2_RE.is_match(line) {
            first_section_idx = Some(i);
            break;
        }
        if let Some(caps) = METADATA_RE.captures(line) {
            let key = caps[1].trim().to_lowercase();
            let value = caps[2].trim().to_string();
            meta.insert(key, value);
        }
    }

    (meta, first_section_idx)
}

/// Parse the `**Apps**:` (or `**Composant**:`) value into a list of app
/// names. Python:
///
/// ```python
/// [a.strip().strip("`").split("(")[0].strip()
///  for a in apps_raw.split(",") if a.strip()]
/// ```
///
/// Note that `a.strip("`")` strips *every* leading/trailing backtick, not
/// just one — e.g. `` "``vcoeur``" `` becomes `"vcoeur"`.
fn split_apps(apps_raw: &str) -> Vec<String> {
    apps_raw
        .split(',')
        .filter(|a| !a.trim().is_empty())
        .map(|a| {
            let stripped = a.trim().trim_matches('`');
            let before_paren = stripped.split('(').next().unwrap_or("");
            before_paren.trim().to_string()
        })
        .collect()
}

/// Extract the first paragraph of body text after the first `## heading`,
/// skipping fenced code blocks, tables, and blank lines before content.
/// Truncated to `SUMMARY_MAX` codepoints with a `...` tail when longer —
/// matching Python's `summary[:297] + "..."` which slices by codepoint.
fn extract_summary(lines: &[&str], first_section_idx: Option<usize>) -> String {
    let Some(idx) = first_section_idx else {
        return String::new();
    };

    let mut para: Vec<String> = Vec::new();
    let mut in_code = false;

    for line in lines.iter().skip(idx + 1) {
        if line.starts_with("```") {
            in_code = !in_code;
            continue;
        }
        if in_code {
            continue;
        }
        if HEADING2_RE.is_match(line) || HEADING3_RE.is_match(line) {
            break;
        }
        let trimmed = line.trim();
        if trimmed.is_empty() && !para.is_empty() {
            // Blank line ends the paragraph only once we've accumulated
            // at least one line of content.
            break;
        }
        if trimmed.is_empty() || line.starts_with('|') {
            // Blank-before-content or table row — skip without breaking.
            continue;
        }
        para.push(trimmed.to_string());
    }

    let joined = para.join(" ");
    if joined.chars().count() > SUMMARY_MAX {
        let head: String = joined.chars().take(SUMMARY_HEAD).collect();
        format!("{head}...")
    } else {
        joined
    }
}

/// Coerce a raw `**Status**:` value into a known priority. Returns
/// `(priority, invalid_status)` where `invalid_status` holds the original
/// raw string (case preserved) when the value wasn't in [`Priority::ALL`].
fn resolve_status(raw: Option<&str>) -> (String, Option<String>) {
    let raw = raw.map(|s| s.trim()).unwrap_or("");
    if raw.is_empty() {
        return ("backlog".to_string(), None);
    }
    let lowered = raw.to_lowercase();
    if Priority::from_lowercase(&lowered).is_some() {
        (lowered, None)
    } else {
        ("backlog".to_string(), Some(raw.to_string()))
    }
}

/// Resolve item kind from `**Kind**:` header, then the caller-provided
/// fallback, then the hardcoded `"project"` default. Python equivalent:
/// `meta.get("kind", "").lower() or kind or "project"`.
fn resolve_kind(from_meta: Option<&str>, fallback: Option<&str>) -> String {
    let from_meta = from_meta.map(|s| s.to_lowercase()).unwrap_or_default();
    if !from_meta.is_empty() {
        from_meta
    } else if let Some(k) = fallback {
        k.to_string()
    } else {
        "project".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(content: &str) -> ItemReadme {
        parse_readme_content(
            content,
            "2026-04-21-some-slug",
            "projects/2026-04/2026-04-21-some-slug/README.md",
            "projects/2026-04/2026-04-21-some-slug",
            None,
        )
        .unwrap()
    }

    #[test]
    fn title_strips_leading_hashes() {
        for (input, expected) in [
            ("# Simple title\n", "Simple title"),
            ("## H2 title\n", "H2 title"),
            ("###   Extra spaces\n", "Extra spaces"),
            ("####\n", ""),
            ("no hash\n", "no hash"),
        ] {
            let r = parse(input);
            assert_eq!(r.title, expected, "input {input:?}");
        }
    }

    #[test]
    fn full_typical_item() {
        let md = "\
# Port condash to Rust + Tauri

**Date**: 2026-04-21
**Kind**: project
**Status**: now
**Apps**: `condash`
**Branch**: `rust-tauri`

## Goal

Evaluate whether to port condash, and if so execute that port.

## Steps

- [x] Decision note
- [ ] Phase 0
- [~] Phase 1 in progress
- [-] Abandoned phase

## Deliverables

- [Report](notes/report.pdf) — top-level summary
";
        let r = parse(md);
        assert_eq!(r.title, "Port condash to Rust + Tauri");
        assert_eq!(r.date, "2026-04-21");
        assert_eq!(r.kind, "project");
        assert_eq!(r.priority, "now");
        assert_eq!(r.invalid_status, None);
        assert_eq!(r.apps, vec!["condash"]);
        assert_eq!(r.severity, None);
        assert!(r.summary.starts_with("Evaluate whether to port condash"));
        // parse_sections drops every section without checkbox items (except
        // a literal empty "Steps"). Goal has only prose; Deliverables has
        // a `- [Report](…)` link which doesn't match CHECKBOX_RE (single
        // char required inside the brackets). So Steps is the only survivor.
        assert_eq!(r.sections.len(), 1);
        assert_eq!(r.sections[0].heading, "Steps");
        assert_eq!(r.sections[0].items.len(), 4);
        assert_eq!(r.deliverables.len(), 1);
        assert_eq!(
            r.deliverables[0].full_path.as_deref(),
            Some("projects/2026-04/2026-04-21-some-slug/notes/report.pdf")
        );
        assert_eq!(r.done, 2); // [x] + [-] both count as done
        assert_eq!(r.total, 4);
    }

    #[test]
    fn missing_status_defaults_to_backlog() {
        let r = parse("# T\n\n## Goal\n\nbody\n");
        assert_eq!(r.priority, "backlog");
        assert_eq!(r.invalid_status, None);
    }

    #[test]
    fn unknown_status_records_invalid_preserving_case() {
        let r = parse("# T\n\n**Status**: InProgress\n\n## Goal\n\nbody\n");
        assert_eq!(r.priority, "backlog");
        assert_eq!(r.invalid_status, Some("InProgress".to_string()));
    }

    #[test]
    fn valid_status_is_lowercased() {
        let r = parse("# T\n\n**Status**: NOW\n\n## Goal\n\nbody\n");
        assert_eq!(r.priority, "now");
        assert_eq!(r.invalid_status, None);
    }

    #[test]
    fn steps_section_is_auto_injected_if_absent() {
        let r = parse("# T\n\n## Goal\n\nbody\n");
        assert!(r.sections.iter().any(|s| s.heading == "Steps"));
        // Goal is empty → filtered out by parse_sections. Only injected Steps remains.
        assert_eq!(r.sections.len(), 1);
        assert!(r.sections[0].items.is_empty());
    }

    #[test]
    fn apps_parsing_strips_backticks_and_parentheses() {
        let r = parse(
            "# T\n\n**Apps**: `condash`, vcoeur-com (frontend), ```alicepeintures```\n\n## G\n\nbody\n",
        );
        assert_eq!(r.apps, vec!["condash", "vcoeur-com", "alicepeintures"]);
    }

    #[test]
    fn composant_is_treated_as_apps_fallback() {
        let r = parse("# T\n\n**Composant**: `condash`\n\n## G\n\nbody\n");
        assert_eq!(r.apps, vec!["condash"]);
    }

    #[test]
    fn apps_header_wins_over_composant() {
        let r = parse("# T\n\n**Apps**: `a`\n**Composant**: `b`\n\n## G\n\nbody\n");
        assert_eq!(r.apps, vec!["a"]);
    }

    #[test]
    fn severity_accented_and_plain_both_read() {
        let r = parse("# T\n\n**Sévérité**: high\n\n## G\n\nbody\n");
        assert_eq!(r.severity.as_deref(), Some("high"));

        let r = parse("# T\n\n**Severity**: low\n\n## G\n\nbody\n");
        assert_eq!(r.severity.as_deref(), Some("low"));
    }

    #[test]
    fn kind_from_meta_wins_over_fallback() {
        let got = parse_readme_content(
            "# T\n\n**Kind**: incident\n\n## G\n\nbody\n",
            "slug",
            "rel/README.md",
            "rel",
            Some("project"),
        )
        .unwrap();
        assert_eq!(got.kind, "incident");
    }

    #[test]
    fn kind_fallback_used_when_header_missing() {
        let got = parse_readme_content(
            "# T\n\n## G\n\nbody\n",
            "slug",
            "rel/README.md",
            "rel",
            Some("document"),
        )
        .unwrap();
        assert_eq!(got.kind, "document");
    }

    #[test]
    fn kind_defaults_to_project_without_fallback() {
        let r = parse("# T\n\n## G\n\nbody\n");
        assert_eq!(r.kind, "project");
    }

    #[test]
    fn summary_skips_code_blocks_and_table_rows() {
        let md = "\
# T

## Goal

```python
ignore me
still ignored
```
| a | b |
| - | - |
| c | d |
Real summary line.

Second paragraph should not appear.
";
        let r = parse(md);
        assert_eq!(r.summary, "Real summary line.");
    }

    #[test]
    fn summary_truncated_at_300_codepoints_with_ellipsis() {
        // 400 'é' characters (2 bytes each in UTF-8) — forces codepoint
        // (not byte) counting to match Python.
        let long: String = "é".repeat(400);
        let md = format!("# T\n\n## Goal\n\n{long}\n");
        let r = parse(&md);
        assert_eq!(r.summary.chars().count(), SUMMARY_MAX);
        assert!(r.summary.ends_with("..."));
        // First 297 codepoints are 'é', then '...'.
        let head: String = r.summary.chars().take(SUMMARY_HEAD).collect();
        assert_eq!(head, "é".repeat(SUMMARY_HEAD));
    }

    #[test]
    fn summary_empty_when_no_h2_heading() {
        let r = parse("# T\n\n**Date**: 2026-04-22\n\nOrphan body with no h2 anywhere.\n");
        assert_eq!(r.summary, "");
    }

    #[test]
    fn deliverables_full_path_prefixed_with_item_dir() {
        let got = parse_readme_content(
            "# T\n\n## Deliverables\n\n- [R](notes/r.pdf)\n",
            "slug",
            "a/b/README.md",
            "a/b",
            None,
        )
        .unwrap();
        assert_eq!(
            got.deliverables[0].full_path.as_deref(),
            Some("a/b/notes/r.pdf")
        );
    }

    #[test]
    fn done_and_total_span_all_sections() {
        let md = "\
# T

## Steps

- [x] 1
- [ ] 2

## Follow-ups

- [x] 3
- [~] 4
- [-] 5
";
        let r = parse(md);
        // done = [x]s + [-]s = 3 (items 1, 3, 5); total = 5
        assert_eq!(r.done, 3);
        assert_eq!(r.total, 5);
    }
}

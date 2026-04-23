//! `## Deliverables` PDF link extraction.
//!
//! Port of `_parse_deliverables`. `full_path` is *not* filled in here —
//! Python's `parse_readme` prepends the item directory after the fact. The
//! caller that owns the item's on-disk path handles that in the phase-2
//! wrapper.

use serde::{Deserialize, Serialize};

use crate::regexes::{DELIVERABLE_RE, HEADING2_RE};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Deliverable {
    pub label: String,
    /// PDF path relative to the item directory.
    pub path: String,
    pub desc: String,
    /// `<item_dir>/<path>` — filled in by `parse_readme_content` once
    /// it knows the item directory. Skipped when absent so standalone
    /// `parse_deliverables` callers see the same three-field shape.
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub full_path: Option<String>,
}

/// Scan `lines` for the first `## Deliverables` heading and collect every
/// `- [Label](path.pdf) — desc` line until the next `## …` heading (or EOF).
pub fn parse_deliverables(lines: &[&str]) -> Vec<Deliverable> {
    let mut out = Vec::new();
    let mut in_section = false;

    for line in lines {
        if HEADING2_RE.is_match(line) {
            if in_section {
                // Hit the next H2 — stop scanning.
                break;
            }
            let heading = line.trim().trim_start_matches('#').trim();
            if heading.eq_ignore_ascii_case("deliverables") {
                in_section = true;
            }
            continue;
        }

        if in_section {
            if let Some(caps) = DELIVERABLE_RE.captures(line.trim()) {
                out.push(Deliverable {
                    label: caps[1].trim().to_string(),
                    path: caps[2].trim().to_string(),
                    desc: caps
                        .get(3)
                        .map(|m| m.as_str().trim().to_string())
                        .unwrap_or_default(),
                    full_path: None,
                });
            }
        }
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(s: &str) -> Vec<&str> {
        s.split('\n').collect()
    }

    #[test]
    fn picks_up_pdfs_in_section() {
        let md = "\
## Deliverables

- [Report](notes/report.pdf) — Q1 summary
- [Annex](notes/annex.pdf)

## Notes
";
        let d = parse_deliverables(&lines(md));
        assert_eq!(d.len(), 2);
        assert_eq!(d[0].label, "Report");
        assert_eq!(d[0].path, "notes/report.pdf");
        assert_eq!(d[0].desc, "Q1 summary");
        assert_eq!(d[1].label, "Annex");
        assert_eq!(d[1].path, "notes/annex.pdf");
        assert_eq!(d[1].desc, "");
    }

    #[test]
    fn ignores_non_pdf_links() {
        let md = "\
## Deliverables

- [Slides](notes/slides.pptx) — nope
- [Report](notes/report.pdf)
";
        let d = parse_deliverables(&lines(md));
        assert_eq!(d.len(), 1);
        assert_eq!(d[0].label, "Report");
    }

    #[test]
    fn no_deliverables_section_returns_empty() {
        let md = "\
# Title

## Steps

- [ ] one
";
        assert!(parse_deliverables(&lines(md)).is_empty());
    }

    #[test]
    fn stops_at_next_h2() {
        let md = "\
## Deliverables

- [A](a.pdf)

## Notes

- [B](b.pdf)
";
        let d = parse_deliverables(&lines(md));
        assert_eq!(d.len(), 1);
        assert_eq!(d[0].label, "A");
    }

    #[test]
    fn heading_match_is_case_insensitive() {
        let md = "\
## DELIVERABLES

- [A](a.pdf)
";
        let d = parse_deliverables(&lines(md));
        assert_eq!(d.len(), 1);
    }
}

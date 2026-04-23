//! Regex primitives shared across parse steps.
//!
//! All patterns are single-line and anchored with `^`/`$` — the call
//! sites feed them line-by-line, so the default `regex` crate
//! behaviour (where `^` is start-of-string) is what we want.

use std::sync::LazyLock;

use regex::Regex;

/// `**Key**: value` metadata line at the top of an item README.
pub static METADATA_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\*\*(.+?)\*\*\s*:\s*(.+)$").expect("METADATA_RE compiles"));

/// `- [x] text`, `- [ ] text`, `- [~] text`, `- [-] text` checklist entry.
/// Capture groups: indent, status char, body.
pub static CHECKBOX_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(\s*)-\s*\[([ xX~\-])\]\s+(.+)$").expect("CHECKBOX_RE compiles")
});

/// `## Heading`.
pub static HEADING2_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^##\s+(.+)$").expect("HEADING2_RE compiles"));

/// `### Heading`.
pub static HEADING3_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^###\s+(.+)$").expect("HEADING3_RE compiles"));

/// `**Status**: …` metadata line. Case-insensitive to match Python's
/// `re.IGNORECASE` — used by callers that just need to test presence.
pub static STATUS_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^\*\*Status\*\*\s*:\s*.*$").expect("STATUS_RE compiles"));

/// `- [Label](path.pdf) — optional description` in the Deliverables section.
pub static DELIVERABLE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"-\s+\[([^\]]+)\]\(([^)]+\.pdf)\)(?:\s*[—–-]\s*(.+))?$")
        .expect("DELIVERABLE_RE compiles")
});

/// `YYYY-MM-DD-slug` folder slug grammar: lowercase ASCII + digits, single
/// hyphens only.
pub static VALID_SLUG_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z0-9]+(?:-[a-z0-9]+)*$").expect("VALID_SLUG_RE compiles"));

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_matches() {
        let caps = METADATA_RE.captures("**Date**: 2026-04-22").unwrap();
        assert_eq!(&caps[1], "Date");
        assert_eq!(&caps[2], "2026-04-22");
    }

    #[test]
    fn metadata_non_greedy_key() {
        // When more than one `**…**:` appears on the same line, the
        // non-greedy `.+?` pairs with the *first* closing `**:` it can
        // reach — so the key is the first bolded segment, not everything
        // up to the last bolded segment. Python's `re` does the same.
        let caps = METADATA_RE
            .captures("**First**: value **Second**: other")
            .unwrap();
        assert_eq!(&caps[1], "First");
        assert_eq!(&caps[2], "value **Second**: other");
    }

    #[test]
    fn checkbox_statuses() {
        let cases = [
            ("- [ ] open", " "),
            ("- [x] done", "x"),
            ("- [X] done", "X"),
            ("- [~] progress", "~"),
            ("- [-] abandoned", "-"),
        ];
        for (line, expected_char) in cases {
            let caps = CHECKBOX_RE.captures(line).unwrap();
            assert_eq!(&caps[2], expected_char, "status char in {line:?}");
        }
    }

    #[test]
    fn checkbox_rejects_wrong_shapes() {
        assert!(CHECKBOX_RE.captures("- [y] wrong char").is_none());
        assert!(CHECKBOX_RE.captures("* [x] wrong bullet").is_none());
        assert!(CHECKBOX_RE.captures("- [x]no space").is_none());
    }

    #[test]
    fn headings() {
        assert!(HEADING2_RE.is_match("## Scope"));
        assert!(!HEADING2_RE.is_match("### Sub"));
        assert!(HEADING3_RE.is_match("### Sub"));
        assert!(!HEADING3_RE.is_match("## Scope"));
    }

    #[test]
    fn status_line_case_insensitive() {
        assert!(STATUS_RE.is_match("**Status**: now"));
        assert!(STATUS_RE.is_match("**status**: now"));
        assert!(STATUS_RE.is_match("**STATUS**: now"));
    }

    #[test]
    fn deliverable_with_description() {
        let caps = DELIVERABLE_RE
            .captures("- [Report](notes/report.pdf) — Q1 summary")
            .unwrap();
        assert_eq!(&caps[1], "Report");
        assert_eq!(&caps[2], "notes/report.pdf");
        assert_eq!(caps.get(3).unwrap().as_str(), "Q1 summary");
    }

    #[test]
    fn deliverable_without_description() {
        let caps = DELIVERABLE_RE
            .captures("- [Report](notes/report.pdf)")
            .unwrap();
        assert_eq!(&caps[1], "Report");
        assert_eq!(&caps[2], "notes/report.pdf");
        assert!(caps.get(3).is_none());
    }

    #[test]
    fn deliverable_only_matches_pdf() {
        assert!(DELIVERABLE_RE.captures("- [Doc](notes/x.docx)").is_none());
    }

    #[test]
    fn valid_slug_shapes() {
        let good = [
            "2026-04-21-condash-rust-tauri-port",
            "a",
            "a-b",
            "foo123",
            "foo-bar-baz",
        ];
        for s in good {
            assert!(VALID_SLUG_RE.is_match(s), "expected match for {s:?}");
        }
        let bad = [
            "Foo",      // uppercase
            "-foo",     // leading hyphen
            "foo-",     // trailing hyphen
            "foo--bar", // double hyphen
            "",         // empty
            "foo_bar",  // underscore
            "foo bar",  // space
        ];
        for s in bad {
            assert!(!VALID_SLUG_RE.is_match(s), "expected no match for {s:?}");
        }
    }
}

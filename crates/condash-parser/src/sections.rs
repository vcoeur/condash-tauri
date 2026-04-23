//! `## Steps`-style sections with checkbox items.
//!
//! Port of `_parse_sections` from `parser.py`. Pure over a slice of lines
//! — no filesystem, no `RenderCtx` dependency.

use serde::{Deserialize, Serialize};

use crate::regexes::{CHECKBOX_RE, HEADING2_RE};

/// Resolved checkbox state.
///
/// The Python parser maps the raw character inside `[…]` to one of four
/// logical states; `done` and `abandoned` both count as "completed" for
/// the done/total tally the dashboard shows, which is why `SectionItem`
/// carries a boolean `done` *and* the richer `status`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CheckboxStatus {
    Open,
    Done,
    Progress,
    Abandoned,
}

impl CheckboxStatus {
    fn from_char(c: &str) -> CheckboxStatus {
        match c {
            "x" | "X" => CheckboxStatus::Done,
            "~" => CheckboxStatus::Progress,
            "-" => CheckboxStatus::Abandoned,
            _ => CheckboxStatus::Open,
        }
    }

    /// Both `done` and `abandoned` count as "this step is finished"
    /// for the progress-bar math — the difference is only visual.
    pub fn is_done(self) -> bool {
        matches!(self, CheckboxStatus::Done | CheckboxStatus::Abandoned)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SectionItem {
    pub text: String,
    pub done: bool,
    pub status: CheckboxStatus,
    /// Zero-based line index in the source README. Matches Python.
    pub line: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Section {
    pub heading: String,
    pub items: Vec<SectionItem>,
}

/// Walk `lines`, return every `## Heading` section that either contains at
/// least one checkbox item *or* is literally named "Steps" (case-insensitive).
///
/// The "keep empty Steps" quirk exists because `parse_readme` relies on a
/// Steps section always being present (it prepends a synthetic empty one
/// if the README doesn't have a real one). Keeping the empty real Steps
/// section here means the call site doesn't have to dedupe.
pub fn parse_sections(lines: &[&str]) -> Vec<Section> {
    let mut sections: Vec<Section> = Vec::new();
    let mut cur: Option<Section> = None;

    for (i, line) in lines.iter().enumerate() {
        if let Some(caps) = HEADING2_RE.captures(line) {
            if let Some(s) = cur.take() {
                sections.push(s);
            }
            cur = Some(Section {
                heading: caps[1].trim().to_string(),
                items: Vec::new(),
            });
            continue;
        }

        if let Some(sec) = cur.as_mut() {
            if let Some(caps) = CHECKBOX_RE.captures(line) {
                let status = CheckboxStatus::from_char(&caps[2]);
                sec.items.push(SectionItem {
                    text: caps[3].trim().to_string(),
                    done: status.is_done(),
                    status,
                    line: i,
                });
            }
        }
    }

    if let Some(s) = cur.take() {
        sections.push(s);
    }

    sections.retain(|s| !s.items.is_empty() || s.heading.eq_ignore_ascii_case("steps"));
    sections
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(s: &str) -> Vec<&str> {
        s.split('\n').collect()
    }

    #[test]
    fn steps_with_mixed_statuses() {
        let md = "\
## Steps

- [ ] open
- [x] done
- [X] also done
- [~] progress
- [-] abandoned
";
        let secs = parse_sections(&lines(md));
        assert_eq!(secs.len(), 1);
        let s = &secs[0];
        assert_eq!(s.heading, "Steps");
        assert_eq!(s.items.len(), 5);

        let expected = [
            ("open", CheckboxStatus::Open, false),
            ("done", CheckboxStatus::Done, true),
            ("also done", CheckboxStatus::Done, true),
            ("progress", CheckboxStatus::Progress, false),
            ("abandoned", CheckboxStatus::Abandoned, true),
        ];
        for (item, (text, status, done)) in s.items.iter().zip(expected) {
            assert_eq!(item.text, text);
            assert_eq!(item.status, status);
            assert_eq!(item.done, done);
        }
    }

    #[test]
    fn empty_steps_section_is_preserved() {
        // Section with no items, named "Steps" → kept (call site relies on
        // a Steps section always being present).
        let md = "## Steps\n\nSome prose but no checkboxes.\n";
        let secs = parse_sections(&lines(md));
        assert_eq!(secs.len(), 1);
        assert_eq!(secs[0].heading, "Steps");
        assert!(secs[0].items.is_empty());
    }

    #[test]
    fn empty_non_steps_section_is_dropped() {
        let md = "## Notes\n\nJust prose, no items.\n";
        let secs = parse_sections(&lines(md));
        assert!(secs.is_empty());
    }

    #[test]
    fn multiple_sections_kept_in_order() {
        let md = "\
## Steps

- [ ] a
- [x] b

## Follow-ups

- [ ] c
";
        let secs = parse_sections(&lines(md));
        assert_eq!(secs.len(), 2);
        assert_eq!(secs[0].heading, "Steps");
        assert_eq!(secs[1].heading, "Follow-ups");
        assert_eq!(secs[0].items.len(), 2);
        assert_eq!(secs[1].items.len(), 1);
    }

    #[test]
    fn line_index_is_zero_based_and_from_whole_readme() {
        let md = "\
# Title

**Date**: 2026-04-22

## Steps

- [ ] first
- [x] second
";
        let secs = parse_sections(&lines(md));
        assert_eq!(secs[0].items[0].line, 6);
        assert_eq!(secs[0].items[1].line, 7);
    }

    #[test]
    fn steps_case_insensitive() {
        let md = "## STEPS\n";
        let secs = parse_sections(&lines(md));
        assert_eq!(secs.len(), 1);
        assert_eq!(secs[0].heading, "STEPS");
    }
}

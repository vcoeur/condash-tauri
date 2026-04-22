//! Step-level mutations on an item README: toggle / add / remove / edit /
//! set-priority / reorder-all. 1:1 with the `_toggle_checkbox`,
//! `_remove_step`, `_edit_step`, `_add_step`, `_set_priority`, and
//! `_reorder_all` helpers in `mutations.py`.
//!
//! Every function reads the file as UTF-8, splits on `\n`, mutates the line
//! slice in place, and re-joins with `\n` before writing. Python's
//! `str.split("\n")` + `"\n".join(...)` round-trips a trailing newline
//! because the split produces an empty final element; the Rust port uses
//! the same primitives (`str::split('\n')` + `Vec::join("\n")`) and so
//! preserves the trailing newline byte-for-byte.

use std::fs;
use std::io;
use std::path::Path;

use condash_parser::sections::CheckboxStatus;
use once_cell::sync::Lazy;
use regex::Regex;

use condash_parser::regexes::{CHECKBOX_RE, HEADING2_RE, HEADING3_RE, METADATA_RE, STATUS_RE};

/// Priority values accepted by [`set_priority`]. Order mirrors Python's
/// `PRIORITIES` tuple in `parser.py`.
pub const PRIORITIES: &[&str] = &["now", "soon", "later", "backlog", "review", "done"];

/// `## Steps` — matches exactly what Python's
/// `re.match(r"^##\s+Steps", line, re.IGNORECASE)` matches: line starts
/// with `##`, at least one whitespace, then `Steps` (case-insensitive).
/// No `\b` anchor on purpose — Python's `re.match` doesn't either, so
/// a heading like `## Steps (draft)` still counts as the Steps section.
static STEPS_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^##\s+Steps").expect("STEPS_HEADING_RE compiles"));

/// Sections that must appear *after* a freshly-created `## Steps` block.
/// When the README has no Steps section, `_add_step` inserts one in front
/// of the first Notes/Timeline/Chronologie heading it finds.
static NOTES_OR_TIMELINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^##\s+(?:Notes|Timeline|Chronologie)\b")
        .expect("NOTES_OR_TIMELINE_RE compiles")
});

/// Any `## …` / `### …` / deeper heading — used by `add_step`'s
/// explicit-section path to find where the target section ends.
static ANY_HEADING_LEVEL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^(#{2,})\s+(.+)$").expect("ANY_HEADING_LEVEL_RE compiles"));

/// Same as [`ANY_HEADING_LEVEL_RE`] but groups only the `#` prefix —
/// cheap enough to keep as a second regex; saves a capture allocation
/// in `_add_step`'s per-line scan inside an existing Steps section.
static ANY_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^(#{2,})\s+").expect("ANY_HEADING_RE compiles"));

/// The literal string checkbox patterns Python's `_toggle_checkbox` tests
/// against. Kept as separate `&str`s (rather than a regex) because the
/// Python reference implementation also uses plain `in` / `str.replace`,
/// and we want byte-identical behaviour.
const OPEN_MARK: &str = "- [ ]";
const DONE_MARK_X: &str = "- [x]";
const DONE_MARK_BIG_X: &str = "- [X]";
const PROGRESS_MARK: &str = "- [~]";
const ABANDONED_MARK: &str = "- [-]";

/// Rewrite the `**Status**: …` metadata line, or insert a new one below
/// the existing metadata block. Returns `Ok(false)` if `priority` is not
/// in [`PRIORITIES`]; Python's `_set_priority` returns `False` in the
/// same case.
///
/// The `**Status** : value` (space before colon) vs `**Status**: value`
/// choice mirrors the surrounding metadata style — Python looks at the
/// first metadata line's spacing when inserting a new status line, so
/// the port does the same.
pub fn set_priority(path: &Path, priority: &str) -> io::Result<bool> {
    if !PRIORITIES.iter().any(|p| *p == priority) {
        return Ok(false);
    }

    let text = fs::read_to_string(path)?;
    let mut lines: Vec<String> = text.split('\n').map(|s| s.to_string()).collect();

    for line in lines.iter_mut() {
        if STATUS_RE.is_match(line) {
            *line = if line.contains(" : ") {
                format!("**Status** : {priority}")
            } else {
                format!("**Status**: {priority}")
            };
            fs::write(path, lines.join("\n"))?;
            return Ok(true);
        }
    }

    // No existing Status line: walk metadata block until the first `## …`
    // heading, remembering the last metadata line so we can insert right
    // under it.
    let mut insert_at: usize = 1;
    for (i, line) in lines.iter().enumerate().skip(1) {
        if HEADING2_RE.is_match(line) {
            break;
        }
        if METADATA_RE.is_match(line) {
            insert_at = i + 1;
        }
    }

    let new_line = if insert_at > 1 && lines[insert_at - 1].contains(" : ") {
        format!("**Status** : {priority}")
    } else {
        format!("**Status**: {priority}")
    };
    lines.insert(insert_at, new_line);
    fs::write(path, lines.join("\n"))?;
    Ok(true)
}

/// Flip one checkbox line through the open → done → progress → abandoned
/// → open cycle. Returns `Ok(None)` if `line_num` is out of bounds or the
/// line isn't a recognised checkbox — same contract as Python's
/// `_toggle_checkbox`, which returns `None` in both cases.
pub fn toggle_checkbox(path: &Path, line_num: usize) -> io::Result<Option<CheckboxStatus>> {
    let text = fs::read_to_string(path)?;
    let mut lines: Vec<String> = text.split('\n').map(|s| s.to_string()).collect();

    if line_num >= lines.len() {
        return Ok(None);
    }

    let line = &lines[line_num];
    let (new_line, new_status) = if line.contains(OPEN_MARK) {
        (
            line.replacen(OPEN_MARK, DONE_MARK_X, 1),
            CheckboxStatus::Done,
        )
    } else if line.contains(DONE_MARK_X) {
        (
            line.replacen(DONE_MARK_X, PROGRESS_MARK, 1),
            CheckboxStatus::Progress,
        )
    } else if line.contains(DONE_MARK_BIG_X) {
        (
            line.replacen(DONE_MARK_BIG_X, PROGRESS_MARK, 1),
            CheckboxStatus::Progress,
        )
    } else if line.contains(PROGRESS_MARK) {
        (
            line.replacen(PROGRESS_MARK, ABANDONED_MARK, 1),
            CheckboxStatus::Abandoned,
        )
    } else if line.contains(ABANDONED_MARK) {
        (
            line.replacen(ABANDONED_MARK, OPEN_MARK, 1),
            CheckboxStatus::Open,
        )
    } else {
        return Ok(None);
    };

    lines[line_num] = new_line;
    fs::write(path, lines.join("\n"))?;
    Ok(Some(new_status))
}

/// Delete the checkbox line at `line_num`. Returns `Ok(false)` if the
/// line isn't a checkbox or the index is out of bounds.
pub fn remove_step(path: &Path, line_num: usize) -> io::Result<bool> {
    let text = fs::read_to_string(path)?;
    let mut lines: Vec<String> = text.split('\n').map(|s| s.to_string()).collect();

    if line_num >= lines.len() {
        return Ok(false);
    }
    if !CHECKBOX_RE.is_match(&lines[line_num]) {
        return Ok(false);
    }
    lines.remove(line_num);
    fs::write(path, lines.join("\n"))?;
    Ok(true)
}

/// Rewrite the body of the checkbox at `line_num`. Preserves indent and
/// status character. Returns `Ok(false)` if the index is out of bounds or
/// the line isn't a checkbox.
///
/// `new_text` has every newline/carriage-return stripped before write —
/// the UI's single-line input control can still contain them if someone
/// pastes a multi-line snippet, and the stored form must stay single-line
/// to preserve the line-indexed mutation protocol.
pub fn edit_step(path: &Path, line_num: usize, new_text: &str) -> io::Result<bool> {
    let cleaned = new_text.replace('\n', " ").replace('\r', "");
    let text = fs::read_to_string(path)?;
    let mut lines: Vec<String> = text.split('\n').map(|s| s.to_string()).collect();

    if line_num >= lines.len() {
        return Ok(false);
    }
    let caps = match CHECKBOX_RE.captures(&lines[line_num]) {
        Some(c) => c,
        None => return Ok(false),
    };
    let indent = caps.get(1).map(|m| m.as_str()).unwrap_or("");
    let status_char = caps.get(2).map(|m| m.as_str()).unwrap_or(" ");
    lines[line_num] = format!("{indent}- [{status_char}] {cleaned}");
    fs::write(path, lines.join("\n"))?;
    Ok(true)
}

/// Insert a new `- [ ] <text>` checkbox. Behaviour:
///
/// 1. If `section_heading` is `Some(h)` and a `## h` / `### h` / deeper
///    heading exists, insert inside that section (right before its next
///    sibling/parent heading, with trailing blank lines trimmed), and
///    return the zero-based insertion line.
/// 2. Otherwise fall through to the `## Steps` section — matched
///    case-insensitively, line-prefix only (see [`STEPS_HEADING_RE`]).
/// 3. If no Steps section exists, create one above the first
///    Notes/Timeline/Chronologie heading, or at EOF if neither exists.
///
/// Always returns the zero-based line index of the inserted checkbox.
pub fn add_step(path: &Path, text: &str, section_heading: Option<&str>) -> io::Result<usize> {
    let cleaned = text.replace('\n', " ").replace('\r', "");
    let raw = fs::read_to_string(path)?;
    let mut lines: Vec<String> = raw.split('\n').map(|s| s.to_string()).collect();

    // 1) Explicit section heading (non-empty).
    if let Some(heading) = section_heading.filter(|s| !s.is_empty()) {
        let mut target_line: Option<usize> = None;
        let mut target_level: usize = 0;
        for (i, line) in lines.iter().enumerate() {
            if let Some(caps) = ANY_HEADING_LEVEL_RE.captures(line) {
                if caps.get(2).map(|m| m.as_str().trim()) == Some(heading) {
                    target_line = Some(i);
                    target_level = caps.get(1).map(|m| m.as_str().len()).unwrap_or(0);
                    break;
                }
            }
        }

        if let Some(start) = target_line {
            // End = next heading whose level is <= target_level.
            let mut end = lines.len();
            for i in (start + 1)..lines.len() {
                if let Some(caps) = ANY_HEADING_RE.captures(&lines[i]) {
                    if caps.get(1).map(|m| m.as_str().len()).unwrap_or(0) <= target_level {
                        end = i;
                        break;
                    }
                }
            }
            let mut insert_at = end;
            while insert_at > start + 1 && lines[insert_at - 1].trim().is_empty() {
                insert_at -= 1;
            }
            lines.insert(insert_at, format!("- [ ] {cleaned}"));
            fs::write(path, lines.join("\n"))?;
            return Ok(insert_at);
        }
        // No matching heading — fall through to the Steps path below.
    }

    // 2) Find the `## Steps` heading.
    let mut ns_line: Option<usize> = None;
    for (i, line) in lines.iter().enumerate() {
        if STEPS_HEADING_RE.is_match(line) {
            ns_line = Some(i);
            break;
        }
    }

    // 3a) No Steps section: create one above Notes/Timeline/Chronologie.
    if ns_line.is_none() {
        let mut insert_before = lines.len();
        for (i, line) in lines.iter().enumerate() {
            if NOTES_OR_TIMELINE_RE.is_match(line) {
                insert_before = i;
                break;
            }
        }
        let block = [
            String::new(),
            String::from("## Steps"),
            String::new(),
            format!("- [ ] {cleaned}"),
            String::new(),
        ];
        lines.splice(insert_before..insert_before, block);
        fs::write(path, lines.join("\n"))?;
        return Ok(insert_before + 3);
    }

    // 3b) Existing Steps section.
    let start = ns_line.unwrap();
    let mut end = lines.len();
    for i in (start + 1)..lines.len() {
        if HEADING2_RE.is_match(&lines[i]) {
            end = i;
            break;
        }
    }
    let mut insert_end = end;
    for i in (start + 1)..end {
        if HEADING3_RE.is_match(&lines[i]) {
            insert_end = i;
            break;
        }
    }
    let mut insert_at = insert_end;
    while insert_at > start + 1 && lines[insert_at - 1].trim().is_empty() {
        insert_at -= 1;
    }
    lines.insert(insert_at, format!("- [ ] {cleaned}"));
    fs::write(path, lines.join("\n"))?;
    Ok(insert_at)
}

/// Reorder checkbox lines in place. `order` gives the source line indices
/// in the desired visual order; the mutation keeps every non-checkbox
/// line exactly where it was and shuffles only the checkbox rows among
/// themselves.
///
/// Every element of `order` must be an in-bounds checkbox line or the
/// whole reorder aborts without writing — same contract as Python's
/// `_reorder_all`.
pub fn reorder_all(path: &Path, order: &[usize]) -> io::Result<bool> {
    let text = fs::read_to_string(path)?;
    let mut lines: Vec<String> = text.split('\n').map(|s| s.to_string()).collect();

    for &ln in order {
        if ln >= lines.len() || !CHECKBOX_RE.is_match(&lines[ln]) {
            return Ok(false);
        }
    }

    let contents: Vec<String> = order.iter().map(|&ln| lines[ln].clone()).collect();
    let mut sorted_positions: Vec<usize> = order.to_vec();
    sorted_positions.sort_unstable();
    for (pos, content) in sorted_positions.into_iter().zip(contents) {
        lines[pos] = content;
    }
    fs::write(path, lines.join("\n"))?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn tmp(content: &str) -> (TempDir, std::path::PathBuf) {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("README.md");
        fs::write(&path, content).unwrap();
        (dir, path)
    }

    // ------------------------------------------------------------------
    // set_priority
    // ------------------------------------------------------------------

    #[test]
    fn set_priority_rewrites_existing_status() {
        let (_dir, p) = tmp("# T\n\n**Date**: 2026-04-22\n**Status**: now\n");
        assert!(set_priority(&p, "soon").unwrap());
        let got = fs::read_to_string(&p).unwrap();
        assert!(got.contains("**Status**: soon"));
        assert!(!got.contains("**Status**: now"));
    }

    #[test]
    fn set_priority_preserves_space_colon_style() {
        let (_dir, p) = tmp("# T\n\n**Date** : 2026-04-22\n**Status** : now\n");
        assert!(set_priority(&p, "done").unwrap());
        let got = fs::read_to_string(&p).unwrap();
        assert!(got.contains("**Status** : done"));
    }

    #[test]
    fn set_priority_inserts_when_missing() {
        // Status line absent, metadata uses `**Date**: …` style.
        let (_dir, p) = tmp("# T\n\n**Date**: 2026-04-22\n**Apps**: `x`\n\n## Goal\n\nbody.\n");
        assert!(set_priority(&p, "now").unwrap());
        let got = fs::read_to_string(&p).unwrap();
        // New Status line appears right after the last metadata line.
        assert!(got.contains("**Apps**: `x`\n**Status**: now\n"), "{got:?}");
    }

    #[test]
    fn set_priority_inserts_with_space_style() {
        let (_dir, p) = tmp("# T\n\n**Date** : 2026-04-22\n\n## Goal\n");
        assert!(set_priority(&p, "soon").unwrap());
        let got = fs::read_to_string(&p).unwrap();
        assert!(got.contains("**Status** : soon"), "{got:?}");
    }

    #[test]
    fn set_priority_rejects_unknown() {
        let (_dir, p) = tmp("# T\n\n**Status**: now\n");
        assert!(!set_priority(&p, "urgent").unwrap());
        let got = fs::read_to_string(&p).unwrap();
        assert_eq!(got, "# T\n\n**Status**: now\n");
    }

    // ------------------------------------------------------------------
    // toggle_checkbox
    // ------------------------------------------------------------------

    #[test]
    fn toggle_cycles_through_states() {
        let (_dir, p) = tmp("- [ ] first\n- [ ] second\n");
        assert_eq!(toggle_checkbox(&p, 0).unwrap(), Some(CheckboxStatus::Done));
        assert_eq!(
            toggle_checkbox(&p, 0).unwrap(),
            Some(CheckboxStatus::Progress)
        );
        assert_eq!(
            toggle_checkbox(&p, 0).unwrap(),
            Some(CheckboxStatus::Abandoned)
        );
        assert_eq!(toggle_checkbox(&p, 0).unwrap(), Some(CheckboxStatus::Open));
    }

    #[test]
    fn toggle_accepts_capital_x() {
        let (_dir, p) = tmp("- [X] capital\n");
        assert_eq!(
            toggle_checkbox(&p, 0).unwrap(),
            Some(CheckboxStatus::Progress)
        );
        assert_eq!(fs::read_to_string(&p).unwrap(), "- [~] capital\n");
    }

    #[test]
    fn toggle_none_for_non_checkbox() {
        let (_dir, p) = tmp("not a checkbox\n- [ ] real\n");
        assert_eq!(toggle_checkbox(&p, 0).unwrap(), None);
        assert_eq!(toggle_checkbox(&p, 99).unwrap(), None);
    }

    #[test]
    fn toggle_preserves_trailing_newline() {
        let (_dir, p) = tmp("- [ ] only\n");
        toggle_checkbox(&p, 0).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        assert_eq!(got, "- [x] only\n");
    }

    // ------------------------------------------------------------------
    // remove_step
    // ------------------------------------------------------------------

    #[test]
    fn remove_step_drops_checkbox_line() {
        let (_dir, p) = tmp("- [ ] keep\n- [ ] drop\n- [ ] keep2\n");
        assert!(remove_step(&p, 1).unwrap());
        assert_eq!(fs::read_to_string(&p).unwrap(), "- [ ] keep\n- [ ] keep2\n");
    }

    #[test]
    fn remove_step_rejects_non_checkbox() {
        let (_dir, p) = tmp("heading\n- [ ] step\n");
        assert!(!remove_step(&p, 0).unwrap());
        // File unchanged.
        assert_eq!(fs::read_to_string(&p).unwrap(), "heading\n- [ ] step\n");
    }

    #[test]
    fn remove_step_out_of_bounds() {
        let (_dir, p) = tmp("- [ ] only\n");
        assert!(!remove_step(&p, 5).unwrap());
    }

    // ------------------------------------------------------------------
    // edit_step
    // ------------------------------------------------------------------

    #[test]
    fn edit_step_rewrites_body_keeps_status() {
        let (_dir, p) = tmp("- [x] old text\n");
        assert!(edit_step(&p, 0, "new text").unwrap());
        assert_eq!(fs::read_to_string(&p).unwrap(), "- [x] new text\n");
    }

    #[test]
    fn edit_step_strips_newlines() {
        let (_dir, p) = tmp("- [ ] old\n");
        assert!(edit_step(&p, 0, "line1\nline2\rdone").unwrap());
        // \n → space, \r → gone.
        assert_eq!(fs::read_to_string(&p).unwrap(), "- [ ] line1 line2done\n");
    }

    #[test]
    fn edit_step_preserves_indent() {
        let (_dir, p) = tmp("    - [~] nested\n");
        assert!(edit_step(&p, 0, "new").unwrap());
        assert_eq!(fs::read_to_string(&p).unwrap(), "    - [~] new\n");
    }

    #[test]
    fn edit_step_rejects_non_checkbox() {
        let (_dir, p) = tmp("plain\n");
        assert!(!edit_step(&p, 0, "x").unwrap());
    }

    // ------------------------------------------------------------------
    // add_step
    // ------------------------------------------------------------------

    #[test]
    fn add_step_creates_steps_section_when_missing() {
        let (_dir, p) = tmp("# Title\n\n## Goal\n\nbody.\n\n## Notes\n\nn.\n");
        let line = add_step(&p, "first", None).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        // Steps block inserted above `## Notes`.
        assert!(got.contains("## Steps\n\n- [ ] first\n\n## Notes"), "{got}");
        // Returned line points at the inserted checkbox.
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] first");
    }

    #[test]
    fn add_step_creates_steps_section_without_notes() {
        let (_dir, p) = tmp("# Title\n\n## Goal\n\nbody.\n");
        let line = add_step(&p, "first", None).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        assert!(got.contains("## Steps\n\n- [ ] first\n"));
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] first");
    }

    #[test]
    fn add_step_appends_to_existing_steps_section() {
        let (_dir, p) = tmp("# T\n\n## Steps\n\n- [ ] one\n- [x] two\n\n## Notes\n\nn.\n");
        let line = add_step(&p, "three", None).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        assert!(got.contains("- [ ] one\n- [x] two\n- [ ] three\n"));
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] three");
    }

    #[test]
    fn add_step_inserts_before_first_h3_inside_steps() {
        let (_dir, p) =
            tmp("# T\n\n## Steps\n\n- [ ] one\n\n### Subsection\n\n- [ ] nested\n\n## Notes\n");
        let line = add_step(&p, "sibling", None).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] sibling");
        // The sibling goes between `- [ ] one` and the `### Subsection`,
        // not after the nested item.
        let pos_one = lines.iter().position(|l| *l == "- [ ] one").unwrap();
        let pos_sib = lines.iter().position(|l| *l == "- [ ] sibling").unwrap();
        let pos_sub = lines.iter().position(|l| *l == "### Subsection").unwrap();
        assert!(pos_one < pos_sib && pos_sib < pos_sub);
    }

    #[test]
    fn add_step_targets_explicit_section_heading() {
        let (_dir, p) = tmp("# T\n\n## Scope\n\nstuff.\n\n## Steps\n\n- [ ] s1\n\n## Notes\n");
        let line = add_step(&p, "scoped", Some("Scope")).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] scoped");
        // Inserted inside Scope, not Steps.
        let pos_scope = lines.iter().position(|l| *l == "## Scope").unwrap();
        let pos_steps = lines.iter().position(|l| *l == "## Steps").unwrap();
        assert!(pos_scope < line && line < pos_steps);
    }

    #[test]
    fn add_step_falls_through_to_steps_when_heading_missing() {
        // Explicit heading that doesn't exist — Python falls through to
        // the Steps path rather than erroring.
        let (_dir, p) = tmp("# T\n\n## Steps\n\n- [ ] s1\n\n## Notes\n");
        let line = add_step(&p, "new", Some("Nonexistent")).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] new");
        let pos_steps = lines.iter().position(|l| *l == "## Steps").unwrap();
        let pos_notes = lines.iter().position(|l| *l == "## Notes").unwrap();
        assert!(pos_steps < line && line < pos_notes);
    }

    #[test]
    fn add_step_strips_newlines_in_text() {
        let (_dir, p) = tmp("# T\n\n## Steps\n\n- [ ] old\n");
        let line = add_step(&p, "a\nb\rc", None).unwrap();
        let got = fs::read_to_string(&p).unwrap();
        let lines: Vec<&str> = got.split('\n').collect();
        assert_eq!(lines[line], "- [ ] a bc");
    }

    // ------------------------------------------------------------------
    // reorder_all
    // ------------------------------------------------------------------

    #[test]
    fn reorder_all_shuffles_checkboxes_only() {
        let (_dir, p) = tmp("## Steps\n\n- [ ] a\n- [x] b\n- [~] c\n");
        // Lines: 0="## Steps", 1="", 2="- [ ] a", 3="- [x] b", 4="- [~] c"
        // Move the three checkboxes into order [c, a, b].
        assert!(reorder_all(&p, &[4, 2, 3]).unwrap());
        let got = fs::read_to_string(&p).unwrap();
        assert_eq!(got, "## Steps\n\n- [~] c\n- [ ] a\n- [x] b\n");
    }

    #[test]
    fn reorder_all_rejects_non_checkbox_index() {
        let (_dir, p) = tmp("heading\n- [ ] a\n- [ ] b\n");
        let original = fs::read_to_string(&p).unwrap();
        // Index 0 is "heading" — not a checkbox.
        assert!(!reorder_all(&p, &[0, 1, 2]).unwrap());
        assert_eq!(fs::read_to_string(&p).unwrap(), original);
    }

    #[test]
    fn reorder_all_rejects_out_of_bounds() {
        let (_dir, p) = tmp("- [ ] a\n- [ ] b\n");
        let original = fs::read_to_string(&p).unwrap();
        assert!(!reorder_all(&p, &[0, 99]).unwrap());
        assert_eq!(fs::read_to_string(&p).unwrap(), original);
    }
}

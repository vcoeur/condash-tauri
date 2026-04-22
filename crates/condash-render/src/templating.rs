//! `minijinja` environment + custom filters — Rust port of
//! `condash/templating.py`.
//!
//! The Jinja2 templates from `crates/condash-render/templates/` are embedded via
//! `include_str!` so they ship inside the binary. Two custom filters
//! match the Python env:
//!
//! - `embed`: JSON-encode then swap `'`→`\'` and `"`→`'` so the result
//!   is safe to drop into an HTML attribute. Returns a safe string
//!   (won't be re-escaped by autoescape).
//! - `subtree_count`: recursive file count for a file-tree group.

use std::sync::OnceLock;

use minijinja::value::Value;
use minijinja::{AutoEscape, Environment, Error, ErrorKind, Output, State};

pub const CARD_TEMPLATE: &str = include_str!("../templates/card.html.j2");
pub const HISTORY_TEMPLATE: &str = include_str!("../templates/history.html.j2");
pub const KNOWLEDGE_CARD_TEMPLATE: &str = include_str!("../templates/knowledge_card.html.j2");
pub const KNOWLEDGE_GROUP_TEMPLATE: &str = include_str!("../templates/knowledge_group.html.j2");
pub const KNOWLEDGE_TREE_TEMPLATE: &str = include_str!("../templates/knowledge_tree.html.j2");
pub const MACROS_TEMPLATE: &str = include_str!("../templates/_macros.html.j2");

fn embed_filter(value: Value) -> Result<Value, Error> {
    let json = serde_json::to_string(&value).map_err(|e| {
        Error::new(
            ErrorKind::InvalidOperation,
            format!("embed: json encode failed: {e}"),
        )
    })?;
    Ok(Value::from_safe_string(embed_json_string(&json)))
}

/// Embed a JSON-serializable value as an HTML-attribute-safe literal.
///
/// Matches Python's `json.dumps(obj).replace("'", "\\'").replace('"', "'")`:
/// the outer quotes become `'`, JSON's `\"` escaping vanishes, and any
/// single quote inside the value is backslash-escaped. Safe to drop
/// inside a double-quoted attribute like `onclick="foo({{…}})"`.
pub fn embed_attr<T: serde::Serialize>(value: &T) -> String {
    let json = serde_json::to_string(value).expect("serialise for embed");
    embed_json_string(&json)
}

fn embed_json_string(json: &str) -> String {
    let ascii = ensure_ascii(json);
    // `json.dumps(x).replace("'", "\\'").replace('"', "'")` — the
    // replacements are applied in order: escape single quotes first,
    // then swap the outer double quotes for singles.
    ascii.replace('\'', "\\'").replace('"', "'")
}

/// Replace every non-ASCII codepoint with `\uXXXX` (or a UTF-16
/// surrogate pair for > U+FFFF). Mirrors Python's
/// `json.dumps(..., ensure_ascii=True)`.
fn ensure_ascii(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        let cp = c as u32;
        if cp < 0x80 {
            out.push(c);
        } else if cp < 0x10000 {
            out.push_str(&format!("\\u{cp:04x}"));
        } else {
            let v = cp - 0x10000;
            let hi = 0xD800 + (v >> 10);
            let lo = 0xDC00 + (v & 0x3FF);
            out.push_str(&format!("\\u{hi:04x}\\u{lo:04x}"));
        }
    }
    out
}

fn markupsafe_escape_to_string(s: &str) -> String {
    let mut buf = String::with_capacity(s.len() + 8);
    for c in s.chars() {
        match c {
            '&' => buf.push_str("&amp;"),
            '<' => buf.push_str("&lt;"),
            '>' => buf.push_str("&gt;"),
            '"' => buf.push_str("&#34;"),
            '\'' => buf.push_str("&#39;"),
            other => buf.push(other),
        }
    }
    buf
}

fn write_out(out: &mut Output, s: &str) -> Result<(), Error> {
    // `minijinja::Output` implements `std::fmt::Write`; use that impl
    // directly and re-wrap its error type into `minijinja::Error`.
    std::fmt::Write::write_str(out, s)
        .map_err(|e| Error::new(ErrorKind::InvalidOperation, format!("write: {e}")))
}

fn markupsafe_formatter(out: &mut Output, state: &State, value: &Value) -> Result<(), Error> {
    if value.is_undefined() || value.is_none() {
        return Ok(());
    }
    let s = value.to_string();
    // `value.is_safe()` is true when the value was wrapped via
    // `Value::from_safe_string` (or produced by a filter that returned
    // a safe string, like our custom `embed`). Safe values are passed
    // through unescaped regardless of autoescape state.
    if matches!(state.auto_escape(), AutoEscape::Html) && !value.is_safe() {
        let escaped = markupsafe_escape_to_string(&s);
        write_out(out, &escaped)
    } else {
        write_out(out, &s)
    }
}

fn dirname_filter(path: String) -> String {
    // Parent-path filter: everything before the last `/`. Mirrors the
    // Python filter of the same name in templating.py. Both engines
    // consume the same macro so both register this.
    match path.rfind('/') {
        Some(i) => path[..i].to_string(),
        None => String::new(),
    }
}

fn subtree_count_filter(group: Value) -> Result<i64, Error> {
    // Python: len(group.get("files") or []) + sum(subtree_count(g) for g in group.get("groups") or [])
    let files_len = match group.get_attr("files") {
        Ok(files) if !files.is_undefined() && !files.is_none() => match files.len() {
            Some(n) => n as i64,
            None => 0,
        },
        _ => 0,
    };
    let mut total = files_len;
    if let Ok(groups) = group.get_attr("groups") {
        if !groups.is_undefined() && !groups.is_none() {
            if let Ok(iter) = groups.try_iter() {
                for sub in iter {
                    total += subtree_count_filter(sub)?;
                }
            }
        }
    }
    Ok(total)
}

static ENV: OnceLock<Environment<'static>> = OnceLock::new();

/// Return the process-wide minijinja environment, built on first access.
///
/// Mirrors Python's `@lru_cache(maxsize=1) env()` pattern.
pub fn env() -> &'static Environment<'static> {
    ENV.get_or_init(build_env)
}

fn build_env() -> Environment<'static> {
    let mut env = Environment::new();
    // Autoescape for .html/.j2 — matches Python's select_autoescape.
    env.set_auto_escape_callback(|name| {
        if name.ends_with(".html") || name.ends_with(".j2") || name.ends_with(".htm") {
            AutoEscape::Html
        } else {
            AutoEscape::None
        }
    });

    // Whitespace control — Python's env sets both trim_blocks and
    // lstrip_blocks. minijinja 2.19+ exposes the same knobs. Without
    // them the two engines diverge on every template that leads with
    // `{% import %}` (or any tag on its own line), producing stray
    // `\n` or `  ` prefixes Python's build doesn't emit.
    env.set_trim_blocks(true);
    env.set_lstrip_blocks(true);

    // Custom formatter: markupsafe-compatible HTML escape. minijinja's
    // default escape encodes `/` as `&#x2f;`, which Python Jinja2 (via
    // markupsafe) doesn't do — so the two engines diverge on every
    // attribute that carries a path. This formatter matches Python's
    // exact output: escape only `& < > " '`, render `"` as `&#34;` and
    // `'` as `&#39;` (markupsafe's canonical forms).
    env.set_formatter(markupsafe_formatter);

    // trim_blocks / lstrip_blocks — match Python's env configuration.
    // minijinja's `keep_trailing_newline` is the inverse of Jinja's
    // default; Python Jinja trims the newline after a block. minijinja
    // default also trims, so no flip needed here.

    env.add_template("_macros.html.j2", MACROS_TEMPLATE)
        .unwrap();
    env.add_template("card.html.j2", CARD_TEMPLATE).unwrap();
    env.add_template("history.html.j2", HISTORY_TEMPLATE)
        .unwrap();
    env.add_template("knowledge_card.html.j2", KNOWLEDGE_CARD_TEMPLATE)
        .unwrap();
    env.add_template("knowledge_group.html.j2", KNOWLEDGE_GROUP_TEMPLATE)
        .unwrap();
    env.add_template("knowledge_tree.html.j2", KNOWLEDGE_TREE_TEMPLATE)
        .unwrap();

    env.add_filter("embed", embed_filter);
    env.add_filter("subtree_count", subtree_count_filter);
    env.add_filter("dirname", dirname_filter);

    env
}

/// Render one template by name with the given context; shortcut for
/// `env().get_template(name).render(ctx)`. Panics if the template
/// renders with an error — render errors are bugs we want loud.
pub fn render(template_name: &str, ctx: Value) -> String {
    match env().get_template(template_name) {
        Ok(tpl) => match tpl.render(ctx) {
            Ok(s) => s,
            Err(e) => panic!("render {template_name}: {e}\n{e:#?}"),
        },
        Err(e) => panic!("load {template_name}: {e}"),
    }
}

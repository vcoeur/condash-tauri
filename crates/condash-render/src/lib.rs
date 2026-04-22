//! HTML rendering for the conception dashboard.
//!
//! Rust port of `src/condash/render.py`. Pairs with `condash-parser`
//! (item + knowledge data types) and `condash-state` (`RenderCtx`,
//! cache). The Jinja2 templates under `crates/condash-render/templates/` are
//! embedded verbatim via `include_str!` in [`templating`] and driven
//! through `minijinja` — no runtime filesystem dependency, no template
//! deviation from the Python build.
//!
//! Phase 2 slice 3 covers the cards, knowledge tree, history, and
//! dashboard shell. Git-strip rendering is stubbed to an empty string
//! here; slice 4 wires the real implementation alongside `git_scan`.
//! Note rendering (`_render_note`, `_render_markdown`) is deferred —
//! those paths depend on pandoc + wikilink resolution and land with
//! the note routes in a later slice.

pub mod git_render;
pub mod icons;
pub mod note_render;
pub mod templating;

pub use note_render::{raw_payload as note_raw_payload, render_note};

use condash_parser::{knowledge_title_and_desc, Item, KnowledgeCard, KnowledgeNode};
use condash_state::{collect_git_repos, RenderCtx};
use minijinja::context;
use minijinja::value::Value;

/// HTML-escape a string — mirror of Python's `html.escape(str(text))`.
/// minijinja's autoescape covers most cases, but direct string
/// interpolation (e.g. into substitution placeholders) still needs it.
pub fn h(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
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

/// Priority ordering — matches Python's `PRI_ORDER` dict lookup where
/// missing priorities sort as 9 ("after everything").
fn pri_order(priority: &str) -> i32 {
    match priority {
        "now" => 0,
        "soon" => 1,
        "later" => 2,
        "backlog" => 3,
        "review" => 4,
        "done" => 5,
        _ => 9,
    }
}

/// Priorities in user-visible order, shared with Python.
pub const PRIORITIES: &[&str] = &["now", "soon", "later", "backlog", "review", "done"];

/// First pending step across all sections, or `None`. Mirrors
/// `_next_step` — "pending" = `open` or `progress`; `abandoned` isn't
/// "next".
fn next_step(item: &Item) -> Option<Value> {
    use condash_parser::sections::CheckboxStatus;
    for sec in &item.readme.sections {
        for step in &sec.items {
            if matches!(step.status, CheckboxStatus::Open | CheckboxStatus::Progress) {
                return Some(Value::from_serialize(step));
            }
        }
    }
    None
}

/// Recursive file count for a group (Python's `_subtree_count`). Used
/// by the card template via the `subtree_count` filter — but also by
/// `_render_card` directly to compute the top-level total.
fn subtree_count(group: &condash_parser::GroupEntry) -> usize {
    group.files.len() + group.groups.iter().map(subtree_count).sum::<usize>()
}

fn total_files(tree: &condash_parser::ItemTree) -> usize {
    tree.files.len() + tree.groups.iter().map(subtree_count).sum::<usize>()
}

/// Render one project card. Port of `_render_card`.
pub fn render_card(item: &Item) -> String {
    let total = total_files(&item.files);
    let ctx = context! {
        item => Value::from_serialize(item),
        priorities => Value::from_serialize(PRIORITIES),
        next_step => next_step(item).unwrap_or(Value::from(())),
        files_tree => Value::from_serialize(&item.files),
        files_total => total,
        icons => icons::icons_value(),
    };
    templating::render("card.html.j2", ctx)
}

/// Public fragment entry point — HTML for one project card. Used by
/// `/fragment` in the route layer.
pub fn render_card_fragment(item: &Item) -> String {
    render_card(item)
}

/// HTML for one knowledge card (file).
pub fn render_knowledge_card_fragment(entry: &KnowledgeCard) -> String {
    let ctx = context! { entry => Value::from_serialize(entry) };
    templating::render("knowledge_card.html.j2", ctx)
}

/// HTML for one knowledge directory (recursive — includes children).
pub fn render_knowledge_group_fragment(node: &KnowledgeNode) -> String {
    let ctx = context! { node => Value::from_serialize(node) };
    templating::render("knowledge_group.html.j2", ctx)
}

/// Render the full knowledge tree under the `{{KNOWLEDGE}}` placeholder.
pub fn render_knowledge(root: Option<&KnowledgeNode>) -> String {
    let ctx = context! {
        root => match root {
            Some(r) => Value::from_serialize(r),
            None => Value::from(()),
        }
    };
    templating::render("knowledge_tree.html.j2", ctx)
}

/// Shape a knowledge-index file (`index.md`) into the dict the badge
/// renderer wants. Returns `None` if the file doesn't exist.
fn index_entry(ctx: &RenderCtx, idx_path: &std::path::Path) -> Option<serde_json::Value> {
    if !idx_path.is_file() {
        return None;
    }
    let (title, desc) = knowledge_title_and_desc(idx_path);
    let rel = idx_path
        .strip_prefix(&ctx.base_dir)
        .map(|p| p.to_string_lossy().replace('\\', "/"))
        .unwrap_or_else(|_| idx_path.to_string_lossy().into_owned());
    Some(serde_json::json!({ "path": rel, "title": title, "desc": desc }))
}

/// Render the history panel. Port of `_render_history`.
pub fn render_history(ctx: &RenderCtx, items: &[Item]) -> String {
    let root_dir = ctx.base_dir.join("projects");
    if !root_dir.is_dir() {
        let tctx = context! { no_projects_dir => true };
        return templating::render("history.html.j2", tctx);
    }

    let mut by_month: std::collections::BTreeMap<String, Vec<&Item>> =
        std::collections::BTreeMap::new();
    for item in items {
        let parts: Vec<&str> = item.readme.path.split('/').collect();
        if parts.len() >= 2 && parts[0] == "projects" {
            by_month.entry(parts[1].to_string()).or_default().push(item);
        }
    }

    // Months rendered newest-first.
    let mut month_names: Vec<String> = by_month.keys().cloned().collect();
    month_names.sort_by(|a, b| b.cmp(a));

    let mut months: Vec<serde_json::Value> = Vec::with_capacity(month_names.len());
    for name in month_names {
        let mut month_items = by_month.remove(&name).unwrap();
        // slug[:10] desc — Python uses `key=lambda x: x["slug"]` with
        // reverse=True (no slug trimming); use whole slug.
        month_items.sort_by(|a, b| b.readme.slug.cmp(&a.readme.slug));
        let items_json: Vec<serde_json::Value> = month_items
            .iter()
            .map(|it| serde_json::to_value(it).unwrap())
            .collect();
        let index = index_entry(ctx, &root_dir.join(&name).join("index.md"));
        months.push(serde_json::json!({
            "name": name,
            "items": items_json,
            "index": index,
        }));
    }

    let root_index = index_entry(ctx, &root_dir.join("index.md"));
    let tctx = context! {
        no_projects_dir => false,
        root_index => match root_index {
            Some(v) => Value::from_serialize(v),
            None => Value::from(()),
        },
        months => Value::from_serialize(months),
    };
    templating::render("history.html.j2", tctx)
}

/// Public entry point for `/`. Port of `render_page`.
///
/// `items` is typically `cache.get_items(ctx)`; `knowledge` is
/// `cache.get_knowledge(ctx)`. `version` is rendered verbatim into the
/// `{{VERSION}}` placeholder — the Tauri host passes its own version
/// string (or propagates the Python wheel version in dual-build mode).
pub fn render_page(
    ctx: &RenderCtx,
    items: &[Item],
    knowledge: Option<&KnowledgeNode>,
    version: &str,
    live_runners: &git_render::LiveRunners,
) -> String {
    // Sort: by (pri_order, slug[:10]), then within each priority reverse
    // by slug[:10]. Matches Python's two-pass sort exactly.
    let mut sorted: Vec<&Item> = items.iter().collect();
    sorted.sort_by(|a, b| {
        let pa = pri_order(&a.readme.priority);
        let pb = pri_order(&b.readme.priority);
        pa.cmp(&pb).then_with(|| {
            a.readme.slug[..a.readme.slug.len().min(10)]
                .cmp(&b.readme.slug[..b.readme.slug.len().min(10)])
        })
    });

    let mut ordered: Vec<&Item> = Vec::with_capacity(sorted.len());
    let mut i = 0usize;
    while i < sorted.len() {
        let pri = &sorted[i].readme.priority;
        let mut j = i;
        while j < sorted.len() && &sorted[j].readme.priority == pri {
            j += 1;
        }
        let mut group: Vec<&Item> = sorted[i..j].to_vec();
        group.sort_by(|a, b| {
            b.readme.slug[..b.readme.slug.len().min(10)]
                .cmp(&a.readme.slug[..a.readme.slug.len().min(10)])
        });
        ordered.extend(group);
        i = j;
    }
    let all_items = ordered;

    // Emit "Now / Soon / Later / Review" group headings before the
    // first card of each priority (only the first four — backlog /
    // done never get a visible heading).
    let mut parts: Vec<String> = Vec::new();
    let mut seen: std::collections::HashSet<&str> = std::collections::HashSet::new();
    for item in &all_items {
        let pri = item.readme.priority.as_str();
        if let Some(label) = labelled_priority(pri) {
            if seen.insert(pri) {
                parts.push(format!(
                    "<div class=\"group-heading hidden\" data-group=\"{pri}\" \
                     data-node-id=\"projects/{pri}\">{label}</div>"
                ));
            }
        }
        parts.push(render_card(item));
    }
    let cards = parts.join("\n");

    let now = chrono::Local::now().format("%Y-%m-%d %H:%M").to_string();

    let (mut cur, mut next, mut bl, mut dn) = (0usize, 0usize, 0usize, 0usize);
    for it in &all_items {
        match it.readme.priority.as_str() {
            "now" | "review" => cur += 1,
            "soon" | "later" => next += 1,
            "backlog" => bl += 1,
            "done" => dn += 1,
            _ => {}
        }
    }

    let git_groups = collect_git_repos(ctx);
    let git_html = git_render::render_git_repos(ctx, &git_groups, live_runners);
    let count_repos: usize = git_groups.iter().map(|g| g.families.len()).sum();

    let knowledge_html = render_knowledge(knowledge);
    let count_knowledge = knowledge.map(|k| k.count).unwrap_or(0);

    let count_projects = all_items.len();
    let history_html = render_history(
        ctx,
        &all_items.iter().map(|&i| i.clone()).collect::<Vec<_>>(),
    );

    // Placeholder substitution — use `replace` (all occurrences) to
    // mirror Python's `str.replace` semantics.
    let mut out = ctx.template.clone();
    out = out.replace("{{CARDS}}", &cards);
    out = out.replace("{{GIT_REPOS}}", &git_html);
    out = out.replace("{{KNOWLEDGE}}", &knowledge_html);
    out = out.replace("{{HISTORY}}", &history_html);
    out = out.replace("{{TIMESTAMP}}", &now);
    out = out.replace("{{COUNT_CURRENT}}", &cur.to_string());
    out = out.replace("{{COUNT_NEXT}}", &next.to_string());
    out = out.replace("{{COUNT_BACKLOG}}", &bl.to_string());
    out = out.replace("{{COUNT_DONE}}", &dn.to_string());
    out = out.replace("{{COUNT_HISTORY}}", &count_projects.to_string());
    out = out.replace("{{COUNT_PROJECTS}}", &count_projects.to_string());
    out = out.replace("{{COUNT_REPOS}}", &count_repos.to_string());
    out = out.replace("{{COUNT_KNOWLEDGE}}", &count_knowledge.to_string());
    out = out.replace("{{VERSION}}", version);
    out
}

fn labelled_priority(pri: &str) -> Option<&'static str> {
    match pri {
        "now" => Some("Now"),
        "soon" => Some("Soon"),
        "later" => Some("Later"),
        "review" => Some("Review"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use condash_parser::{
        sections::{CheckboxStatus, Section, SectionItem},
        Deliverable, ItemReadme, ItemTree,
    };

    fn simple_item(slug: &str, priority: &str) -> Item {
        Item {
            readme: ItemReadme {
                slug: slug.into(),
                title: format!("Title {slug}"),
                date: "2026-04-22".into(),
                priority: priority.into(),
                invalid_status: None,
                apps: vec!["condash".into()],
                severity: None,
                summary: "Summary text.".into(),
                sections: vec![Section {
                    heading: "Steps".into(),
                    items: vec![SectionItem {
                        text: "one".into(),
                        done: false,
                        status: CheckboxStatus::Open,
                        line: 3,
                    }],
                }],
                deliverables: vec![Deliverable {
                    label: "Report".into(),
                    path: "notes/r.pdf".into(),
                    desc: String::new(),
                    full_path: Some(format!("projects/2026-04/{slug}/notes/r.pdf")),
                }],
                done: 0,
                total: 1,
                path: format!("projects/2026-04/{slug}/README.md"),
                kind: "project".into(),
            },
            files: ItemTree::default(),
        }
    }

    #[test]
    fn h_escapes_the_five_html_specials() {
        assert_eq!(h("a<b>&\"'c"), "a&lt;b&gt;&amp;&quot;&#x27;c");
    }

    #[test]
    fn render_card_produces_card_div() {
        let item = simple_item("2026-04-22-foo", "now");
        let html = render_card(&item);
        eprintln!("=== HTML BEGIN ===\n{html}\n=== HTML END ===");
        assert!(html.contains("class=\"card collapsed\""));
        assert!(html.contains("Title 2026-04-22-foo"));
        assert!(html.contains("data-node-id=\"projects/now/2026-04-22-foo\""));
    }

    #[test]
    fn render_card_fragment_matches_render_card() {
        let item = simple_item("slug", "soon");
        assert_eq!(render_card_fragment(&item), render_card(&item));
    }

    #[test]
    fn render_knowledge_empty_tree() {
        let html = render_knowledge(None);
        assert!(html.contains("No <code>knowledge/</code>"));
    }

    #[test]
    fn render_knowledge_group_fragment_round_trips() {
        let node = KnowledgeNode {
            name: "topics".into(),
            label: "Topics".into(),
            rel_dir: "knowledge/topics".into(),
            index: None,
            body: vec![],
            children: vec![],
            count: 0,
        };
        let html = render_knowledge_group_fragment(&node);
        assert!(html.contains("data-node-id=\"knowledge/topics\""));
    }

    #[test]
    fn render_page_without_items_still_fills_template() {
        let ctx = RenderCtx {
            base_dir: std::path::PathBuf::from("/nonexistent"),
            template: "<html>{{CARDS}} | count={{COUNT_PROJECTS}} | v={{VERSION}}</html>".into(),
            ..Default::default()
        };
        let live: git_render::LiveRunners = Default::default();
        let out = render_page(&ctx, &[], None, "0.99.0", &live);
        assert!(out.contains("count=0"));
        assert!(out.contains("v=0.99.0"));
    }
}

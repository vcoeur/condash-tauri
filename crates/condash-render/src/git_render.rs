//! Git-strip rendering — peer cards, branch rows, runner buttons,
//! open-with launcher buttons.
//!
//! The public entry points take a [`LiveRunners`] map keyed by runner
//! key. Each entry records the checkout that owns the session and the
//! exit code (or `None` if still live). Three visible bits of UI lean
//! on this: the peer-card "live" tag, the `.runner-term-mount` div the
//! frontend attaches xterm + WebSocket to (only emitted on the row
//! that owns the session), and the tri-state Start / Stop / Switch
//! button on every row of the same runner. The Rust server builds the
//! map from `state.runner_registry`; tests pass an empty map.

use std::collections::HashMap;

use condash_state::{Checkout, Family, Group, Member, RenderCtx};

use crate::h;
use crate::icons::Icons;

/// Canonical runner-registry key. Sub-repos use `<repo>--<sub>` to
/// keep each submodule's runner session distinct from the parent's.
pub fn runner_key(repo_name: &str, sub_name: Option<&str>) -> String {
    match sub_name {
        None => repo_name.to_string(),
        Some(s) => format!("{repo_name}--{s}"),
    }
}

/// Snapshot of a runner session as far as the renderer is concerned.
/// The server builds one of these per live-or-exited entry in the
/// runner registry before rendering so the render crate stays pure.
#[derive(Debug, Clone, Default)]
pub struct RunnerLive {
    /// `checkout_key` that started the session (`"main"` or a worktree
    /// key). The mount + "live" row modifier only appear on this
    /// checkout's row.
    pub checkout_key: String,
    /// `Some(code)` iff the session has exited; `None` while the PTY
    /// is still running.
    pub exit_code: Option<i32>,
}

/// Map of runner-key → session snapshot. Empty is the common case;
/// populated as sessions start and drop as they are cleared.
pub type LiveRunners = HashMap<String, RunnerLive>;

fn runner_key_for_member(family: &Family, member: &Member) -> String {
    if member.is_subrepo {
        runner_key(&family.name, Some(&member.name))
    } else {
        runner_key(&family.name, None)
    }
}

/// The "Open with …" split button — primary icon + caret → popover
/// picker. Phase 2 rendering is static; the interactive JS lives in
/// the bundled dashboard frontend.
pub fn render_open_with(ctx: &RenderCtx, path: &str) -> String {
    let path_h = h(path);
    let primary_slot = "main_ide";
    let primary_title = ctx
        .open_with
        .get(primary_slot)
        .map(|s| s.label.clone())
        .unwrap_or_else(|| primary_slot.to_string());

    let mut picker_items = String::new();
    for slot_key in ["main_ide", "secondary_ide", "terminal"] {
        let label = ctx
            .open_with
            .get(slot_key)
            .map(|s| s.label.clone())
            .unwrap_or_else(|| slot_key.to_string());
        let icon = icon_for(slot_key);
        picker_items.push_str(&format!(
            "<button type=\"button\" class=\"open-popover-item\" \
             data-action=\"open-path\" data-stop=\"1\" \
             data-path=\"{path_h}\" data-tool=\"{slot_key}\">\
             <span class=\"open-popover-icon\">{icon}</span>\
             <span>{label_h}</span></button>",
            label_h = h(&label),
        ));
    }
    let integrated_title = "Open in integrated terminal";
    picker_items.push_str(&format!(
        "<button type=\"button\" class=\"open-popover-item\" \
         data-action=\"open-in-terminal\" data-stop=\"1\" data-prevent=\"1\" \
         data-path=\"{path_h}\">\
         <span class=\"open-popover-icon\">{icon}</span>\
         <span>{title_h}</span></button>",
        icon = Icons::integrated_terminal,
        title_h = h(integrated_title),
    ));
    let popover = format!("<div class=\"open-popover\" role=\"menu\" hidden>{picker_items}</div>");
    format!(
        "<div class=\"open-grp\">\
         <button type=\"button\" class=\"open-primary\" title=\"{title_h}\" \
         aria-label=\"{title_h}\" \
         data-action=\"open-path\" data-stop=\"1\" \
         data-path=\"{path_h}\" data-tool=\"{primary_slot}\">\
         {primary_icon}</button>\
         <button type=\"button\" class=\"open-caret\" title=\"Open with…\" \
         aria-haspopup=\"menu\" aria-label=\"Open with menu\" \
         data-action=\"git-toggle-open-popover\" data-stop=\"1\" data-prevent=\"1\">\
         {caret}</button>\
         {popover}</div>",
        title_h = h(&primary_title),
        primary_icon = icon_for(primary_slot),
        caret = Icons::open_caret,
    )
}

fn icon_for(slot_key: &str) -> &'static str {
    match slot_key {
        "main_ide" => Icons::main_ide,
        "secondary_ide" => Icons::secondary_ide,
        "terminal" => Icons::terminal,
        _ => "",
    }
}

/// Per-checkout Run / Stop / Switch pill. The icon + onclick depend on
/// whether a live session owns this runner key, and if so which
/// checkout it is anchored to:
///
/// - no session (or session exited)     → green Start
/// - session on this checkout           → red Stop
/// - session on a different checkout    → amber Switch (confirm dialog)
fn render_runner_button(
    key: &str,
    checkout_key: &str,
    checkout_path: &str,
    live: Option<&RunnerLive>,
) -> String {
    let key_h = h(key);
    let checkout_h = h(checkout_key);
    let path_h = h(checkout_path);
    // Stop/switch/start — dispatched in JS via `data-action="runner-<op>"`.
    // The `switch` variant reuses the /api/runner/start endpoint, which
    // returns 409 and drives a confirm-swap flow client-side.
    let (title, cls, icon, op) = match live {
        None => (
            "Start dev runner",
            "git-action-runner-run",
            Icons::runner_run,
            "start",
        ),
        Some(RunnerLive { exit_code, .. }) if exit_code.is_some() => (
            "Start dev runner",
            "git-action-runner-run",
            Icons::runner_run,
            "start",
        ),
        Some(RunnerLive {
            checkout_key: owner,
            ..
        }) if owner == checkout_key => (
            "Stop dev runner",
            "git-action-runner-stop",
            Icons::runner_stop,
            "stop",
        ),
        Some(_) => (
            "Switch runner to this checkout",
            "git-action-runner-switch",
            Icons::runner_run,
            "switch",
        ),
    };
    format!(
        "<button class=\"git-action-btn git-action-runner {cls}\" \
         title=\"{t}\" aria-label=\"{t}\" \
         data-action=\"runner-{op}\" data-stop=\"1\" \
         data-key=\"{key_h}\" data-checkout=\"{checkout_h}\" data-path=\"{path_h}\">\
         {icon}</button>",
        t = h(title),
    )
}

/// Inline runner mount — returns the empty string unless the runner
/// identified by `key` has a live-or-exited session anchored at
/// `checkout_key`. Fresh mounts start collapsed; the user reveals the
/// output by clicking the header. `data-exit-code` is set on exited
/// sessions so the header styling flips to the muted variant.
fn render_runner_mount(key: &str, checkout_key: &str, live: Option<&RunnerLive>) -> String {
    let Some(session) = live else {
        return String::new();
    };
    if session.checkout_key != checkout_key {
        return String::new();
    }
    let exited_attr = match session.exit_code {
        Some(code) => format!(" data-exit-code=\"{code}\""),
        None => String::new(),
    };
    let label = format!("{key} @ {checkout_key}");
    // `hx-preserve="true"` tells idiomorph (and any future htmx swap)
    // to leave this subtree untouched. The runner-viewer attaches xterm
    // + a `/ws/runner/<key>` WebSocket to `.runner-term-host` inside;
    // a parent `#git-panel` morph swap on `sse:code` would otherwise
    // tear the WebSocket-attached DOM down.
    format!(
        "<div class=\"runner-term-mount runner-collapsed\" \
         hx-preserve=\"true\" \
         data-runner-key=\"{k}\" data-runner-checkout=\"{c}\"{ex}>\
         <div class=\"runner-term-header\" \
         title=\"Click to collapse / expand (keeps process running)\" \
         data-action=\"runner-toggle-collapse\">\
         <span class=\"runner-term-label\">{label_h}</span>\
         <span class=\"runner-term-status\" aria-live=\"polite\"></span>\
         <button class=\"runner-control runner-collapse\" \
         aria-label=\"Collapse terminal\" tabindex=\"-1\" \
         data-action=\"runner-toggle-collapse\" data-stop=\"1\">\
         {collapse_icon}</button>\
         <button class=\"runner-control runner-popout\" \
         title=\"Pop out\" aria-label=\"Pop out\" \
         data-action=\"runner-popout\" data-stop=\"1\">\
         {popout_icon}</button>\
         <button class=\"runner-control runner-stop-inline\" \
         title=\"Stop\" aria-label=\"Stop\" \
         data-action=\"runner-stop-inline\" data-stop=\"1\">\
         {stop_icon}</button>\
         </div>\
         <div class=\"runner-term-host\"></div>\
         </div>",
        k = h(key),
        c = h(checkout_key),
        ex = exited_attr,
        label_h = h(&label),
        collapse_icon = Icons::runner_collapse,
        popout_icon = Icons::runner_popout,
        stop_icon = Icons::runner_stop,
    )
}

fn branch_status_cell(info: &Checkout) -> String {
    if info.missing {
        "<span class=\"branch-missing\">missing</span>".into()
    } else if info.dirty {
        format!("<span class=\"branch-dirty\">{}</span>", info.changed)
    } else {
        "<span class=\"branch-clean\">\u{2713}</span>".into()
    }
}

fn branch_status_cell_member(info: &Member) -> String {
    // Python shares `_branch_status_cell` across Member + Checkout via
    // dict-key access — our two types differ, so mirror the logic
    // against `Member` explicitly.
    if info.missing {
        "<span class=\"branch-missing\">missing</span>".into()
    } else if info.dirty {
        format!("<span class=\"branch-dirty\">{}</span>", info.changed)
    } else {
        "<span class=\"branch-clean\">\u{2713}</span>".into()
    }
}

fn branch_dot(info_missing: bool, info_dirty: bool, is_live: bool) -> String {
    let cls = if is_live {
        "live"
    } else if info_missing {
        "missing"
    } else if info_dirty {
        "dirty"
    } else {
        "clean"
    };
    format!("<span class=\"b-dot b-dot-{cls}\"></span>")
}

/// One branch row inside a peer-card. `info_*` carries the per-row
/// state; `is_main=true` picks up the parent-checkout quirks.
#[allow(clippy::too_many_arguments)]
fn render_branch_row_inner(
    ctx: &RenderCtx,
    family: &Family,
    member: &Member,
    info_branch: &str,
    info_path: &str,
    info_missing: bool,
    info_dirty: bool,
    info_changed: usize,
    info_changed_files: &[String],
    branch_status_html: &str,
    checkout_key: &str,
    is_main: bool,
    node_id: &str,
    live: &LiveRunners,
) -> String {
    // Branch label: subrepo's main row inherits the parent's branch.
    let branch_label = if !info_branch.is_empty() {
        info_branch.to_string()
    } else if is_main && member.is_subrepo {
        family
            .members
            .first()
            .map(|p| p.branch.clone())
            .unwrap_or_default()
    } else {
        info_branch.to_string()
    };
    let kind_label = if is_main { "checkout" } else { "worktree" };

    // Runner pill — only for configured members that aren't missing.
    let mut runner_pill = String::new();
    let member_key = runner_key_for_member(family, member);
    let session = live.get(&member_key);
    let is_live = session
        .map(|s| s.exit_code.is_none() && s.checkout_key == checkout_key)
        .unwrap_or(false);
    if !info_missing && ctx.repo_run_keys.contains(&member_key) {
        runner_pill = render_runner_button(&member_key, checkout_key, info_path, session);
    }
    let _ = info_changed;
    let _ = info_changed_files;

    let open_cell = if info_missing {
        "<span class=\"open-grp open-grp-empty\" aria-hidden=\"true\"></span>".to_string()
    } else {
        render_open_with(ctx, info_path)
    };

    let mut row_cls = String::from("peer-row");
    if is_main {
        row_cls.push_str(" peer-row-main");
    }
    if info_missing {
        row_cls.push_str(" peer-row-missing");
    } else if is_live && info_dirty {
        row_cls.push_str(" peer-row-dirty peer-row-live");
    } else if is_live {
        row_cls.push_str(" peer-row-live");
    } else if info_dirty {
        row_cls.push_str(" peer-row-dirty");
    }

    let branch_display = if branch_label.is_empty() {
        "&mdash;".to_string()
    } else {
        h(&branch_label)
    };

    format!(
        "<div class=\"{row_cls}\" data-node-id=\"{node_id_h}\" title=\"{path_h}\">\
         {dot}\
         <span class=\"b-name\">{branch}<span class=\"b-kind\">{kind}</span></span>\
         <span class=\"b-status\">{status}</span>\
         <span class=\"b-run\">{run}</span>\
         {open}</div>",
        node_id_h = h(node_id),
        path_h = h(info_path),
        dot = branch_dot(info_missing, info_dirty, is_live),
        branch = branch_display,
        kind = h(kind_label),
        status = branch_status_html,
        run = runner_pill,
        open = open_cell,
    )
}

fn render_branch_row_main(
    ctx: &RenderCtx,
    family: &Family,
    member: &Member,
    node_id: &str,
    live: &LiveRunners,
) -> String {
    let status_html = branch_status_cell_member(member);
    render_branch_row_inner(
        ctx,
        family,
        member,
        &member.branch,
        &member.path,
        member.missing,
        member.dirty,
        member.changed,
        &member.changed_files,
        &status_html,
        "main",
        true,
        node_id,
        live,
    )
}

fn render_branch_row_worktree(
    ctx: &RenderCtx,
    family: &Family,
    member: &Member,
    wt: &Checkout,
    node_id: &str,
    live: &LiveRunners,
) -> String {
    let status_html = branch_status_cell(wt);
    render_branch_row_inner(
        ctx,
        family,
        member,
        &wt.branch,
        &wt.path,
        wt.missing,
        wt.dirty,
        wt.changed,
        &wt.changed_files,
        &status_html,
        &wt.key,
        false,
        node_id,
        live,
    )
}

/// One peer card (parent or promoted subrepo). Port of
/// `_render_peer_card`.
fn render_peer_card(
    ctx: &RenderCtx,
    family: &Family,
    member: &Member,
    member_id: &str,
    live: &LiveRunners,
) -> String {
    let is_subrepo = member.is_subrepo;
    let is_missing = member.missing;

    let mut dirty_branches = 0usize;
    if member.dirty {
        dirty_branches += 1;
    }
    for wt in &member.worktrees {
        if wt.dirty {
            dirty_branches += 1;
        }
    }

    let head_tag = if is_missing {
        "<span class=\"peer-tag peer-tag-missing\">missing</span>".to_string()
    } else if dirty_branches > 0 {
        let noun = if dirty_branches == 1 {
            "branch"
        } else {
            "branches"
        };
        format!("<span class=\"peer-tag peer-tag-dirty\">{dirty_branches} {noun} dirty</span>")
    } else {
        "<span class=\"peer-tag peer-tag-clean\">clean</span>".to_string()
    };
    let member_key = runner_key_for_member(family, member);
    let session = live.get(&member_key);
    let is_live = !is_missing && session.map(|s| s.exit_code.is_none()).unwrap_or(false);
    // Emit the mount (exited or running) whenever a session is anchored
    // here — so the "exited: N" state survives until the user clicks
    // Stop. Matches Python's `_render_runner_mount` truth table.
    let has_session_here = !is_missing && session.is_some();
    let head_tag = if is_live {
        format!("{head_tag}<span class=\"peer-tag peer-tag-live\">live</span>")
    } else {
        head_tag
    };

    let kind_label = if is_subrepo { "sub-repo" } else { "repo" };

    let mut card_cls = String::from("peer-card");
    if is_subrepo {
        card_cls.push_str(" peer-card-sub");
    } else {
        card_cls.push_str(" peer-card-parent");
    }
    if dirty_branches > 0 {
        card_cls.push_str(" peer-card-dirty");
    }
    if is_live {
        card_cls.push_str(" peer-card-live");
    }
    if is_missing {
        card_cls.push_str(" peer-card-missing");
    }

    let mut parts: Vec<String> = Vec::new();
    parts.push(format!(
        "<div class=\"{card_cls}\" data-node-id=\"{id_h}\">",
        id_h = h(member_id)
    ));
    parts.push("<div class=\"peer-head\">".into());
    parts.push(format!(
        "<span class=\"peer-name\">{name}</span>",
        name = h(&member.name)
    ));
    parts.push(head_tag);
    parts.push(format!(
        "<span class=\"peer-kind\">{kind}</span>",
        kind = h(kind_label)
    ));
    // Repo-level "nuclear" stop. One per repo (not per branch) because
    // the underlying command kills whatever is holding the port — no
    // notion of which checkout is active. Rendered only when the user
    // configured `force_stop:` in configuration.yml and the repo is on
    // disk (otherwise the peer card itself is tagged missing and the
    // button would be meaningless).
    if !is_missing && ctx.repo_force_stop_templates.contains_key(&member_key) {
        parts.push(format!(
            "<button type=\"button\" class=\"peer-force-stop\" \
             title=\"Force stop (run configured force_stop command)\" \
             aria-label=\"Force stop\" \
             data-action=\"runner-force-stop\" data-stop=\"1\" \
             data-key=\"{key_h}\">{icon}</button>",
            key_h = h(&member_key),
            icon = Icons::runner_force_stop,
        ));
    }
    parts.push("</div>".into());
    parts.push("<div class=\"peer-rows\">".into());

    parts.push(render_branch_row_main(
        ctx,
        family,
        member,
        &format!("{member_id}/b:main"),
        live,
    ));
    for wt in &member.worktrees {
        let wt_id = format!("{member_id}/wt:{}", wt.key);
        parts.push(render_branch_row_worktree(
            ctx, family, member, wt, &wt_id, live,
        ));
    }
    parts.push("</div>".into()); // /peer-rows

    // Inline runner terminal mount — rendered on the row that owns the
    // session (live or exited). Empty string when no session here.
    if has_session_here {
        let owner_checkout = session.map(|s| s.checkout_key.as_str()).unwrap_or("main");
        let mount = render_runner_mount(&member_key, owner_checkout, session);
        if !mount.is_empty() {
            parts.push(format!("<div class=\"peer-term\">{mount}</div>"));
        }
    }

    let foot_path = &member.path;
    let mut foot = format!(
        "<span class=\"peer-foot-path\">{p}</span>",
        p = h(foot_path)
    );
    if is_live {
        foot.push_str(&format!(
            "<button type=\"button\" class=\"peer-jump\" \
             title=\"Jump to live terminal\" aria-label=\"Jump to live terminal\" \
             data-action=\"runner-jump\" data-stop=\"1\">{icon}</button>",
            icon = Icons::peer_jump,
        ));
    }
    parts.push(format!("<div class=\"peer-foot\">{foot}</div>"));

    parts.push("</div>".into()); // /peer-card
    parts.join("\n")
}

/// One family → bucket-grid wrapper. Port of `_render_flat_group`.
fn render_flat_group(
    ctx: &RenderCtx,
    family: &Family,
    group_id: &str,
    live: &LiveRunners,
) -> String {
    let family_id = format!("{group_id}/{}", family.name);
    let is_compound = family.members.len() > 1;
    let cls = if is_compound {
        "flat-group flat-group-compound"
    } else {
        "flat-group flat-group-solo"
    };
    let mut parts: Vec<String> = Vec::new();
    parts.push(format!(
        "<div class=\"{cls}\" data-node-id=\"{id}\">",
        id = h(&family_id)
    ));
    if is_compound {
        parts.push(format!(
            "<div class=\"flat-group-ornament\">{name}</div>",
            name = h(&family.name)
        ));
    }
    for member in &family.members {
        let member_id = format!("{family_id}/m:{}", member.name);
        parts.push(render_peer_card(ctx, family, member, &member_id, live));
    }
    parts.push("</div>".into());
    parts.join("\n")
}

/// Render the full Code tab given the list of discovered groups.
/// Port of `_render_git_repos`.
pub fn render_git_repos(ctx: &RenderCtx, groups: &[Group], live: &LiveRunners) -> String {
    if groups.is_empty() {
        return String::new();
    }
    let mut parts: Vec<String> = Vec::new();
    for group in groups {
        let group_id = format!("code/{}", group.label);
        parts.push(format!(
            "<section class=\"flat-bucket\" data-node-id=\"{id}\">\
             <h3 class=\"flat-bucket-heading\">{label}</h3>\
             <div class=\"flat-bucket-body\">",
            id = h(&group_id),
            label = h(&group.label),
        ));
        for family in &group.families {
            parts.push(render_flat_group(ctx, family, &group_id, live));
        }
        parts.push("</div></section>".into());
    }
    parts.join("\n")
}

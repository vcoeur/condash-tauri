//! New-item scaffolding — backing for `POST /create-item`. Lays down
//! `projects/YYYY-MM/YYYY-MM-DD-<slug>/README.md` with a kind-specific
//! template and an empty `notes/` sibling, then stamps the
//! `.index-dirty` marker so the index refresh flow knows to run.

use std::fs;
use std::io;
use std::path::Path;
use std::sync::LazyLock;

use condash_parser::{Kind, Priority};
use regex::Regex;
use serde::Serialize;

/// Kind of a new item — mirrors `parser.KINDS`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ItemKind {
    Project,
    Incident,
    Document,
}

impl ItemKind {
    pub fn from_str(v: &str) -> Option<ItemKind> {
        match v.trim().to_ascii_lowercase().as_str() {
            "project" => Some(ItemKind::Project),
            "incident" => Some(ItemKind::Incident),
            "document" => Some(ItemKind::Document),
            _ => None,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            ItemKind::Project => "project",
            ItemKind::Incident => "incident",
            ItemKind::Document => "document",
        }
    }
}

impl From<ItemKind> for Kind {
    fn from(k: ItemKind) -> Kind {
        match k {
            ItemKind::Project => Kind::Project,
            ItemKind::Incident => Kind::Incident,
            ItemKind::Document => Kind::Document,
        }
    }
}

/// Input spec for `create_item` — the fields the `/create-item` and
/// `/api/items` routes collect from the new-item modal.
#[derive(Debug, Default, Clone)]
pub struct NewItemSpec {
    pub title: String,
    pub slug: String,
    pub kind: String,
    pub status: String,
    pub apps: String,
    pub environment: String,
    pub severity: String,
    pub languages: String,
}

/// `{ok, rel_path, slug, folder_name, priority, month}` on success
/// or `{ok: false, reason}` on a validation failure.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum CreateItemResult {
    Ok {
        ok: bool,
        rel_path: String,
        slug: String,
        folder_name: String,
        priority: String,
        month: String,
    },
    Err {
        ok: bool,
        reason: String,
    },
}

impl CreateItemResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, CreateItemResult::Ok { .. })
    }
}

const ENVIRONMENTS: &[&str] = &["PROD", "STAGING", "DEV"];
const SEVERITIES: &[&str] = &["low", "medium", "high"];

static VALID_SLUG_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z0-9]+(?:-[a-z0-9]+)*$").expect("VALID_SLUG_RE compiles"));

fn render_apps(apps_raw: &str) -> String {
    apps_raw
        .split(',')
        .map(|p| p.trim().trim_matches('`'))
        .filter(|p| !p.is_empty())
        .map(|p| format!("`{p}`"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn render_item_template(
    kind: ItemKind,
    title: &str,
    date: &str,
    status: &str,
    apps_line: &str,
    environment: &str,
    severity: &str,
    languages: &str,
) -> String {
    let mut header: Vec<String> = vec![
        format!("# {title}"),
        String::new(),
        format!("**Date**: {date}"),
        format!("**Kind**: {}", kind.as_str()),
        format!("**Status**: {status}"),
    ];
    if !apps_line.is_empty() {
        header.push(format!("**Apps**: {apps_line}"));
    }
    if kind == ItemKind::Incident {
        if !environment.is_empty() {
            header.push(format!("**Environment**: {environment}"));
        }
        if !severity.is_empty() {
            header.push(format!("**Severity**: {severity}"));
        }
    }
    if kind == ItemKind::Document && !languages.is_empty() {
        header.push(format!("**Languages**: {languages}"));
    }

    let body: Vec<String> = match kind {
        ItemKind::Project => vec![
            "## Goal".into(),
            String::new(),
            "_Describe the user-facing outcome this project aims to achieve._".into(),
            String::new(),
            "## Scope".into(),
            String::new(),
            "_What is in scope; what is explicitly out of scope._".into(),
            String::new(),
            "## Steps".into(),
            String::new(),
            "- [ ] First milestone".into(),
            String::new(),
            "## Timeline".into(),
            String::new(),
            format!("- {date} — Project created."),
            String::new(),
            "## Notes".into(),
            String::new(),
        ],
        ItemKind::Incident => vec![
            "## Description".into(),
            String::new(),
            "_Observable symptoms, scope, when it started._".into(),
            String::new(),
            "## Symptoms".into(),
            String::new(),
            "- _Error messages, user-facing effects, log patterns._".into(),
            String::new(),
            "## Analysis".into(),
            String::new(),
            "_Investigation findings, hypotheses, references to `notes/`._".into(),
            String::new(),
            "## Root cause".into(),
            String::new(),
            "_Not yet identified._".into(),
            String::new(),
            "## Steps".into(),
            String::new(),
            "- [ ] Reproduce".into(),
            String::new(),
            "## Timeline".into(),
            String::new(),
            format!("- {date} — Incident opened."),
            String::new(),
            "## Notes".into(),
            String::new(),
        ],
        ItemKind::Document => vec![
            "## Goal".into(),
            String::new(),
            "_What this document is for and who the audience is._".into(),
            String::new(),
            "## Steps".into(),
            String::new(),
            "- [ ] Collect sources".into(),
            "- [ ] Draft".into(),
            "- [ ] Review".into(),
            String::new(),
            "## Deliverables".into(),
            String::new(),
            "**Audience**: _who the PDF is for_".into(),
            "**Key elements**: _structural spec — what sections must appear_".into(),
            "**Sources**: _where to read from to produce the deliverable_".into(),
            "**Current summary**: _Not yet generated._".into(),
            String::new(),
            "## Timeline".into(),
            String::new(),
            format!("- {date} — Created."),
            String::new(),
            "## Notes".into(),
            String::new(),
        ],
    };

    let mut all = header;
    all.push(String::new());
    all.extend(body);
    all.join("\n")
}

/// Scaffold a new conception item under
/// `projects/YYYY-MM/YYYY-MM-DD-<slug>/`. Writes a minimal `README.md`,
/// creates an empty `notes/` sibling, and touches
/// `projects/.index-dirty` so the index-refresh flow knows to run.
/// Never leaves partial state on validation failure.
///
/// `today` is expected as a pre-formatted `(YYYY, MM, DD)` tuple so
/// tests can feed a deterministic date. In production the route handler
/// sources it from `chrono::Local::now()`.
pub fn create_item(
    base_dir: &Path,
    spec: NewItemSpec,
    today: (u16, u8, u8),
) -> io::Result<CreateItemResult> {
    let title = spec.title.trim().to_string();
    // Preserve slug casing so the regex can reject uppercase (the
    // folder name must be lowercase — silent mangling would mask typos).
    let slug = spec.slug.trim().to_string();
    let kind_raw = spec.kind.trim().to_ascii_lowercase();
    let status_raw = spec.status.trim().to_ascii_lowercase();
    let apps_raw = spec.apps.trim().to_string();
    let environment = spec.environment.trim().to_ascii_uppercase();
    let severity = spec.severity.trim().to_ascii_lowercase();
    let languages = spec.languages.trim().to_ascii_lowercase();

    if title.is_empty() {
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: "title required".into(),
        });
    }
    let kind = match ItemKind::from_str(&kind_raw) {
        Some(k) => k,
        None => {
            return Ok(CreateItemResult::Err {
                ok: false,
                reason: "kind must be one of ['project', 'incident', 'document']".into(),
            });
        }
    };
    if Priority::from_lowercase(&status_raw).is_none() {
        let joined = Priority::ALL
            .iter()
            .map(|p| format!("'{}'", p.as_str()))
            .collect::<Vec<_>>()
            .join(", ");
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: format!("status must be one of [{joined}]"),
        });
    }
    if !VALID_SLUG_RE.is_match(&slug) {
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: "slug must be lowercase letters, digits, and single hyphens".into(),
        });
    }
    if kind == ItemKind::Incident
        && !environment.is_empty()
        && !ENVIRONMENTS.contains(&environment.as_str())
    {
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: "environment must be one of ['PROD', 'STAGING', 'DEV']".into(),
        });
    }
    if kind == ItemKind::Incident
        && !severity.is_empty()
        && !SEVERITIES.contains(&severity.as_str())
    {
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: "severity must be one of ['low', 'medium', 'high']".into(),
        });
    }

    let (y, m, d) = today;
    let month = format!("{y:04}-{m:02}");
    let date_str = format!("{y:04}-{m:02}-{d:02}");
    let folder_name = format!("{date_str}-{slug}");

    let projects_root = base_dir.join("projects");
    let month_dir = projects_root.join(&month);
    let item_dir = month_dir.join(&folder_name);

    // Python: item_dir.resolve().relative_to(projects_root.resolve())
    // We replicate the invariant with a literal prefix check since the
    // path doesn't exist yet. The slug regex already rejects traversal
    // in practice (no `/` or `..`).
    let projects_canonical = fs::canonicalize(&projects_root).unwrap_or(projects_root.clone());
    let hypothetical = projects_canonical.join(&month).join(&folder_name);
    if !hypothetical.starts_with(&projects_canonical) {
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: "resolved path escapes projects/".into(),
        });
    }
    if item_dir.exists() {
        return Ok(CreateItemResult::Err {
            ok: false,
            reason: "item with this slug already exists today".into(),
        });
    }

    let body = render_item_template(
        kind,
        &title,
        &date_str,
        &status_raw,
        &render_apps(&apps_raw),
        &environment,
        &severity,
        &languages,
    );

    fs::create_dir_all(item_dir.join("notes"))?;
    fs::write(item_dir.join("README.md"), body)?;

    // Best-effort — failure here doesn't roll back the write.
    let _ = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(projects_root.join(".index-dirty"));

    Ok(CreateItemResult::Ok {
        ok: true,
        rel_path: format!("projects/{month}/{folder_name}/README.md"),
        slug,
        folder_name,
        priority: status_raw,
        month,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    // ----- create_item -----

    #[test]
    fn create_item_project_scaffolds_tree() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        let r = create_item(
            base,
            NewItemSpec {
                title: "Port condash".into(),
                slug: "port-condash".into(),
                kind: "project".into(),
                status: "now".into(),
                apps: "condash, condash/cli".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        match r {
            CreateItemResult::Ok {
                rel_path,
                folder_name,
                month,
                ..
            } => {
                assert_eq!(
                    rel_path,
                    "projects/2026-04/2026-04-22-port-condash/README.md"
                );
                assert_eq!(folder_name, "2026-04-22-port-condash");
                assert_eq!(month, "2026-04");
            }
            _ => panic!("expected ok"),
        }
        let readme = base.join("projects/2026-04/2026-04-22-port-condash/README.md");
        let body = fs::read_to_string(&readme).unwrap();
        assert!(body.starts_with("# Port condash\n"));
        assert!(body.contains("**Kind**: project"));
        assert!(body.contains("**Apps**: `condash`, `condash/cli`"));
        assert!(body.contains("## Goal"));
        assert!(base
            .join("projects/2026-04/2026-04-22-port-condash/notes")
            .is_dir());
        assert!(base.join("projects/.index-dirty").exists());
    }

    #[test]
    fn create_item_incident_includes_environment_and_severity() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        let r = create_item(
            base,
            NewItemSpec {
                title: "DB outage".into(),
                slug: "db-outage".into(),
                kind: "incident".into(),
                status: "now".into(),
                environment: "prod".into(),
                severity: "high".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        assert!(r.is_ok());
        let readme = base.join("projects/2026-04/2026-04-22-db-outage/README.md");
        let body = fs::read_to_string(&readme).unwrap();
        assert!(body.contains("**Environment**: PROD"));
        assert!(body.contains("**Severity**: high"));
        assert!(body.contains("## Root cause"));
    }

    #[test]
    fn create_item_document_languages() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        let r = create_item(
            base,
            NewItemSpec {
                title: "Spec".into(),
                slug: "spec".into(),
                kind: "document".into(),
                status: "now".into(),
                languages: "FR, en".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        assert!(r.is_ok());
        let body =
            fs::read_to_string(base.join("projects/2026-04/2026-04-22-spec/README.md")).unwrap();
        assert!(body.contains("**Languages**: fr, en"));
        assert!(body.contains("## Deliverables"));
    }

    #[test]
    fn create_item_validates_slug() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        for bad in ["BadCase", "-leading", "trailing-", "double--hyphen", ""] {
            let r = create_item(
                base,
                NewItemSpec {
                    title: "x".into(),
                    slug: bad.into(),
                    kind: "project".into(),
                    status: "now".into(),
                    ..Default::default()
                },
                (2026, 4, 22),
            )
            .unwrap();
            assert!(!r.is_ok(), "must reject slug={bad:?}");
        }
    }

    #[test]
    fn create_item_rejects_duplicate() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        let spec = NewItemSpec {
            title: "One".into(),
            slug: "one".into(),
            kind: "project".into(),
            status: "now".into(),
            ..Default::default()
        };
        let _ = create_item(base, spec.clone(), (2026, 4, 22)).unwrap();
        let r = create_item(base, spec, (2026, 4, 22)).unwrap();
        assert!(!r.is_ok());
    }

    #[test]
    fn create_item_rejects_missing_title_and_bad_kind() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        let r = create_item(
            base,
            NewItemSpec {
                title: "".into(),
                slug: "x".into(),
                kind: "project".into(),
                status: "now".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        assert!(!r.is_ok());

        let r = create_item(
            base,
            NewItemSpec {
                title: "hi".into(),
                slug: "hi".into(),
                kind: "widget".into(),
                status: "now".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        assert!(!r.is_ok());
    }

    #[test]
    fn create_item_rejects_bad_environment_severity() {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path();
        fs::create_dir_all(base.join("projects")).unwrap();
        let r = create_item(
            base,
            NewItemSpec {
                title: "x".into(),
                slug: "x".into(),
                kind: "incident".into(),
                status: "now".into(),
                environment: "stage".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        assert!(!r.is_ok());

        let r = create_item(
            base,
            NewItemSpec {
                title: "y".into(),
                slug: "y".into(),
                kind: "incident".into(),
                status: "now".into(),
                severity: "nuclear".into(),
                ..Default::default()
            },
            (2026, 4, 22),
        )
        .unwrap();
        assert!(!r.is_ok());
    }

    #[test]
    fn render_apps_basic() {
        assert_eq!(render_apps(""), "");
        assert_eq!(render_apps("condash"), "`condash`");
        assert_eq!(render_apps("a, b"), "`a`, `b`");
        assert_eq!(render_apps("`a`, b"), "`a`, `b`");
        assert_eq!(render_apps(" a , , b ,"), "`a`, `b`");
    }
}

//! Integration tests for the Phase 3 slice 3 file-level mutation routes.
//!
//! Each test builds a temp conception tree with one seeded item, hands
//! the axum router an HTTP POST (JSON or multipart), and asserts on the
//! HTTP status + JSON body + on-disk filesystem effects.

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::http::{Method, Request, StatusCode};
use condash_lib::server::{build_router, AppState};
use condash_state::{RenderCtx, WorkspaceCache};
use serde_json::{json, Value};
use tempfile::TempDir;
use tower::ServiceExt;

struct Harness {
    _tmp: TempDir,
    state: AppState,
    base: PathBuf,
    item_dir: PathBuf,
    readme_rel: String,
}

fn harness() -> Harness {
    let tmp = TempDir::new().expect("tempdir");
    let base = tmp.path().to_path_buf();
    let item_dir = base.join("projects/2026-04/2026-04-22-demo");
    std::fs::create_dir_all(item_dir.join("notes")).expect("notes dir");
    std::fs::write(
        item_dir.join("README.md"),
        "# demo\n\n## Steps\n\n- [ ] one\n",
    )
    .expect("seed readme");

    let ctx = Arc::new(RenderCtx::with_base_dir(&base));
    let cache = Arc::new(WorkspaceCache::new());
    let state = AppState {
        ctx,
        cache,
        asset_dir: Arc::new(PathBuf::from("/nonexistent")),
        version: Arc::new("test".into()),
    };

    Harness {
        _tmp: tmp,
        state,
        base,
        item_dir,
        readme_rel: "projects/2026-04/2026-04-22-demo/README.md".into(),
    }
}

async fn post_json(state: &AppState, url: &str, body: Value) -> (StatusCode, Value) {
    let app = build_router(state.clone());
    let req = Request::builder()
        .method(Method::POST)
        .uri(url)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let status = resp.status();
    let bytes = to_bytes(resp.into_body(), 1024 * 1024).await.unwrap();
    let parsed: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, parsed)
}

// ---------------------------------------------------------------------
// /note
// ---------------------------------------------------------------------

#[tokio::test]
async fn note_overwrites_file_and_returns_mtime() {
    let h = harness();
    let note = h.item_dir.join("notes/journal.md");
    std::fs::write(&note, "old body\n").unwrap();

    let (status, body) = post_json(
        &h.state,
        "/note",
        json!({
            "path": "projects/2026-04/2026-04-22-demo/notes/journal.md",
            "content": "fresh body\n",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert!(body["mtime"].is_number(), "body was {body}");
    assert_eq!(std::fs::read_to_string(&note).unwrap(), "fresh body\n");
}

#[tokio::test]
async fn note_rejects_stale_mtime_with_409() {
    let h = harness();
    let note = h.item_dir.join("notes/j.md");
    std::fs::write(&note, "body\n").unwrap();
    let (status, body) = post_json(
        &h.state,
        "/note",
        json!({
            "path": "projects/2026-04/2026-04-22-demo/notes/j.md",
            "content": "new",
            "expected_mtime": 0.0_f64,
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(body["ok"], json!(false));
    assert_eq!(body["reason"], json!("file changed on disk"));
    assert!(body["mtime"].is_number());
    // File unchanged.
    assert_eq!(std::fs::read_to_string(&note).unwrap(), "body\n");
}

#[tokio::test]
async fn note_rejects_invalid_path() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note",
        json!({"path": "../escape.md", "content": ""}),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(body["error"], json!("invalid path"));
}

#[tokio::test]
async fn note_rejects_non_editable_extension() {
    let h = harness();
    let pdf = h.item_dir.join("notes/report.pdf");
    std::fs::write(&pdf, b"%PDF-1.4").unwrap();
    let (status, body) = post_json(
        &h.state,
        "/note",
        json!({
            "path": "projects/2026-04/2026-04-22-demo/notes/report.pdf",
            "content": "x",
        }),
    )
    .await;
    // .pdf is not in the md/text whitelist.
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("not editable"));
}

// ---------------------------------------------------------------------
// /note/rename
// ---------------------------------------------------------------------

#[tokio::test]
async fn note_rename_moves_file_and_returns_new_path() {
    let h = harness();
    let old = h.item_dir.join("notes/old.md");
    std::fs::write(&old, "x").unwrap();
    let (status, body) = post_json(
        &h.state,
        "/note/rename",
        json!({
            "path": "projects/2026-04/2026-04-22-demo/notes/old.md",
            "new_stem": "renamed",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(
        body["path"],
        json!("projects/2026-04/2026-04-22-demo/notes/renamed.md")
    );
    assert!(h.item_dir.join("notes/renamed.md").exists());
    assert!(!old.exists());
}

#[tokio::test]
async fn note_rename_refuses_readme() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/rename",
        json!({
            "path": h.readme_rel.clone(),
            "new_stem": "whatever",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["error"],
        json!("only files under <item>/notes/ can be renamed")
    );
}

#[tokio::test]
async fn note_rename_refuses_invalid_stem() {
    let h = harness();
    let old = h.item_dir.join("notes/old.md");
    std::fs::write(&old, "x").unwrap();
    let (status, body) = post_json(
        &h.state,
        "/note/rename",
        json!({
            "path": "projects/2026-04/2026-04-22-demo/notes/old.md",
            "new_stem": "has space",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("invalid filename"));
}

// ---------------------------------------------------------------------
// /note/create
// ---------------------------------------------------------------------

#[tokio::test]
async fn note_create_at_root_writes_empty_file() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/create",
        json!({
            "item_readme": h.readme_rel.clone(),
            "filename": "draft.md",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body["path"],
        json!("projects/2026-04/2026-04-22-demo/draft.md")
    );
    assert!(h.item_dir.join("draft.md").exists());
}

#[tokio::test]
async fn note_create_in_existing_subdir() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/create",
        json!({
            "item_readme": h.readme_rel.clone(),
            "filename": "n.md",
            "subdir": "notes",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert!(h.item_dir.join("notes/n.md").exists());
}

#[tokio::test]
async fn note_create_refuses_missing_subdir() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/create",
        json!({
            "item_readme": h.readme_rel.clone(),
            "filename": "n.md",
            "subdir": "nope",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("subdirectory does not exist"));
}

#[tokio::test]
async fn note_create_refuses_bad_filename() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/create",
        json!({
            "item_readme": h.readme_rel.clone(),
            "filename": "no_ext",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("invalid filename"));
}

#[tokio::test]
async fn note_create_refuses_duplicate() {
    let h = harness();
    std::fs::write(h.item_dir.join("dup.md"), "").unwrap();
    let (status, body) = post_json(
        &h.state,
        "/note/create",
        json!({"item_readme": h.readme_rel.clone(), "filename": "dup.md"}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("file exists"));
}

// ---------------------------------------------------------------------
// /note/mkdir
// ---------------------------------------------------------------------

#[tokio::test]
async fn note_mkdir_creates_nested_dir() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/mkdir",
        json!({
            "item_readme": h.readme_rel.clone(),
            "subpath": "assets/ui",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(body["rel_dir"], json!("assets/ui"));
    assert_eq!(body["subdir_key"], json!("2026-04-22-demo/assets/ui"));
    assert!(h.item_dir.join("assets/ui").is_dir());
}

#[tokio::test]
async fn note_mkdir_refuses_existing_with_409() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/mkdir",
        json!({"item_readme": h.readme_rel.clone(), "subpath": "notes"}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(body["ok"], json!(false));
    assert_eq!(body["reason"], json!("exists"));
}

#[tokio::test]
async fn note_mkdir_refuses_empty_subpath() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/note/mkdir",
        json!({"item_readme": h.readme_rel.clone(), "subpath": "   "}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("invalid subdirectory name"));
}

// ---------------------------------------------------------------------
// /note/upload (multipart)
// ---------------------------------------------------------------------

fn multipart(fields: &[(&str, &str, &[u8])]) -> (String, Vec<u8>) {
    // Build a minimal multipart/form-data body. `fields` is a list of
    // (name, filename_or_empty, bytes). An empty filename means "plain
    // text field" — the Content-Disposition omits the filename= key.
    let boundary = "----condash-test-boundary";
    let mut body: Vec<u8> = Vec::new();
    for (name, filename, bytes) in fields {
        body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
        if filename.is_empty() {
            body.extend_from_slice(
                format!("Content-Disposition: form-data; name=\"{name}\"\r\n\r\n").as_bytes(),
            );
        } else {
            body.extend_from_slice(
                format!(
                    "Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                )
                .as_bytes(),
            );
            body.extend_from_slice(b"Content-Type: application/octet-stream\r\n\r\n");
        }
        body.extend_from_slice(bytes);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
    (format!("multipart/form-data; boundary={boundary}"), body)
}

async fn post_multipart(
    state: &AppState,
    url: &str,
    ctype: &str,
    body: Vec<u8>,
) -> (StatusCode, Value) {
    let app = build_router(state.clone());
    let req = Request::builder()
        .method(Method::POST)
        .uri(url)
        .header("content-type", ctype)
        .body(Body::from(body))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let status = resp.status();
    let bytes = to_bytes(resp.into_body(), 4 * 1024 * 1024).await.unwrap();
    let parsed: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, parsed)
}

#[tokio::test]
async fn upload_writes_files_and_returns_stored_list() {
    let h = harness();
    let (ctype, body) = multipart(&[
        ("item_readme", "", h.readme_rel.as_bytes()),
        ("subdir", "", b"notes"),
        ("file", "a.txt", b"hello"),
        ("file", "b.txt", b"world"),
    ]);
    let (status, body) = post_multipart(&h.state, "/note/upload", &ctype, body).await;
    assert_eq!(status, StatusCode::OK, "body: {body}");
    assert_eq!(body["ok"], json!(true));
    let stored = body["stored"].as_array().unwrap();
    assert_eq!(stored.len(), 2);
    assert!(stored[0]
        .as_str()
        .unwrap()
        .ends_with("projects/2026-04/2026-04-22-demo/notes/a.txt"));
    assert_eq!(
        std::fs::read_to_string(h.item_dir.join("notes/a.txt")).unwrap(),
        "hello"
    );
}

#[tokio::test]
async fn upload_rejects_when_no_files() {
    let h = harness();
    let (ctype, body) = multipart(&[
        ("item_readme", "", h.readme_rel.as_bytes()),
        ("subdir", "", b""),
    ]);
    let (status, body) = post_multipart(&h.state, "/note/upload", &ctype, body).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("no files in upload"));
}

#[tokio::test]
async fn upload_rejects_invalid_item() {
    let h = harness();
    let (ctype, body) = multipart(&[
        ("item_readme", "", b"../bad/README.md"),
        ("subdir", "", b""),
        ("file", "a.txt", b"x"),
    ]);
    let (status, body) = post_multipart(&h.state, "/note/upload", &ctype, body).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("invalid item"));
}

#[tokio::test]
async fn upload_records_invalid_filenames_in_rejected() {
    let h = harness();
    let (ctype, body) = multipart(&[
        ("item_readme", "", h.readme_rel.as_bytes()),
        ("subdir", "", b""),
        ("file", "../evil", b"x"),
    ]);
    let (status, body) = post_multipart(&h.state, "/note/upload", &ctype, body).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert!(body["stored"].as_array().unwrap().is_empty());
    let rejected = body["rejected"].as_array().unwrap();
    assert_eq!(rejected.len(), 1);
    assert_eq!(rejected[0]["reason"], json!("invalid filename"));
}

// ---------------------------------------------------------------------
// /create-item
// ---------------------------------------------------------------------

#[tokio::test]
async fn create_item_scaffolds_project() {
    let h = harness();
    // Ensure projects/ root exists (the harness already created one
    // item, so projects/ is there).
    let (status, body) = post_json(
        &h.state,
        "/create-item",
        json!({
            "title": "Port PTY",
            "slug": "port-pty",
            "kind": "project",
            "status": "now",
            "apps": "condash",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert!(body["rel_path"]
        .as_str()
        .unwrap()
        .ends_with("port-pty/README.md"));
    let month = body["month"].as_str().unwrap();
    let folder_name = body["folder_name"].as_str().unwrap();
    let readme_path = h
        .base
        .join(format!("projects/{month}/{folder_name}/README.md"));
    assert!(readme_path.exists(), "expected {readme_path:?}");
    let content = std::fs::read_to_string(&readme_path).unwrap();
    assert!(content.contains("# Port PTY"));
    assert!(content.contains("**Apps**: `condash`"));
    assert!(content.contains("## Goal"));
}

#[tokio::test]
async fn create_item_rejects_bad_slug() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/create-item",
        json!({
            "title": "x",
            "slug": "BadCase",
            "kind": "project",
            "status": "now",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"].as_str().unwrap().contains("slug must be"));
}

#[tokio::test]
async fn create_item_rejects_missing_title() {
    let h = harness();
    let (status, body) = post_json(
        &h.state,
        "/create-item",
        json!({
            "title": "",
            "slug": "hi",
            "kind": "project",
            "status": "now",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("title required"));
}

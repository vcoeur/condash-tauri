//! README.md write-side mutations — Rust port of `src/condash/mutations.py`.
//!
//! Phase 3 slice 1 covered the six step-mutation helpers behind the
//! `/toggle`, `/add-step`, `/remove-step`, `/edit-step`, `/set-priority`,
//! and `/reorder-all` routes ([`steps`]).
//!
//! Phase 3 slice 3 adds the file-level write helpers ([`files`]) behind
//! `/note`, `/note/rename`, `/note/create`, `/note/mkdir`, `/note/upload`,
//! and `/create-item`.
//!
//! Every helper reads the target file(s) as UTF-8 (or raw bytes for
//! uploads), mutates in place, and writes back — byte-identical to the
//! Python port, including the trailing-newline convention Python's
//! `str.split("\n")` + `"\n".join(...)` round-trips.
//!
//! The helpers are pure with respect to [`RenderCtx`][condash_state::RenderCtx]
//! — path validation is the caller's job (see `src-tauri/src/paths.rs`)
//! and these functions take already-resolved absolute paths.

pub mod files;
pub mod steps;

pub use files::{
    create_item, create_note, create_notes_subdir, rename_note, store_uploads, write_note,
    CreateItemResult, CreateNoteResult, CreateSubdirResult, ItemKind, NewItemSpec, RenameResult,
    StoreUploadsResult, UploadRejection, WriteNoteResult,
};
pub use steps::{
    add_step, edit_step, remove_step, reorder_all, set_priority, toggle_checkbox, PRIORITIES,
};

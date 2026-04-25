//! README.md write-side mutations.
//!
//! Two surfaces:
//!
//! - [`steps`] — the six step-mutation helpers behind `/toggle`,
//!   `/add-step`, `/remove-step`, `/edit-step`, `/set-priority`, and
//!   `/reorder-all`.
//! - [`files`] — file-level write helpers behind `/note`,
//!   `/note/rename`, `/note/create`, `/note/mkdir`, `/note/upload`,
//!   and `/create-item`.
//!
//! Every helper reads the target file as UTF-8 (or raw bytes for
//! uploads), mutates in place, and writes back — preserving the
//! trailing-newline convention that `str::split('\n').collect::<_>()
//! .join('\n')` round-trips.
//!
//! The helpers are pure with respect to
//! [`RenderCtx`][condash_state::RenderCtx] — path validation is the
//! caller's job (see `src-tauri/src/paths.rs`) and these functions
//! take already-resolved absolute paths.

pub mod create_item;
pub mod files;
pub mod steps;

pub use create_item::{create_item, CreateItemResult, ItemKind, NewItemSpec};
pub use files::{
    create_note, create_notes_subdir, rename_note, store_uploads, write_note, CreateNoteResult,
    CreateSubdirResult, RenameResult, StoreUploadsResult, UploadRejection, WriteNoteResult,
};
pub use steps::{add_step, edit_step, remove_step, reorder_all, set_priority, toggle_checkbox};

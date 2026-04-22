//! README.md write-side mutations — Rust port of the step-level helpers in
//! `src/condash/mutations.py`.
//!
//! Phase 3 slice 1 covers the six step-mutation functions behind the
//! `/toggle`, `/add-step`, `/remove-step`, `/edit-step`, `/set-priority`,
//! and `/reorder-all` routes. Every function reads the target file as UTF-8,
//! mutates the line buffer in place, and writes it back — byte-identical to
//! the Python port, including the trailing-newline convention Python's
//! `str.split("\n")` + `"\n".join(...)` round-trips.
//!
//! The helpers are pure with respect to [`RenderCtx`][condash_state::RenderCtx]
//! — path validation is the caller's job and lives in `condash-state::paths`
//! (or, today, on the Python side). They take an absolute [`Path`] and do
//! not re-check the sandbox.

pub mod steps;

pub use steps::{
    add_step, edit_step, remove_step, reorder_all, set_priority, toggle_checkbox, PRIORITIES,
};

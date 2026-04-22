//! File-extension classifier — drives the preview dispatcher.
//!
//! Rust port of `_note_kind` in `src/condash/parser.py`. The extension
//! lists mirror the Python `_IMAGE_EXTS` / `_PDF_EXTS` / `_TEXT_EXTS`
//! sets one-for-one; anything else classifies as `binary`.

use std::path::Path;

pub const IMAGE_EXTS: &[&str] = &[".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif"];

pub const PDF_EXTS: &[&str] = &[".pdf"];

pub const TEXT_EXTS: &[&str] = &[
    ".txt",
    ".log",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bash",
    ".zsh",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".sql",
    ".env",
    ".gitignore",
];

/// Classify a file by extension. Returns one of `"md"`, `"pdf"`,
/// `"image"`, `"text"`, `"binary"` — verbatim the strings the frontend
/// expects.
pub fn note_kind(path: &Path) -> &'static str {
    let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
        return "binary";
    };
    let lower = name.to_ascii_lowercase();
    // Python's Path.suffix only looks at the segment after the last dot;
    // for dotfiles like ".gitignore" the suffix is empty and the file
    // classifies as binary. Mirror that behavior rather than matching on
    // bare filename.
    let ext = match lower.rfind('.') {
        Some(0) | None => return "binary",
        Some(i) => &lower[i..],
    };
    if ext == ".md" {
        return "md";
    }
    if PDF_EXTS.contains(&ext) {
        return "pdf";
    }
    if IMAGE_EXTS.contains(&ext) {
        return "image";
    }
    if TEXT_EXTS.contains(&ext) {
        return "text";
    }
    "binary"
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn classifies_by_extension() {
        for (name, expected) in [
            ("README.md", "md"),
            ("note.MD", "md"),
            ("paper.pdf", "pdf"),
            ("photo.jpg", "image"),
            ("photo.JPEG", "image"),
            ("diagram.svg", "image"),
            ("script.py", "text"),
            ("config.toml", "text"),
            ("bundle.JS", "text"),
            ("data.bin", "binary"),
            ("no-ext", "binary"),
            (".gitignore", "binary"),
        ] {
            let p = PathBuf::from(name);
            assert_eq!(note_kind(&p), expected, "name {name:?}");
        }
    }
}

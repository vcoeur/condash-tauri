//! Parser for conception item READMEs and the knowledge tree.
//!
//! Layered by side-effect so unit tests can exercise the pure core
//! without touching the disk:
//!
//!   - Pure string-level primitives: [`regexes`], [`sections`],
//!     [`deliverables`], [`readme`] (`parse_readme_content`),
//!     [`note_kind`].
//!   - Filesystem-walking: [`tree`] (`list_item_tree`), [`knowledge`]
//!     (`collect_knowledge` + tree walker), [`collect`]
//!     (`parse_readme` + `collect_items`).

pub mod collect;
pub mod deliverables;
pub mod knowledge;
pub mod note_kind;
pub mod readme;
pub mod regexes;
pub mod sections;
pub mod tree;

pub use collect::{collect_items, parse_readme, Item};
pub use deliverables::{parse_deliverables, Deliverable};
pub use knowledge::{
    collect_knowledge, collect_tree, knowledge_title_and_desc, KnowledgeCard, KnowledgeNode,
};
pub use note_kind::note_kind;
pub use readme::{parse_readme_content, ItemReadme};
pub use sections::{parse_sections, CheckboxStatus, Section, SectionItem};
pub use tree::{flatten_tree_paths, list_item_tree, FileEntry, GroupEntry, ItemTree};

/// Ordered priority / status enum. Variant order is load-bearing:
/// sort-by-`as usize` yields the dashboard's canonical column order
/// (now → soon → later → backlog → review → done).
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize, serde::Deserialize,
)]
#[serde(rename_all = "lowercase")]
pub enum Priority {
    Now,
    Soon,
    Later,
    Backlog,
    Review,
    Done,
}

impl Priority {
    pub const ALL: [Priority; 6] = [
        Priority::Now,
        Priority::Soon,
        Priority::Later,
        Priority::Backlog,
        Priority::Review,
        Priority::Done,
    ];

    /// Parse a lowercase string; returns `None` for unknown values.
    /// `parse_readme_content` coerces unknowns to `Backlog` and
    /// records the raw input in the item's `invalid_status` field.
    pub fn from_lowercase(value: &str) -> Option<Priority> {
        match value {
            "now" => Some(Priority::Now),
            "soon" => Some(Priority::Soon),
            "later" => Some(Priority::Later),
            "backlog" => Some(Priority::Backlog),
            "review" => Some(Priority::Review),
            "done" => Some(Priority::Done),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Priority::Now => "now",
            Priority::Soon => "soon",
            Priority::Later => "later",
            Priority::Backlog => "backlog",
            Priority::Review => "review",
            Priority::Done => "done",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Project,
    Incident,
    Document,
}

impl Kind {
    pub fn from_lowercase(value: &str) -> Option<Kind> {
        match value {
            "project" => Some(Kind::Project),
            "incident" => Some(Kind::Incident),
            "document" => Some(Kind::Document),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Kind::Project => "project",
            Kind::Incident => "incident",
            Kind::Document => "document",
        }
    }
}

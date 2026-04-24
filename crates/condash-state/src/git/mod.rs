//! Git repo discovery + status + fingerprinting for the dashboard's
//! Code tab.

pub mod fingerprint;
pub mod scan;

pub use fingerprint::{compute_git_node_fingerprints, git_fingerprint};
pub use scan::{collect_git_repos, Checkout, Family, Group, Member};

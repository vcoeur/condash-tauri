//! Git repo discovery + status for the dashboard's Code tab.

pub mod scan;

pub use scan::{collect_git_repos, Checkout, Family, Group, Member};

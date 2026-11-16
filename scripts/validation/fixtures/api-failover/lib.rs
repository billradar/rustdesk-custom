extern crate self as hbb_common;
pub use log;
fn api_failover_proxy() -> Result<Option<reqwest::Proxy>, String> { Ok(None) }
pub mod api_failover;

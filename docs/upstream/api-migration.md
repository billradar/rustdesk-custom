# API migration: Patch Set v1 to v2

Inspection: 2026-10-01. Official repository `rustdesk/rustdesk`; queried default branch
`master`, exact SHA `fada664df7a294d1d1a9ca3e7cd3637069122f17`.
Frozen v1 stable SHA: `6c578292e8ebbbec708b76986ba8c4bc7c509747` (tag 1.4.9).

## Source evidence and adaptation

| Type | Old API / source | New API / source | Affected patch / adaptation |
|---|---|---|---|
| MOVED / STRUCTURE_CHANGED | hbb_common::config::keys::OPTION_ALLOW_REMOTE_CONFIG_MODIFICATION, libs/hbb_common/src/config.rs | base::config::keys::OPTION_ALLOW_REMOTE_CONFIG_MODIFICATION, libs/base/src/config/keys.rs | Common 0002: use the new public client-only key path; maps remain hbb_common config |
| REMOVED / FLUTTER_API_CHANGED | desktop_home_page.dart buildPluginEntry; settings enum plugin and pluginFeatureIsEnabled | Upstream removed plugin entry/setting implementation | SOS 0002/0003: preserve simplified homepage and guards on remaining tabs; do not resurrect removed upstream feature |
| CONFIG_CHANGED / FLUTTER_API_CHANGED | Settings general tab unconditional; printer lacks disable-settings condition | General honors kOptionHideGeneralSetting; printer honors isDisableSettings | SOS 0003: add SOS guard with AND, retaining both new upstream conditions |
| SIGNATURE_CHANGED | connection_page.dart onConnect lacks isTcpTunneling | New optional isTcpTunneling routes through existing controller entry | SOS home/right-pane hiding remains; native/controller behavior is not upgraded to Level 3 |
| BUILD_SYSTEM_CHANGED | Historical Cargo/Flutter/workflow hashes | Cargo lock, libs/base workspace member, build.py/build.rs, Flutter locks and official workflows changed | Build monitor WARNING; missing required adapter inputs FAIL. Rust probe must compile actual helper against base + hbb_common |

Exact source links:
- [old common](https://github.com/rustdesk/rustdesk/blob/6c578292e8ebbbec708b76986ba8c4bc7c509747/src/common.rs)
- [new key](https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/libs/base/src/config/keys.rs)
- [new common imports](https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/src/common.rs)
- [new settings](https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/flutter/lib/desktop/pages/desktop_setting_page.dart)
- [new home](https://github.com/rustdesk/rustdesk/blob/fada664df7a294d1d1a9ca3e7cd3637069122f17/flutter/lib/desktop/pages/desktop_home_page.dart)

Original GitHub detection: https://github.com/billradar/rustdesk-custom-test/actions/runs/36819199270
Common patch application succeeded there, but the moved key API failed the structural check.
During v2 extraction, real SOS apply failed on removed buildPluginEntry context. Inspection
also found removed plugin settings and new upstream general/printer guard conditions.
The v2 patches are generated against new source semantics, not by making old hunk lines fit.

## Behavior contract (source/build design intent, not runtime validation)

Common:
- ID server/key: compile-time constants in official submodule, no change to stored-config priority.
- API: compile-time fallback at the same get_api_server_ fallback layer; explicit configuration
  and upstream host derivation still take priority.
- Relay: optional DEFAULT_SETTINGS entry; empty means native discovery; existing defaults
  retain priority via entry/or_insert.
- Fixed password: unchanged HARD_SETTINGS plaintext preset; verification-method remains
  use-permanent-password. No new salt/storage/H1 mechanism.
- allow-remote-config-modification=Y and allow-hide-cm=Y defaults retained, without overwriting
  existing entries. Same two initialization paths call defaults.
- Common settings retain hide-cm UI availability under the upstream password condition.

SOS:
- Common applies first; BUILTIN_SETTINGS sos-mode=Y follows, without duplicate servers.
- Hide ordinary right controller pane/divider; retain left ID/password and background service
  source paths; keep the historical SOS width/title/online-status design.
- Hide setupServerWidget and ID popup in SOS; hide main Settings icon.
- Non-About tabs get SOS guards plus their current upstream predicates; About remains.
- No native incoming-only policy, no CLI/deep-link denial, no Level 3 upgrade.
- Plugin functionality removed by upstream stays removed; its absence is an upstream baseline
  difference, not restoration work. New upstream routing features are not claimed blocked.

Runtime/UI Validation: **SKIPPED BY USER**. Real remote session: **NOT TESTED**.
v2 preserves source/build design intent; no runtime equivalence claim.

## Unchanged APIs reviewed

hbb_common HARD_SETTINGS / DEFAULT_SETTINGS / BUILTIN_SETTINGS map types, ID/key constants,
Config::get_option and get_rendezvous_server, native built-in-option binding, incoming/settings
bindings and four desktop page types remain. Thus hbb two-line config patch, hide-cm Common
patch and sos-mode patch are reused byte-identically, with explicit review rather than blind
line-number edits. Root default helper uses the new key namespace. Home/settings patches
are rebuilt on the new upstream trees.

Future incoming-only improvements remain deferred. No password redesign, production config,
signing or platform additions are part of migration.

## Actual candidate compatibility evidence

[Run 36828069170](https://github.com/billradar/rustdesk-custom-test/actions/runs/36828069170) at maintenance commit
ceb48ac57fcf4aa2d3467ff942637af8c51a2c3d and upstream
fada664df7a294d1d1a9ca3e7cd3637069122f17: resolver v1 INCOMPATIBLE,
v2 selected; both Common/SOS config/API preflight, real Rust fast compilation,
Bridge and Flutter analyze PASS. Downloaded aggregate artifact reports overall PASS
and selected v2 full_compatibility COMPATIBLE. Windows full-build job SKIPPED by design.
No client release created. v2 metadata status is compatibility_validated, not Windows-build
or runtime validated; original runtime/session limitations remain unchanged.

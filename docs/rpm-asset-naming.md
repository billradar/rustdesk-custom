# Public RPM asset names

The RPM-native Release and Architecture fields remain inside each package.
Public v3.2+ filenames carry architecture once and distinguish ordinary from
SUSE RPM; filenames are normalized during asset staging without changing any
RPM headers, package identity or payload bytes.

| Variant | Architecture | Ordinary RPM | SUSE RPM |
| --- | --- | --- | --- |
| Standard | x86_64 | `rustdesk-1.5.3-linux-x86_64.rpm` | `rustdesk-1.5.3-linux-x86_64-suse.rpm` |
| Standard | aarch64 | `rustdesk-1.5.3-linux-aarch64.rpm` | `rustdesk-1.5.3-linux-aarch64-suse.rpm` |
| SOS | x86_64 | `rustdesk-1.5.3-sos-linux-x86_64.rpm` | `rustdesk-1.5.3-sos-linux-x86_64-suse.rpm` |
| SOS | aarch64 | `rustdesk-1.5.3-sos-linux-aarch64.rpm` | `rustdesk-1.5.3-sos-linux-aarch64-suse.rpm` |

For example, raw `standard-rustdesk-1.5.3-x86_64-0.x86_64-suse.rpm` becomes
`rustdesk-1.5.3-linux-x86_64-suse.rpm`. Normalizing an already canonical name
returns the same name. Unexpected or mismatched RPM architecture suffixes fail
rather than being relabeled. Two inputs normalizing to one name fail aggregation
before any package is copied; Standard/SOS or RPM/SUSE bytes never overwrite one
another.

The v3 updater's exact filename selector changes with the producer. This is a
Common patch-content change, allocating v3.2 from integration base
`c1d6942ee173979a8d73c393a7ceb12abda20186`. v3.1 history, all SOS patch bytes, and
all v1/v2 patch files/manifests remain unchanged. v1/v2 aggregation explicitly
retains legacy RPM names so their clients are not silently broken.

Existing v3.1 Draft assets are not renamed or overwritten. A future qualified
v3.2 build uses its own content tag `v1.5.3-custom.v3.2`. Older clients with fixed
legacy RPM filenames require manual upgrade to v3.2 or later; no alias transition
is introduced. DEB, Wayland DEB, Windows, macOS and Android names are unchanged.

The attested manifest continues to contain one entry per installer, with distinct
`rpm` and `suse-rpm` package selectors. JSON-consuming client update logic remains
a separate change.

## Validation

Run qualification, client-update, Profile and patchset-content contracts. The
client-update suite compiles and executes both historical v2 and current v3 Rust
policies, comparing their selectors to staged filenames across all 31 packages
(including four Wayland DEBs). Exact-source Standard/SOS patch application and
structural/helper checks must also pass for official 1.5.3. No local contract
proves RPM installation, a device upgrade or real remote sessions.

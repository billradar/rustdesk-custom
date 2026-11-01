# Public branding variables

Both Common generations include `0006-public-branding.patch`. Configure public
GitHub repository **Variables**, not Secrets. The prepared-source workflow reads
only the declared variables, treating missing, empty and whitespace-only values
as unset. It freezes one validated public snapshot per build, then uses that
snapshot for Standard/SOS, Dart text, platform display resources and package
metadata. `branding.json`, generated Dart values and native resource changes are
covered by the prepared-source inventory and `branding_sha256`.
Branding files and prepared-source text checks explicitly use UTF-8 on every
platform, including Windows hosts whose default text encoding is cp1252.

## Twenty base variables

| Variable | Default when unset |
|---|---|
| `CUSTOM_DISPLAY_NAME` | RustDesk; internal application name is unchanged |
| `CUSTOM_ABOUT_TITLE` | Upstream localized title; derived from a supplied display name |
| `CUSTOM_ANDROID_APP_LABEL` | RustDesk; derived from a supplied display name |
| `CUSTOM_ANDROID_SERVICE_LABEL` | RustDesk Input; derived from a supplied display name |
| `CUSTOM_LINUX_APP_LABEL` | RustDesk; derived from a supplied display name |
| `CUSTOM_DESCRIPTION` | Preserve platform-specific upstream descriptions; no extra About description |
| `CUSTOM_SLOGAN` | Preserve the upstream localized slogan |
| `CUSTOM_INSTALLER_TITLE` | Preserve the upstream title; derived from a supplied display name |
| `CUSTOM_INSTALLER_DESCRIPTION` | Preserve upstream; use a supplied product description if present |
| `CUSTOM_PUBLISHER` | Do not add a customization publisher or replace original attribution |
| `CUSTOM_MAINTAINER` | Preserve upstream package maintainer |
| `CUSTOM_CONTACT_EMAIL` | Do not add a new contact address |
| `CUSTOM_CUSTOMIZATION_NOTICE` | Absent; generated when a publisher is supplied |
| `CUSTOM_WINDOWS_COMPANY_NAME` | Purslane Tech Pte. Ltd.; falls back to a supplied publisher |
| `CUSTOM_LINUX_GENERIC_NAME` | Remote Desktop |
| `CUSTOM_LINUX_COMMENT` | Remote Desktop; falls back to a supplied product description |
| `CUSTOM_WEBSITE_URL` | Build repository homepage |
| `CUSTOM_HELP_URL` | Build repository README |
| `CUSTOM_SUPPORT_URL` | Build repository Issues |
| `CUSTOM_PRIVACY_URL` | Preserve the upstream privacy link |

For this project's preferred publisher, set `CUSTOM_PUBLISHER` to
`Bill Radar (houxnan)`. It is not hardcoded into forks. The generated notice is
separate from original copyright and license text, which remains intact.
An explicit dependent field overrides generated text. Names, descriptions and
links are never used as package names, service names, update repository IDs or
version identities. Repository links follow the frozen build repository.

`CUSTOM_MAINTAINER` must be a complete `Name <email>` value or be accompanied by
`CUSTOM_CONTACT_EMAIL`; an email alone uses the publisher or RustDesk as its
display name. Contact information is public and becomes part of the package.
URLs must be HTTPS without embedded credentials. Control characters, oversized
values, known credentials and build-preprocessor expressions are rejected.

## Optional language overrides

These twelve text fields also accept `_EN` and `_ZH_CN` suffixes (24 additional
optional variables): display name, About title, Android app/service labels,
Linux app label/generic name/comment, product description, slogan, installer
title/description and customization notice. Explicit localized text takes
precedence over base text; generated dependent text respects explicit overrides.
The Flutter UI follows its selected language. Native default resources prefer
English overrides, then base text; Android and Linux also emit Simplified Chinese
resources. Other languages retain upstream fallbacks where no custom text exists.
This does not replace the ordinary button/error translation system.

## Reserved image interfaces

Five further variables are reserved:

- `CUSTOM_LOGO_PATH`
- `CUSTOM_LOGO_LIGHT_PATH`
- `CUSTOM_LOGO_DARK_PATH`
- `CUSTOM_APP_ICON_PATH`
- `CUSTOM_TRAY_ICON_PATH`

Leave them unset. This phase never replaces or regenerates images. A nonempty
image value is rejected with an explicit reserved-interface error rather than
being silently ignored. Image loading/conversion can be implemented later.

There are **20 base + 24 language + 5 reserved image = 49 optional variable
interfaces**; no variable is mandatory.

## Build and installation boundaries

The patch provides UI hooks and a safe generated map; source preparation applies
the same frozen text to native labels/resources without changing critical
upstream recipes. Windows MSI display name/description are separated from
`Product`/executable naming and UpgradeCode generation. Android applicationId,
macOS bundle/product identity, Linux executable/package/service/URI/configuration
paths, image assets and signing identities remain unchanged. DEB metadata is
repacked before checksums, preserving package identity, dependencies, scripts and
payload; RPM display fields and MSI ARP links use escaped values.
The legacy Windows EXE installer's registry display/publisher strings and
shortcut/service names still follow upstream `app_name`; this patch does not
rewrite its command-script installer. Use the MSI for custom Windows package
display metadata. Original copyright/license attribution always remains.

Changes affect a **new build**, not an already installed client or uploaded
package. Existing completed-batch deduplication is intentionally unchanged:
changing Variables alone does not authorize overwriting or force-rebuilding a
completed release identity. A fresh eligible upstream/patch build applies the
new snapshot. Independent branding-aware release deduplication is outside this
patch. Do not claim that editing a Variable immediately refreshes a Release.

Validate defaults, representative overrides and escaping with
`python3 -m scripts.validation.branding_contract`, prepared-source contracts,
Flutter analysis and affected packaging/signing contracts. Native installers and
real-device display/upgrade behavior still require exact-package testing.

Wayland unattended DEBs apply public branding before their mandatory Standard/SOS
summary label. Their Description first line remains `RustDesk Wayland unattended
(STANDARD)` or `RustDesk Wayland unattended (SOS)` for independent variant validation;
other public metadata and payload remain subject to the existing branding rules.

### About version and build variant

Desktop and mobile About pages display the validated prepared-source identity.
A Stable build shows `<upstream>-custom.<patch-revision>` (for example,
`1.5.0-custom.v2.1`); CI/Nightly builds show `<upstream>-custom` without claiming
a Stable revision. The variant is `Standard` or `SOS`. The dedicated Wayland
unattended build adds ` + Wayland 无人值守` to that variant, after verifying the
same-run prepared source and before compilation. An ordinary Linux build on a
Wayland desktop does not receive this build-flavor label.

The generated Dart constants are bound to the native update identity and source
inventory. Packaging checks the expected ordinary/unattended display identity.
Package/protocol versions, native `mainGetVersion` and update ordering are
unchanged. Public branding Variables cannot override these identity fields.
Previously built clients retain their existing About text until updated.

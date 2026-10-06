# Phase 4 parallel execution update

Parallel preparation follows successful exact-source resolution, reviewed build interface and patchset selection:

- Rust/config preflight Standard and SOS run on separate Linux matrix runners.
- Default Bridge generation runs alongside Rust preflight.
- Windows x64 WindowInjection helper runs alongside both, once per run. CI quick checks skip this Windows helper.
- After Bridge generation, Flutter analyze Standard/SOS run in parallel, independently of Rust preflight completion.
- The outer reusable compatibility call must finish successfully before Prepared Source and client builds start.
- Standard/SOS client matrix remains parallel. Both consumers verify the shared helper's exact helper commit, upstream SHA, run, DLL SHA256 and AMD64 header before use.
- Paired artifact validation and Draft remain after both builds. Any critical job failure blocks client building or Draft creation at its downstream Gate.

This deliberately permits independent small preparation jobs to continue if another compatibility check fails, preserving diagnostics. It does not permit expensive client builds after failed compatibility. No secrets enter these preparation jobs; existing production compile configuration is unchanged.

Validation: 45 local unit/regression tests PASS. New Actions execution still requires observation. An already-started workflow uses its original commit and is not retroactively changed or cancelled by this update.

No runtime/UI validation, real remote session, signing, platform promotion, patch changes or old-repository writes. Stable remains Draft only; Nightly artifacts only.

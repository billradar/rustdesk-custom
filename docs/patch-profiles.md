# Patch Profiles and candidate isolation

`metadata/patch-profiles.json` is the routing policy. Numeric source version chooses a Profile; applicability, SHA, build success and patch hashes do not influence selection. Source identity remains separately locked to an exact upstream SHA.

| Source version | Profile | Patchset | Stable eligibility |
| --- | --- | --- | --- |
| Below 1.5.0 | legacy-pre-1.5 | v1 | Existing historical policy |
| 1.5.0 | rd-1.5.0 | v2.8 | Existing gates apply |
| 1.5.1 | rd-1.5.1 | v2.8 | Existing gates apply |
| 1.5.3 | rd-1.5.3 | v3.2 | Explicit formal-release admission; existing gates apply |
| Unadapted versions, including 1.5.2 | latest_maintained | currently v3.2 | Forbidden |

The historical 1.5.3 candidate commit `05b9f2d8919b5cdfaa0bb3280601a02881556a42` from compatibility run 42572512338 established the isolated v3.1 patch baseline; it was not a release tag. Official release `1.5.3` now points to `95cca3f661f635b3cc85c04935fe8d96d8f432ef`, and the separately audited formal `rd-1.5.3` Profile was admitted with those v3.1 patch bytes; current v3.2 changes only the RPM updater selector to match normalized public RPM names. The old `rd-1.5.3-candidate` registry entry remains Stable-forbidden. `latest_maintained` now names the formal Profile, but unknown-version fallback is still forbidden in Stable regardless of that Profile’s own eligibility. No 1.5.2 source snapshot or release is approved by this change. Unknown-version fallback means “try the latest maintained patchset and report compatibility”; it does not promise applicability or support.

The selection report records `profile`, `selected`, `fallback`, `compatibility_test_only` and `stable_allowed`. Exact candidate Profiles are test-only even though `fallback=false`. CI/Nightly may test them; adapter approvals and publication authorization remain independent. Stable rejects candidates/fallback even in dry-run, and rechecks policy at lock/preflight/content revision and client identity gates. Test success never updates registry policy. No build identity schema, hash algorithm for patch contents, signing permissions or publishing authorization is changed.

Common patches are applied in lexical order, with 0001 targeting the locked hbb_common submodule. Standard stops after Common 0006; SOS then applies SOS 0001–0003. Each patch must pass `git apply --check` before application. A failure stops immediately without trying an older profile. Source preparation validates that supplied patchset matches numeric source version and channel, preventing v3 from leaking into 1.5.1.

v3 exists to preserve isolation using existing vN patch/provenance interfaces. It derives from v2 revision 8 and only rebases Common 0004's chat-model visibility hooks. It preserves upstream `setWindowsCmWindowBounds`, monitor selection, physical-pixel scaling and `ignoreDevicePixelRatio: true`, plus non-Windows fallback branches. It does not restore the malformed intermediate patch from PR #247 history. From v3.2, Common 0005 also uses normalized RPM names. Other Common/SOS patch bytes remain identical to v2.8; v2 itself is unchanged.

## Validation

```sh
python3 -m scripts.upstream.patch_profiles_contract
python3 -m scripts.build.build_adapter_contract
python3 -m scripts.upstream.patchset_version verify --base origin/main
python3 scripts/validation/repository_contract.py
```

For each clean exact upstream snapshot, copy independent Standard/SOS trees, run `PATCHSET=v2` (1.5.1) or `PATCHSET=v3` (candidate) through `scripts/source/apply_patches.sh`, then `scripts.validation.compatibility.contracts`. Run the CM contract on prepared source; Dart policy execution requires Dart. Native build, generated bridge, Flutter analysis and real-session validation require their reviewed toolchains and remain distinct from structural checks.

The v3 top-level status is now `validation_pending`, consistent with the existing v1/v2 lifecycle marker: formal Profile admission is not evidence of full platform builds or runtime testing. Its original candidate baseline and revision-1 history/hashes remain recorded immutably; v3.2 advances only the current Common hash for RPM matching. New Profiles require reviewed metadata and exact fresh evidence before Stable eligibility can be enabled. Unknown native build interface signatures continue to block build execution; do not add signatures merely because patches apply.

Local source identities, test counts and limitations: [audit record](patch-profile-audit.md).

## Official 1.5.3 admission

The [formal admission audit](audits/stable-1.5.3-admission/review.json) binds official
Tag/release metadata to an exact clean source and hbb_common identity. Independent
Standard/SOS copies pass all patch checks, structural/CM/update/branding contracts,
native configuration-helper compilation and upstream DPI preservation. Existing
Windows/bridge, Windows ARM64, seven native interface approvals and both Standard
Wayland architecture preflights pass without adding or relaxing fingerprints.

The current Profile/lock/preflight/client-identity contracts accept v3.2 for formal
1.5.3. v2.8 remains assigned to 1.5.0/1.5.1; unknown versions and the historical
candidate entry remain Stable-forbidden. Formal admission itself did not change patch content. The later RPM selector
change allocates v3.2 without altering historical v3.1 identity. A fresh supported-target aggregate, production signatures
where required, attestation and publication checks remain mandatory. Native
packages, generated bridge, Flutter analysis, device upgrades, UI and real remote
sessions are not proven by these local admission checks.

Reproduce the formal-source checks using a clean official checkout with its
locked hbb_common submodule (Rust on PATH enables the native helper check):

```sh
PYTHONPATH=. python3 - <<'PYTHON'
import json
from pathlib import Path
from scripts.upstream.patch_profile_sources_contract import exercise
print(json.dumps(exercise(Path('/path/to/clean/1.5.3'), '1.5.3',
    '95cca3f661f635b3cc85c04935fe8d96d8f432ef', 'v3', 'stable'), indent=2))
PYTHON
```

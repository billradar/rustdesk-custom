# Build and validation

[English](build-and-validation.md) · [简体中文](build-and-validation-zh.md)

## Platform support

`metadata/platform/matrix.json` is the authoritative list of platforms, architectures, variants, runners, enabled targets, support states, and required targets. Reviewed upstream build parameters are recorded in `metadata/platform/adapter-profiles.json`.

- **SUPPORTED** means the target meets the repository's current build and artifact checks. It does not claim that every UI, remote session, or runtime scenario was tested.
- **EXPERIMENTAL** means the target can be included through an explicit or experimental build path; it is not automatically a required Stable target.
- **PLANNED** means activation requirements are not yet met.
- **BLOCKED / UNSUPPORTED / DISABLED** targets must not be presented as normally available.

## Build stages

1. `scripts/release/qualification.py` plans targets from the platform matrix.
2. `scripts/build/` invokes the platform toolchains.
3. `scripts/platform/` builds, packages, and collects sanitized diagnostics.
4. Artifact checks validate target, architecture, checksums, build information, source identity, and configuration.
5. Aggregation checks the required target set and confirms that artifacts share one source/build identity.
6. CI Qualification binds a successful result to the exact custom commit and upstream version for Stable workflows.

Build failures must remain visible and provide enough sanitized information to diagnose the first failing step.

## Validation layers

| Layer | What it checks |
| --- | --- |
| Repository contract | Structure, metadata, workflow boundaries, and required files |
| Upstream compatibility | Upstream definitions, patch application, and build interfaces |
| Prepared source | Commit SHA, patch identity, submodules, and clean source state |
| Target build | Compilation, platform configuration, and packaging |
| Artifact validation | ABI, package, checksum, build info, and provenance |
| Aggregation and qualification | Required targets and shared source identity |
| Stable release gate | Qualification for the exact custom commit and upstream version |

## Useful checks

~~~bash
python3 scripts/validation/repository_contract.py
python3 -m scripts.release.channel_contract
python3 -m scripts.release.qualification_contract
python3 -m scripts.release.production_contract
python3 -m scripts.build.config_mir_contract
python3 -m scripts.validation.native_config_contract
python3 -m scripts.signing.android_signing_contract
~~~

Check that a contract exists and inspect its CLI before running it. Do not invoke a release or signing entry point as a substitute for a contract.

## Interpreting results

- A successful job does not mean the entire workflow passed.
- A successful build does not mean aggregation or qualification passed.
- CI Qualification does not mean a Draft or public release exists.
- Android ABI build success does not validate production certificate compatibility or device upgrade behavior.
- Mark a check PASS only when it was actually run and succeeded.

## Reviewed upstream interfaces

The 1.5.1 development snapshot `1297da6d186e58d9096be24072ae3998cdbbf8fe` has reviewed critical signature `fead600e14fce31e0d4f16df77bf86ab2166f01f80464c59b0714c05f53c96f2`. Toolchains and the Windows helper pin match the reviewed 1.5.0 baseline; changes add tests, optional update metadata, a non-Flutter Sciter branch update, and an optional DRM dependency. This is an interface review, not proof of a successful build or runtime behavior. The separate unattended workflow remains bound to its own reviewed DRM policy.

The Windows ARM64 lane uses a native `windows-11-arm` runner, Flutter 3.44, and same-source ARM64 bridge. It validates the Dart, Flutter engine, Rust output, helper DLL, EXE, and MSI architecture. Tag and Nightly include it by default; ordinary CI remains x86_64-only. Runtime qualification is still required before calling it supported.

## Upstream test-key fixture

The prepared-source scanner permits only `libs/hbb_common/tests/data/websocket-key.pem` with the reviewed complete SHA-256 `95cf7a0a6890435c98bb3f644678d4fd20d80ff4a296d438a515802e233c6ec9`. This is a path-and-content-specific exception for an upstream test fixture. It does not exempt test directories, PEM files, other paths, or changed content. Production input and package scanners remain strict.

## Native platform recipe review

The current 1.5.1 adapter profile records reviewed native signatures for supported platform architectures and critical file hashes. The macOS profile includes conditional tests, deployment-target export, and optional upstream signing/update routing; custom macOS packages remain unsigned. Approval of a build recipe is not package or runtime validation. Unknown future files, tools, recipes, and disabled jobs remain blocked.

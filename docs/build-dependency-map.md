# Build dependency map

| Input/output | Sharing rule | Reason |
|---|---|---|
| Official source + recursive submodules | once per exact SHA | common immutable source identity |
| Patched Common baseline | once per selected patchset/hash | identical Standard/SOS customization |
| Standard/SOS source archive | separate artifacts | SOS UI delta must not contaminate Standard |
| Default FRB bridge | share at same exact SHA/profile | current patches do not modify flutter_ffi.rs bridge declarations; require file hash and bridge SHA checks |
| WindowInjection.dll | same helper commit + Windows arch | independent source, target-specific; never share across architectures |
| Rust/Flutter compiled app | never across variants/architectures | patched UI, environment configuration and native target matter |
| vcpkg packages | only same manifest/toolchain/triplet | caches accelerate, not trusted provenance |
| SBOM | per patched variant or final artifact | official unpatched SBOM is not ours |
| Native config probe | per final DLL | verifies actual packaged config, including password, without printing values |

Prepared source contains no production inputs. Configuration enters only platform compile jobs. Cargo/Flutter dependency caches are optional acceleration. Prepared source is a run-bound artifact and must be verified after download.

# Prototype dependency record

Recorded for the successful JDK 21 build on 2026-10-03.

## Runtime / explicitly activated dependency

There are no signing-backend runtime dependencies for the mock provider. The explicitly triggered read-only discovery utility has one pinned runtime dependency, XiPKI `ipkcs11wrapper` 1.0.9; it is not connected to the signing SPI.

| Artifact | Version | Scope | Source | SHA-256 |
|---|---:|---|---|---|
| `org.xipki:ipkcs11wrapper` | `1.0.9` | compile/runtime (explicit discovery only) | Maven Central | `b7deea6cde2f5f540f0bf612402d9db5adab13f4751f01f49d643c740b313f62` |

The artifact bundles `natives/unix/linux-aarch64/release/libpkcs11wrapper.so` (ELF AArch64), SHA-256 `ec55efcef1073a0387b4a6045bd14e9f2614dcc2e549b82c05134334e313e3b1`. XiPKI's POM identifies the IAIK PKCS#11 Wrapper License for the included IAIK component and Apache License 2.0 for the remaining code. The fixed release's native library hash matches the ARM64 native library in the source checkout inspected for the candidate survey. Maven Central metadata reports 1.0.9 as the latest/release; the candidate survey did not pin an exact artifact version.

The OpenSC PKCS#11 module is an operating-system package, not a Maven dependency. On the discovery host it is OpenSC 0.26.1-2 at `/usr/lib/aarch64-linux-gnu/opensc-pkcs11.so`.

## Test dependencies

| Artifact | Version | Scope | Source | SHA-256 |
|---|---:|---|---|---|
| `org.junit.jupiter:junit-jupiter` | `5.10.2` | test | Maven Central | `263e43447f4b40f126ad6b1dcbd7df379448413bdedb8e0d240c5bcbba7c7a4f` |
| `org.junit.jupiter:junit-jupiter-api` | `5.10.2` | test (transitive) | Maven Central | `afff77c186cd317275803872fa5133aa801fd6ac40bd91c78a6cf8009b4b17cc` |
| `org.junit.jupiter:junit-jupiter-engine` | `5.10.2` | test (transitive) | Maven Central | `b6df35da750a546ae932376f11b3c0df841f0c90c7cb2944cd39adb432886e4b` |
| `org.junit.jupiter:junit-jupiter-params` | `5.10.2` | test (transitive) | Maven Central | `edb1e43ff0b8067626ffb55e5e9eeca1d9ab2478141a7c7f253d115b29cc7cf2` |
| `org.junit.platform:junit-platform-commons` | `1.10.2` | test (transitive) | Maven Central | `b56a5ec000a479df4973b18bba24c98fe0db8faa14c8907d3ef451d8c71fd8ae` |
| `org.junit.platform:junit-platform-engine` | `1.10.2` | test (transitive) | Maven Central | `905cba9b4998ccc29d1239085a7fb1fe0e28024d7526152356d810edec0a49a3` |
| `org.opentest4j:opentest4j` | `1.3.0` | test (transitive) | Maven Central | `48e2df636cab6563ced64dcdff8abb2355627cb236ef0bf37598682ddf742f1b` |
| `org.apiguardian:apiguardian-api` | `1.1.2` | test (transitive) | Maven Central | `b509448ac506d607319f182537f0b35d71007582ec741832a1f111e5b5b70b38` |

## Build plugins

All declared lifecycle plugins are version-pinned in `pom.xml`: Maven Clean 3.2.0, Resources 3.3.1, Compiler 3.13.0, Surefire 3.2.5, and Dependency 3.8.1. Plugin dependencies belong to Maven's build tooling and are not project/runtime dependencies.

`mvn dependency:tree -Dverbose` completed successfully. It shows XiPKI 1.0.9 at compile/runtime scope and JUnit only at test scope. The default test lifecycle does not initialize the XiPKI module or access hardware; hardware requires the explicit `yubikey-discovery` profile.

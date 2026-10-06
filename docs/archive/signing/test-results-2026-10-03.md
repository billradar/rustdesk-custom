# RustDesk Android Signing Bridge — 完整测试报告

**执行时间：** 2026-10-03（Asia/Shanghai）  
**工作目录：** `tools/android-signing-bridge/`  
**仓库：** `/home/bill/rustdesk-custom` (`billradar/rustdesk-custom`)  
**构建平台：** Debian 13，`aarch64`  
**Java：** OpenJDK 21.0.12.1+1-1~deb13u1  
**Maven：** 3.9.9

## 总结果

| 项目 | 结果 |
|---|---|
| `mvn clean test` | **PASS** |
| 测试总数 | **30** |
| 失败 / 错误 / 跳过 | **0 / 0 / 0** |
| `mvn dependency:tree -Dscope=test` | **PASS** |
| Source/build validation | **PASS** (`mvn clean test`; `bash -n run-real-yubikey-once`) |
| 签名 bridge 静态安全搜索 | **PASS**：未找到 PIN/password 的 `String` 声明、环境变量读取、标准输出/日志、文件写入或子进程执行代码 |

最新构建由 Maven Compiler Plugin 3.13.0 使用 `javac --release 21` 编译 15 个主源文件和 10 个测试源文件；Surefire 3.2.5 执行 JUnit 5 测试。所有声明的 Maven build plugin 及测试依赖均有固定版本，依赖及已下载 artifact SHA-256 见 [DEPENDENCIES.md](DEPENDENCIES.md)。

## 逐测试类结果

| 测试类 | 测试数 | 失败 | 错误 | 跳过 | 覆盖内容 |
|---|---:|---:|---:|---:|---|
| `EcdsaEncodingTest` | 5 | 0 | 0 | 0 | 普通 r/s；r/s 高位需正数 `00` 前缀；前导零处理；r/s 为零；非法 raw 长度与畸形 DER；P-256 64 字节 raw 和 DER 长度 |
| `AdaptiveSigningFlowTest` | 8 | 0 | 0 | 0 | certificate fingerprint 唯一匹配；证书 CKA_ID 选择对应私钥且不回退；P-256/P-384/P-521 component sizing；`CKA_ALWAYS_AUTHENTICATE` 条件路由；identity mismatch 不请求 PIN；0/多 key fail-closed；登录失败不重试或签名 |
| `LoginFailureTest` | 2 | 0 | 0 | 0 | `CKU_USER` 或 context login 失败后立即停止；不调用 `C_Sign`；关闭 session；清零 PIN |
| `PinZeroizationTest` | 3 | 0 | 0 | 0 | 签名异常和 context login runtime 异常时清零；确认 key 与 SPI 无 PIN 数组字段 |
| `ProviderTest` | 3 | 0 | 0 | 0 | Provider 注册 apksig 使用的 `SHA256withECDSA` 与 `SHA512withECDSA`；按 provider 名称和无 provider 参数的默认 JCA 查询选择；临时插入后恢复 Provider 列表；production token/object/fingerprint 常量 |
| `SignatureFlowTest` | 5 | 0 | 0 | 0 | SHA-256/SHA-512、单段/多段 update、P-256/P-384 ECDSA mock signing 与软件公钥验签；确认 opaque key 的 `getEncoded()` 和 `getFormat()` 均为 null |
| `WrongKeyTest` | 3 | 0 | 0 | 0 | 拒绝软件 EC key、RSA key、错误 token、错误对象 ID、错误证书指纹；后端身份不匹配时不请求 PIN、不登录、不签名 |

## 已验证行为

- **Provider / service：PASS (mock)。** Provider 暴露 apksig 对 P-384 signer 实际选择的 `SHA256withECDSA` 与 `SHA512withECDSA`；通过指定名称和临时插入首位的默认 JCA 查找验证服务选择，测试后恢复 provider 列表。
- **Hashing：PASS (mock)。** SPI 对 SHA-256 与 SHA-512 算法分别只哈希一次，再把 32-byte 或 64-byte digest 传给 mock `CKM_ECDSA`；产生的 DER 签名由匹配的软件公钥验签成功。
- **调用顺序：PASS (mock)。** 正常路径记录 `OPEN → USER_LOGIN → KEY_DISCOVERY → SIGN_INIT → CONTEXT_LOGIN → SIGN → CLOSE`。真实运行使用 process-scoped session，在一次 `CKU_USER` 后对每个 `C_SignInit` 执行 context-specific login。
- **Fail-closed：PASS。** 登录失败后不重试、不调用 sign。身份 guard 发现后端 token/certificate identity 不符时，在 PIN supplier 被调用前拒绝操作。
- **PIN 清零：PASS。** 测试传入可保留引用的假 `char[]`，验证成功路径、登录失败和签名/运行时异常路径均被清零。SPI 和 key 均不保存 PIN 数组字段。
- **ECDSA 格式：PASS。** PKCS#11 raw `r || s` 转换为 Java 要求的 ASN.1 DER `SEQUENCE(INTEGER r, INTEGER s)`；测试覆盖正数编码、零值、长度及往返转换；最终签名经实际 JCA 软件验签通过。
- **身份匹配：PASS（mock 范围）。** Existing `SigningIdentity` provider prototype 核对 mock token/object/fingerprint；adaptive flow 以唯一 production certificate fingerprint 为 trust anchor，再使用证书 CKA_ID 选择私钥。identity mismatch 时不调用 PIN supplier。
- **Adaptive/JCA hardware preflight：PASS（真实硬件只读）。** 以 `github-runner` 加载 OpenSC/XiPKI，动态发现唯一匹配的 production certificate，得到 CKA_ID `02`、P-384 公钥、48-byte EC component size；没有枚举私钥或提示 PIN。
- **apksig 调用轨迹：PASS (instrumented mock)。** 对选定 APK 实际执行本机 apksig 0.9，minSdk 22，保持输入 APK 已有的 scheme profile：v1/v2 enabled，v3/v3.1/v4 disabled。合并运行记录到两个签名事件：SPI #2 `SHA256withECDSA` (`initSign`; update 1 次/52,910 bytes; sign 1 次，对应 v1)；SPI #4 `SHA512withECDSA` (`initSign`; update 1 次/576 bytes; sign 1 次，对应 v2)。独立 scheme 运行分别关联了 v1 与 v2；每个实际 `sign()` 对应一个硬件签名操作。因此 `EXPECTED APKSIG JCA SIGNATURE COUNT=2`、`EXPECTED HARDWARE SIGNATURE COUNT=2`。mock APK 独立验证 v1/v2 true、v3/v3.1/v4 false。未调用 YubiKey。
- **Real JCA hardware signature：PASS (user-provided real-terminal result)。** 用户报告 production certificate/CKA_ID 02 匹配；`RustDeskSigning` 的 `SHA256withECDSA` 调用一次硬件签名，通过公钥验证；`CKU_USER` 与 `CKU_CONTEXT_SPECIFIC` 均 PASS，PIN 清零、session/module 清理 PASS。Codex 没有重复硬件测试，也没有接触 PIN。
- **真实 apksig APK signing（layer A）：PASS (user-provided result in key9.md)。** Run `36902005326` 已由用户报告真实完成两次硬件签名、原输入哈希不变、PIN 清零，并由 apksigner 验证 v1/v2 与 production certificate。Codex 本轮没有重跑。

## 真实 APK 验证：Phase 5.1

Run `36902005326` 的真实 apksig/YubiKey 签名证据同时用于 layer A（Bridge integration）与 layer B（production signing identity）。依 key10.md 修订后的候选策略，同一可信 APK 可以覆盖两个验证目标；这只是对既有结果重新分类，没有重复签名。输入 SHA-256 为 `596591B25C4910D7E17FBD2EC499DC2592B06256965F6C50A885B538F6E81325`；真实操作数预期/实际均为 2，v1/v2 验证通过，最终单一签名者 SHA-256 精确匹配 production identity `559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`，输入未改变、私钥未导出、PIN 清零通过。此轮另对已有签名 APK 执行了只读 `apksigner verify`，结果 PASS。详细来源、artifact 和证据见 [PHASE5-1-LOCAL-VALIDATION-REPORT.md](phase5.1-local-validation.md)。

## 安全与范围边界

- mock tests 不加载硬件；另有独立无 PIN preflight 加载 OpenSC PKCS#11 module，并只枚举 token 与公开 certificate。用户之后提供了真实终端执行 adaptive hardware one-shot 的结果。
- 用户先前在真实终端输入 PIN 一次完成 JCA one-shot。用户提供的结果未包含 PIN 值；Codex 未接收或记录 PIN；终端报告 PIN zeroization PASS。
- 用户提供的真实终端结果报告：JCA provider 使用 `CKU_CONTEXT_SPECIFIC` 对 YubiKey PIV 9C 私钥成功签名一次，并通过证书公钥验签；私钥未导出。
- Codex 本轮没有运行 `apksigner sign`，没有签 APK。用户提供的既有 layer-A 结果报告真实 APK signing 与独立验证 PASS。
- 没有修改 `.github/workflows/`、GitHub Secrets、YubiKey 或系统 OpenSC 配置。
- 没有 commit、push 或 release。Git 工作树新增内容限于独立 `tools/android-signing-bridge/` prototype 目录；workflow 没有改动。
- Android hardware signing bridge：**VALIDATED**。Production signing identity：**VALIDATED**。APK production signing：**LOCALLY VALIDATED**。Phase 5.1：**PASS**，依据 Run `36902005326` 的既有真实结果；本轮未重复硬件操作。Git tag / Android release asset 不可用；release publishing、GitHub Actions automated hardware signing、upgrade installation compatibility 均 **NOT VALIDATED**。

## 记录的验证状态

```text
BUILD: PASS
TESTS: PASS (30 run, 0 failures, 0 errors, 0 skipped)
PROVIDER LOAD: PASS
SHA256withECDSA SERVICE: PASS
HASH EXACTLY ONCE: PASS (mock semantics)
CALL ORDER: PASS (mock)
FAIL-CLOSED LOGIN: PASS (mock)
LOGIN RETRY COUNT: PASS (one attempt)
PIN ZEROIZATION: PASS (test buffers)
PIN STORED IN PRIVATE KEY: NO
PIN STORED IN SIGNATURE SPI: NO
RAW ECDSA TO DER: PASS
SOFTWARE PUBLIC-KEY VERIFY: PASS
WRONG KEY REJECTION: PASS
IDENTITY GUARD DESIGN: PASS (mock only)
REAL OPENSC LOADED: PASS (read-only preflight)
REAL CERTIFICATE DISCOVERY: PASS (fingerprint-pinned, exactly one match)
REAL YUBIKEY ADAPTIVE ECDSA: PASS (user-supplied real-terminal result)
PIN INPUT COUNT: 1 (user entered in real terminal; PIN value not received or recorded by Codex)
CKU_USER: PASS
PRIVATE KEY DISCOVERY AFTER LOGIN: PASS (exactly one; ID 02, EC, label SIGN key)
CKA_ALWAYS_AUTHENTICATE: TRUE
C_SignInit: PASS
CKU_CONTEXT_SPECIFIC: PASS
C_Sign: PASS
RAW ECDSA TO DER: PASS (terminal reported RAW?DER: PASS)
CERTIFICATE PUBLIC-KEY VERIFY: PASS
PIN ZEROIZATION: PASS
SESSION CLOSE: PASS
MODULE FINALIZE: PASS
PRIVATE KEY EXPORTED: NO
YUBIKEY MODIFIED: NO
REAL JCA HARDWARE SIGNATURE: PASS (user-provided terminal output; not rerun)
APKSIG MOCK SIGNATURE COUNT: PASS (candidate-preserving profile: v1=1, v2=1, v3=0, v3.1=0, v4=0; total=2)
APKSIG EXPECTED SIGNATURE ALGORITHMS: v1 SHA256withECDSA; v2 SHA512withECDSA
EXPECTED APKSIG JCA SIGNATURE COUNT: 2
EXPECTED HARDWARE SIGNATURE COUNT: 2
EACH HARDWARE OPERATION: C_SignInit -> CKU_CONTEXT_SPECIFIC -> C_Sign
PROCESS PIN INPUT COUNT: 1; mutable process buffer with disposable per-operation copies; cleared at process end
APK SCHEME PROFILE SOURCE: preserved from candidate original verification (v1/v2 true; v3/v3.1/v4 false)
V3.1 ENABLED: NO (no lineage/rotation configuration)
REAL APK SIGNED (LAYER A): YES (user-reported; Run 36902005326)
SAME APK ACCEPTED FOR LAYER B: YES (per revised key10.md policy; no repeat signing)
PRODUCTION SIGNING IDENTITY: VALIDATED
APK PRODUCTION SIGNING: LOCALLY VALIDATED
PHASE 5.1: PASS
GIT TAG: NOT AVAILABLE
ANDROID RELEASE ASSET: NOT AVAILABLE
RELEASE PUBLISHING: NOT VALIDATED
ACTIONS AUTOMATED HARDWARE SIGNING: NOT VALIDATED
UPGRADE INSTALLATION COMPATIBILITY: NOT VALIDATED
WORKFLOW MODIFIED: NO
COMMIT: NO
PUSH: NO
```

## 当前状态

**Phase 5.1: PASS.** Run `36902005326` 的真实 hardware apksig 结果同时满足 Bridge integration 与 production signing identity 两层验证。依据 key10.md，不要求另一个 tag/release candidate，也没有重做签名。APK production signing 为 **LOCALLY VALIDATED**；release publishing、GitHub Actions 自动硬件签名和 upgrade installation compatibility 仍为 **NOT VALIDATED**。完整证据见 [PHASE5-1-LOCAL-VALIDATION-REPORT.md](PHASE5-1-LOCAL-VALIDATION-REPORT.md)。

## Phase 5.1 artifact and release status

只读查询确认 Run `36902005326` 是成功的 Stable workflow run，提供 Standard Android aarch64 APK artifact `11186832321`。远端没有 Git tag；现有 draft release 没有 Android APK asset。按 key10.md，这些事实不阻止对 APK production signing identity 的 Phase 5.1 验证：Run `36902005326` 已同时作为 layer A 与 layer B 的证据来源。

```text
PHASE 5.1: PASS
SOURCE RUN: 36902005326
SOURCE TYPE: SUCCESSFUL STABLE WORKFLOW ARTIFACT
INPUT APK SHA256: 596591B25C4910D7E17FBD2EC499DC2592B06256965F6C50A885B538F6E81325
REAL YUBIKEY ECDSA: PASS (prior user-provided terminal result)
REAL JCA YUBIKEY SIGNATURE: PASS (prior user-provided terminal result)
REAL APKSIG YUBIKEY APK SIGNING: PASS (prior user-provided terminal result)
PRODUCTION CERTIFICATE IDENTITY: PASS
FINAL APK CERTIFICATE IDENTITY: PASS (read-only verify this turn)
INPUT IMMUTABILITY: PASS
PRIVATE KEY EXPORTED: NO
PIN ZEROIZATION: PASS
HARDWARE OPERATION COUNT: PASS (2 expected / 2 actual)
ANDROID HARDWARE SIGNING BRIDGE: VALIDATED
PRODUCTION SIGNING IDENTITY: VALIDATED
APK PRODUCTION SIGNING: LOCALLY VALIDATED
GIT TAG: NOT AVAILABLE
ANDROID RELEASE ASSET: NOT AVAILABLE
RELEASE PUBLISHING: NOT VALIDATED
ACTIONS AUTOMATED HARDWARE SIGNING: NOT VALIDATED
UPGRADE INSTALLATION COMPATIBILITY: NOT VALIDATED
PIN USED THIS ROUND: NO
PRIVATE KEY OPERATION THIS ROUND: NO
YUBIKEY MODIFIED: NO
WORKFLOW MODIFIED: NO
RELEASE MODIFIED: NO
COMMIT / PUSH: NO
```

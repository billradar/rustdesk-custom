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
| 测试总数 | **26** |
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
| `LoginFailureTest` | 1 | 0 | 0 | 0 | `CKR_PIN_INCORRECT` 后立即失败；context login 次数为 1；没有调用 sign；关闭 session；清零 PIN |
| `PinZeroizationTest` | 3 | 0 | 0 | 0 | 签名异常和 context login runtime 异常时清零；确认 key 与 SPI 无 PIN 数组字段 |
| `ProviderTest` | 3 | 0 | 0 | 0 | Provider 只注册 `SHA256withECDSA`；按 provider 名称和无 provider 参数的默认 JCA 查询选择；临时插入后恢复 Provider 列表；production token/object/fingerprint 常量 |
| `SignatureFlowTest` | 2 | 0 | 0 | 0 | mock 完成 ECDSA 签名与软件公钥验签；确认 opaque key 的 `getEncoded()` 和 `getFormat()` 均为 null |
| `WrongKeyTest` | 3 | 0 | 0 | 0 | 拒绝软件 EC key、RSA key、错误 token、错误对象 ID、错误证书指纹；后端身份不匹配时不请求 PIN、不登录、不签名 |

## 已验证行为

- **Provider / service：PASS。** 通过 JCA Provider 名称取得 `SHA256withECDSA` 服务；临时将 Provider 插入首位时，未指定 provider 的 JCA 查找选中该 Provider，测试后恢复原 provider 列表。
- **Hashing：PASS。** SPI 使用 Java SHA-256 产生 32-byte digest，并传给 mock `CKM_ECDSA`。mock 使用 `NONEwithECDSA` 对 digest 签名，生成的 DER 签名再由公钥对原始消息执行 `SHA256withECDSA` 验证成功，覆盖了一次 SHA-256 的语义。
- **调用顺序：PASS。** 正常路径 mock 记录 `OPEN → SIGN_INIT → CONTEXT_LOGIN → SIGN → CLOSE`，对应 `C_SignInit → C_Login(CKU_CONTEXT_SPECIFIC) → C_Sign`。
- **Fail-closed：PASS。** 登录失败后不重试、不调用 sign。身份 guard 发现后端 token/certificate identity 不符时，在 PIN supplier 被调用前拒绝操作。
- **PIN 清零：PASS。** 测试传入可保留引用的假 `char[]`，验证成功路径、登录失败和签名/运行时异常路径均被清零。SPI 和 key 均不保存 PIN 数组字段。
- **ECDSA 格式：PASS。** PKCS#11 raw `r || s` 转换为 Java 要求的 ASN.1 DER `SEQUENCE(INTEGER r, INTEGER s)`；测试覆盖正数编码、零值、长度及往返转换；最终签名经实际 JCA 软件验签通过。
- **身份匹配：PASS（mock 范围）。** Existing `SigningIdentity` provider prototype 核对 mock token/object/fingerprint；adaptive flow 以唯一 production certificate fingerprint 为 trust anchor，再使用证书 CKA_ID 选择私钥。identity mismatch 时不调用 PIN supplier。
- **Adaptive hardware preflight：PASS（真实硬件只读）。** 以 `github-runner` 加载 OpenSC/XiPKI，动态发现 token 与唯一匹配的 production certificate，得到 CKA_ID `02`、EC 公钥、48-byte EC component size；preflight 没有枚举私钥或提示 PIN。

## 安全与范围边界

- mock tests 不加载硬件；另有独立无 PIN preflight 加载 OpenSC PKCS#11 module，并只枚举 token 与公开 certificate。用户之后提供了真实终端执行 adaptive hardware one-shot 的结果。
- 用户在真实终端输入 PIN 一次。输出未包含 PIN 值，Codex 未接收或记录 PIN；终端报告 PIN zeroization PASS。
- 用户提供的真实终端结果报告：使用 `CKU_CONTEXT_SPECIFIC` 对 YubiKey PIV 9C 私钥成功签名一次，并通过证书公钥验签；私钥未导出。
- 没有运行 `apksigner sign`，没有签 APK。
- 没有修改 `.github/workflows/`、GitHub Secrets、YubiKey 或系统 OpenSC 配置。
- 没有 commit、push 或 release。Git 工作树新增内容限于独立 `tools/android-signing-bridge/` prototype 目录；workflow 没有改动。
- Android APK signing 仍为 **NOT VALIDATED**。真实硬件 ECDSA 操作已验证，但没有签署 APK。

## 记录的验证状态

```text
BUILD: PASS
TESTS: PASS (26 run, 0 failures, 0 errors, 0 skipped)
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
APK SIGNED: NO
WORKFLOW MODIFIED: NO
COMMIT: NO
PUSH: NO
```

## 当前状态

**REAL YUBIKEY ADAPTIVE ECDSA VALIDATION: PASS**。详见 [REAL-YUBIKEY-ECDSA-RESULTS.md](REAL-YUBIKEY-ECDSA-RESULTS.md)。

**APK PRODUCTION SIGNING: NOT VALIDATED**。没有签署 APK；也没有修改 workflow、commit 或 push。**LEGACY ANDROID SIGNING IDENTITY: NOT RECOVERED / NOT VALIDATED**。

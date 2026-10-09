# Android 生产签名：原理与操作步骤

## 1. 目标与安全边界

Android Standard 的生产签名由专用硬件签名路径处理，与普通 CI 的编译和打包分离。普通 CI 不应访问生产签名 Environment、YubiKey、PKCS#11 设备或生产 PIN。

生产签名流程必须由明确授权的 Stable Workflow 触发，并满足工作流中的仓库、分支、事件、构建成功和资格验证条件。仅有构建成功不能触发生产签名。

## 2. 当前记录的身份

机器可读身份记录位于 `metadata/signing/android-standard.json`。当前文件记录：

- Android 包名：`com.carriez.flutter_hbb`
- 生产硬件身份：YubiKey PIV slot `9C`
- PKCS#11 object ID：`02`
- 生产证书 SHA-256：`559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5`

**重要：生产证书与记录中的 legacy 证书指纹不同。** 当前元数据将 legacy Android 签名身份标记为未恢复/未验证，升级兼容性也不能据此推断为通过。除非专门验证并更新证据，否则不能宣称新身份可无缝覆盖安装旧签名 APK。

## 3. 执行结构

1. 普通 Android build Job 生成待签名产物。
2. 独立的 `android-sign` Job 只在工作流定义的受限条件下运行。
3. Job 使用专用 self-hosted ARM64 Runner 标签组：`self-hosted`、`linux`、`arm64`、`rustdesk-signing`、`android-signing`、`yubikey`。
4. Job 进入 GitHub Environment：`android-production-signing`。
5. Environment Secret `YUBIKEY_PIV_PIN` 只注入需要它的预检/签名步骤，不应打印或传递给普通构建。
6. 签名辅助逻辑校验输入产物来源、包名、ABI、身份指纹和签名结果；任何不匹配都应失败关闭。
7. 签名完成后，结果进入后续聚合验证，不应绕过最终产物验证。

专用 Runner、Environment 和 PIN 的真实配置状态应在 GitHub 设置中核实；文档只能说明仓库要求，不能代替在线配置检查。

## 4. 操作前检查清单

- [ ] 确认正在运行的是仓库官方 Stable Release Pipeline，而不是普通 CI 或 Nightly。
- [ ] 确认目标自定义提交和上游 SHA 已通过对应资格验证。
- [ ] 确认工作流输入明确授权当前生产签名操作。
- [ ] 确认专用 Runner 在线且是预期的可信设备。
- [ ] 确认 Environment 审批和 Secret 配置符合仓库策略。
- [ ] 确认公开身份元数据中的证书指纹、slot 和 object ID 与真实硬件一致。
- [ ] 确认签名产物来源、ABI、包名和校验和可追溯。

## 5. 执行步骤

1. 在 GitHub Actions 中打开 Stable Release Pipeline。
2. 先核对当前分支、提交 SHA、上游版本和 release mode；生产签名只允许工作流实际定义的受限上下文执行。
3. 使用 dry-run 验证非破坏性的发布门禁；dry-run 不会替代真实硬件签名验证。
4. 只有所有资格、Runner、Environment 和授权条件满足时，才执行被明确授权的生产流程。
5. 检查签名 Job 的结果、证书指纹验证、产物上传和最终聚合结果。
6. 保存运行链接和非敏感验证摘要；不要保存 PIN 或可用于重放签名的敏感材料。

## 6. 安全禁止事项

- 不得将 `YUBIKEY_PIV_PIN` 放入仓库文件、命令行参数、日志、PR 评论或文档。
- 不得把生产 Secret 暴露给普通 build、Nightly 或不受信任的 PR。
- 不得使用软件密钥替代硬件身份以绕过失败门禁。
- 不得在身份、来源或 Runner 有疑问时继续签名。
- 不得将“签名工具可用”或“签名 Job 通过”直接等同于旧版本升级兼容性已验证。


## 3.1 签名原理：从私钥到可验证 APK

### 核心概念

APK 签名不是对文件名或版本号盖章，而是用签名私钥对 APK 内容的完整性摘要及签名数据执行密码学签名，并把签名数据和证书写入 APK。Android 安装器据此验证内容是否被修改，以及签名者身份是否符合应用更新规则。

本仓库的生产签名路径记录为：

- **密钥载体**：YubiKey 硬件令牌；签名私钥应留在硬件内部。
- **PIV 槽位**：`9C`。
- **PKCS#11 对象 ID**：`02`。
- **密钥类型**：椭圆曲线 EC，曲线 `secp384r1`。
- **身份校验**：签名后证书 SHA-256 必须等于工作流/脚本中配置的预期指纹。
- **签名工具接口**：当前脚本调用 Runner 上安装的 `/usr/local/bin/rustdesk-sign`，并使用 `--pin-source env` 从进程环境读取 PIN。

仓库脚本调用的是本机签名工具接口。签名工具内部的 PKCS#11 provider、设备连接方式和驱动配置属于专用 Runner 的部署配置；不能仅从 Python 调用处推断其所有内部实现细节。

### 一次签名的密码学步骤

1. **准备待签名 APK**：上游源码经过补丁、构建和打包后形成 APK；此时它是测试签名产物，不是生产签名产物。
2. **计算受保护内容的摘要**：APK 签名工具按所用 Android 签名方案计算 APK 内容摘要。v2/v3 会保护 APK 的关键内容和 ZIP 元数据，签名块本身按方案定义处理。
3. **请求硬件签名**：签名工具通过硬件/PKCS#11 接口请求 YubiKey 使用 PIV `9C` 对相应签名数据签名。正常设计下，私钥不导出到 Runner 文件系统；PIN 用于令牌访问授权，不是签名私钥本身。
4. **组装签名块**：工具把签名结果、证书和必要的签名元数据写入 APK。
5. **验证签名**：使用 `apksigner verify` 检查 APK 签名方案和签名完整性，再读取签名证书指纹。
6. **核对身份与产物**：只有证书指纹与预期身份完全匹配，且包名、ABI、来源信息均匹配时，才把产物标记为生产签名并输出验证回执。

### v1、v2、v3 的区别

| 方案 | 主要机制 | 本项目脚本中的判定 |
| --- | --- | --- |
| v1（JAR 签名） | 对 APK 中的条目进行 JAR 签名；旧版 Android 兼容性相关 | 当前生产签名脚本要求至少验证到 v2 或 v3，并未把 v1 单独视为足够 |
| v2 | 将签名数据放入 APK Signing Block，并验证受保护 APK 内容的完整性 | 满足当前脚本的最低生产签名方案门槛 |
| v3 | 在 v2 基础上增加 SDK 范围等信息，并定义签名密钥轮换证明结构 | 满足当前脚本的最低生产签名方案门槛；存在 v3 签名本身不代表已完成旧密钥轮换授权 |

签名方案的支持情况与目标设备 Android 版本有关。当前脚本验证签名工具报告的 v2/v3 结果，但没有据此证明所有目标 Android 版本上的安装、覆盖升级或密钥轮换都已经通过实机测试。

参考：Android Open Source Project 的 [APK 签名概述](https://source.android.google.cn/docs/security/features/apksigning?hl=en)、[v2 方案](https://source.android.google.cn/docs/security/features/apksigning/v2?hl=en)和 [v3 方案](https://source.android.google.cn/docs/security/features/apksigning/v3?hl=en)。

## 3.2 生产签名端到端流程

~~~text
Stable Release Pipeline（显式 workflow_dispatch）
          │
          ├─ 解析上游 Stable ref → 固定 upstream SHA
          ├─ 检查 revision / draft preflight
          ├─ 验证相同 custom SHA + upstream SHA 的 CI Qualification
          ├─ 准备 Standard / SOS 源码
          └─ 构建 Android Standard 三种 ABI
                     │
                     ▼
             android-build artifacts
             （测试签名，非生产签名）
                     │
                     ▼
          独立 android-sign Job 门禁
          ├─ 仓库、分支、事件条件
          ├─ 前置资格和构建结果成功
          ├─ 专用 ARM64 self-hosted Runner
          ├─ android-production-signing Environment
          └─ Environment Secret PIN 可用
                     │
                     ▼
             下载并验证输入产物
          ├─ SHA256SUMS
          ├─ build-info / source-manifest
          ├─ custom SHA / upstream SHA / patchset / run ID
          ├─ APK 原始签名有效
          ├─ package name
          └─ APK ABI 与已验证 native library 一致
                     │
                     ▼
        rustdesk-sign → YubiKey PIV 9C
                     │
                     ▼
             验证生产签名 APK
          ├─ apksigner verify
          ├─ 证书 SHA-256 指纹完全匹配
          ├─ v2 或 v3 至少一种验证成功
          ├─ 包名与 ABI 再次核对
          ├─ 生成 android-signing-verification.json
          ├─ 更新 build-info.json / SHA256SUMS
          └─ 上传生产签名产物
                     │
                     ▼
          Stable 最终聚合与发布门禁
                     │
              Dry-run / Draft / Release
~~~

这条链路的关键是：**生产签名不是重新编译，也不是只对 APK 做一次命令调用；它是在验证构建来源后，对确定的 APK 执行硬件签名，再验证签名身份并形成可追溯回执。**

## 3.3 输入产物为什么要在签名前检查

签名会为输入内容建立可信签名，因此必须先验证“正在签什么”。当前 `scripts/signing/android_yubikey_sign.py` 对每个 ABI 执行以下检查：

1. 输入目录中恰好存在一个 `build-info.json`，且其路径没有逃逸到产物根目录之外。
2. 下载产物中不允许出现符号链接；必需文件 `SHA256SUMS`、`source-manifest.json` 和验证用的 `librustdesk.so` 必须存在。
3. `sha256sum -c SHA256SUMS` 成功。
4. `build-info.json` 中的平台、变体、架构、包类型、状态、仓库、custom SHA、upstream SHA、上游版本、patchset、run ID 必须与当前签名工作流输入一致。
5. `source-manifest.json` 与 build-info 的来源身份必须一致，准备源码身份哈希也必须匹配。
6. 每种架构恰好一个输入 APK；原始 APK 的签名必须可验证。
7. Android 包名必须是 `com.carriez.flutter_hbb`。
8. APK 中对应 ABI 的 `lib/<abi>/librustdesk.so` 必须与产物内已验证的 native library 完全相同。

任一条件失败，都应停止该签名任务；不能通过忽略来源不匹配、重新命名文件或手工改写 manifest 继续签名。

## 3.4 签名后验证与回执

签名完成后，脚本再次执行验证，而不是假定签名工具返回成功就代表产物可信：

- `apksigner verify --verbose --print-certs` 必须成功；
- 证书 SHA-256 必须与预期生产指纹完全相同；
- 必须至少有一个 v2/v3 签名方案验证成功；
- 包名和 ABI 再次核对；
- `build-info.json` 更新为 `PRODUCTION SIGNED / IDENTITY VERIFIED`，并记录签名身份、方案和运行 ID；
- `android-signing-verification.json` 记录证书匹配结果、包名、版本、ABI、APK SHA-256、签名方案、PIV slot、PKCS#11 ID 和运行身份；
- 重新生成 `SHA256SUMS`，使签名后的文件和验证回执也纳入校验清单；
- 最后上传各架构的生产签名产物，并清理工作区和 Runner 临时目录。

验证回执用于审计，不是私钥，也不能代替对 APK 本身的签名验证。

## 3.5 应用更新兼容性是另一道独立门槛

Android 包名相同，并不意味着不同签名证书的 APK 可以直接覆盖安装。通常应用更新需要签名身份兼容；v3 的 proof-of-rotation 只有在正确建立并验证密钥轮换证明时，才可能支持相应的轮换场景。

本仓库元数据记录的 legacy 证书指纹与当前 YubiKey 生产证书指纹不同，并将 legacy 签名身份标记为未恢复/未验证。因此：

- 当前生产签名流程验证的是**新生产身份的签名正确性**；
- 它不证明新 APK 能覆盖安装由 legacy 证书签名的已安装应用；
- 不能只因为签名使用 v3 就宣称密钥轮换已完成；
- 如需保持旧版应用的无缝升级，必须先解决旧签名身份/轮换链的可验证性，再通过真实设备上的覆盖升级测试。

在身份迁移问题解决之前，不应把新证书的 APK 当作旧签名 APK 的可直接升级替代品。

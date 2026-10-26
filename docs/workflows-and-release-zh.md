# 工作流与发布流程

[English](workflows-and-release.md) · [简体中文](workflows-and-release-zh.md)

## 1. 工作流职责

| Workflow | 主要职责 |
| --- | --- |
| `.github/workflows/ci.yml` | 对 PR、push 和手动运行进行变更分类；文档专属变更走轻量路径，功能变更进入来源解析、兼容性和资格验证 |
| `.github/workflows/compat-check.yml` | 可复用的上游来源、补丁集、架构契约和兼容性检查流程 |
| `.github/workflows/prepare-source.yml` | 准备带有明确来源身份的 Standard / SOS 源码 |
| `.github/workflows/build.yml` / `build-platform.yml` | 规划构建目标、执行平台构建并传递产物身份 |
| `.github/workflows/build-stable-windows.yml` | Stable Windows 构建入口 |
| `.github/workflows/build-stable-platforms.yml` | Stable Linux / macOS 等平台构建入口 |
| `.github/workflows/build-stable-android.yml` | Stable Android 构建入口；生产签名在独立的受保护 Job 中执行 |
| `.github/workflows/tag.yml` | Stable 解析、revision 预检、构建、产物聚合、Android 生产签名门禁及 Dry-run / Draft / Release 决策 |
| `.github/workflows/upstream-stable.yml` | 定期发现官方 Stable Release，并将最新版本路由到已签名的私有 Draft 构建 |
| `.github/workflows/upstream-main-compatibility.yml` | 定期验证官方上游默认分支的兼容性；不构建或发布 Nightly 产物 |
| `.github/workflows/android-yubikey-signing-test.yml` | 需要手动触发并明确授权的 YubiKey 签名冒烟测试，不发布或提升 Release |

本表用于导航。触发器、输入、权限、条件、Job 依赖和发布语义均以当前工作流文件为准。不要引用仓库中不存在的旧工作流名。

新 Pull Request 使用 [PR 模板](../.github/PULL_REQUEST_TEMPLATE.md)，按实际情况填写背景、变更、验证、影响范围和风险/回滚信息。

## 2. 普通 CI

Pull Request、受支持的 push 或手动触发首先进行变更分类：

- 所有变更均明确属于文档时，执行轻量文档验证，不运行无关的完整构建、资格验证、生产签名或发布。
- 任何功能或有歧义的变更都进入功能性验证。
- `force_rebuild` 是 `ci.yml` 的输入，用于请求完整功能性路径；不能据此推断 Stable 工作流也有同名输入。
- 不得通过忽略错误、放宽契约或错误设置路径过滤，让必需检查变成永久 Pending。

## 3. 上游兼容性检查

`upstream-main-compatibility.yml` 定期解析官方 `rustdesk/rustdesk` 默认分支的当前提交 SHA，并运行兼容性检查。它只提供持续兼容性信号，不触发 Nightly 构建、不生成开发版发布，也不能替代 Stable 版本的资格验证。

Nightly 根据用户 2026-10-25 的要求恢复为独立构建通道；它不能替代 Stable 资格验证，也不能绕过来源、补丁、构建接口和包检查。详见下面的同步策略。

## 4. Stable 资格验证与发布

Stable 发布以**准确的自定义提交 + 准确的官方上游 Stable 版本/SHA + 当前补丁集身份**为约束。

~~~text
发现官方 Stable Release
       ↓
Stable 路由 / 解析准确上游 SHA，并生成私有 Draft
       ↓
Draft / Revision 预检
       ↓
检查当前自定义提交及目标身份的资格记录
       ↓
准备源码与平台构建
       ↓
产物验证和聚合
       ↓
Android 生产签名（仅满足所有授权门禁时）
       ↓
最终聚合与发布预检
       ↓
Dry-run / Draft / Release
~~~

重要规则：

1. 不要把某个自定义提交的资格记录用于另一个提交、上游 SHA、patchset、revision 或构建配置。
2. 预检发现同版本/同 revision 的既有产物时，按门禁结果处理；不要手动覆盖或删除以绕过防重。
3. Dry-run 不代表 Release 已创建或发布。
4. Draft 和正式 Release 是不同操作；正式发布必须明确请求并通过完整聚合门禁。
5. Stable router 仅触发已签名的私有 Draft，不会公开发布。它复用 Stable 发布预检校验完整构建身份、资产清单和 SHA-256 摘要；相同完整构建已存在时跳过，活动构建时不重复派发。
6. Android 生产签名属于受保护的独立 Job，不是普通构建的一部分。

Stable 去重身份现在包括上游 SHA、自定义仓库提交 SHA、补丁集及 Common/SOS 补丁哈希、
Wayland 开关和启用时的策略 SHA-256。身份相同才复用版本修订号；修订号仍使用
`v版本-custom.v补丁集.序号`，不同身份会取得新的序号。复用前检查完成标记、身份字段、
准确资产清单、已上传状态、大小及 GitHub 提供的 SHA-256 摘要；不完整或不匹配时停止。
正式发布已有 Draft 时，会再次核对身份和资产，再执行 Draft 到正式 Release 的状态转换。
旧格式记录缺少新身份字段时不会被直接当作相同身份复用，会走新的修订号。

## 5. 推荐的 Stable 操作顺序

1. 确认待验证的自定义提交、官方上游 ref 和解析后的 SHA。
2. 在 `ci.yml` 中对目标执行所需资格验证，并确认该记录对应准确的自定义提交和上游身份。
3. 等待所有必需目标、产物验证、聚合和资格 Job 成功。
4. 在 Stable Release Pipeline 中查看当前 `release_mode` 选项，选择准确上游 ref 和所需模式。
5. 首次验证使用 dry-run；确认门禁、revision 和产物身份正确后，才按实际需求创建 Draft 或发布。
6. 如涉及 Android 生产签名，额外确认专用 Runner、Environment、显式授权条件、证书身份以及 APK v2/v3 验证。
7. 记录最终 Workflow URL、自定义 commit SHA、上游 SHA、patchset、产物验证和真实发布结果。

修改工作流输入或触发方式后，应同步更新本文并核实所有引用；不得保留已经删除的工作流名或过期的输入说明。

## Wayland 变体

`wayland.yml` 是由 Tag 和 Nightly 通过 `include_wayland`（默认开启）调用的 amd64/ARM64 实验性 reusable workflow。Tag 的 Draft/Release 会重新验证并附加两份 DEB；Nightly 会将其纳入聚合。该变体单独进行资格验证。详见 [Wayland 构建与门禁](wayland-unattended-zh.md)。

## 未知上游接口的审查自动化

上游 main 监测器会在常规兼容性检查之外执行只读检查。已知签名无需额外审查；遇到未知接口时，会在同一运行中生成 JSON 报告，记录观察到的接口、关键文件/工具指纹变化、上游比较链接，以及 Standard/SOS 补丁应用和 API 结构检查结果。该未批准路径明确**不会运行** Rust 编译、bridge 生成、Flutter 分析或运行时测试；接口完成审查前，常规兼容性门禁仍会失败。

独立的可信 main job 仅持有仓库内容和 PR 写入权限，可创建仅包含报告的 Draft PR。它不能修改已批准 profile、补丁策略、签名或发布设置。报告位于 `docs/upstream-interface-reviews/`；自动化分支按完整接口签名去重。部分 PR 创建失败后的重试，只能复用仅含预期报告的分支，不会重置或强推；不会自动重开已关闭的审查。

流程不使用 PAT 或生产配置。仓库/组织必须允许 GitHub Actions 创建 PR；否则报告 artifact 仍可用，写入步骤会明确失败。由 GITHUB_TOKEN 创建的 PR 可能不会自动触发新的 CI，因此报告不代表 CI Qualification。人工必须检查 diff，必要时添加经过审查的 profile，并运行完整兼容性流程。没有任何内容会自动批准、合并或发布。

## Nightly 同步与构建

官方 `flutter-nightly.yml` 每天 UTC 00:00（香港时间 08:00）启动。
`upstream-nightly.yml` 在每小时 :07/:22/:37/:52 检查官方成功完成的构建，
发现新批次后触发 `nightly.yml`。GitHub 定时任务可能延迟；不按固定等待分钟数猜测完成状态。
官方计划见 https://github.com/rustdesk/rustdesk/blob/master/.github/workflows/flutter-nightly.yml 。

来源绑定官方仓库、默认分支、工作流路径、成功状态、运行 ID 和完整 40 位 SHA；
不使用可能滞后的 `nightly` 标签，也不追逐尚未成功构建的最新 master。
本次接入时，官方成功运行 40146600534 对应 `1297da6d186e58d9096be24072ae3998cdbbf8fe`，
而 `nightly` 标签指向其他提交，因此两者不能混用。

构建复用 Tag 的 `prepare-source.yml`、Windows/Linux/macOS/Android 构建核心，
从同批 Common 补丁源码分出 Standard/SOS；目标及 ARM64/amd64 范围来自同一平台矩阵。
Android 仍仅 Standard。Windows ARM64 作为实验性目标由平台矩阵默认加入 Tag/Nightly，安装包通过架构与来源校验后随发布资产附带；普通 CI 仍不自动构建它，运行时资格待补充。
DRM/Wayland 实验构建已作为默认开启的子流程接入，保留独立审核策略和资格结果，不冒充普通 Standard 目标。
v1/v2 的强制关闭软件渲染策略由 Common 层继承。未知构建接口继续阻断。

自动路由仅从本仓库 main 执行，按官方上游 SHA、自定义提交 SHA、发布模式和
Wayland 选择去重；官方运行 ID 只作为来源记录，不会让相同 SHA 重复构建。
手动 Nightly 也在源码解析后执行相同检查。相同身份仍在运行或已成功时跳过；
失败最多自动尝试三次。自定义代码、上游 SHA 或 Wayland 构建选择变化都会形成新身份。
旧运行标题和同运行 discovery 产物会用于迁移期识别；无法安全确认的历史身份不会用于复用产物。

全矩阵和同批来源验证通过后，安装包、SHA256SUMS 与验证报告出现在
`nightly-qualification-<run-id>` Actions 产物中；单目标失败不会发布完整批次。
Nightly 的 `release_mode` 默认 `draft`：仅主分支的直接签名 job 绑定 Android
生产签名 Environment 与 YubiKey，全部构建和签名验证通过后创建 prerelease Draft。
普通构建 job 不接触 PIN，Draft job 也不接触 PIN；公开 Nightly 预发布版只能通过明确选择
`release` 手动触发。
`dry-run` 跳过签名和草稿，汇总原始测试签名 APK，支持在 development 验证。
重复的完整 Draft 保持不变，不重建或覆盖；明确选择 `release` 时，只有上游/自定义
SHA、补丁集、Wayland 配置、完成状态、资产清单及远端 SHA-256 全部匹配，才复用该 Draft
并转为公开 Nightly 预发布版。身份或远端资产有任何不一致时均停止，不覆盖原发布。
运行时与真实远程连接状态保持未测试，构建成功不能证明锁屏兼容。

定时工作流需要合入 main 后才会生效；代码/契约检查通过与真实全平台构建成功应分别报告。

### Nightly 签名与 Draft 门禁

Nightly 路由请求 `release_mode=draft`；公开 prerelease 必须由人工明确选择 `release`。签名和发布写入仅允许仓库 main、准确的 Nightly workflow ref 和 `workflow_dispatch`；development 只能运行 dry-run。Android 签名 job 与 Tag 共用 Environment、Runner 标签、PIV 身份、v2/v3 要求和实体密钥并发锁。输入 APK 的通道必须匹配 `SIGNING_CHANNEL`，Nightly 回执也会记录通道。

Draft 和 release 模式下，父级聚合要求三种 Android ABI 均有生产签名产物。独立的 contents-write job 下载同一运行中的签名包和可选 Wayland 包，在任何写入前重新验证。它扫描已完成的构建日志，创建不可变的 Nightly prerelease Draft，上传软件包及 SHA256SUMS，核对远端文件名、大小和 SHA-256 摘要，全部通过后才写入 `automation_state=complete`。明确选择 release 时，只有元数据、清单、远端大小和摘要都匹配的完整 Draft 才会复用；不匹配或不完整的发布不会被覆盖。Windows/macOS 签名状态与 Tag 相同（未启用）。

运行标题包含上游 SHA、自定义 SHA、模式和 Wayland 选择。工作流会串行化相同提交/模式/Wayland 批次，resolve job 在准备源码前检查旧运行。成功的 dry-run 不会阻止带签名的 Draft 构建。此工作流必须合入 main 后才能实际执行生产签名和创建 Draft；单元检查和 CI 不能证明硬件签名已经运行。

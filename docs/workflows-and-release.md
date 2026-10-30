# 工作流与发布流程

## 1. 工作流职责

| Workflow | 主要职责 |
| --- | --- |
| `.github/workflows/ci.yml` | 对 PR、push 和手动运行进行变更分类；文档专属变更走轻量路径，功能变更进入来源解析、兼容性和资格验证 |
| `.github/workflows/compat-check.yml` | 可复用的上游来源、补丁集、架构契约和兼容性检查流程 |
| `.github/workflows/prepare-source.yml` | 准备带有明确来源身份的 Standard / SOS 源码 |
| `.github/workflows/build.yml` / `build-platform.yml` | 规划构建目标、执行平台构建并传递产物身份 |
| `.github/workflows/build-stable-windows.yml` | Stable Windows 构建入口 |
| `.github/workflows/build-stable-platforms.yml` | Stable Linux / macOS 等平台构建入口 |
| `.github/workflows/build-stable-android.yml` | Stable Android 构建入口；可选生产签名在独立的受保护 Job 中执行 |
| `.github/workflows/tag.yml` | Stable 解析、revision 预检、构建、产物聚合、可选 Android 生产签名及 Dry-run / Draft / Release 决策 |
| `.github/workflows/upstream-stable.yml` | 定期发现官方 Stable Release，并将最新版本路由到已签名的私有 Draft 构建 |
| `.github/workflows/upstream-main-compatibility.yml` | 定期验证官方上游默认分支的兼容性；不构建或发布 Nightly 产物 |
| `.github/workflows/android-yubikey-signing-test.yml` | 需要手动触发并明确授权的 YubiKey 签名冒烟测试，不发布或提升 Release |

本表用于导航。触发器、输入、权限、条件、Job 依赖和发布语义均以当前工作流文件为准。不要引用仓库中不存在的旧工作流名。

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
Android 生产签名（仓库变量开启且所有授权门禁满足时）
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
5. Stable router 仅在官方版本高于最近一个已完成 Stable 版本时自动触发已签名的私有 Draft，不会公开发布。手动运行默认使用同一版本门槛；显式设置 `allow_same_version` 后才继续检查同版本身份。Stable 发布预检校验完整构建身份、资产清单和 SHA-256 摘要；相同完整构建已存在时跳过，活动构建时不重复派发。
6. Android 生产签名属于受保护的独立 Job，不是普通构建的一部分。

Stable 去重身份包括上游 SHA、按 Stable 版本边界选中的补丁集及其 Common/SOS 补丁哈希、
Wayland 开关和启用时的策略 SHA-256，以及 Android 签名策略。自定义仓库提交 SHA 仍记录为来源信息，
但普通仓库提交不改变构建身份。身份相同才复用版本修订号；修订号仍使用
`v版本-custom.v补丁集.序号`，不同身份会取得新的序号。复用前检查完成标记、身份字段、
准确资产清单、已上传状态、大小及 GitHub 提供的 SHA-256 摘要；不完整或不匹配时停止。
正式发布已有 Draft 时，会再次核对身份和资产，再执行 Draft 到正式 Release 的状态转换。
旧版 v3 记录会在核对其记录的来源 SHA、所选补丁内容哈希及其他构建策略后复用；不符合时不会复用。

## 5. 推荐的 Stable 操作顺序

1. 确认待验证的自定义提交、官方上游 ref 和解析后的 SHA。
2. 在 `ci.yml` 中对目标执行所需资格验证，并确认该记录对应准确的自定义提交和上游身份。
3. 等待所有必需目标、产物验证、聚合和资格 Job 成功。
4. 在 Stable Release Pipeline 中查看当前 `release_mode` 选项，选择准确上游 ref 和所需模式。
5. 首次验证使用 dry-run；确认门禁、revision 和产物身份正确后，才按实际需求创建 Draft 或发布。
6. 如涉及 Android 生产签名，额外确认专用 Runner、Environment、显式授权条件、证书身份以及 APK v2/v3 验证。
7. 记录最终 Workflow URL、自定义 commit SHA、上游 SHA、patchset、产物验证和真实发布结果。

修改工作流输入或触发方式后，应同步更新本文并核实所有引用；不得保留已经删除的工作流名或过期的输入说明。

## Wayland unattended build

`wayland.yml` is an internal reusable amd64/ARM64 experimental build, enabled by default through `include_wayland` in Tag and Nightly. Tag draft/release revalidates and attaches both DEBs; Nightly includes them in its aggregate. The flavor remains separately qualified. See [contracts and usage](wayland-unattended.md).

## Unknown-interface review automation

The existing upstream-main monitor runs a separate read-only inspection alongside
normal compatibility checks. Known signatures produce no review. Unknown ones
produce a same-run JSON report with the observed interface, changed critical
file/tool fingerprints, a full upstream compare link, and Standard/SOS patch
application and API-structure results. Rust compilation, bridge generation,
Flutter analysis and runtime are explicitly **not run** in this unapproved path.
The normal compatibility gate continues to fail until the interface is reviewed.

A separate trusted-main job, with only repository contents/PR write permissions,
can propose a **draft, report-only PR**. It cannot change the approved profile
list, patch policy, signing or release settings. Reports live under
`docs/upstream-interface-reviews/`; automation branches use the full interface
signature and are deduplicated across repeated runs. Partial PR-creation retries
can reuse only a branch containing the single expected report; they never reset
or force-update a branch. Existing closed reviews are not silently reopened.

No PAT or production configuration is used. GitHub Actions must be permitted by
the repository/organization to create pull requests; otherwise the report artifact
remains available and the writer fails visibly. GITHUB_TOKEN-created PRs may not
trigger new CI automatically; the report makes no CI-qualification claim. A human
must inspect the diff, add a reviewed profile if appropriate, and run the full
compatibility path. Nothing is automatically approved, merged or published.

## Nightly 同步与构建

官方 `flutter-nightly.yml` 每天 UTC 00:00（香港时间 08:00）启动。
`upstream-nightly.yml` 每天 UTC 02:23（香港时间 10:23）检查官方成功完成的构建，
避开整点调度，但不保证无延迟。手动和自动构建都在解析阶段选择最新成功的官方运行，
不等待当天运行，不提供运行 ID/SHA 输入；选定后锁定运行 ID 和完整源码 SHA，供下游统一使用。
GitHub 定时任务可能延迟，因此使用官方运行状态而非猜测完成时间。
官方计划见 https://github.com/rustdesk/rustdesk/blob/master/.github/workflows/flutter-nightly.yml 。

来源绑定官方仓库、默认分支、工作流路径、成功状态、运行 ID 和完整 40 位 SHA；
不使用上游可能滞后的 `nightly` 标签，也不追逐尚未成功构建的最新 master。
例如官方运行 40146600534 对应源码 SHA `1297da6d186e58d9096be24072ae3998cdbbf8fe`；
上游 Release 的 tag 与运行源码 SHA 应分别看待。

构建复用 Tag 的 `prepare-source.yml`、Windows/Linux/macOS/Android 构建核心，
从同批 Common 补丁源码分出 Standard/SOS；目标及 ARM64/amd64 范围来自同一平台矩阵。
Android 仍仅 Standard。Windows ARM64 作为实验性目标由平台矩阵默认加入 Tag/Nightly，安装包通过架构与来源校验后随发布资产附带；普通 CI 仍不自动构建它，运行时资格待补充。
DRM/Wayland 实验构建已作为默认开启的子流程接入，保留独立审核策略和资格结果，不冒充普通 Standard 目标。
v1/v2 的强制关闭软件渲染策略由 Common 层继承。未知构建接口继续阻断。

自动路由仅从本仓库 main 执行，按官方上游 SHA、所选 patchset 的 Common/SOS 补丁哈希、
发布模式、Wayland 策略和签名模式去重；自定义提交 SHA 与官方运行 ID 只作为来源记录，
不会因无关仓库提交或同一源码的上游重跑而重复构建。
手动 Nightly 也在源码解析后执行相同检查。相同身份仍在运行或已成功时跳过；
失败最多自动尝试三次。上游 SHA、所选补丁内容或相关构建策略变化会形成新身份。
旧运行标题和同运行 discovery 产物会用于迁移期识别；无法安全确认的历史身份不会用于复用产物。

全矩阵和同批来源验证通过后，安装包、SHA256SUMS 与验证报告出现在
`nightly-qualification-<run-id>` Actions 产物中；单目标失败不会发布完整批次。
Nightly 的 `release_mode` 默认 `draft`：仓库变量开启时，主分支的直接签名 job 绑定 Android
生产签名 Environment 与 YubiKey，全部构建和签名验证通过后创建 prerelease Draft。变量关闭或未设置时，跳过签名并在来源验证后附带未签名 APK。
普通构建 job 不接触 PIN，Draft job 也不接触 PIN；公开 Nightly 预发布版只能通过明确选择
`release` 手动触发。
`dry-run` 跳过签名和草稿，汇总原始测试签名 APK，支持在 development 验证。
所有 Nightly 输出使用固定的 `nightly` tag 和同一个 Release 入口。全矩阵、签名、
来源和校验和验证通过后，更新 tag 到本次自定义仓库提交，清除旧 assets，上传并验证新产物；
替换期间先把 Release 暂设为 Draft，验证完成后按 `release_mode` 保持 Draft 或公开为 prerelease。
Release 记录和下载入口保持稳定。构建或验证失败时不会开始替换；身份、tag 所有权或远端
资产校验不符合预期时停止。相同来源与构建配置仍按去重规则跳过，不重复构建。
运行时与真实远程连接状态保持未测试，构建成功不能证明锁屏兼容。

定时工作流需要合入 main 后才会生效；代码/契约检查通过与真实全平台构建成功应分别报告。

### Nightly signing and Draft contract

The user explicitly requested Tag-equivalent signing and Draft stages. The router
requests `release_mode=draft`; public prerelease requires an explicit manual
`release_mode=release` dispatch. Signing and release writes are restricted to
repository main, the exact Nightly workflow reference and workflow_dispatch;
development must use dry-run. The direct Android signing job shares Tag's Environment, runner labels,
PIV identity, v2/v3 requirements and physical-key concurrency lock. The input APK
channel must match `SIGNING_CHANNEL`; Nightly receipts also record the channel.

The complete parent aggregate requires all three production-signed Android ABIs
in Draft and release modes when signing is enabled. If it is disabled, the aggregate
uses validated unsigned Android build artifacts instead. A separate contents-write job downloads the exact
same-run Android packages and optional Wayland pair and revalidates them before any
write. It scans completed build logs, then refreshes the fixed `nightly` tag and
Release only after validation succeeds. The existing Release is temporarily made a
Draft, prior assets are removed, the tag is moved to the custom build commit, and
the new packages and SHA256SUMS are uploaded and verified by name, size and digest.
Only then is automation_state marked complete and the Release left as a Draft or
published prerelease according to the selected mode. A release-write concurrency
lock prevents overlapping builds from replacing each other's assets. Windows/macOS
signing status remains the same as Tag (not enabled).

Run titles include the upstream SHA, custom SHA, mode and Wayland selection. The
workflow serializes matching upstream/mode/Wayland batches, and the resolve job checks
prior runs before source preparation. A successful dry-run cannot suppress a signed
Draft batch. This workflow must be merged to main before production signing/Draft
can execute; unit and CI checks do not prove a hardware signing operation occurred.

### Android production signing switch

Stable Tag and Nightly read the GitHub Actions repository variable
`ANDROID_PRODUCTION_SIGNING_ENABLED`. Set it to the string `true` to request the
protected YubiKey signing job. Set it to `false`, or leave it undefined, to skip
that job and publish validated unsigned Android packages. The switch is part of
the Stable build identity, so a Draft made with one signing mode is not reused
after changing modes.

For a cloned repository, configure this variable under **Settings → Secrets and
variables → Actions → Variables**. Enabling the switch does not provision a key:
the clone also needs its own protected runner, Environment, PIN secret, and
reviewed Android signing identity. Never claim the original repository's
certificate identity for a different key.

Stable 手动和自动构建均自动计算并锁定构建身份，不提供身份输入框。自动路由读取同一运行生成的身份锁进行去重和重试计数；活动运行尚未生成锁时保守跳过，已结束运行缺少锁时停止并要求检查。锁文件绑定本次运行、仓库提交、上游版本/SHA、补丁哈希、Wayland 和签名策略，以下游必需的摘要校验防止漂移。强制重建/覆盖旧发布开关暂不恢复，旧发布保持不可覆盖。

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

The upstream-main monitor provides patch/API, bridge and Flutter compatibility
signals only; it does not collect native platform fingerprints or propose
interface-review PRs. Its reviewed bridge/build recipe gate remains in place
before executing dependency or generator commands.

Nightly owns interface discovery for the exact upstream SHA selected from a
successful official Nightly run. After source resolution and duplicate checks,
a separate read-only job inspects that same immutable source, independently of
source preparation. Known signatures produce no review. Unknown ones produce a
same-run JSON report with interface fingerprints, a full upstream compare link,
and Standard/SOS patch application and API-structure results. Compilation,
bridge generation, Flutter analysis and runtime are **not run** by this report
collector. Native preflight remains fail-closed before bridge dependencies;
creating or merging a report never approves an interface.

Reports normalize YAML mapping keys using the same collision-rejecting rules as
their identity digest before writing JSON. This preserves identity across the
artifact upload/download boundary, including YAML 1.1 boolean keys such as `on`.
The writer still rejects changed identities, stale run/commit bindings and
fabricated validation claims.

A separate job in the protected-main Nightly workflow, restricted to its
`workflow_dispatch` context and with contents/PR write and Actions read permissions,
can propose a **draft, report-only PR**. It cannot change the approved profile
list, patch policy, signing or release settings. Reports live under
`docs/upstream-interface-reviews/`; automation branches use the full interface
signature and are deduplicated across repeated runs. Partial PR-creation retries
can reuse only a branch adding one regular, non-executable JSON report. Recovery
compares immutable commit IDs, verifies the stored report's filename/source and
interface digest, and checks its recorded discovery run against this repository's
trusted Nightly discovery workflow. Immutable historical upstream-main reports
remain eligible for recovery after the same provenance checks; new CI reports
cannot create PRs. Different upstream source commits may share an interface
branch: recovery retains the original file and creates only the missing draft PR,
with the historical source/run and current discovery clearly distinguished. It
does not copy old check results onto the new source. Extra files, malformed or
untrusted reports, truncated trees, executable/symlink reports and refs changing
during validation stop recovery. Branches are never reset or force-updated.
Existing closed reviews are not silently reopened.

No PAT or production configuration is used. GitHub Actions must be permitted by
the repository/organization to create pull requests; otherwise the report artifact
remains available and the writer fails visibly. GITHUB_TOKEN-created PRs may not
trigger new CI automatically; the report makes no CI-qualification claim. A human
must inspect the diff, add a reviewed profile if appropriate, and run the full
compatibility path. Nothing is automatically approved, merged or published.

## Shared interface approvals for Nightly and Stable

Nightly and Stable consume the same reviewed build/platform metadata and exact
architecture-specific recipe policies. A fingerprint approved after Nightly
review is reusable by Stable when its complete checked identity matches; no
separate Stable copy of the registry or version-wide approval is created.
Unknown fingerprints still fail closed in both channels. Nightly success or a
report PR is not itself approval.

Stable separately requires an official Stable tag and locked source SHA,
Stable-eligible Profile, reviewed patch content revision, complete artifact
qualification and its signing/publication authorization. Nightly artifacts or
qualification are not promoted implicitly. In particular, 1.5.1 keeps v2
revision 8 and candidate/fallback Profiles remain ineligible for Stable.

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
普通构建 job 不接触 PIN，Draft job 也不接触 PIN；Nightly 公开发布已屏蔽，只保留 dry-run 和 Draft。
`dry-run` 跳过签名和草稿，汇总原始测试签名 APK，支持在 development 验证。
所有 Nightly 输出只使用固定的 `nightly` Git tag 和最新一份 Release，不为每天创建独立历史 Tag。
全矩阵、签名、来源和校验和验证通过后，首次创建 Draft 会明确创建真实的 `refs/tags/nightly`；
已有该 ref 时使用 GitHub 的 `PATCH force=true` 直接移动到本次自定义仓库提交，绝不采用先删除 Git Tag 再创建的方式。
只有经过归属和证明验证的旧私有 Draft 才能刷新；公开 Release 不会被隐藏或替换。新产物上传验证后仍保留 Draft。
刷新私有 Draft 时 Release ID 及 `untagged-*` 下载 URL 可以变化，不保证固定；构建或验证失败时不会开始替换；身份、tag 所有权或远端
资产校验不符合预期时停止。相同来源与构建配置仍按去重规则跳过，不重复构建。
运行时与真实远程连接状态保持未测试，构建成功不能证明锁屏兼容。

定时工作流需要合入 main 后才会生效；代码/契约检查通过与真实全平台构建成功应分别报告。

### Nightly signing and Draft contract

The user explicitly requested Tag-equivalent signing and Draft stages. The router
requests `release_mode=draft`; public Nightly publication is disabled. Signing and release writes are restricted to
repository main, the exact Nightly workflow reference and workflow_dispatch;
development must use dry-run. The direct Android signing job shares Tag's Environment, runner labels,
PIV identity, v2/v3 requirements and physical-key concurrency lock. The input APK
channel must match `SIGNING_CHANNEL`; Nightly receipts also record the channel.

The complete parent aggregate requires all three production-signed Android ABIs
in Draft mode when signing is enabled. If it is disabled, the aggregate
uses validated unsigned Android build artifacts instead. A separate contents-write job downloads the exact
same-run Android packages and optional Wayland pair and revalidates them before any
write. It scans completed build logs, then refreshes the fixed `nightly` tag and
Release only after validation succeeds. Refreshing a private Draft first rechecks its
workflow ownership, unchanged metadata and Draft state, then deletes it and creates a
new Release ID; even an exact matching Draft is not reused in draft mode. The moving
Git tag is retained and moved to the validated custom build commit when needed.
New packages and both attested JSON files are uploaded and verified by name, size and digest.
Nightly refuses to hide/delete an already public canonical Release. Verified output remains a private Draft, with identity in attested JSON; no public mode or native proof generation is available. A release-write concurrency
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


## Stable 草稿与 Git tag

Stable Release 的 `tag_name` 与 Git 引用 `refs/tags/...` 是两件事。草稿页面的 `untagged-*` 是 GitHub 的内部地址，不表示仓库把版本名称设置成了 untagged。单独创建真实 Git tag 也不保证草稿页面 URL 立即变化；不要为改变地址而自动发布 Release。

Stable 自动化在完成产物、架构、来源和上传清单校验后，显式创建 `v{上游版本}-custom.{补丁修订}` 的不可变 Git tag，指向本批产物记录的 `custom_repository_sha`，而非上游仓库 SHA 或稍后变化的 main HEAD。草稿仍保持 `draft=true`。

已有轻量/附注 tag 只有在最终指向同一提交时才可复用；同名异提交立即失败，绝不强制更新或删除。引用创建失败时保留草稿并停止，不提升令牌权限。旧草稿在用户明确选择发布、且原有身份与远程校验全部通过后，也会检查/补建 tag，再进行原有发布动作。此修改不批量修复历史草稿，也不主动发布任何草稿。


Nightly 私有草稿刷新采用删除重建，当前草稿在本地产物、签名、清单和日志校验完成前不会删除。删除前再次检查草稿归属和完整状态快照；删除后确认旧 Release 不存在，才创建新 Release。保留同源成功构建去重，不为刷新日期强制重编译。删除重建存在窗口：若删除后创建或上传失败，该次可能暂时没有完整草稿；Actions 产物仍保留，可按原流程恢复。新草稿只有上传摘要全部匹配才标记 complete。

[GitHub 对 `created_at` 的说明](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)指出它可能表示关联 tag/commit 的日期，不能保证删除重建后页面 “drafted … ago” 一定刷新；不要伪造提交时间或创建空提交。说明末尾单独记录真实 UTC 产物校验完成时间和 Actions 运行链接。这个字段不参与源码/构建身份，也不代表 Runtime 测试或公开发布。


**Draft Tag 绑定校验（Stable 与 Nightly）：** 已创建的真实 Git Tag 与 GitHub Draft 页面 URL 是不同层次的对象。
Stable `qualification.py` / `channel.py` 会在通过产物校验并确认不可变 Git ref 后，显式更新
Release 的 `tag_name`、`target_commitish` 和 `draft=true`，并检查 API 回执。
Nightly 首次 Draft 也会创建真实 `nightly` Git ref，后续只移动该固定 ref；更新和上传失败不能标记
`automation_state=complete`。任何情况下都不得为了去除 GitHub 页面上的 `untagged-*`
而擅自将 Draft 公开发布。`untagged-*` 可能仍是 GitHub 的内部 Draft URL，即便 REST API
的 `tag_name` 和真实 Git ref 都正确。使用 `gh api repos/billradar/rustdesk-custom/git/ref/tags/<版本>`
和 `gh api repos/billradar/rustdesk-custom/releases` 分别验证真实 Git 引用和 Draft 元数据；
不要把浏览器 URL 当作 Git Tag 的唯一证据。

Nightly 维持**最新一份**策略：仅创建/移动 `nightly`，新草稿完成后清理同通道旧 Release；
替换草稿涉及多个非原子 API 操作。如果新产物上传中途失败，可能产生尚未完成的 Draft，
必须检查并重试，不能承诺在所有故障情况下旧附件始终可下载。

## Release names and rerun reports

Public package names are normalized once or repeatedly to the same name by
`scripts/release/naming.py`. Standard has no variant token; SOS has `-sos`.
Linux DEB normalization strips an existing OS/architecture prefix even when the
extension immediately follows it. v1/v2 RPM names retain their legacy architecture suffix for immutable client
selectors. v3.2+ emits `.rpm` or `-suse.rpm` after one OS/architecture prefix and
uses matching client selectors; see [RPM asset naming](rpm-asset-naming.md).
No historical asset is renamed by this change.

Aggregation reserves every public filename before copying packages into a fresh
asset directory. Duplicate normalized names, reserved checksum names, symlinks,
and an existing destination fail the aggregate gate; no payload is overwritten.
Wayland attachment retains its independent collision and provenance checks.

Rerunnable discovery, qualification and compatibility reports use
`<base>-<run_id>-attempt-<run_attempt>`. Readers select the newest available report
for the same run up to its current attempt, with legacy unsuffixed fallback.
A failed-jobs-only rerun can reuse an untouched job's prior report; a newer report
replaces that job's older failure. Missing or malformed evidence does not create
a successful gate. Immutable prepared-source, installer and signing payload names
remain unchanged. Run `python3 -m scripts.release.artifacts_contract` together
with qualification, Nightly and summary contracts after changing these handoffs.

## Public release integrity format

New releases use `update-manifest.json` plus a Sigstore `release-attestation.json`
bundle, replacing public `SHA256SUMS` directly. The main-only aggregate job signs
the qualified manifest; write jobs revalidate it before Release/tag writes.
Checksum-only historical Drafts cannot pass the new publication/reuse gate.
See [Release inventory and Sigstore attestation](release-attestation.md) for the
trust policy, old-client boundary and internal checksum exceptions.

Stable Tag 创建 API 成功后，读取 API 可能短暂返回 404（运行 43146078797
的 Draft 作业在此失败，事后已确认 Tag 指向正确构建提交，33 个资产仍保留
在私有 Draft）。创建后的回读最多尝试 5 次，间隔 1、2、4、8 秒；只重试
“引用暂不可见”，不重复 POST、不移动引用。出现错误 SHA、无效响应、权限
或其他 API 错误立即失败；超过次数仍不可见也失败，不以 POST 成功代替验证。
已有 Draft/Tag 不应通过重跑整套 CD、删除或覆盖来恢复，必须先核对实际状态。

### Attested JSON and human release notes

New release automation uses schema-v2 `update-manifest.json` for build identity,
options and installer inventory; `release-attestation.json` binds its exact bytes.
Stable preflight/promotion and Nightly reuse/ownership/cleanup verify these assets,
not Release body markers. Body contains upstream notes and human customization
changes only. Detailed patch hashes, audit limitations and compatibility records
remain in repository records and JSON. Legacy schema-v1/checksum/body-only objects
fail closed and require explicit review; existing historical Releases are not
silently rewritten. Current v3.3 clients consume the same attested selectors;
historical clients need a manual upgrade. See [Client updates](client-updates.md).

Stable 的构建流同样只保留 dry-run/Draft。公开发布由手动触发的 [publish-stable.yml](manual-stable-publication.md) 完成；它核验并发布指定 Draft，不重新构建或上传附件。

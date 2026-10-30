# 日常操作手册

## 1. 准备环境

基础仓库工具需要 Python 3 和 Git；完整构建还需要对应平台的 RustDesk、Flutter、Rust、Native 工具链及工作流配置的其他依赖。

~~~bash
git clone https://github.com/billradar/rustdesk-custom.git
cd rustdesk-custom
git checkout development
python3 -m pip install -r requirements.txt
~~~

## 2. 分支与 PR 约定

本仓库的两个长期分支是：

- `main`：受保护的稳定集成和发布基线。
- `development`：共享开发与集成分支。

常规修改直接在 `development` 上进行，完成检查后创建从 `development` 指向 `main` 的 PR。除非用户明确要求或平台限制确有必要，不创建 `feature/*`、`fix/*` 等临时分支。不要直接写入受保护的 `main`。

开始工作前检查两个分支的 HEAD、merge-base、ahead/behind 和相关提交。不要把文件树相同误认为 Git 历史相同。不得擅自重置、强推、rebase、删除或替换共享分支引用；任何破坏性历史操作都必须先获得明确授权并核对目标 SHA。

PR 已创建不代表已合并。合并后应核实合并提交和分支比较结果。

## 3. 修改前先理解边界

1. 找到实现所在的 `scripts/`、`.github/workflows/`、`.github/actions/` 或 `metadata/`。
2. 找到调用它的工作流和契约测试。
3. 确认当前权威配置，而不是先改 README 或复制一份配置。
4. 判断变更是纯文档还是功能变更。
5. 对涉及发布、签名、来源身份的变更，先列出安全边界和失败条件。

## 4. 本地验证

仓库级检查：

~~~bash
python3 scripts/validation/repository_contract.py
~~~

随后运行与变更相关的契约脚本，并检查退出码。需要构建的变更还必须通过 GitHub Actions 中实际使用的工具链完成兼容性、构建、产物和聚合验证。

仅修改文档时，不需要本地构建 RustDesk；文档 PR 应由轻量检查覆盖。不要为了让文档 PR 通过而修改功能契约或关闭检查。

## 5. 提交、PR 与验证记录

1. 在 `development` 完成范围明确的修改。
2. 检查完整 diff，确认没有无关功能变更、密钥材料或过期路径。
3. 执行相关验证，记录真实结果和运行链接。
4. 创建从 `development` 到 `main` 的 PR。
5. 检查所有必需 CI 结果、文档链接和 PR 描述。
6. 按授权进行审查与合并；不要把“已创建 PR”描述为“已合并”。
7. 合并后核实最终提交 SHA 和两个分支的实际状态。

## 8. GitHub Actions 发布操作

所有生产发布都从 GitHub 仓库的 **Actions** 页面启动。选择工作流后点击 **Run workflow**，发布操作选择 `main` 分支；发布/签名门禁会拒绝不符合条件的分支和事件。`development` 只用于开发验证，Nightly 在该分支仅允许 `dry-run`。

### Stable

1. 打开 **Stable Release Pipeline**（`.github/workflows/tag.yml`）。
2. `upstream_ref` 填官方 Stable tag（例如 `1.5.1` 或仓库实际使用的 `v1.5.1` 格式）；留空表示自动解析当前官方 Stable。以工作流解析结果中的版本和 SHA 为准。
3. `include_wayland` 默认开启；启用时两个 Wayland DEB 会参与验证并随发布附加。该变体仍是实验性构建。
4. 初次验证使用 `dry-run`。确认来源 SHA、patchset、revision、必需平台和聚合资格均匹配后，选择 `draft` 创建 GitHub Draft Release；只有明确准备公开发布时才选择 `release`。
5. 正式发布会重新校验准确身份和远端资产。若已有完整、身份完全匹配的 Draft，流程会复核后发布该 Draft；不匹配或不完整时会停止，不能通过删 Release、改身份字段或手动覆盖资产来绕过。

Stable router（`.github/workflows/upstream-stable.yml`）每小时发现官方最新 Stable；只有版本高于仓库中最近一个已完成 Stable 版本时，才自动路由到 `main` 上的签名私有 Draft 构建。手动运行默认遵守同一版本门槛；显式勾选 `allow_same_version` 后，可让同版本继续经过发布预检，仍会跳过身份完全相同的已完成构建。路由会核对完整资产清单和摘要，不会公开发布。

### Nightly

1. 自动同步由 **Upstream Nightly Router**（`.github/workflows/upstream-nightly.yml`）每日 UTC 02:23（香港时间 10:23）启动，避开整点；不保证这是低峰时段或能准点执行。路由检查最新成功的官方 Nightly 并派发构建，不等待当天尚未成功的运行；GitHub schedule 可能延迟。
2. 手动构建时运行 **Nightly Build Pipeline**（`.github/workflows/nightly.yml`），选择 `main` 分支。手动和自动均选择启动时最新成功的官方 `flutter-nightly.yml` 运行，不再提供 `official_run_id`、`expected_sha` 输入。解析阶段记录运行 ID 并锁定完整源码 SHA，后续各阶段共用该 SHA。
3. `release_mode` 选 `dry-run` 做无发布验证，`draft` 创建私有 prerelease Draft，`release` 仅用于明确公开已验证的 Nightly prerelease。生产模式要求所有平台与 Android 生产签名门禁通过。`include_wayland` 默认开启。
4. development 分支只允许 `dry-run`，用于开发验证；不得把 development 的构建结果当作 main 的发布资格。
5. 上游 SHA、按上游版本选择的 patchset 及 Common/SOS 补丁哈希、模式、Wayland 策略和签名模式都相同时，重复 Nightly 会跳过；自定义提交 SHA 和官方运行 ID 只作来源记录。自动失败最多尝试三次；达到上限后先读日志并定位首个失败步骤，再决定是否修复后重跑。不要为了强制重建而更改历史记录或伪造 SHA。
6. Nightly `release` 会先要求存在身份和资产均匹配的完整 Draft，再发布为公开 prerelease。Draft 不完整或身份不一致时流程停止；不能手动补造 `automation_state=complete` 或用旧批次产物拼装。

### Wayland 变体

`wayland.yml` 是被 Stable/Nightly 调用的 reusable workflow，不能作为独立手动发布入口。通过父工作流的 `include_wayland` 开关控制。启用时 x86_64 与 aarch64 两个 DEB 都必须完成来源、包内容及聚合检查；任一目标失败则父流程不能发布完整批次。见 [Wayland 操作和门禁](wayland-unattended.md)。

### 检查结果与重试

- 在 Actions 运行摘要中记录 workflow URL、分支/提交 SHA、上游版本及 SHA、patchset、Wayland 选择和最终 mode。区分“job 成功”“资格验证通过”“Draft 已创建”“Release 已公开”。
- 打开失败 Job 的日志，从第一个失败步骤开始排查，并同时核对构建身份；入口见[故障排查手册](troubleshooting.md)。
- 若只有临时 Runner/网络问题，使用该次运行的 **Re-run failed jobs**，保留原身份并只重试失败部分。若代码、上游 SHA、patchset 或构建选项改变，重新 dispatch 新运行并重新验证，不混用旧产物。
- 工作流显示跳过时先看前置 gate 的输出和原因。去重命中不是失败；确认已有成功运行/完整 Draft 对应同一身份后再继续。
- 生产签名、Draft 创建和公开 Release 必须由受保护 GitHub Actions 完成。不要下载密钥/PIN 到普通 Runner、个人机器或日志；签名身份或远端资产校验不通过就停止并调查。

工作流的真实输入、授权条件和最终行为以当前 `.github/workflows/*.yml` 及相应契约脚本为准；本节是操作步骤，不授权绕过门禁。

## 6. 文档变更要求

- 当前规则只保留一个权威说明；其他文档链接到它。
- 文档中的文件路径、工作流名、输入名和命令必须在仓库中真实存在。
- 把“已实现”“已测试”“已发布”分开表述。
- 涉及时间变化的状态（例如某次 CI 结果）要附带具体运行链接或提交身份，避免将历史结果误写成当前状态。
- 工作流或接口发生变化时，搜索并修正所有失效引用。

## 7. 生产操作限制

生产发布和 Android 签名必须使用受保护的 GitHub Actions 路径。不要把 PIN、令牌、密钥材料、签名输入或完整敏感环境转储写入日志、Issue、PR 或文档。遇到身份不匹配、来源不明或 Runner 不可信时，应停止操作并调查。


### 构建稳定性与单目标恢复

- Android 在原生编译前安装应用/Flutter 的 compile SDK 和 `desktop_drop` 所需 API 33。平台目录必须有匹配的 API 元数据和可校验的 `android.jar`；显式声明的 build-tools 也会准备。每次安装超时为 5 分钟，最多 3 次，间隔 10/20 秒。每次下载使用独立临时目录，校验成功后才放入 SDK；只清理精确定位的无效组件，不删除整个 SDK 或缓存；失败仍阻止构建。
- `Build reliability and targeted recovery` 在 main 的 Stable/Nightly 运行结束后生成 `build-reliability-*` Actions artifact，保留 30 天。记录各 Job 的创建、启动、完成时间、runner 标签、执行/排队时间和失败分类。未获得 runner 的任务不伪造 0 秒排队，单独记录未分配时长。成功 Job 的 API 时间用于估算排队，不是云平台资源监控。
- 仅有明确 SDK 安装下载异常、runner 关闭或容量不足证据的失败构建目标可自动恢复；普通编译错误、未知故障、来源准备/校验任务、签名和发布任务不直接重试。public `release` 模式及整个运行被取消时不自动恢复。已上传有效产物的失败目标也交由人工处理，避免重传冲突。
- 每次结束最多请求重跑一个受影响的叶子 Job，以及 GitHub 定义的依赖任务；整个运行最多 3 个 attempt（初次 + 2 次恢复）。成功的其他目标、固定源码和来源锁沿用原运行；依赖的签名、聚合和 Draft 仍执行原有保护和校验。多个目标同时故障或次数耗尽时，查看报告并人工决定后续操作。
- 仓库变量 `BUILD_INFRA_AUTO_RETRY_ENABLED=false` 可关闭自动恢复，继续保留报告。新增 workflow 需合并到 main 后才生效，不会主动重跑历史运行。本次改动不自动派发生产构建、签名或发布。

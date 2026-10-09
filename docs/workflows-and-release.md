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
| `.github/workflows/build-stable-android.yml` | Stable Android 构建入口；生产签名在独立的受保护 Job 中执行 |
| `.github/workflows/tag.yml` | Stable 解析、revision 预检、构建、产物聚合、Android 生产签名门禁及 Dry-run / Draft / Release 决策 |
| `.github/workflows/nightly.yml` | 接收 dispatch 并执行 Nightly 构建、验证和开发产物流程；不发布 Stable Release，也不进行 Android 生产签名 |
| `.github/workflows/upstream-stable.yml` | 定期发现官方 Stable Release，并对下游 Stable 流水线执行去重后的 dry-run 路由 |
| `.github/workflows/upstream-nightly.yml` | 定期发现并验证官方成功的定时 Flutter Nightly 运行及其发布资产，再将固定 SHA 路由给下游 Nightly 流水线 |
| `.github/workflows/upstream-main-compatibility.yml` | 定期验证官方上游默认分支的兼容性；与 Stable 发布和 Nightly 产物路由分离 |
| `.github/workflows/android-yubikey-signing-test.yml` | 需要手动触发并明确授权的 YubiKey 签名冒烟测试，不发布或提升 Release |

本表用于导航。触发器、输入、权限、条件、Job 依赖和发布语义均以当前工作流文件为准。不要引用仓库中不存在的旧工作流名。

## 2. 普通 CI

Pull Request、受支持的 push 或手动触发首先进行变更分类：

- 所有变更均明确属于文档时，执行轻量文档验证，不运行无关的完整构建、资格验证、生产签名或发布。
- 任何功能或有歧义的变更都进入功能性验证。
- `force_rebuild` 是 `ci.yml` 的输入，用于请求完整功能性路径；不能据此推断 Nightly 或 Stable 工作流也有同名输入。
- 不得通过忽略错误、放宽契约或错误设置路径过滤，让必需检查变成永久 Pending。

## 3. 上游检测与 Nightly

Nightly 是开发和兼容性信号，不等同于 Stable 发布。

### 自动路由

- `upstream-nightly.yml` 每小时检查官方 `rustdesk/rustdesk` 的 `flutter-nightly.yml` 定时工作流。
- 路由器要求找到成功完成、来源正确且带有效 40 位 `head_sha` 的官方定时运行。
- 它还验证官方 `nightly` Release 是已发布的 prerelease、资产已上传且大小有效，并检查资产更新时间相对于运行开始时间足够新。
- 路由时会传递固定上游 SHA、官方运行 ID 和 Release 更新时间；下游 `nightly.yml` 会再次核验运行来源、状态、SHA 和 Release 状态，不能因为上游路由器已验证就移除下游验证。
- 路由器使用 `release_mode=build`。自动 Nightly 路由只构建/验证开发产物，不发布 Stable Release，也不访问 Android 生产签名环境。
- 路由器按 SHA 和运行状态去重。遇到失败应检查具体运行和日志，不要通过移除去重或来源门禁来“修复”。

### 手动 Nightly

`nightly.yml` 是 dispatch 驱动的下游工作流。手动运行可按当前输入指定上游 SHA 或明确的手动 ref；当使用官方自动路由标记时，必须提供并通过官方运行来源验证。始终以工作流当前输入和条件为准。

- 上游 ref 会被解析并锁定到准确 SHA。
- 实验目标是可配置的开发目标，不得未经明确策略变更就自动成为 Stable 必需目标。
- Nightly 不进行 Android 生产签名。其构建成功不能证明生产签名成功，也不能证明 Stable Release 已发布。
- 当前 Nightly 工作流没有 `force_rebuild` 输入；不要把 `ci.yml` 的输入假定为跨工作流通用接口。

### 上游默认分支兼容性

`upstream-main-compatibility.yml` 定期解析官方上游默认分支的当前提交 SHA，并运行兼容性检查。它是持续兼容性信号，不等同于 Stable Release 检查，也不应被描述为自动发布 Nightly。

## 4. Stable 资格验证与发布

Stable 发布以**准确的自定义提交 + 准确的官方上游 Stable 版本/SHA + 当前补丁集身份**为约束。

~~~text
发现官方 Stable Release
       ↓
Stable dry-run 路由 / 解析准确上游 SHA
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
5. Stable router 自动触发的是 dry-run，不是发布授权。
6. Android 生产签名属于受保护的独立 Job，不是普通构建的一部分。

## 5. 推荐的 Stable 操作顺序

1. 确认待验证的自定义提交、官方上游 ref 和解析后的 SHA。
2. 在 `ci.yml` 中对目标执行所需资格验证，并确认该记录对应准确的自定义提交和上游身份。
3. 等待所有必需目标、产物验证、聚合和资格 Job 成功。
4. 在 Stable Release Pipeline 中查看当前 `release_mode` 选项，选择准确上游 ref 和所需模式。
5. 首次验证使用 dry-run；确认门禁、revision 和产物身份正确后，才按实际需求创建 Draft 或发布。
6. 如涉及 Android 生产签名，额外确认专用 Runner、Environment、显式授权条件、证书身份以及 APK v2/v3 验证。
7. 记录最终 Workflow URL、自定义 commit SHA、上游 SHA、patchset、产物验证和真实发布结果。

修改工作流输入或触发方式后，应同步更新本文并核实所有引用；不得保留已经删除的工作流名或过期的输入说明。

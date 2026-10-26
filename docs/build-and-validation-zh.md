# 构建与验证原理

[English](build-and-validation.md) · [简体中文](build-and-validation-zh.md)

## 1. 平台矩阵是唯一平台清单

`metadata/platform/matrix.json` 定义平台、架构、变体、Runner、启用状态、支持状态和是否为必需目标。不要仅凭 README 中的表格判断目标是否会参与构建。

`metadata/platform/adapter-profiles.json` 保存经过审查的上游构建参数/适配器配置。资格验证会检查启用目标与审查配置之间的一致性。

支持状态的含义：

- **SUPPORTED**：满足仓库当前定义的构建/产物验证要求；不自动代表用户界面、远程会话或运行时行为已经验证。
- **EXPERIMENTAL**：可按明确选项纳入实验构建，不应自动提升为必需的 Stable 目标。
- **PLANNED**：尚未满足启用条件。
- **BLOCKED / UNSUPPORTED / DISABLED**：不能当作可用的正常目标。

## 2. 构建分层

1. `scripts/release/qualification.py` 根据矩阵生成目标计划。
2. `scripts/build/` 的平台脚本负责调用对应工具链。
3. `scripts/platform/` 执行构建、采集脱敏诊断信息并处理打包。
4. 产物验证检查 target、架构、校验和、构建信息、来源身份及配置。
5. 聚合步骤核对所需目标是否齐全，以及产物是否属于同一组上游/补丁/构建身份。
6. CI Qualification 把成功结果与准确的自定义提交和上游版本关联，供 Stable 流程消费。

构建脚本不得把失败伪装成成功；失败应保留足够的脱敏诊断信息，并归类到可排查的错误类别。

## 3. 验证层次

| 层次 | 验证对象 | 解决的问题 |
| --- | --- | --- |
| 仓库契约 | 目录、元数据、工作流边界和功能结构 | 仓库是否满足约定 |
| 上游兼容性 | 上游定义、补丁应用和构建接口 | 补丁是否适用于目标上游 |
| 准备源码验证 | SHA、补丁身份、子模块、工作区状态 | 构建输入是否可信 |
| 单目标构建 | 编译、平台配置和打包 | 单个目标是否能生成产物 |
| 产物验证 | ABI、包、校验和、build-info、来源 | 产物是否完整且身份正确 |
| 聚合与资格验证 | 必需目标集合及统一来源身份 | 是否达到 CI Qualification 门槛 |
| Stable 发布门禁 | 同一自定义提交和上游版本的资格记录 | 是否允许进入发布流程 |

## 4. 常用检查命令

仓库级契约：

~~~bash
python3 scripts/validation/repository_contract.py
~~~

针对改动区域，还应检查对应的契约脚本，例如：

~~~bash
python3 scripts/release/channel_contract.py
python3 scripts/release/qualification_contract.py
python3 scripts/release/production_contract.py
python3 scripts/build/config_mir_contract.py
python3 scripts/validation/native_config_contract.py
python3 scripts/signing/android_signing_contract.py
~~~

具体命令是否适用于当前分支，应以文件存在情况和脚本 CLI 为准；先查看脚本的参数说明，不要盲目执行发布或签名入口。

## 5. 如何理解“通过”

- 单个 Job 通过，不等于整个 Workflow 通过。
- 构建通过，不等于聚合和资格验证通过。
- CI Qualification 通过，不等于已创建 Draft 或正式发布。
- Android ABI 构建通过，不等于生产证书兼容性或应用覆盖安装升级已验证。
- 只有实际执行并成功的验证，才能标记为 PASS。

## 已审核的 1.5.1 CI 接口

上游 CI 快照 `1297da6d186e58d9096be24072ae3998cdbbf8fe` 的关键签名 `fead600e14fce31e0d4f16df77bf86ab2166f01f80464c59b0714c05f53c96f2` 已完成审核。Rust/Flutter/LLVM/vcpkg、bridge 生成和 Windows helper 固定版本与已审核的 1.5.0 相同。变化包括 Windows job 新增测试和可选的更新元数据步骤、`build.rs` 非 Flutter Sciter 分支变化，以及 `build.py` 可选 DRM 依赖更新。自定义工作流不会继承上游签名或发布凭据。这是接口审查，不是构建或运行时证据。

`build_adapter_contract.py` 会验证缺少审查、关键文件变化、工具链漂移和未经审核的 Runner 仍会失败关闭。独立无人值守工作流仍固定到其已审核的 1.5.0 DRM 策略；本 profile 不授权新的 libdrmtap 固定版本或无人值守包。

Windows ARM64 是使用原生 `windows-11-arm` Runner 的独立实验 lane。它使用 Flutter 3.44 和同一来源的 ARM64 bridge，验证 Dart、Flutter engine、Rust 输出、helper DLL、EXE 和 MSI 架构，并生成按架构区分的 Standard/SOS 安装包。Tag 和 Nightly 默认包含该 lane；普通 CI 仍仅构建 x86_64。提升为正式支持前仍需准确运行的编译和运行时资格验证。

## 准备源码时允许的上游测试密钥样例

Nightly 运行 `40198211193` 成功完成官方 bridge 生成，但源码扫描拒绝了 `libs/hbb_common/tests/data/websocket-key.pem`，这是上游 WebSocket TLS 集成测试样例。已审核的上游 `1297da6d` 固定 hbb_common 到 `edefa08b`；该样例由 hbb_common 提交 `3aade011` 引入。准备源码流程仅允许该相对路径和完整 SHA-256 `95cf7a0a6890435c98bb3f644678d4fd20d80ff4a296d438a515802e233c6ec9`。

此例外不适用于 tests 目录、其他 PEM 文件、其他路径或已修改内容。扫描失败时只报告文件名，不输出内容。全局生产输入/软件包/日志扫描仍保持严格，不含此源码专用例外。回归契约覆盖内容变化、密钥移动位置以及 ASCII/UTF-16 token。

## 1.5.1 原生平台 recipe 审查

运行 `40199720676` 通过了准备源码扫描，但 Linux/macOS/Android 在各自的平台 adapter 门禁停止。Windows/bridge profile 的批准不等于平台 recipe 获批。`metadata/platform/adapter-profiles.json` 现在记录了上游 `1297da6d` 的准确原生签名、七个受支持的原生架构 profile、基线比较、关键文件哈希和审查范围。Linux/Android job 定义及工具链未变化；全局版本及共享源码/构建文件指纹发生变化。macOS 还新增条件测试、deployment target 导出，以及可选的官方签名/更新路由。仅继承指定的 setup/build 脚本；自定义 macOS 包仍未签名。

此次审查不扩展独立 Wayland DRM 策略。签名批准不代表软件包或运行时已验证；未来未知文件、工具、recipe 和禁用 job 仍会被阻断，并由回归测试覆盖。

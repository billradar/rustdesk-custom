# 构建与验证原理

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

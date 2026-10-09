# 工作流与发布流程

## 1. 工作流职责

| Workflow | 主要职责 |
| --- | --- |
| \`.github/workflows/ci.yml\` | 对变更分类；文档专属变更走轻量路径，功能变更进入兼容性、构建和资格验证 |
| \`.github/workflows/compat-check.yml\` | 验证指定上游提交与当前补丁集的兼容性 |
| \`.github/workflows/prepare-source.yml\` | 生成可复用、带来源身份的 Standard / SOS 准备源码 |
| \`.github/workflows/build.yml\` | 计划目标、调用平台构建并汇总产物 |
| \`.github/workflows/build-platform.yml\` | 执行单平台/目标构建入口 |
| \`.github/workflows/nightly.yml\` | 对配置的上游测试 ref 执行 Nightly 构建和开发产物流程 |
| \`.github/workflows/tag.yml\` | Stable 的解析、预检、资格验证、构建、生产签名和发布流程 |
| \`.github/workflows/upstream-event-router.yml\` | 处理上游事件并路由到相应验证/构建工作流 |

具体触发器、输入名、权限、条件表达式和 Job 依赖以工作流文件本身为准；不要仅依靠本表推断某个事件一定会触发。

## 2. 普通 CI

Pull Request 或受支持的 push / 手动触发首先进行变更分类：

- 所有变更都属于文档类时，运行轻量的文档变更摘要，不执行无关的完整构建、资格验证、生产签名或发布。
- 任何功能或有歧义的变更都会进入功能性验证。
- 不得通过忽略错误、放宽契约或错误设置路径过滤，让必需检查变成永久 Pending。

## 3. Nightly

Nightly 用于跟踪配置的上游测试分支，验证新上游变化是否仍能通过当前补丁和构建流程。它是开发/兼容性信号，不等同于 Stable 发布。

- 上游 ref 会被解析为准确 SHA。
- 已有验证结果和强制重建选项决定是否需要重复构建。
- 实验目标应明确启用，且不得自动提升为 Stable 必需目标。
- Nightly 产物不能被描述为经过生产签名的 Stable 产物。

## 4. Stable 资格验证与发布

Stable 发布以**准确自定义提交 + 准确上游 Stable 版本/SHA + 当前补丁集身份**为约束。

~~~text
解析 Stable 上游
       ↓
Draft / Revision 预检
       ↓
检查同一自定义提交的 CI Qualification
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

1. 不要把某个提交的资格记录用于另一个自定义提交或另一个上游 SHA。
2. 预检发现同版本/同 revision 的既有产物时，应按门禁结果处理；不要手动覆盖或删除来绕过防重。
3. Dry-run 不应被描述为发布成功。
4. Draft 和正式 Release 是不同操作；正式发布必须明确授权。
5. 生产签名属于受保护的单独 Job，不是普通构建的一部分。

## 5. 推荐的 Stable 操作顺序

1. 确认待发布的自定义提交已合并且工作树/提交身份准确。
2. 在 CI Workflow 中对目标 Stable 上游版本执行资格验证。
3. 等待所有必需目标、产物验证、聚合和资格 Job 成功。
4. 在 Stable Release Pipeline 中选择准确的上游 ref 和所需的 release mode。
5. 首次验证发布逻辑时使用 dry-run；确认门禁、目标 revision 和产物身份正确后，才按实际需求创建 Draft 或发布。
6. 如涉及 Android 生产签名，额外确认专用 Runner、Environment、授权输入和证书身份门禁。
7. 记录最终 Workflow URL、commit SHA、上游 SHA、patchset 和发布结果。

若工作流输入或触发方式发生变化，先阅读 \`ci.yml\` / \`tag.yml\` 中的当前 inputs，再按实际界面操作。

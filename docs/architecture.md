# 系统架构与设计原则

## 1. 项目定位

RustDesk Custom 是上游 RustDesk 的维护、构建、验证和发行仓库，不是保存完整上游源码副本的长期 Fork。仓库通过受审查的补丁集表达自定义修改，并针对固定的上游提交执行构建和发布。

## 2. 总体数据流

~~~text
官方 RustDesk 上游
       │ 固定 ref / commit SHA
       ▼
上游解析与兼容性检查
       │ 选定 patchset
       ▼
准备源码（校验上游身份、子模块、补丁和清洁状态）
       │ Standard / SOS 独立源码树
       ▼
平台矩阵与构建适配器
       │ 每个 target 的构建产物与 build-info
       ▼
产物、架构、校验和、来源与配置验证
       │
       ▼
聚合与 CI Qualification
       │                         ┌─ Android 生产签名（仅显式授权）
       └─────────────────────────┤
                                 ▼
                         Stable Draft / Release
~~~

每个阶段只负责自己的输入、输出和校验。构建完成不代表资格验证成功；资格验证成功也不代表已经发布。

## 3. 仓库分层

| 路径 | 职责 |
| --- | --- |
| `.github/workflows/` | 工作流编排、条件、权限、依赖关系和产物传递 |
| `.github/actions/` | 可复用的具体 Action 实现 |
| `scripts/upstream/` | 上游解析、补丁集选择及补丁身份校验 |
| `scripts/source/` | 获取源码、应用补丁、准备并验证源码树 |
| `scripts/build/` | 各平台/变体的构建入口和配置 |
| `scripts/platform/` | 平台适配、构建执行、打包与产物验证 |
| `scripts/release/` | Channel 身份、资格验证、产物聚合和发布门禁 |
| `scripts/signing/` | Android 身份检查、签名配置及生产签名辅助逻辑 |
| `scripts/validation/` | 仓库结构、兼容性和配置契约 |
| `metadata/` | 平台、发布、上游和签名等机器可读事实来源 |
| `patchsets/` | 经审核的自定义补丁集 |
| `tools/` | 开发与维护辅助工具 |

## 4. 身份与可追溯性

一次可审计构建至少要能关联：

- 上游仓库、上游 ref 和解析后的 40 位 commit SHA；
- 选中的 patchset 及补丁内容哈希；
- Standard / SOS 变体及目标平台、架构；
- 自定义仓库提交 SHA；
- 构建运行身份、产物校验和与验证结果。

不能只用版本号、分支名或产物文件名来证明来源。分支名可以移动，版本号也不能唯一标识提交。

## 5. 事实来源优先级

- 平台是否启用、是否必需、支持状态：`metadata/platform/matrix.json`。
- 上游平台构建参数的审查记录：`metadata/platform/adapter-profiles.json`。
- Android 包名和证书身份记录：`metadata/signing/android-standard.json`；执行时还要检查签名工作流实际引用的 YubiKey 身份元数据。
- 发布身份：以当前代码实际读取的 `metadata/release/identity.json` 为准。
- 运行行为：以对应脚本、Reusable Workflow 和调用方条件为准。

文档不得复制一份容易过期的配置当作第二个事实来源。

## 6. 失败关闭原则

来源 SHA 不匹配、补丁不能应用、产物来源不完整、目标平台不在审查矩阵、包名/ABI/证书不符合预期时，应停止流程。不能通过忽略错误、降低契约要求、替换签名身份或手工伪造验证结果来“修复”流水线。

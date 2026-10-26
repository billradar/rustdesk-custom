# CI/CD 架构流程

[English](ci-cd-flow.md) · [简体中文](ci-cd-flow-zh.md)

## 1. 事实来源规则

- 官方上游 SHA 是源码身份。
- Patchset 表示应用到该上游源码上的定制代际。
- 版本号标识上游发行版本。
- 自定义仓库 SHA 用于来源追踪，不是 Stable 资格门禁。
- CI Qualification 独立验证兼容性；Stable CD 不消费 CI Qualification 产物。

## 2. 功能流程

~~~text
官方上游 / 请求输入
        │
        ▼
解析上游 → 选择 patchset → 检查兼容性
        │
        ▼
准备 Standard / SOS 源码
        │
        ├── CI Qualification：记录准确源码身份和验证结果
        │
        ├── Stable CD：独立执行预检、构建、签名、聚合和发布门禁
        │
        └── Nightly：使用官方成功运行对应的固定 SHA
~~~

各通道的成功条件彼此独立。CI Qualification 是证据，不会自动启动 Stable 构建或发布。

## 3. Stable 发布 DAG

Stable 流程先解析来源并执行 Draft/revision 预检。需要新产物时，再准备源码并并行运行 Windows、Linux/macOS 和 Android 构建；随后执行 Android 生产签名、聚合验证和发布。

~~~text
Resolve → Preflight → Prepare → [Windows | Linux/macOS | Android]
         → Android Sign → Aggregate → Publication
~~~

如果已有完整且身份匹配的 Draft，经过预检后可沿专用路径发布该 Draft。任何已有发布信息或资产不匹配时均停止，不覆盖产物。

## 4. Nightly 与 CI

- **Nightly**：解析官方成功 Nightly 运行，绑定其固定 SHA，然后执行兼容性、准备源码、构建、聚合及配置所要求的签名/草稿门禁。
- **CI Qualification**：变更分类、来源解析、兼容性验证和资格记录。

## 5. 通道隔离

CI Qualification、Stable CD 和 Nightly 是独立流程。Stable 构建或发布不得依赖 CI qualification 产物、`compat-check.yml` 或 `verify_source.py`；Stable 资格使用准确上游 SHA、经过验证的 patchset 和版本身份。

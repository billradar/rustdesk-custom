# GitHub Actions Summary Dashboard

Summary 是展示层，不参与补丁选择、构建成败、资格、恢复次数、签名授权或发布判定。公共渲染器位于 `scripts/validation/summary.py`；只读证据收集器位于 `summary_dashboard.py`。

## 展示结构与数据来源

- **总览**：读取 GitHub Run/Jobs API 的实际名称、结果、Run ID、Attempt、Commit、成功/失败/跳过/取消数量，以及创建至最后 Job 完成的墙钟耗时。耗时包含等待与部分重跑之间的间隔。运行中快照按采集时刻计算，并显示 RUNNING，不提前声明最终通过。
- **构建目标与上游**：目标来自真实 Job 名称；上游版本/SHA 来自同一运行的 discovery/Stable lock Artifact。锁文件须匹配运行 ID 和自定义仓库提交；不以当前最新上游版本替代该运行的固定来源。
- **兼容性**：按 Standard/SOS 合并同一 SHA、patchset 的实际 JSON 报告，分别列出 Patch Apply、Rust Compile、Flutter Analyze、Build System、SDK Preflight 和 Overall Compatibility。原有 JSON 字段继续保留，并补充实际失败的检查项。
- **恢复**：仅接收真实恢复控制器产生的决策，包括故障 Job、分类、选中的 Job、当前 Attempt、作出决策的 Attempt、既定最大次数及是否需要人工处理。发起重跑后，两种 Attempt 可能不同，因此分别显示。展示不额外派发重试。
- **契约测试**：模拟场景仅保留完整控制台日志。测试运行期间隔离 `GITHUB_STEP_SUMMARY`，测试结束后根据 unittest 的真实结果写入一张计数卡；失败原因折叠显示，不生成正式恢复卡片。

同一 Step 中，同一 section key 会替换旧内容，而不是重复追加。prepare 成功阶段等待后续实际 Rust/Flutter 阶段生成概要；prepare 失败仍立即展示失败。JSON、变更文件和诊断放在 `<details>` 中，超过显示大小限制时保留 Artifact 为完整证据来源。

## 状态含义

| 状态 | 含义 |
| --- | --- |
| PASS | 有实际成功执行证据 |
| FAIL | 有实际失败证据 |
| WARNING | 有明确告警，例如构建接口文件变化或 Flutter 非致命 warning |
| NOT RUN | 未执行或缺少足够证据；绝不推断为通过 |
| SKIPPED | 有明确跳过记录 |
| RUNNING | GitHub API 显示仍在执行 |

Rust Compile 指已有的真实配置 Rust probe，不代表完整客户端编译。桌面兼容性流程没有执行 Android SDK 预检时，该项为 NOT RUN；需要全部列出检查的 Overall Compatibility 不会因此显示为 PASS。原有 workflow gate 的结果单独列出，判定表达式保持不变。

CI 原运行最后的 Dashboard Job 提供运行中快照。这个新增的纯展示 Job 是 advisory，失败仍可在日志中查看，但不改变已有构建和资格门禁；原有检查 Job 不使用该豁免。Workflow 完成后的最终 Dashboard 由 `build-reliability.yml` 的只读 `ci-dashboard` Job 展示；它从 main 检出代码，只有 contents/actions read，无恢复或签名权限。该 Job 不进入原有 Tag/Nightly 恢复路径。观察 Workflow 必须先存在于 main，新增后不会主动扫描历史运行。

Stable/Nightly 的实际恢复任务继续使用原来的受保护来源与权限。其原始 `report.json` 保持保留，补充的 dashboard evidence 单独保存。现有兼容性 JSON、MD、log 与诊断 Artifact 均保留。专用硬件签名 smoke Workflow 的授权、稀疏检出和签名执行边界不变。

## 安全与兼容性

渲染仅使用标题、表格、Unicode 图标和 GitHub 支持的 details/summary/pre 子集，无 CSS、JavaScript 或外部图片。动态单元格转义 Markdown 和 HTML 特殊字符，移除危险控制字符；详细 JSON 按 HTML 文本转义。下载的 Artifact 只读取 JSON 数据，限制大小、路径和固定文件名，不导入或执行其中代码。

API 不可用或缺少数据时展示缺失/NOT RUN 提示，不伪造 0 个失败或 PASS。渲染和 Summary 文件写入异常不覆盖原有命令退出码、JSON 或恢复判定。

验证入口：

```bash
PYTHONPATH=. python3 -m scripts.validation.summary_contract
PYTHONPATH=. python3 -m scripts.validation.build_reliability_contract
python3 scripts/validation/repository_contract.py
```

模拟隔离、真实字段合并、Markdown/HTML 转义、去重、缺失数据、UTF-8 路径、Flutter warning、原失败退出码保留及只读观察器权限均有契约测试；现有 CI 域契约继续执行。

# 三条旧 Nightly 来源补证核查

核查日期：2026-11-03（北京时间）。线上 main 仍为
`95abfaf706766f670dddcecea41530320c0ebb66`；实现审查基线为 PR #178 的
`35905fec1668c1c526dd7f0836ea235ac5c13d88`。

**结论：三个上游 SHA 已确认，先前“来源不可恢复”的描述需要修正。**
此前清点只选取现代 Nightly Discovery / Stable Lock 类型的身份 Artifact，
遗漏了仍可下载的旧式 `channel-discovery` 和 `channel-validation`。
不是这些运行没有留下来源证据。旧报告与 v1 目录保持冻结，新证据独立留档。

| 历史运行 | 事件 | 已确认上游 SHA | 证据交叉核对 |
| --- | --- | --- | --- |
| [36872771101](https://github.com/billradar/rustdesk-custom/actions/runs/36872771101) | workflow_dispatch | `fada664df7a294d1d1a9ca3e7cd3637069122f17` | resolve 输出、兼容性 checkout、prepare checkout、discovery/validation JSON |
| [37185958897](https://github.com/billradar/rustdesk-custom/actions/runs/37185958897) | schedule | `e5bc204fe4dacc4db9c3cdb1f1338813986c89e7` | 同上；另有 platform aggregate |
| [37279734509](https://github.com/billradar/rustdesk-custom/actions/runs/37279734509) | schedule | `e5bc204fe4dacc4db9c3cdb1f1338813986c89e7` | 同上；另有 platform aggregate |

## 已执行的证据验证

- 重新读取 run attempt 1：仓库、head repository、main、workflow 路径、custom SHA、事件、完成状态和 success 结论均匹配既有清单。
- 读取各运行 resolve、compatibility resolve 和 prepare 三个任务的日志，SHA 一致；只归档白名单 SHA 行，不保存原始日志或凭据。
- 下载并逐字节核对 16 个仍未过期的 ZIP，全部与 GitHub Artifact SHA-256 相符。归档 JSON 原文及其 SHA-256 保存在下方机器可读证据中。
- 对三个 custom repository 历史提交分别读取 v2 补丁，以当时 `scripts/patchsets.py` 的文件名加 NUL、CRLF 规范化算法重新计算 Common/SOS 内容摘要，全部与各自 channel-validation 相符；未使用当前补丁代替历史补丁。
- 三个 channel-validation 均记录 PASS、channel=nightly、patchset=v2、signing=NOT ENABLED。后两个 aggregate 记录当时 13 个目标 PASS；第一个运行只有 Windows Standard/SOS 两个实际原生构建任务。未据此宣称今天的矩阵或原生包通过验证。

三者共有的历史补丁摘要：

- Common：`a62750763d0ddec4f8f0358b20060db7734ef9e2b7a84cbc400b7a38c2f2c8e7`
- SOS：`076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`

完整数据：[evidence.json](audits/coordinator-nightly-source-recovery-20261103/evidence.json)。
该文件保留每个 Artifact ID、所属 run/custom SHA、ZIP digest、JSON 原文摘要、
历史代码文件摘要、重新计算的补丁摘要及经过筛选的日志行。
SHA256SUMS 仅记录原文摘要；本次没有据其重新下载或逐项验证所有原生安装包。

## 为什么仍不能直接变成现代成功身份

历史 workflow 在各自 custom SHA 调用 `scripts/phase4.py resolve --channel nightly`。
当时的实现直接解析官方 default branch 的 tip（运行时为 master），没有先选择
“最新成功的官方 flutter-nightly run”。不能补造一个 official run ID 来重写其来源。

这些 workflow 是旧版 Development artifacts 路径，未提供现代 release_mode 输入，
历史工作流树中也没有 Wayland 工作流。签名报告及任务元数据没有显示执行生产
签名：36872771101 没有 signing job；37185958897 的 android-sign 被跳过；
37279734509 的 signing-preflight 被跳过。本次未下载 APK 验证证书，不把这些事实
扩展为现代 Android v2/v3 签名或发布门禁通过的声明。

因此，**Source Identity 的 SHA、patchset 和 Common/SOS Hash 已补证；现代完整
Build Identity/发布用途的兼容映射仍需独立审查。** 不把旧的 artifact-only 行为
自动填成今日的 draft、release 或 dry-run，更不将其导入为伪造的 Worker SUCCEEDED。

## 对阻断范围的实际影响

补证足以支持下一份受审查的迁移变更：保留 REVIEW_REQUIRED，只将三条记录的
“整个 Nightly 渠道阻断”收窄到上述各自的准确上游 SHA。相同旧来源仍须审核，
其他来源继续经过原有 Artifact、Coordinator、签名和发布门禁。

**本报告没有执行这项迁移。** 原始审计、source-rows pin、v1 catalog 与其运行时
判定均未改变，三条全局阻断目前仍存在。后续应使用独立、追加式 resolution schema
绑定本报告的证据摘要及审核来源；不得直接编辑冻结的旧行或修改测试断言放行。
没有合并 PR、运行构建/签名、改动 Release 或写入生产状态。

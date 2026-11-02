# Release Coordinator 上线前保护核查与历史迁移方案

核查日期：2026-11-02。权威线上基线：`95abfaf706766f670dddcecea41530320c0ebb66`；实现审查基线：PR #173 的 `b442d1de6ab84de23de478f09ced993f1bee1d5f`。本报告是只读审计及迁移设计，不是生产状态，也不是重试授权。

## 实际核查结果

| 项目 | 证据及结论 | 状态 |
| --- | --- | --- |
| main 保护 | ruleset `24412604` 活跃；目标仅 `refs/heads/main`；禁止删除、非快进；要求 PR、解决评审线程；无 bypass；必需审批人数为 0 | 已核查；不更改现有主分支规则 |
| 状态日志保护 | 包含父级的 ruleset 清单只返回上述 main 规则，没有匹配生产 journal 的 ruleset | 待应用专用保护；登录后的经典保护页面未列出任何规则 |
| 运行索引保护 | 同一 ruleset 清单没有匹配生产 run-index 的规则 | 待应用不可变索引保护 |
| 签名 Environment | 公开只读 API 读取到 `android-production-signing`；custom branch policy 唯一记录为 branch `main`；`can_admins_bypass=false` | 已核查 |
| 人工审批 | Environment 的 protection_rules 只含 branch_policy，未列 required_reviewers/wait_timer | 当前允许 main 自动签名的既有语义；本次不擅自增加审批门禁 |
| 签名隔离 | 对 main 与待合并实现的 Tag/Nightly YAML 均核对：相同 Environment、6 个专用标签、同一硬件 concurrency、唯一签名步骤绑定 PIN；源码 SHA-256 在清单中 | 结构核查通过；没有读取任何密钥值 |
| 实际 Runner | 最新 Stable/Nightly 成功签名任务使用 `raspberrypi-rustdesk-signing`，runner_id=21，group=`Default`，标签包含 self-hosted/linux/arm64/rustdesk-signing/android-signing/yubikey | 历史分配与当前管理页面均已核查；当前 Idle、没有运行任务 |
| Runner 访问控制 | 登录后的管理页面确认仓库级 Runner 及标签；Runner 详情按 runs-on 标签调度；Actions Policies 显示未创建策略，未显示专属工作流白名单控制 | 仓库 UI 核查完成；硬件宿主隔离及工作流专属限制不能仅凭标签证明 |
| 经典分支保护 | 登录后的 Branch protection rules 页面仅显示新增入口，未列出现有经典规则 | 已核查；现有 main 保护来自 ruleset |
| 默认 Actions 权限 | Read repository contents and packages；创建/批准 PR 选项未勾选 | 已核查，保持只读默认值 |
| fork PR 审批 | Require approval for first-time contributors 已选中，all external contributors 未选中 | 已核查；不是所有外部贡献者都要求审批 |
| Actions 来源与保留 | Allow all actions/reusable workflows；强制 full-SHA pinning 未选中；保留 90 天 | 已核查；不更改现有设置 |

Environment 原始只读端点：`GET /repos/billradar/rustdesk-custom/environments/android-production-signing` 及其 `/deployment-branch-policies`。无需提高普通 CI 权限即可核查这些公开配置。早先匿名管理 API 的 401 仅代表请求未认证；用户完成登录后，已从管理页面补齐以上 UI 核查，不再以登录为阻塞。

## 两份可审阅保护配置

- [journal-protection.proposed.json](audits/coordinator-preactivation-20261102/journal-protection.proposed.json)：仅匹配生产 Stable/Nightly journal；禁止删除和非快进；保留正常创建、快进更新。
- [run-index-protection.proposed.json](audits/coordinator-preactivation-20261102/run-index-protection.proposed.json)：仅匹配生产 run-index；允许创建，禁止更新、删除及非快进；无 bypass。

**这两份 JSON 尚未应用。**连接器没有规则写入能力。不得给 journal 加 `pull_request`、`required_signatures`、禁止所有 update 或限制 creation：这些会阻断当前 GitRefStore 的直接原子追加。索引独立设置 update 限制，不覆盖 journal。规则依据：[GitHub repository rules REST schema](https://docs.github.com/en/rest/repos/rules)。应用前后先在隔离测试命名空间验证等价规则下的创建、允许的快进及预期拒绝，不能把无规则环境中的已通过测试当成受规则保护后的兼容性证明。

## 完整历史清点

- 7 页、650 条仓库运行，650 个唯一 ID；其中主分支 Tag/Nightly 共 25 条。
- 逐项读取历史 attempts 后为 34 次：9 次额外旧尝试中有 4 次取消、4 次失败、1 次成功。最新 25 条均为 success，不能据此抹去旧失败。
- 完整读取 951 条 job 记录，含历史 attempt；一个 94-job 运行的大页请求超时后改为 30 条分页，已完成计数及唯一性核对。
- 31 个 workflow attempt 有已执行的真实编译步骤；另有 3 条 Stable preflight 明确 `build_needed=false` 且无执行编译，真实构建尝试为 0。
- 下载 25 个小型 Lock/Discovery/Preflight ZIP；全部 SHA-256 与 GitHub Artifact digest 相符。归档 JSON 已逐字节重建并与原文件 SHA-256 核对，完整内容保存在清单的 `archived_document_utf8`，不依赖未来 Artifact 继续存活。
- 已删除的运行不可从当前历史证明；本报告不把“列表里没有”当成从未构建。

详见 [机器可读清单与原始身份文档](audits/coordinator-preactivation-20261102/migration-plan.json)。该清单所有记录的 `automatic_retry_allowed`、`ledger_import_allowed` 均为 false。

| 运行 | 渠道 | 最新 attempt | 有真实编译的 attempts | 早期尝试结论 | 迁移处置 |
| --- | --- | --- | --- | --- | --- |
| [41422335564](https://github.com/billradar/rustdesk-custom/actions/runs/41422335564) | nightly | 1 | 1 | 无 | 身份已验证，保留成功去重 |
| [41398573672](https://github.com/billradar/rustdesk-custom/actions/runs/41398573672) | stable | 1 | 1 | 无 | 身份已验证，保留成功去重 |
| [41292973439](https://github.com/billradar/rustdesk-custom/actions/runs/41292973439) | nightly | 2 | 1,2 | 1:cancelled | 身份已验证，保留成功去重 |
| [41289240322](https://github.com/billradar/rustdesk-custom/actions/runs/41289240322) | stable | 1 | 1 | 无 | 身份已验证，保留成功去重 |
| [40924598685](https://github.com/billradar/rustdesk-custom/actions/runs/40924598685) | nightly | 2 | 1,2 | 1:failure | 身份已验证，保留成功去重 |
| [40737839195](https://github.com/billradar/rustdesk-custom/actions/runs/40737839195) | nightly | 2 | 1,2 | 1:failure | 身份已验证，保留成功去重 |
| [40647868248](https://github.com/billradar/rustdesk-custom/actions/runs/40647868248) | stable | 1 | 无 | 无 | 未构建，复用原产物 |
| [40550247760](https://github.com/billradar/rustdesk-custom/actions/runs/40550247760) | nightly | 1 | 1 | 无 | 身份已验证，保留成功去重 |
| [40510561738](https://github.com/billradar/rustdesk-custom/actions/runs/40510561738) | stable | 1 | 1 | 无 | 历史身份待审核 |
| [40454023730](https://github.com/billradar/rustdesk-custom/actions/runs/40454023730) | nightly | 1 | 1 | 无 | 历史身份待审核 |
| [40453508604](https://github.com/billradar/rustdesk-custom/actions/runs/40453508604) | stable | 1 | 1 | 无 | 历史身份待审核 |
| [40323682122](https://github.com/billradar/rustdesk-custom/actions/runs/40323682122) | stable | 3 | 1,2,3 | 1:cancelled, 2:cancelled | 历史身份待审核 |
| [40307813132](https://github.com/billradar/rustdesk-custom/actions/runs/40307813132) | nightly | 2 | 1,2 | 1:cancelled | 历史身份待审核 |
| [40281097212](https://github.com/billradar/rustdesk-custom/actions/runs/40281097212) | nightly | 1 | 1 | 无 | 历史身份待审核 |
| [38111020257](https://github.com/billradar/rustdesk-custom/actions/runs/38111020257) | stable | 3 | 1,2,3 | 1:failure, 2:failure | 历史身份待审核 |
| [37657952527](https://github.com/billradar/rustdesk-custom/actions/runs/37657952527) | stable | 1 | 1 | 无 | 历史身份待审核 |
| [37612132102](https://github.com/billradar/rustdesk-custom/actions/runs/37612132102) | stable | 2 | 1,2 | 1:success | 历史身份待审核 |
| [37558994519](https://github.com/billradar/rustdesk-custom/actions/runs/37558994519) | stable | 1 | 无 | 无 | 未构建，原身份待审核 |
| [37554194185](https://github.com/billradar/rustdesk-custom/actions/runs/37554194185) | stable | 1 | 无 | 无 | 未构建，原身份待审核 |
| [37310654296](https://github.com/billradar/rustdesk-custom/actions/runs/37310654296) | stable | 1 | 1 | 无 | 历史身份待审核 |
| [37279734509](https://github.com/billradar/rustdesk-custom/actions/runs/37279734509) | nightly | 1 | 1 | 无 | 历史身份待审核 |
| [37193423254](https://github.com/billradar/rustdesk-custom/actions/runs/37193423254) | stable | 1 | 1 | 无 | 历史身份待审核 |
| [37186687889](https://github.com/billradar/rustdesk-custom/actions/runs/37186687889) | stable | 1 | 1 | 无 | 历史身份待审核 |
| [37185958897](https://github.com/billradar/rustdesk-custom/actions/runs/37185958897) | nightly | 1 | 1 | 无 | 历史身份待审核 |
| [36872771101](https://github.com/billradar/rustdesk-custom/actions/runs/36872771101) | nightly | 1 | 1 | 无 | 历史身份待审核 |

### 当前最重要的两条成功身份

- Stable `41398573672`：Artifact 的 Stable v4 digest 为 `0d5dd098c5ce4211570ace802496f331fa90fd431969b692b0aa21e9a5b9859e`，新键为 `e3fc1025a3af8830537446ecf5aa5218e42185de65d10a1b1dbd38f275233d48`。保留其成功去重，不重建。
- Nightly `41422335564`：新键为 `c46008d9ac6d7e56accc4c1e295e841efd2cf8c1db69b12b085dfe779164cf1b`，上游为 `23e5bb471a040d62f0a6ad52591fb30784265b73`，对应的官方成功 Run `41366206478` 的仓库、workflow、master、事件与 SHA 均已再次核对。保留成功去重。

共 7 个真实成功构建的完整身份及 1 个未构建复用记录的身份可映射；15 个已构建历史记录、2 个未构建记录仍缺少完整身份信息，保留人工审核。缺少字段通常来自旧版 Lock/Discovery 契约，不能用今天的 patch hash、签名开关或 Wayland 策略填补。

Nightly `41292973439` 的原官方 Run `41280309181` 现返回 404。它的归档 SHA 可由另一个官方成功 Run `41366206478` 佐证；保留原来源 ID 和不可用标记，不能仅因为 Run ID 消失而改变 Build Identity。该原始 provenance 在最终导入前仍需审核。

### 必须特殊处理的记录

- `40647868248`：preflight 复用 `v1.5.0-custom.v2.5`，没有编译。其 Lock 绑定当前运行的 custom SHA，而 preflight 指向原产物的 custom SHA；这符合复用语义，不伪造新 producer。当前 Release 清单没有该 v2.5，原 producer/产物关系需人工补证；不算一次失败或构建。
- `37558994519`、`37554194185`：同样无编译、preflight 复用旧 `custom.1`，但没有完整现代身份。两者均为零构建尝试并保持身份审核。
- `38111020257` 的 attempts 1、2：实际失败步骤是 `Production Android signing`；分类为生产签名失败，禁止自动重试。attempt 3 已成功；不能再对历史失败发起补偿构建。
- `40924598685`、`40737839195` 的 attempt 1：可定位到 Android 目标失败；未读取足以证明基础设施故障的日志，因此分类未知，不能自动重试。
- 4 次早期取消：保留取消，不自动重试。另一个旧成功 attempt 不会重置后续累计实际构建数。

## 现有三个 Draft

读取到 `v1.5.1-custom.v2.1`（431170313）、`nightly`（431350507）、`v1.5.0-custom.v2.6`（430489827）。三个均为 Draft、各 32 个附件，元数据声明 complete；声明的文件名清单与 API 附件清单一致，附件有非空大小及 GitHub SHA-256。

这只是清单层核验，**没有下载 SHA256SUMS 正文或所有安装包**，因此不能宣称全量摘要复核或生产签名重验通过。后续复用与发布仍必须执行原来的远程摘要门禁。两个 Stable Draft 的真实 tag_name 为 untagged，canonical revision 在 name；现有 channel.release_tag_name 已支持这种情况，不重命名、不覆盖、不删除。

## 分阶段迁移实施方案

1. 应用并验证专用 refs 保护；仓库级 Runner/Actions 配置已核查，仍须独立评估硬件宿主隔离及工作流专属限制，不更改现有签名/发布语义。先安排 cutover 窗口暂停两个 Router 和新的手动构建，再重新清点真实排队/运行任务。此次只读快照没有活动构建，但不能把快照结论永久沿用。
2. 重新抓取元数据，与本清单的 run ID、attempt、custom SHA、Artifact digest 和 JSON digest 对比。有新增运行、rerun、Artifact 缺失或内容冲突即停止迁移；不使用 created_at 计算完成或冷却。
3. 分开保存 legacy 成功证据、未构建复用关系、未知身份及旧失败/取消。旧失败不能覆盖后来已验证成功；未构建记录没有自己的 producer，不能导入为一次成功构建或失败尝试。
4. 当前实现尚无经过评审的 legacy alias/import 接口。因此本清单**不能直接写进生产 journal**，也不能伪造 UUID、fence、run_attempt=1 或 Worker 来制造 SUCCEEDED。原有 Artifact 恢复路径仍是权威兼容入口，未知历史继续 fail-closed。
5. 若需要消除历史 Artifact 过期依赖，另开迁移实现 PR：引入只读、版本化且受保护的 legacy evidence/alias 记录，明确绑定完整身份、来源 run/attempt、原始 JSON/ZIP digest、结果证据及审核者；与当前预约/worker 状态分离。仅成功证据阻止重复构建，不发放签名或发布授权；未知证据只能阻止/送审。为 alias 配置独立不可变保护，并测试篡改、重复导入、并发、过期 Artifact 和 native rerun 兼容性。该接口尚未实现，本报告不将其记为完成。
6. 对 7 个身份已验证的成功构建先审核归档；对 3 个未构建记录补查原 producer；所有 17 个缺完整身份的记录（含上述 2 个未构建记录）保持审核，不以人工批准重试代替身份验证。只有完整身份已闭环的任务才可另走单次人工重试授权；所有安全门禁继续有效。
7. 迁移后先做不签名、不发布的受控验证，再按明确授权启用生产 Router。Stable 仍跟随最新官方版本、不自动补历史；Nightly 仍只跟随最新成功官方源，历史取消和失败不会触发过时 Nightly 补建。

## 回滚与验收

本 PR 仅增加文档、只读证据和未应用的保护配置，不改变运行行为。回滚只需撤回本 PR，不能删除原 Release、Tag 或生产状态。真正 cutover 的回滚是停止新准入、保留日志/索引/别名、对账活动与未知派发，再逆序撤回接入代码。不得通过删除状态或放宽断言恢复调度。

验收仍有三个条件：实际应用并验证生产 ref 保护；独立评估 Runner 的工作流专属限制和硬件宿主隔离（仓库 UI 与经典保护已核查）；单独评审并实现需要的 legacy alias 导入。未完成前不宣称生产迁移已结束。本次没有合并 PR、触发构建/签名/发布、写入生产状态或读取 PIN。

### 已登录管理页面补充核查

用户完成登录后，已实际打开 Runner 列表/详情、Branches、Actions General、Actions Policies 页面。账号为 billradar。当前签名 Runner 在线空闲，六个标签与配置相符；经典保护没有列出规则，Actions Policies 明确显示尚未创建策略。默认令牌只读，Actions 创建/批准 PR 关闭，fork 审批仅首次贡献者。没有点击任何 Save、Remove 或新建策略按钮，也没有读取凭据或密钥内容。页面地址、选中值和核查范围记录在 migration-plan.json 的 administrative_ui_followup。

Runner 标签是调度条件，不是专属访问授权的证明。当前 UI 没有展示签名工作流独占白名单，且没有任何新增 Actions Policies；不能据此宣称硬件 Runner 已实现强隔离。建议在受控上线前单独评估是否需要审批所有外部贡献者，以及是否采用受限工作流 Runner 组或独立私有签名仓库。这是待评估的加固选项，不是已经验证的可利用缺陷；本次不擅自更改审批或签名语义。

## 后续隔离保护验证（PR #175）

已创建并经管理 API 确认 Active、无 bypass 的隔离 ruleset：journal `26375171`、run-index `26375414`。真实运行 `41467995091` 通过 3 项正向操作、5 项服务器 422 拒绝/原 head 不变核对及 7 项受保护存储检查。详见 [验证记录](release-coordinator-protection.md)。生产两份配置仍未应用：功能 CI `41467994953` 在官方上游 `6aec306…` 的未知 bridge 构建接口门禁失败，需独立 staging 审查并重新验证；不以修改身份、来源选择或测试断言掩盖失败。

# Patchset 独立版本：历史审计与迁移契约（阶段 1）

审计基线：`main 2b871ad992a62fcac2d39b83e6ad045f3083b916`，2026-11-03。
本阶段提供只读历史映射、可执行碰撞检查和迁移阻塞诊断。**没有激活新版本语义，没有分配 v2.7，没有修改发布或预约行为。**

## 当前版本来源与调用链

| 层 | 真实实现 | 当前语义 |
| --- | --- | --- |
| 官方 Stable | `scripts/upstream/resolve.py` → `choose_stable` | 官方版本、Tag、精确 SHA |
| Generation | `scripts/upstream/patchsets.py` | `<1.5.0` 用 v1，`>=1.5.0` 用 v2；不按 hash/可应用性选择 |
| Patch 内容 | 同文件 `patch_hash` / `verify` | 按文件名排序，逐个拼接 UTF-8 basename、NUL、CRLF→LF 的完整 patch bytes，再计算 SHA256；包含 patch 头、上下文和文件名 |
| Manifest | `patchsets/v{1,2}/patchset.json` | 两者 `revision=1`；当前仅为历史字段，并非 Stable 版本来源；`hashes` 是完整性门禁，validation 是历史证据 |
| Stable 版本分配 | `channel.release_preflight` → `next_patch_revision` | 扫描 Releases 的 canonical tag 或 Draft name，按 **官方版本 + Generation** 取 max+1；相同身份先复用 |
| 旧契约元数据 | `metadata/release/patch-revision-record.json` | 明确写着 Per upstream Stable version and Patch Set；不是持久内容版本账本 |
| 旧生产适配器 | `metadata/release/identity.json` → `production.py` | legacy numeric revision=1；不得误当当前 Patchset Revision |
| Stable 冻结 | `tag.yml` → `stable_lock.plan/create/read/preflight` | 精确 custom/run/source/options、hash、Stable v4 Identity；下游复验 digest 和锁内容 |
| Stable Router | `upstream-stable.yml` → `stable_router` → coordinator runtime | latest 官方选择、现有版本保护、共享原子预约；不授权公开发布 |
| Stable 发布 | `qualification._release` / `publish_existing` → `stable_tag` | 配对源、完整矩阵、校验、签名、远端摘要、不可变 ref 和 Draft；现有同 Tag 异 Identity 拒绝覆盖 |
| Nightly | `upstream-nightly.yml` / `nightly.yml` → `nightly.discover` → coordinator | resolve 时最新成功官方 flutter-nightly；默认分支/事件/仓库/workflow/SHA 核验；不读取 manifest revision；不应添加公开固定 run/SHA 入口 |
| 客户端 | `prepare-source.yml` → `source/update_identity.py`；common/0005 patch | Stable revision 从 preflight 注入；About display-only；CI/Nightly revision=null；更新按官方三元组优先、同官方版本按 Generation/Revision 数值比较 |
| 产物 | `release/naming.py`、qualification、platform/Wayland | 保留原生版本和平台命名；Standard/SOS 与 Wayland flavor 单独校验 |
| Release Notes | `qualification.build_release_body`；`nightly.draft` | 官方正文 + 机器元数据；当前没有独立 Patchset Changelog |

完整补丁 SHA256 算法已经确定性规范化 CRLF，不应在迁移中无声改成只 hash diff hunk 或剥离上下文。那会改变现有 provenance 的含义。

## PR #110 与 #111

- [#110](https://github.com/billradar/rustdesk-custom/pull/110)，merge `61f97f854ad1a4dc22700d8ce1d19aa0c0a25028`：建立扫描 Releases 自动分配、immutable revision、Build Identity 复用、从 GitHub `untagged-*` Draft 的 `name` 恢复 canonical tag。最终 `custom.vP.R` 的 R 是官方版本内发布分配号，不是内容计数。
- [#111](https://github.com/billradar/rustdesk-custom/pull/111)，merge `ce6e2c93e87899a9cdd4f01e7241d6f5013f7569`：除了迁移 stale qualification Draft 测试，还将错误的 `PATCH_REVISION_RE` generation 检查改为 `PATCHSET_RE`。PR 描述声称仅测试修复，但真实 diff 包含 `channel.py` 的生产解析修复；审计以 diff 为准。
- 当前 main 已包含 Coordinator 后续系列至 #191。初次 REST `/pulls?state=open` 和连接器搜索均为空，不能把已合并 Coordinator 当作未来计划另行重写。
- `development` 对 main ahead 36 / behind 43，merge-base `7ad28419caf5a68098b722a9df1addd12991d521`，82 个文件有差异。按用户明确要求独立阶段 PR，从最新 main 创建本阶段分支，不 reset/rebase/覆盖共享 development。

## 历史映射与证据等级

机器快照：`metadata/release/patchset-migration-audit.json`。REST Releases 完整分页返回三条，均为 Draft，没有 Published Release。Git tags 为下面两个 Stable 加 moving `nightly`。这只证明观察时可见的库存，不能证明历史上从未发布/删除过其他记录。

| canonical 名称 | 分配语义 | 内容身份 | Git / Release 证据 |
| --- | --- | --- | --- |
| v1.5.0-custom.v2.5 | 旧官方版本内发布分配 | Common `7bfc16729d9d16fbd289ddb6de9b6f98b1e86ea38869273a69416a7e2fb25845`；SOS 见下 | 仅归档 run 40647868248 的 preflight 复用观察；当前无同名 Tag/Release；原 producer 未闭环 |
| v1.5.0-custom.v2.6 | 同上 | Common `c35f6c64abb16565f0018fa068369b2463cfe5067c3dadd0ca1323ac16ad02f6` | Git ref → `bed8113783f8e9da9ae0ae9a4b300f68bc445ddd`；Draft 430489827，tag_name=untagged-1adf51dab8dd95750d11 |
| v1.5.1-custom.v2.1 | 同上，官方升级后重从 1 分配 | Common `ba803951d999a4feacf6d754e263f86ebcabd2f4b53d447abe413259b019416a` | Git ref → `82859cd32d4608e6507314de1cdd5cf9ebb2860c`；Draft 431170313，tag_name=untagged-ae5bef8b7a54e85070ed |
| nightly | moving Nightly，非 Stable revision | 与当前 v1.5.1 Draft 相同 | Draft 431350507；Git ref → `95abfaf706766f670dddcecea41530320c0ebb66`；来源 run 41366206478 |

上述 SOS 都是 `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813`。Stable 官方 SHA 分别为 `fada664df7a294d1d1a9ca3e7cd3637069122f17` 和 `23e5bb471a040d62f0a6ad52591fb30784265b73`。两个 tag 对应 commit 的 manifest 都是 revision=1，再次证明旧 tag 后缀不是 manifest 内容修订号。

早期 `.1`–`.4` 的每个分配到内容身份的完整对应关系没有现存证据，不能补造。既有 Coordinator 归档还记录两次旧 `custom.1` 的无构建复用（37558994519、37554194185），不应解释成现代 generation/content version。

快照保存原 body 的 SHA256 和 API 附件 ID/name/size/digest，不包含临时下载 URL。**未下载验证 SHA256SUMS 或安装包，不声称重新验证生产签名。** 现有远端摘要及签名门禁仍是复用/发布的必要条件。

## 迁移起始版本

v2 的可见旧分配最大值为 6，故 **7 是当前证据下避免旧数字回退的候选下界**；v1 没有已知同格式分配，候选为 1。候选并未写进 manifest，不等同于已经确定的生效版本，不表示它是第七次历史内容修改。

正式迁移须固定 cutover custom SHA、旧只读映射 digest、每代 baseline hashes、初始 revision 和 reviewed baseline Changelog。新记录使用显式 `patchset-content-v1` 语义标记；旧 tag 仅通过显式映射识别，未知格式相同的 tag 仍送审。每代新的 baseline 是一次迁移，不虚构之前 N 个语义 Changelog。

仅凭候选 7 不能安全激活：旧分配库存不完整，且持续运行的旧工作流仍可能分配下一个数字。必须在一致切换窗口重新核验全部 Tag/Draft/Release、Coordinator 状态及所有 queued/in-progress workers，旧身份记录保留只读。不能移动 Tag、删除 Release 或改旧签名来消除碰撞。

## 可执行迁移契约

```sh
python3 -m scripts.upstream.patchset_migration
python3 -m scripts.upstream.patchset_migration --check
python3 -m scripts.upstream.patchset_migration_contract
```

普通模式输出确定性 JSON 历史诊断；`--check` 当前预期返回 **1 / BLOCKED**，输入非法返回 2。没有修改远端或分配版本的模式。`classify` 不按正则赋予新语义；`target_available` 同时识别 Git tag、Draft name 和归档已消费名称，离线无冲突也不授权发布。该检查尚未接入生产工作流，不能声称现有自动发布已经暂停。

11 个测试覆盖旧 Draft/Tag/归档碰撞、跨官方版本 floor、未知同格式 tag、元数据不一致、重复记录、自激活拒绝、JSON/退出码，以及当前共享 Identity 的 A→B→A 碰撞。后者是必须消除的阻塞证据，不能当成期望长期保留的产品行为。

## 必须先统一的 Coordinator 合约

1. `SourceIdentity` 仅有 upstream SHA、generation、Common/SOS hash、官方 repo，没有 Patchset Revision。A→B→A 在同一官方 SHA 上回到原来的 source/build key，即使内容 revision 已变为 N+2。现有成功终态和 legacy catalog 会阻止新构建，不能绕开它们另写预约器。
2. `BuildIdentity.policy_version=1`，Stable v4 也没有完整工具链/构建策略 digest。工具链、adapter、branding 等可能影响输出却不一定改变 identity。必须定义经过审核的 canonical build-policy inventory，覆盖会影响输出的有效输入，排除 run ID/时间等 provenance，并在 **同一共享** identity schema 中版本化。
3. 需要显式 v2 Identity/Stable Lock 迁移、v1 historical adapter、legacy alias/hold、不可变预约/journal 名字空间的兼容。不得把空新 ledger 当成可重建，未知历史继续 hold。Revision 必须进入适当的共享身份以区分新有效回退；不能只给 release tag 添加后缀。
4. 同 upstream+Patchset Version、不同 build policy 时，Stable 目标 Tag 仍相同，必须在任何昂贵构建/签名前明确 `IMMUTABLE_TAG_BUILD_IDENTITY_COLLISION`，不分配 Release Revision，也不伪造 Patchset bump。
5. 观察到 Nightly worker [41566163005](https://github.com/billradar/rustdesk-custom/actions/runs/41566163005) 仍 in_progress。没有停止或取消它；该事实已足以否定当前时刻是 quiescent cutover。这个观察会过期，必须实时重查，不能靠删除本报告 blocker 激活。

因此此阶段只交付审计与阻塞契约。**尚未达到安全迁移/发布条件。** 不在未解决上述共享协议的情况下接入新 Stable/Nightly reader。

## 后续阶段的具体文件与接口

| 阶段 | 文件 | 实施契约 |
| --- | --- | --- |
| PR 2 | `scripts/upstream/patchset_version.py`、独立 contract、两代 manifest、`patchsets/vN/CHANGELOG.md` 和结构化历史、read-only PR workflow | 以最新 base SHA 为锚；canonical Common/SOS hash 任一变化只 +1；同 PR 多次 bump 始终 base.N+1；无变化不得 bump；历史 append-only；回退 hash 仍 +1；bump 只写本地模板，语义/reason/分类/PR或commit/compatibility/limitations/前后hash 经审核才可通过；base 前进则重算并拒绝过期分配；普通 PR 无写权限 |
| PR 3 前置 | `coordinator/identity.py`、runtime/legacy/contracts、`stable_lock.py`、channel identity、legacy catalog 兼容、相关 docs | 在现有原子预约接口统一 Revision + build policy，保留 v1 历史识别和 fence/retry/hold；切换需无活动 worker |
| PR 3 | `channel.py`、`stable_lock.py`、`nightly.py`、`qualification.py`、Tag/Nightly workflow 及相关 contract、patch-revision-record | 版本只读 manifest；相同 Tag+Identity 走现有完整复用；不同 identity 拒绝；共享确定性 Notes renderer：当前功能摘要和本 revision delta 分开；官方变化单独陈述；Nightly 不宣称没有变化的功能为新增，不 bump |
| PR 4 | `source/update_identity.py`、两代 common/0005、client_update_contract、naming/qualification/platform/signing/Wayland/coordinator contracts、AGENTS/docs | 客户端双语义显式识别；官方 numeric tuple 优先，同官方版本 revision 单调；Nightly metadata 与 Stable 更新资格分开；native/package/protocol version 不变；客户端 patch 真实变化须通过 PR2 再 +1 |

并发 PR 的合并门禁必须验证最新 main 的确切 SHA，而非只验证旧 merge-base；需要 GitHub up-to-date/merge-queue 保护或等效强制门禁。客户端 patch 本身是 patch 内容，不能绕过 N+1。文档/调度/验证结果/兼容记录不增加 revision。历史身份不得随新 hash 重写。

## 验证与边界

本阶段只运行无生产凭证的本地 contracts 和 PR CI，不 dispatch Tag/Nightly、不生产签名、不发布、不合并 PR。Wayland 本地 dpkg fixture 要求 umask 022；本环境继承 umask 077 的首次 repository contract 因 fixture DEBIAN 权限 0700 失败，复验应在正常 packaging umask 下执行，不修改生产门禁以规避。

Review 和 CI 状态记录在 PR 中，不能从本文件推断未来 head 已通过。后续阶段必须重新检查最新 main 与 open PR，不能把本次库存当作永久事实。

本阶段本地验证：repository contract PASS；23 个相关 domain modules、365 个测试，3 个因所需外部工具/平台而跳过，其余通过。跳过不等于设备/安装/签名验证通过。`patchset_migration --check` 按设计返回 1（BLOCKED）。

## 后续实施状态（本审计之后）

PR2/PR3 和 PR4 已按后续用户指示实施，不等待 Review/CI 才继续。上述章节保留审计当时的事实；当前实现、版本 v1.2/v2.8、验证和仍未激活的生产切换请读 [交付记录](patchset-version-delivery.md)。历史库存 JSON 不随当前代码或线上运行变化改写。

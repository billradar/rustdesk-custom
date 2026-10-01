# RustDesk Custom — Production Maintenance

RustDesk 自定义补丁维护仓库。目标仓库：`billradar/rustdesk-custom`。
构建时取得官方 `rustdesk/rustdesk` 精确 SHA 与官方 submodules；本仓库不保存整个客户端源码树或 upstream 历史。

Standard = official + Common；SOS = same official SHA + same Common + SOS。
Standard 保留完整客户端设计；SOS 保留历史简化 UI 与设置入口限制，不是 native incoming-only / Level 3 功能禁用。

## 迁移与补丁

迁移来源为测试仓库 `billradar/rustdesk-custom-test`，精确 commit
`d40235baa3e414dac3f52c1866c4c563e62b4390`。文件来源见 `metadata/migration-baseline.json`。
v1/v2 的 patch bytes、metadata、Resolver、prepare/apply 和原生 Windows 构建脚本保持不变。
生产层改动和验证见 `docs/production-migration-report.md`。

- v1：已验证 RustDesk 1.4.9，SHA `6c578292e8ebbbec708b76986ba8c4bc7c509747`；按精确 SHA 固定映射。
- v2：开发分支新 API；已在测试仓库通过 Rust / Bridge / Flutter 兼容性检测。未声称完成开发分支 Windows 全构建。
- 未知 SHA：独立 clean workspaces 探测 candidate；无兼容代则 STOP；下游仍需实际编译检查。
- 未来 v3/v4 必须先在测试仓库开发、验证与审查，再人工迁入；正式仓库不会自动修改 Patch。

## GitHub Variables / Secrets

Settings → Secrets and variables → Actions。

| 类型 | 名称 | 用途 |
|---|---|---|
| Variable | RUSTDESK_ID_SERVER | rendezvous 默认地址 |
| Variable | RUSTDESK_RELAY_SERVER | relay 默认地址 |
| Variable | RUSTDESK_API_SERVER | HTTPS API 地址，无 URL 用户名/密码 |
| Variable | RUSTDESK_KEY | base64 32-byte server public key，绝非私钥 |
| Secret | RUSTDESK_PASSWORD | 当前历史固定密码初始化输入 |
| Variable | PRODUCTION_RELEASE_ENABLED | 默认不配置；验证后设 true 才允许正式发布及 stable schedule |

缺少生产配置时构建失败；不会 fallback 到测试配置。仅客户端 build steps 读取固定密码 Secret，不向第三方安装 Actions 暴露该环境变量。
Resolver、compile preflight、Bridge/Flutter analyze 使用公开虚构配置；这些中间诊断不是正式客户端。
客户端分别在两份全新工作树编译，生产参数必须确实出现在最终 native library 中；值不写日志或 build-info。
服务器配置 fingerprint 排除密码，只用于 Standard/SOS 以及首次 Dry Run 的来源一致性检查。

## 首次运行

在正式仓库配置上表四个 Variables 与一个 Secret，先保持发布开关关闭。
Actions → Production - Stable Standard and SOS release → Run workflow：

1. upstream_ref=1.4.9，dry_run=true，force_rebuild=false，dry_run_id 留空。
2. 等 Standard/SOS、Bridge、编译、checksum、PE AMD64、provenance 与生产配置验证全部成功。
3. 检查日志和产物后，将 PRODUCTION_RELEASE_ENABLED 设为 true。
4. 同一 maintenance commit 再运行 dry_run=false，并填写成功的 Dry Run run ID。不得通过提交报告改变该 maintenance SHA 后复用旧 Dry Run。

首次发布必须验证真实成功 Dry Run 的 event、workflow、SHA、validation artifact 与来源数据。之后 stable schedule 自动检测新正式 upstream Release 并运行同样的构建/验证 Gate；compatibility 永不发布。
手动 dry_run 默认为 true；force_rebuild 对已发布版本仅生成 Actions artifacts，绝不覆盖 tag 或 assets。

## Release 与可追溯性

一个正式 `vX.Y.Z-custom.N` Release 同时包含 Standard/SOS Windows x86_64 ZIP、
`build-info-standard.json`、`build-info-sos.json` 和 `SHA256SUMS`。
内部 Cargo/Flutter/Windows 版本沿用官方；修改自定义内容需递增 `patch-revision.txt`。
两边 upstream SHA、Patch Set、Common hash、服务器配置 fingerprint、maintenance SHA 和 workflow run 必须一致。
所有 payload 文件有校验和，最终 ZIP 也有外部 SHA256SUMS。先准备一个 draft，上传所有资产并检查，再公开为非 prerelease 的 Release。
遇到部分 API 失败保留未公开 draft，后续停止，不覆盖、删除或猜测恢复。

Compatibility 每日 UTC 03:23；stable 检查 UTC 05:41 / 17:41。schedule 已配置不代表实际触发已验证，须以 event=schedule 的真实记录补证。
正常 jobs contents:read；日志审核和跨运行 Dry Run artifact 读取 jobs 额外 actions:read；只有 Release job contents:write。
仅使用本仓库 GITHUB_TOKEN，不需要 PAT。

## 验证和安全边界

Build Reproduction: PASS（测试仓库）。正式 Production Dry Run / Release 尚待真实执行。
Runtime/UI Validation: SKIPPED BY USER。
Real Remote Session Validation: NOT TESTED。
Code Signing: NOT ENABLED。
Windows x86_64 only。Password Security V2: DEFERRED。

GitHub Secret 保护 CI 输入，不能使编译进客户端的固定密码不可提取。客户端所有者可分析 native library；不要将高权限 CI、SSH、云账号或服务端私钥用作客户端配置。
Gate 扫描已知测试配置、常见 token/private-key 格式和已完成 job 的可见日志；该检测不保证识别所有编码/未知凭据形式，仍需首个生产运行的人工日志复审。
发布前报告只记录配置名称和 configured 状态，不记录密码或密码摘要。

官方 Flutter engine 的 main 下载、hosted runners 与系统 packages 仍是历史浮动依赖，不能承诺字节级重复构建。
产物是可解压的 Flutter 客户端目录，不是签名 MSI；未包含旧 workflow 额外下载的打印/虚拟显示驱动安装扩展。

`rustdesk-custom-test` 保留 staging、API migration 与实验职责；`rustdesk-custom` 只接收经过审查的 Patch Sets 和稳定构建。
旧 `billradar/rustdesk`、`billradar/rustdesk-sos` 和历史 Releases 全部保留、零写入。
许可沿用 upstream AGPL-3.0；ZIP 内包含对应补丁和 LICENCE，upstream SHA + maintenance SHA 可恢复对应源码。

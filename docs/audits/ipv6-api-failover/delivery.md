# 最终实施与验证交付

只读基线及风险见 [audit.md](audit.md)，当前配置和状态机见 [../../api-failover.md](../../api-failover.md)。最终范围按用户补充为：仅 Web/API 主备；原生端口沿用既有双栈；v1/v2 归档且禁止所有新构建。后两项明确取代最初的旧版重建要求和原生备用需求。

## 实施

- v3 Common `0007-api-failover.patch`：严格 TLS 的 IPv6 主入口、HTTPS 备用、Primary/PrimaryUnavailable/Fallback/RecoveryProbe 状态、60 秒冷却、无认证恢复 HEAD；HTTP 状态和发送后结果不明的请求不重放。
- API 调用覆盖：`common.rs` 的公开 HTTP/POST/status 入口，Flutter 登录/currentUser/设备/组/地址簿，后台 heartbeat/sysinfo/审计/部署、OIDC、单次流式录屏上传。逻辑账号和 Token 存储键保持主 origin。下载/更新信任域不改写。Flutter 同 URL 并发请求用不发送至服务器的 UUID fragment 分开轮询，终态读取后消费。
- `prepare-source.yml` 只为 v3 读取公开 `RUSTDESK_API_SERVER` 和新 `RUSTDESK_API_FALLBACK_SERVER`；`scripts/source/api_policy.py` 校验、冻结并生成 Rust/Dart 策略。生产域名未硬写入补丁。备用为空时明确禁用功能。
- `prepared_source.py` 将快照 SHA256、生成文件纳入来源清单；复用时校验来源、生成内容和主 API 配置漂移，Standard/SOS 验证相同策略。包的 prepared_source_identity 绑定清单；没有未校验的编译期 fallback 环境覆盖。
- v3 内容历史追加 r5；现有 r1–r4 不变，runtime/real-session 验证状态未提升。
- `archive/abandoned-patchsets/v1`、`v2`：原始所有补丁、manifest、CHANGELOG 按字节移入，不再维护。`metadata/abandoned-patchsets.json` 固定完整文件清单；`patch-profiles.json` 明确退休。选择器拒绝所有 CI/Nightly/Stable 的旧版本，补丁应用、内容 revision 修改、准备源码和旧 prepared-source 复用均拒绝退休集；不回退 v3。
- 新增策略/退休契约、实际 selector TLS 测试和无凭据桌面 CI；现有测试夹具改用当前维护的 v3，归档文件仅作历史完整性证据读取。README、中文 README、AGENTS 和相关指南声明新生命周期。

## Actions 变量

需设置公开 repository Variables：

| 名称 | 值 |
| --- | --- |
| `RUSTDESK_API_SERVER` | `https://rustdesk.houxnan.com`（原有变量） |
| `RUSTDESK_API_FALLBACK_SERVER` | `https://rustdesk-backup.houxnan.com`（新增，仅 v3 读取） |

本环境读取和尝试创建新备用变量均被 GitHub integration 返回 HTTP 403，因此**未设置/未确认线上变量**；需要有 Variables 写权限的账号完成设置。未修改 Secrets、现有主变量或生产网络配置。变量修改只影响新且符合既有构建资格/去重规则的批次，不覆盖旧 Release。

## 本地验证证据

| 检查 | 结果/范围 |
| --- | --- |
| 全领域契约 | compat-check.yml 列出的全部领域命令通过，逐项结果见 domain-results.json；包括策略 3 项、退休 3 项、Profile 10 项、内容版本 11 项、发布/签名/来源/工作流隔离 |
| 实际 Rust selector | Rust 1.75 上 2 项测试通过（一项含完整顺序 TLS 故障场景），Clippy `-D warnings` 通过；源/夹具哈希见 transport-msrv-results.json |
| v3 Standard/SOS | 官方 1.5.3 当前补丁应用、结构契约、配置辅助编译及上游 DPI 保留检查通过，见 source-results-final.json；已知成功 Nightly 源 7949eca16c15b3eb86d89a9d4f5ac223026dd215 的两变体同类检查也通过，见 nightly-source-results.json；不代表未来 Nightly 自动兼容 |
| 归档保护 | 原提交 `7e346edef8914045d07bfbf0762f9bc0a445c06a` 的 v1/v2 全文件逐字节一致，当前退休契约通过；无历史 Tag/Release/签名产物操作 |
| 静态检查 | 新 selector Rust 1.75 rustfmt 通过；变更工作流 actionlint 1.7.12 通过；repository architecture contract 通过 |
| 完整产品编译 | 已尝试 Rust 1.75 cargo check，rust-webm 的 libwebm 子模块下载被代理 HTTP 403 阻止，未完成完整集成类型检查 |
| Dart/Flutter、设备与生产网络 | 未测试。固定 Dart 3.5.4 SDK 下载被 HTTP 403 阻止；不能宣称 analyze、真机或生产主备认证通过 |

额外核对上游 Cargo.toml 后补齐 `use hbb_common::tokio`：上游根 crate 仅将 Tokio 列为 dev-dependency，正式代码须经 hbb_common 使用。测试现以单独 facade 重导出 Tokio/log，根测试 crate 不直接依赖 Tokio，避免测试编译掩盖正式依赖缺失。

已修复 Codex 对 `9f9064f` 的 P2 review：IPv6 literal 不再用带方括号的主机名做 DNS，而是直接构造 IPv6 socket；主 origin 比较兼容压缩/展开写法，保持 IP SAN 证书验证。新的 Flutter HTTP 服务和生成策略文件已加入现有 Flutter analyze 文件清单，关闭功能时不额外调用原生 API getter。测试覆盖 literal 主连接及恢复、私有 polling fragment 不发往服务器。

本地 TLS 场景包括：双栈 localhost 的实际 IPv6 peer；无 IPv6 地址、DNS 错误、TCP 拒绝、TLS 错误、TLS 黑洞超时的预发送回退；401/403/500/503 不切换；备用 503；POST 已发送后断线/超时不重放；认证头/body/Host 保留；无凭据 HEAD 恢复、冷却与并发、取消探测租约回收；备用 TCP 不可达明确失败。均为本地模拟，不是线上 FRP 或真实登录/Token 测试。

## CI 和限制

Draft PR：<https://github.com/billradar/rustdesk-custom/pull/261>。以 PR 当前 head 的 checks 为准，初版提交的结果不能覆盖后续变量读取/退休变更。初版 Linux 传输测试通过；Windows 首轮在旧补丁应用阶段因 checkout CRLF 转换失败，已在新测试 workflow checkout 前固定 LF，未改写任何旧补丁。macOS 首轮随后在 Homebrew Python 的 PEP 668 安装保护处失败，已为测试矩阵增加固定 SHA 的 setup-python 3.12，未使用 break-system-packages。最终 head 的 CI 结果在交付答复/PR 检查中单独记录。

真实 API 登录/currentUser/Token、OIDC 回调白名单、地址簿/设备后端一致性、现场 IPv4-only/IPv6-only/双栈及 API FRP 故障仍需运行环境验证。既有原生双栈按用户确认保持现状，不另建备用。

`source-results-before-retirement.json` 和 `v2-protection-before-retirement.json` 只记录用户改变旧版处置策略之前的审计阶段，不能作为当前仍允许 1.5.1 构建的依据。当前行为为**明确禁止新构建**。本任务未合并、正式签名、发布或覆盖历史产物。

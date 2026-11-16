# 实施与验证交付记录

基线、只读发现与风险分级见 [audit.md](audit.md)，运行策略见 [../../api-failover.md](../../api-failover.md)。本任务在独立 `audit/ipv6-api-failover` 分支实施，最终以 `audit/ipv6-api-failover-review` 提交审查（首次推送被 GitHub 邮箱隐私保护拒绝，原本地历史保留）；没有合并、正式签名、发布或生产网络变更。

## 实施文件

- `patchsets/v3/common/0007-api-failover.patch`：新增 `src/hbbs_http/api_failover.rs`；接入 `src/common.rs` 三个公开 API 请求入口及其 HTTP helpers，`src/hbbs_http.rs` 的严格代理配置，OIDC account 预热、record_upload 单次流传输、Flutter `http_service.dart` 和 `ui_interface.rs` 的独立请求轮询键及消费。
- `patchsets/v3/{patchset.json,CHANGELOG.md}`：追加 v3.5，历史 revision 记录不变，runtime/real-session 状态不提升。
- `scripts/validation/api_failover_transport.py`、`fixtures/api-failover/`：实际 selector 的锁定依赖 TLS 故障测试。测试 CA/密钥只存在临时目录。
- `.github/workflows/api-failover.yml`：无凭据桌面传输矩阵；不访问生产服务器，不执行签名/发布。
- `scripts/upstream/{patch_profiles_contract,patchset_version_contract}.py`：当前 v3 revision 断言读取 canonical metadata；重建历史 v3.1 候选夹具时排除新补丁，仍严格验证原历史 hash。
- `AGENTS.md`、`docs/README.md`、`docs/api-failover.md` 及本审计目录：配置、证据和限制。

## 参数与实现状态

没有新增环境变量。主 API 继续使用原有 `RUSTDESK_API_SERVER`；只有编译值匹配已审查主 origin 时，v3 的内容绑定策略启用所提供的备用 HTTPS origin。原因：避免将未被旧配置指纹收录的新编译变量带入身份/签名边界。未修改 repository Variables，且其实际值读取被 GitHub integration 以 HTTP 403 拒绝，不能声称已验证线上启用。

API 已实现严格 IPv6 主入口、保守自动回退、60 秒冷却和请求机会恢复；具体请求覆盖与超时预算见运行文档。用户已确认其他原生端口已有双栈、无需备用；ID/Relay 及相关端口按此要求保持现状，不属于本次实施范围。

## 本地验证

| 检查 | 结果与范围 |
| --- | --- |
| 实际 selector TLS 测试 | Rust 1.75.0 和 1.100.0 各 2 项测试通过，其中一项包含完整顺序网络故障场景；仅本机 TLS，不是完整客户端 |
| Clippy | 两个上述工具链，actual selector + 测试，`-D warnings` 通过 |
| Rust 格式 | 新 selector 使用 Rust 1.75 rustfmt `--check` 通过；补丁未夹带历史 defaults 的格式重写 |
| 工作流静态检查 | actionlint 1.7.12 对新增工作流通过；repository contract 的 YAML/签名/发布隔离检查通过 |
| Profile/内容版本 | Profile 10 项、内容版本 11 项通过；对 origin/main 的 append-only verify 通过 |
| 1.5.1/v2 与 1.5.3/v3 | 两版本 Standard/SOS 共四次完整 patch 应用、结构契约及配置辅助编译通过；v3 上游 DPI 逻辑保留检查通过 |
| 现有相关契约 | config_mir 11、native_config 11、production 38、android_signing 17、client_update 10、branding 11 项通过；CM patch parity 通过 |
| 原生 UI、Dart、真实会话 | 未测试；环境无 Flutter/Dart，尝试下载固定 Dart 3.5.4 SDK 被 HTTP 403 拒绝，未伪造 analyze/format 结果 |
| 完整跨平台客户端 | 已尝试 Rust 1.75 `cargo check --locked --no-default-features --features flutter`，依赖 rust-webm 的 libwebm 子模块下载被代理 HTTP 403 阻止；未到本次集成代码的完整类型检查。桌面矩阵只编译测试传输模块，不能代替 Android/Windows/Linux/macOS 完整产品构建 |

首轮 TLS 夹具漏 Content-Length 导致 Rustls EOF，已修正后重测；Clippy 提示 single_match 已修正后通过。早期使用错误 PYTHONPATH/umask 的契约运行失败；按项目 setup 的 PYTHONPATH 与 umask 022 重跑后通过。所有通过结论只指纠正后的明确检查。

## 网络测试矩阵

| 场景 | 本地证据 | 生产状态 |
| --- | --- | --- |
| IPv6 主正常、双栈优先 | localhost 双栈解析，实际响应 peer 为 IPv6 | 未测试真实网络 |
| 无 IPv6 地址/仅 IPv4 入口 | primary 解析仅 IPv4 时仅备用收到业务 POST | 未测试真实 IPv4-only 网络 |
| 主 DNS 错误、TCP 拒绝 | 自动备用，限定预算，POST 不重复 | 未测试真实 DNS/防火墙 |
| 主 TLS 证书错误/握手黑洞 | 严格拒绝/3 秒连接预算，自动备用 | 未测试真实路由黑洞 |
| 401/403/500/503 | 主响应直接返回，无备用请求 | 未测试真实认证 |
| 备用 503 | 原样报告，保持 Fallback | 未测试真实后端 |
| POST 已发送后断开/超时 | 返回不确定结果，无备用重放 | 未测试真实登录切网 |
| 冷却、恢复、并发 | 冷却不探测；无认证 HEAD；探测租约可回收；并发业务请求各发一次 | 未测试真实远程会话 |
| fallback/FRP 故障 | 关闭备用 TCP 端口模拟，明确报错，无循环 | FRP 未操作/未测试 |
| Token/currentUser、设备/地址簿/OIDC | 源调用链统一；测试认证头、body、Host 保留 | 真实 Token、回调及数据后端一致性未测试 |
| Relay 不可达/网络重注册 | 已审计原生路径及端口 | 沿用既有双栈方案；不新增原生备用 |

## 1.5.1 v2 r8 保护证据

[v2-protection.json](v2-protection.json) 对基线确认 v1/v2、Profile 注册表、现有构建/来源/签名/发布实现均无变动；v2 Common SHA256 `a9a8ef83aa02890f09beb19e0b4818b268d4d873362f9ccf7ee9b09d3415e5b0`、SOS SHA256 `076a08c0d4a710e19ce08fd6e77f0c207293868b98c83a6471ab9a77e5d40813` 不变，revision 仍为 8。未触碰旧 Tags、Release 或产物。源码/契约隔离得到验证；没有重新生产签名或设备运行，不能把它表述为新 APK 签名或旧产物逐字节重建已验证。

## 尚待完成

Draft PR 的确切 head CI、桌面传输矩阵结果另在 PR/最终答复记录。完整客户端编译、Dart/Flutter 分析、Android TLS、真实主备 API 登录/Token/OIDC/地址簿、IPv6-only/IPv4-only 网络及 API FRP 故障仍需新证据。原生端口的现有双栈属于用户确认的基础设施，本次未操作。不得将这些未验证项写成通过。

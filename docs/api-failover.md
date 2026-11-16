# v3 IPv6 API 优先与 IPv4 HTTPS 备用

实现及只读审计见 [审计报告](audits/ipv6-api-failover/audit.md)。仅 v3.5+ 应用 Common `0007-api-failover.patch`。v1/v2 现已归档且禁止新构建；原始补丁字节和历史发布产物保持原样。

## Actions 配置与身份

在仓库 Settings → Secrets and variables → Actions → Variables 配置公开变量：

| 变量 | 值 | 作用域 |
| --- | --- | --- |
| `RUSTDESK_API_SERVER` | `https://rustdesk.houxnan.com` | 原有主 API 变量，保持原义 |
| `RUSTDESK_API_FALLBACK_SERVER` | `https://rustdesk-backup.houxnan.com` | 新增，仅在 v3 源码准备阶段读取 |

生产域名不硬写进补丁。`prepare-source.yml` 只为 v3 读取这两个变量，校验为不同的严格 HTTPS origin（禁止用户名/密码、路径、query、fragment），冻结为单次准备输入。Common 阶段生成 Rust/Dart 策略及 `api-failover.json`，再复制 Standard/SOS。`api_policy_sha256` 与两个生成文件一起进入来源清单；下游验证快照、生成内容和可用的主 API 编译配置，配置漂移明确失败。包的 `prepared_source_identity` 绑定整个来源清单。既有服务器配置指纹字段不被悄悄扩展。

备用变量为空时明确禁用主备，不默认任何生产域名。设置/修改变量只影响新且符合现有构建规则的批次，不覆盖已有 Release/产物，也不绕过既有去重。此环境对 repository Variables 的访问被 integration 403 拒绝，无法代用户确认变量已设置。

逻辑 API 返回值和账号/Token 存储键保持主 origin。仅匹配冻结主 origin 的 `/api/` 请求由此策略管理；显式其他服务器、下载器和更新来源不转发到备用。

v1/v2 已按用户最新确认移到 `archive/abandoned-patchsets/`，只保存原始证据，不再维护；CI/Nightly/Stable 选择、补丁应用及旧 prepared-source 复用入口均禁止它们，包括 1.5.1。此决策取代最初的旧版重建要求；历史 Tag、Release、签名和发布产物未改动。

## 传输规则

- Primary：解析主域名，只保留 IPv6 socket 地址；URL 仍是域名，保留证书名称校验、SNI、Host。DNS 上限 3 秒，TCP/TLS 连接上限 3 秒，请求上限 12 秒。新建客户端，无连接池复用引起的跨次隐式重放。
- PrimaryUnavailable → Fallback：DNS/客户端建立失败或 reqwest `is_connect()` 错误时才允许将尚未发送的请求尝试备用一次。发送后超时、响应读取/写入异常不重放；结果不确定的操作应先查询实际状态再由用户重试。状态为进程内共享，非持久配置。
- HTTP 401/403/业务错误/5xx/3xx 原样返回，不以状态切换或重试。禁用重定向，认证头不会通过重定向转发；备用 HTTP 错误由现有调用方显示。
- Fallback 冷却 60 秒。到期后的新请求最多领取一次 RecoveryProbe，向主 `/api/login-options` 发无认证、无 body 的 HEAD；任何 HTTP 状态证明传输可达。成功后该请求使用主；失败续用备用。探测租约 10 秒，调用取消后可重试；过时探测不能覆盖新的失败状态。无后台定时器、不重启 ID/Relay 或远程会话。
- 最坏预发送回退预算为主 DNS 3 秒 + 主连接 3 秒 + 备用请求 12 秒，约 18 秒；结果不确定的原请求不加第二次业务请求。系统调度和代理初始化不属于硬实时保证。
- 配置了用户代理时，无法证明远端代理 DNS 选择 IPv6，直接将主视为不可验证并通过该用户代理访问备用；不绕过代理直连。代理配置错误明确失败，不静默使用系统环境代理或默认客户端。
- Flutter 登录、currentUser、地址簿、设备/组走现有 Rust 桥；后台同步、OIDC、部署/审计及录屏采用同一 origin 策略。流上传先用无认证 HEAD 选择端点，固定已验证 IPv6 地址，再单次发送流；不重放。下载器及客户端更新的独立信任域不改写。
- Flutter 桥用 UUID fragment 区分同 URL 并发请求；HTTP 不发送 fragment。Rust 读取终态后消费该条结果，避免串响应和已消费结果积累。无桥签名或生成代码变更。
- 新传输不读取上游不安全 TLS cache，不调用证书绕过，不触发原生 TCP API 重发。日志只含 origin/端点角色/故障类别，不记录认证头、body、URL 查询或底层可能含 URL 的错误。

## 验证

```bash
python3 scripts/validation/api_failover_transport.py --source /path/to/prepared-v3-source --output /tmp/api-transport.json
python3 -m scripts.upstream.patch_profiles_contract
python3 -m scripts.upstream.patchset_version verify --base origin/main --check
```

TLS harness 从已准备源码复制实际 selector，与上游锁定的 reqwest/Tokio 版本一起编译；代理 helper 使用无代理测试替身，不能将其通过视为真实用户代理验证。OpenSSL 在临时目录生成测试 CA 和服务器密钥，以 `SSL_CERT_FILE` 加载本机临时信任，不改变系统信任或 production TLS 代码。测试不会访问生产主备域名。单个顺序集成测试覆盖多种故障，另有 origin/重写边界测试。

桌面 CI 矩阵仅验证实际 Rust 传输模块及本地 TLS 场景，不是完整客户端跨平台构建。Android 真机 TLS 根证书、Dart 分析、完整 native 编译、OIDC 回调域名、Token 共用后端以及真实 FRP/IPv4-only/IPv6-only/双栈会话仍需相应环境证据。

## 原生协议状态

用户已补充：其他原生端口已有双栈，只需 Web/API 备用。因此 ID Server、Relay、NAT 测试及其既有双栈连接流程均保持现状，不新增原生备用地址或端口映射。原生代码审计保留为边界说明；本任务的完成范围是 API 切换，不要求原生协议另建主备。

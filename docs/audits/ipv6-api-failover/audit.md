# IPv6 主入口 / IPv4 备用审计（实施前）

审计基线：custom `7e346edef8914045d07bfbf0762f9bc0a445c06a`；上游官方 1.5.3 `95cca3f661f635b3cc85c04935fe8d96d8f432ef`；hbb_common `fae47e024dd83cef6aaecde0aa7d11731df11649`。下述上游路径均相对于这一固定源码，不是本仓库内的完整源码副本。

## 已确认事实

- 本地初始分支 work，工作区干净。main 为上述 custom SHA；development 为 `7397c22c3aad3505b144c457d6b2fd31a662e70f`，merge-base 为 development，main 独有一个合并提交，development 无独有提交。2026-11-16 GitHub pulls REST 查询 open 返回空列表。
- `metadata/patch-profiles.json` 与 `scripts/upstream/patchsets.py`：1.5.1/1.5.0 精确映射 v2 r8；1.5.3 映射 v3 r4，状态 validation_pending；1.5.2 为 latest-maintained 兼容测试 fallback，禁止 Stable。不得修改路由来逃避适配。
- `patchsets/v3/common/0001-hbb-server-defaults.patch` 将 hbb_common `RENDEZVOUS_SERVERS` 替换为单个编译期 ID 地址。0002 将 common::get_api_server_ 的末尾默认值替换为编译期 API 地址，并注入可选 relay-server 默认值。显式 api-server、自定义 ID 派生 API、Windows EXE 配置优先级仍在上游函数中，不得将它们的认证头转发给内置备用。
- `.github/workflows/{build,build-platform,build-stable-windows,build-wayland-target}.yml` 从同名 repository Variables 导入 API/ID/Relay；`scripts/build/{linux,linux_wayland}.sh` 显式透传容器环境。这些变量跨 Profile 共用，修改其值会影响旧版重建。`scripts/signing/production_config.py`、`scripts/build/config_mir.py`、`scripts/source/verify_source.py`、`scripts/platform/platform_package.py` 和 release/package.py 校验现有构建配置；本任务不改变已有字段含义。
- 上游 `flutter/lib/utils/http_service.dart::sendRequest` 在非 web 上依据本地选项和代理选择 Dart/Rust；Dart 分支超时 30 秒，Rust 分支每次 12 秒。登录 user_model.dart::login/refreshCurrentUser、地址簿 ab_model.dart、设备/组 group_model.dart 共用该服务。未发现独立 refresh_token 端点；refreshCurrentUser 实际向 /api/currentUser 发 POST，不能声称已测试不存在的刷新接口。
- 上游 `src/common.rs::{post_request,post_request_with_status,http_request_sync}` 汇集后台 heartbeat/sysinfo、OIDC、Flutter HTTP。旧路径 `with_tcp_proxy_fallback` 在 Err 或 5xx 后重发；`post_request_`、`get_http_response_async` 和 hbbs_http/http_client.rs 的非 strict 客户端会尝试 invalid certificate。**高风险：新主备功能必须完全绕过上述重放及证书降级路径。** 不修改 v2 历史行为。
- 其他出口：hbbs_http/record_upload.rs::RecordUploader::send 为同步流上传，account.rs::ensure_client 有 TLS 预热；downloader/updater 为独立下载信任域，不应改写 GitHub/任意下载 URL。
- 上游 hbb_common/config.rs::get_rendezvous_servers 优先 EXE、自定义单服务器、PROD，然后才考虑 serial 更新列表及内置列表；update_latency 选择最快节点。rendezvous_mediator.rs::start_all 对服务器并发注册、退出后重试；不是按主备顺序注册。client.rs::connect_rendezvous 对服务器列表逐一 TCP 尝试。common.rs::test_rendezvous_server_ 比较连接延迟。
- hbb_common/socket_client.rs::{connect_tcp_local,new_udp_for,rebind_udp_for} 和 tcp.rs::FramedStream::new 共用于 Android/Windows/Linux/macOS；TCP 按解析顺序逐地址尝试，每地址 CONNECT_TIMEOUT=18000ms；不是固定 IPv6 优先。UDP test_target 及重新绑定属于另一条路径，不能复制 HTTP 切换逻辑。
- 原生端口：common.rs::test_nat_type_ 用 ID 端口及其 -1（默认 TCP 21116/21115）；mediator::start/start_tcp 使用 UDP/TCP 21116；client::create_relay 默认 TCP 21117。hbb_common/config.rs 定义 WS 21118/21119；仅启用相应 WebSocket 模式才需要，不能据此宣称当前服务端开放。直连监听是客户端端口，非 hbbs FRP 映射的自动要求。
- Relay：mediator::get_relay_server 优先本地 relay-server，然后 hbbs 提供值，最后 ID 地址 +1；client::request_relay/create_relay 使用收到/协商的 relay 地址及 UUID。仅增加 ID 列表不能保证 relay 可达。网络重新注册不等于现有远程会话可无缝恢复。
- 历史 CI：main SHA 上 Nightly run [43796320397](https://github.com/billradar/rustdesk-custom/actions/runs/43796320397) success；兼容监视 [43816430773](https://github.com/billradar/rustdesk-custom/actions/runs/43816430773) success。这是历史证据，不覆盖本次变更，也不能证明现场网络可用。

## 尚未验证

提供的 DNS、Cloudflare、FRP、OpenResty 拓扑属于用户提供的信息；本环境没有生产配置证据。API 内部 21114 与上游 ID-2 默认一致，但源站实际监听/反代必须现场核对。浏览器访问备用 HTTPS 不证明登录、同一 Token、设备列表、地址簿、OIDC 的一致性。主备必须到同一认证/数据后端；跨域 cookie、OIDC apiDomain 和身份提供商回调白名单仍需验证。不得发送测试登录或变更生产配置。

## 实施边界及风险

拟仅增加 v3 Common 补丁、v3 内容版本/CHANGELOG、针对性验证脚本、说明；复用 Flutter→Rust 现有桥，不生成新桥 API。保留逻辑 API URL/认证存储键，只在传输时选择物理端点。请求级连接失败仅在 reqwest is_connect（DNS/TCP/TLS，尚未发送 HTTP 请求）时可回退一次；发送后超时/读写错误不自动重放。任何 HTTP 状态均不触发切换。冷却后只在后续 API 请求机会发送无认证 HEAD 探测；不主动重启原生会话。

不需要修改：v1/v2 全部文件、Profile 路由、签名/Build Identity/发布脚本、生产配置、Secrets、Tag/Release、上游桥生成物、下载器信任策略。v3 内容更新必须按 append-only revision 流程分配新 revision，不冒用 r4。

高风险：发送不确定请求重放、证书绕过、任意域名认证泄漏、共享配置改变 v2。中风险：代理行为、并发探测、冷却恢复、OIDC/Token 后端兼容、流上传中途断网。未证明跨平台编译/运行前保持验证状态 pending。

## 原生协议实施前置条件

需要用户选定真实 IPv4 DNS-only 原生域名；验证 VPS TCP 21115/21116/21117 和 UDP 21116 各自 FRP 映射至同一 hbbs/hbbr（TCP 映射不覆盖 UDP）。不部署第二套服务。检查 hbbs 下发 relay：可选择同一 hbbr 的双栈灰云域名，或审查双端一致的 relay 地址映射，保持 UUID/密钥及协议校验。橙云 API 域名不可用于原生 TCP/UDP。先利用原生列表重试能力，再补严格优先级及恢复策略；未有真实地址/映射验证前不启用，不宣称原生 HA。

## 验证计划

补丁 Standard/SOS 应用；版本路由和 v2 哈希不变；仓库/版本/来源契约；Rust 格式、独立传输单元/集成测试、Clippy；工作流静态检查及可用跨目标编译。模拟无 AAAA、IPv6 黑洞/TCP 拒绝/TLS 错误、连接超时、401/403/5xx、POST 已发送后断开不重放、冷却和恢复、同时请求及敏感日志。现场矩阵需 IPv4-only/IPv6-only/双栈、真实认证、FRP 故障和远程会话；环境缺失一律记录未测试。正式签名/发布不在验证范围。

## 用户补充后的最终范围

实施期间用户明确“备用只备用 web/api，而其他端口无需备用”，并说明“其他端口已经具备双栈”。因此原生协议的审计作为现有路径说明保留；上文原生主备实施前置条件不再是本任务的待办，不添加原生备用域名或配置。只实现 Web/API 主备；不改动已有原生双栈路径。Repository Variables 的实时读取返回 HTTP 403（Resource not accessible by integration），因此提供的主 API 地址作为需求输入，未冒称已读取线上构建配置。

## 最终补充授权与配置设计修订

用户随后要求“需要 action 读取，不要硬写入”，因此初版固定端点方案已撤销，改用 Actions 变量冻结到 v3 prepared source，详见 `docs/api-failover.md` 和 `scripts/source/api_policy.py`。

用户进一步明确确认“按最新要求归档并禁止构建 v1/v2”。这项确认取代原始 1.5.1 重建不变要求：v1/v2 原字节移入 `archive/abandoned-patchsets/`，所有新构建入口明确拒绝，不能静默回退 v3；旧 Tag/Release/签名产物不动。上文有关旧版仍可构建的事实是实施前基线，不是最终行为。

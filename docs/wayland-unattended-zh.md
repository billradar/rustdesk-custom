# Tag 与 Nightly 中的 Wayland 无人值守构建

[English](wayland-unattended.md) · [简体中文](wayland-unattended-zh.md)

`wayland.yml` 是内部 reusable workflow，没有独立的手动发布入口。`tag.yml` 和 `nightly.yml` 将固定的上游 SHA、版本、通道、patchset 及同一次运行准备的 Standard 产物传入该流程。公共补丁策略（包括强制关闭软件渲染）与普通构建共用；Wayland lane 不会重复解析、获取或准备源码。

两个父工作流均提供 `include_wayland` 布尔选项，默认开启。它会使用原生 amd64 (`ubuntu-22.04`) 和 ARM64 (`ubuntu-22.04-arm`) Runner 构建 DEB。构建不支持的旧源码（如 1.4.9）时需显式关闭。缺少或未经审核的 DRM 接口会在安装 bridge 依赖前失败。

普通平台矩阵中的 Wayland 项仍为实验状态且 `enabled: false`；`workflow_enabled: true` 只启用这个 reusable lane。它不是普通 Standard/SOS qualification 的替代品。源码变体为 Standard，`build_flavor: unattended-wayland` 标识单独捕获的功能集合。

## 已审核接口与软件包门禁

`metadata/build/wayland-policy.json` 记录上游 1.5.0（`libdrmtap 0.5.8`）和已审核 1.5.1 快照 `1297da6d`（`libdrmtap 0.5.12`）的 DRM job/build.py 成对哈希与依赖固定信息。未知组合会失败关闭。依赖版本必须同时匹配准备源码清单中的准确 build.py 哈希，不能只匹配库版本。普通 Linux adapter 签名仍需通过。

1.5.1 审核覆盖官方 DRM job 新增测试，以及库的 0.5 ABI、帧生命周期/文件描述符检查和特权环境加固。源码审核不等于新 pin 的软件包或运行时验证。

禁用 helper 的 EGL 库由原生工具链构建；编译和打包采用审核过的 Linux recipe，并启用 `drm` 与 `drm-wake`。1.5.0 profile 有八组测试；1.5.1 有十二组，包括 DRM pacing、CRTC refresh、loader 和 clipboard 测试。每组至少运行一个测试。DEB 需通过架构、libc 下限、EGL/capture/wake 标记、与普通包的 Conflicts/Provides/Replaces、库和 soname、校验和、配置、凭据扫描及源码来源检查。该变体不生成 RPM；两个架构都必须在同一工作流运行中通过。

## 聚合与发布行为

启用 Wayland 时，父工作流会等待该 lane 完成后再执行最终聚合。包下载到独立目录，不能冒充普通平台目标。最终聚合会再次验证两份 DEB，并将来源清单身份、准备运行 ID、Common patch hash 和配置指纹绑定到普通 Standard 构建。缺失、重复、过期、跨通道或来源不匹配都会阻断聚合。

Tag 的 Draft/Release job 会在发布 job 中再次下载并校验两份 Wayland 包，将其加入常规资产目录并重新生成公开 `SHA256SUMS`。发布元数据记录 Wayland 策略摘要和实验状态。不可变的既有 release/draft 不会被追加或覆盖：若旧 revision 没有匹配的 Wayland 证据，启用该选项会失败。可关闭该选项复用旧 revision，或按现有 revision 流程创建新构建身份。

Nightly 会将两份 DEB 纳入聚合 Actions artifact，并在受保护的 main Draft 模式下纳入 prerelease Draft。该模式中的 Android 签名仍由与 Tag 相同的独立受保护 YubiKey job 执行。Wayland job 不接触 PIN 或签名 Runner；Nightly 不会自动公开发布。

目标产物名为 `rustdesk-wayland-<version>-<upstream-sha>-<arch>`；`wayland-qualification-<run-id>` 记录配对及 stable/nightly 通道身份。父聚合报告也包含独立的 Wayland 结果。

该软件包与普通 RustDesk 冲突。早期 1.5.0 包曾在关闭强制软件渲染后于一次用户确认的锁屏会话中成功；这不是新构建、ARM64、登录/重启或其他 GPU 的运行证据。

相关契约：`scripts/platform/wayland_contract.py`、`scripts/release/nightly_contract.py`、`scripts/release/channel_contract.py`、`scripts/release/qualification_contract.py` 和 `scripts/validation/repository_contract.py`。

## ARM64 打包后验证

官方 Linux ARM recipe 会将 Flutter Linux 命令替换为 flutter-elinux，并把 build.py 中的 x64/release 路径调整为 arm64/release。运行 `40202174271` 曾成功构建 ARM64 binary 和 DEB，但最终包检查错误地将转换后的脚本与原始 fingerprint 比较。最终化流程现从锁定 Git object 取回 build.py，对照准备清单和 DRM 策略验证哈希，并仅允许 ARM64 出现上述两项审核过的替换（amd64 不允许替换）。额外变更、错误 SHA 和被修改的清单仍会被阻断。该修复仍需新的完整构建验证最终产物。

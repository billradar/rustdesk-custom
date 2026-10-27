# RustDesk Custom

[English](README.md) · 中文

[![Stable Release](https://img.shields.io/github/actions/workflow/status/billradar/rustdesk-custom/tag.yml?branch=main&style=flat-square&label=Stable%20Release)](https://github.com/billradar/rustdesk-custom/actions/workflows/tag.yml)
[![Nightly](https://img.shields.io/github/actions/workflow/status/billradar/rustdesk-custom/nightly.yml?branch=main&style=flat-square&label=Nightly)](https://github.com/billradar/rustdesk-custom/actions/workflows/nightly.yml)
[![Upstream Main Compatibility](https://img.shields.io/github/actions/workflow/status/billradar/rustdesk-custom/upstream-main-compatibility.yml?branch=main&style=flat-square&label=Upstream%20Main%20Compatibility)](https://github.com/billradar/rustdesk-custom/actions/workflows/upstream-main-compatibility.yml)
[![CI](https://img.shields.io/github/actions/workflow/status/billradar/rustdesk-custom/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/billradar/rustdesk-custom/actions/workflows/ci.yml)

## 项目简介

RustDesk Custom 是一个基于上游 RustDesk 的维护与发行项目，用于管理经过审核的自定义补丁，并提供完整的构建、验证、打包、签名和发布自动化。

本仓库不是完整的 RustDesk 源码 Fork，而是一个维护和发行仓库。上游源码按指定版本获取，自定义修改通过经过审核的 patchset 管理。

## 主要功能

- 维护经过审核的 RustDesk 自定义补丁。
- 固定并记录构建所使用的准确上游版本。
- 构建 Standard 和 SOS 版本。
- 验证软件包、架构、校验和、配置及构建来源。
- 生成机器可读的构建和发布元数据。
- 将 Android 生产签名与普通 CI 完全隔离。
- 自动执行 CI 资格验证和 Stable 发布流程。

## 支持的平台

| 平台 | 架构 | Standard | SOS |
| --- | --- | :---: | :---: |
| Windows | x86_64 | ✓ | ✓ |
| Linux | x86_64 | ✓ | ✓ |
| Linux | ARM64 | ✓ | ✓ |
| macOS | x86_64 | ✓ | ✓ |
| macOS | ARM64 | ✓ | ✓ |
| Android | ARM64 | ✓ | — |
| Android | ARMv7 | ✓ | — |
| Android | x86_64 | ✓ | — |

Windows ARM64 已作为实验性目标接入 Tag 和 Nightly 构建，生成的安装包会进入发布资产；运行时验证尚未完成。iOS 仍在计划中；Web 目前暂不支持。

权威平台支持矩阵：[metadata/platform/matrix.json](metadata/platform/matrix.json)。

## 工作流程

正常流程：

```text
上游 RustDesk → 补丁选择 → 准备源码 → 平台构建 → 产物验证 → 汇总 → Android 生产签名（可选） → CI 资格验证 → Stable 发布
```

每个阶段都有独立职责。构建不会自动发布，Android 生产签名也不属于普通 CI。

## 仓库结构

```text
.github/       GitHub Actions 和工作流
metadata/      机器可读的构建、平台、发布、签名和上游元数据
patchsets/     经过审核的自定义补丁集
scripts/       构建、平台、发布、签名、源码、上游和验证逻辑
docs/          实现原理、操作步骤与故障排查文档
tools/         开发和维护工具
requirements.txt
README.md
```

详细架构：[docs/README.md](docs/README.md)。

## 环境要求

- Python 3
- Git
- GitHub Actions（用于托管 CI）
- 本地构建所需的平台专用 RustDesk、Flutter 和 Native 构建依赖

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
```

## 自定义克隆仓库

克隆本仓库后，请在 **Settings → Secrets and variables → Actions** 中为自己的仓库配置以下内容。工作流会在构建时读取这些设置；原仓库的配置不会自动复制过来。

### 仓库变量

| 名称 | 是否必需 | 用途 |
| --- | --- | --- |
| `RUSTDESK_API_SERVER` | 是 | 自建 API 服务的 HTTPS 地址；不要在 URL 中放入认证信息。 |
| `RUSTDESK_ID_SERVER` | 是 | 自建 ID/rendezvous 服务的主机名或地址。 |
| `RUSTDESK_RELAY_SERVER` | 否 | 中继地址覆盖项。中继与 ID 服务器同主机并使用标准端口时可省略；上游会自动发现中继地址，未提供时也会回退到同一主机。只有客户端需要指定不同中继主机或端口时才设置。 |
| `ANDROID_PRODUCTION_SIGNING_ENABLED` | 否，默认 `false` | 只有配置好自己的生产签名身份和 Runner 后才设为 `true`。 |

### 仓库密钥

| 名称 | 是否必需 | 用途 |
| --- | --- | --- |
| `RUSTDESK_KEY` | 是 | 自建 RustDesk 服务的 Base64 编码 32 字节公钥。工作流读取的是同名**仓库密钥**。 |
| `RUSTDESK_PASSWORD` | 是 | 注入客户端的默认永久密码。它会编入客户端，因此取得该构建产物的用户可能恢复这个共享默认值，请据此选择。 |

服务地址和公钥必须属于同一套自建服务。构建验证会检查服务配置及其是否编入产物，但不会打印配置值。

### 可选：Android 生产签名

生产签名与普通构建隔离。要在克隆仓库中启用：

1. 创建名为 `android-production-signing` 的 GitHub Environment，并在其中添加 `YUBIKEY_PIV_PIN` 密钥。
2. 配置专用自托管 Linux ARM64 Runner，标签为 `self-hosted`、`linux`、`arm64`、`rustdesk-signing`、`android-signing`、`yubikey`；部署经过审核的签名桥接程序并连接 YubiKey。
3. 将仓库变量 `ANDROID_PRODUCTION_SIGNING_ENABLED` 设为 `true`。
4. 配置 Environment 的部署保护规则，并将签名工作流限制在受保护的 `main` 分支。

本仓库当前在 `metadata/signing/android-standard.json`、`scripts/signing/android_yubikey_sign.py`、工作流检查和契约中固定校验本项目的 Android 证书指纹。使用其他证书的克隆仓库必须先把这些身份校验及相关契约更新为自己的证书，再启用签名。签名器要求 APK 同时具有 v2 和 v3 签名方案。不要复制原仓库的 PIN 或签名身份。

不要把密钥写入源文件、命令行参数、日志或构建产物。由 Fork 的 Pull Request 触发的工作流不会获得仓库密钥；不要让生产凭据参与构建未经审核的代码。

## 开发

```bash
git clone https://github.com/billradar/rustdesk-custom.git
cd rustdesk-custom
git checkout development
```

修改前可以运行：

```bash
python3 scripts/validation/repository_contract.py
```

## CI

Stable 构建必须针对准确的 custom commit、准确的 Stable 上游版本、对应的 upstream commit 和当前 patchset 生成 CI qualification。

手动执行 CI 时：

1. **Stable upstream version** 填写目标版本，例如 `1.5.0`。
2. **Force rebuild** 一般保持关闭。
3. **Run Stable CD dry-run after qualification** 一般保持关闭，只有测试发布流程时才开启。
4. 等待 CI qualification 成功。
5. 对相同 custom revision 运行 Stable Release Pipeline。

构建成功不等于 Stable qualification 成功；custom commit 和 upstream revision 必须完全匹配。

## Release

Stable Release Pipeline 只有在准确 custom revision 已经通过目标 Stable 上游版本的 CI qualification 后才会继续。

```text
CI Qualification → Stable Preflight → 平台构建 → 产物验证 → Android 生产签名（授权时） → 汇总 → Draft / Publish
```

## Android 生产签名

Android Standard 生产签名与普通 CI 完全隔离，需要明确授权、专用 Runner、`android-production-signing` Environment、受保护的 `YUBIKEY_PIV_PIN` Secret，以及签名后的身份验证。

普通 CI 不需要访问 YubiKey、PKCS#11 凭据或生产 PIN。

权威签名元数据：[metadata/signing/android-standard.json](metadata/signing/android-standard.json)。详细实现原理和操作步骤见 [Android 生产签名文档](docs/android-production-signing.md)。

## 验证

仓库级验证：

```bash
python3 scripts/validation/repository_contract.py
```

其他 Contract 位于 `scripts/release/`、`scripts/build/`、`scripts/validation/` 和 `scripts/signing/`。

## 文档

从 [文档总目录](docs/README.md) 开始，按实现原理、源码与补丁、构建验证、工作流与发布、Android 生产签名和故障排查组织。

## 上游项目

- 上游仓库：https://github.com/rustdesk/rustdesk
- 项目官网：https://rustdesk.com/

## 安全

- 生产签名凭据不会存储在仓库中。
- 普通构建 Job 不执行生产签名。
- 签名需要明确 Workflow 授权。
- 发布前会验证构建产物。

发现安全问题时，请不要在公开 Issue 中提交凭据、签名材料或其他敏感信息。

## 许可证

RustDesk Custom 包含 RustDesk 的维护和自动化代码。具体许可证条款请以上游 RustDesk 项目及本仓库相关文件为准。

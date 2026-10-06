# RustDesk Custom

[English](README.md)

[![Stable Release Pipeline](https://github.com/billradar/rustdesk-custom/actions/workflows/tag.yml/badge.svg)](https://github.com/billradar/rustdesk-custom/actions/workflows/tag.yml)
[![Nightly - Development artifacts](https://github.com/billradar/rustdesk-custom/actions/workflows/nightly.yml/badge.svg)](https://github.com/billradar/rustdesk-custom/actions/workflows/nightly.yml)
[![CI - Patch and Build compatibility](https://github.com/billradar/rustdesk-custom/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/billradar/rustdesk-custom/actions/workflows/ci.yml)

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

Windows ARM64 和 iOS 当前计划支持；Web 目前暂不支持。

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
docs/          当前文档及历史记录
tools/         开发和维护工具
requirements.txt
README.md
```

详细架构：[docs/architecture/current.md](docs/architecture/current.md)。

## 环境要求

- Python 3
- Git
- GitHub Actions（用于托管 CI）
- 本地构建所需的平台专用 RustDesk、Flutter 和 Native 构建依赖

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
```

## 开发

```bash
git clone https://github.com/billradar/rustdesk-custom.git
cd rustdesk-custom
git checkout test/development
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

权威签名元数据：[metadata/signing/android-standard.json](metadata/signing/android-standard.json)。

## 验证

仓库级验证：

```bash
python3 scripts/validation/repository_contract.py
```

其他 Contract 位于 `scripts/release/`、`scripts/build/`、`scripts/validation/` 和 `scripts/signing/`。

## 文档

- [架构](docs/architecture/) — 仓库架构
- [构建](docs/build/) — 构建系统和依赖
- [平台](docs/platform/) — 平台信息
- [发布](docs/release/) — 发布和资格验证
- [签名](docs/signing/) — Android 生产签名
- [上游](docs/upstream/) — 上游源码和补丁管理
- [历史记录](docs/archive/) — 历史迁移和验收记录

历史文档用于追溯，不属于当前运行架构。

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

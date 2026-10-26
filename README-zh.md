# RustDesk Custom

[English](README.md) · [简体中文](README-zh.md)

RustDesk Custom 是基于 [RustDesk](https://github.com/rustdesk/rustdesk) 构建的社区维护发行版。在保留上游远程桌面体验的基础上，提供经过审核的定制内容，以及适用于多个平台的 Standard 和 SOS 版本。

项目尽量贴近上游，并通过 GitHub Releases 发布安装包。本仓库用于维护和发行定制版本，不是完整复制 RustDesk 源码的独立分支。

## 主要功能

- 面向桌面平台的 Standard 和 SOS 版本。
- 基于官方 RustDesk 源码构建，并绑定准确的上游版本。
- 提供经过校验的安装包、校验和及架构信息。
- 提供实验性的 Linux Wayland 无人值守软件包。
- 提供 Android 构建；只有通过受保护签名流程后才会发布生产签名包。

## 支持平台

| 平台 | 架构 | 可用版本 |
| --- | --- | --- |
| Windows | x86_64 | Standard、SOS |
| Windows | ARM64 | 实验性支持 |
| Linux | x86_64、ARM64 | Standard、SOS |
| macOS | x86_64、ARM64 | Standard、SOS |
| Android | ARM64、ARMv7、x86_64 | Standard |

平台可用性表示构建和软件包支持，不代表已在所有设备上完成运行测试。当前范围请查看[平台矩阵](metadata/platform/matrix.json)。

## 下载

安装包和发行说明位于 [GitHub Releases](https://github.com/billradar/rustdesk-custom/releases)。请根据操作系统和处理器架构选择软件包，并在安装前阅读发行说明。

## 文档

项目指南请见[中文文档目录](docs/README-zh.md)。英文文档从[英文目录](docs/README.md)进入。

## 上游项目

RustDesk Custom 基于开源远程桌面应用 [RustDesk](https://github.com/rustdesk/rustdesk)。上游项目和产品介绍请访问 [rustdesk.com](https://rustdesk.com/)。

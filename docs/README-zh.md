# 文档目录

[English](README.md) · [简体中文](README-zh.md)

本文档介绍 RustDesk Custom 的使用、维护和故障排查。代码、工作流和机器可读元数据定义当前行为；文档提供背景说明和操作步骤。

## 文档索引

- [项目架构](architecture-zh.md)：仓库定位、主要组成和事实来源。
- [上游源码与补丁](source-and-patches-zh.md)：固定上游提交、选择补丁集和准备源码。
- [构建与验证](build-and-validation-zh.md)：平台状态、构建门禁及验证结果说明。
- [工作流与发布](workflows-and-release-zh.md)：CI、Stable、Nightly 和发布操作。
- [日常操作](operations-zh.md)：环境准备、贡献流程和安全使用工作流。
- [Android 生产签名](android-production-signing-zh.md)：签名要求、安全边界和验证流程。
- [故障排查](troubleshooting-zh.md)：常见问题及诊断步骤。
- [Wayland 无人值守构建](wayland-unattended-zh.md)：实验性 Linux 软件包范围和门禁。
- [CI/CD 流程](architecture/ci-cd-flow-zh.md)：工作流依赖关系概览。

## 文档维护约定

- 英文文档使用 `name.md`，对应中文文档使用 `name-zh.md`。
- 中文页面只链接中文版本，英文页面只链接英文版本；页面顶部提供语言切换链接。
- 行为或操作步骤变化时同步更新两种语言，并保持事实一致。
- 若文档与代码、工作流或元数据不一致，以后者为准。
- 明确区分构建支持与运行时验证，并标出实验性功能。

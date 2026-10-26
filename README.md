# RustDesk Custom

[English](README.md) · [简体中文](README-zh.md)

RustDesk Custom is a community-maintained distribution built from [RustDesk](https://github.com/rustdesk/rustdesk). It offers the upstream remote desktop experience with a reviewed set of customizations, plus Standard and SOS editions for supported platforms.

This project keeps its changes close to upstream and publishes installation packages through GitHub Releases. It is a maintenance and distribution project, not a separate full copy of RustDesk.

## Features

- Standard and SOS editions for desktop platforms.
- Packages built from official RustDesk source and tied to a specific upstream version.
- Verified installers with checksums and architecture information.
- Experimental unattended Wayland packages for Linux.
- Android builds; production-signed packages are provided only when the protected signing process succeeds.

## Platforms

| Platform | Architectures | Availability |
| --- | --- | --- |
| Windows | x86_64 | Standard and SOS |
| Windows | ARM64 | Experimental |
| Linux | x86_64, ARM64 | Standard and SOS |
| macOS | x86_64, ARM64 | Standard and SOS |
| Android | ARM64, ARMv7, x86_64 | Standard |

Platform availability describes build/package support; it does not guarantee runtime testing on every device. See the [platform matrix](metadata/platform/matrix.json) for current scope.

## Download

Get packages and release notes from [GitHub Releases](https://github.com/billradar/rustdesk-custom/releases). Choose the package that matches your operating system and architecture, and read the release notes before installing.

## Documentation

See the [documentation index](docs/README.md) for project guides. The Chinese documentation is available from the [中文目录](docs/README-zh.md).

## Upstream

RustDesk Custom is based on [RustDesk](https://github.com/rustdesk/rustdesk), an open-source remote desktop application. Visit [rustdesk.com](https://rustdesk.com/) for the upstream project and general product information.

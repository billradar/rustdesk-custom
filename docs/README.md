# Documentation

[English](README.md) · [简体中文](README-zh.md)

This guide set explains how to use, maintain, and troubleshoot RustDesk Custom. Source code, workflows, and machine-readable metadata define current behavior; the guides provide context and operating instructions.

## Guides

- [Project architecture](architecture.md): repository scope, components, and source-of-truth rules.
- [Source and patches](source-and-patches.md): upstream revision locking, patch selection, and prepared source.
- [Build and validation](build-and-validation.md): platform support, build gates, and how to read validation results.
- [Workflows and releases](workflows-and-release.md): CI, Stable, Nightly, and release operations.
- [Operations](operations.md): local setup, contribution process, and safe workflow usage.
- [Android production signing](android-production-signing.md): signing requirements, safeguards, and verification.
- [Troubleshooting](troubleshooting.md): common failures and diagnostic steps.
- [Wayland unattended builds](wayland-unattended.md): experimental Linux package scope and gates.
- [CI/CD flow](architecture/ci-cd-flow.md): high-level workflow dependencies.

Chinese readers can use the matching `-zh.md` pages, starting at [the Chinese index](README-zh.md).

## Documentation rules

- Keep English and Chinese guides paired: the English page uses `name.md`; its Chinese counterpart uses `name-zh.md`.
- Link to the same language version as the current page.
- Update both versions when behavior or instructions change, and keep their claims aligned.
- Treat code, workflows, and metadata as authoritative when documentation differs.
- Separate build support from runtime validation and clearly identify experimental features.

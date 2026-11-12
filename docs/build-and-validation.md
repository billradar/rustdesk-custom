# 构建与验证原理

## 1. 平台矩阵是唯一平台清单

`metadata/platform/matrix.json` 定义平台、架构、变体、Runner、启用状态、支持状态和是否为必需目标。不要仅凭 README 中的表格判断目标是否会参与构建。

`metadata/platform/adapter-profiles.json` 保存经过审查的上游构建参数/适配器配置。资格验证会检查启用目标与审查配置之间的一致性。

支持状态的含义：

- **SUPPORTED**：满足仓库当前定义的构建/产物验证要求；不自动代表用户界面、远程会话或运行时行为已经验证。
- **EXPERIMENTAL**：可按明确选项纳入实验构建，不应自动提升为必需的 Stable 目标。
- **PLANNED**：尚未满足启用条件。
- **BLOCKED / UNSUPPORTED / DISABLED**：不能当作可用的正常目标。

## 2. 构建分层

macOS runner 识别直接接受 Intel 的 `macos-26-intel` 和 ARM64 的
`macos-26`。旧上游标签仍按 `metadata/platform/runner-migrations.json`
映射到对应的 26 镜像，以保留旧版重建兼容性。跨架构、预览版和未知未来标签
继续拒绝；runner 标签识别不替代完整上游接口签名审核。

对上游 `3ccb4c4b5b5a8422276dd5f6f211b42e05ec9534` 的静态接口审核
见 [审核记录](audits/nightly-interfaces-3ccb4c4b/review.json)。Linux 配方只为
`inputs.upload-artifact` 提供固定的 `false` 值，执行上游 x86_64 CI 测试分支；
这不启用上游上传，也不接受其他未知输入。普通 Linux 和 Wayland 共用该规则。
Android 在依赖阶段先执行已审核配方中的 JNI 检查；检查失败即停止，旧配方
没有该步骤时保持原行为。macOS ARM64 的新签名、来源 runner 与完整工作流哈希
另行登记，历史策略继续保留。本次审核不代表原生编译、签名或运行验证通过。

1. `scripts/release/qualification.py` 根据矩阵生成目标计划。
2. `scripts/build/` 的平台脚本负责调用对应工具链。
3. `scripts/platform/` 执行构建、采集脱敏诊断信息并处理打包。
4. 产物验证检查 target、架构、校验和、构建信息、来源身份及配置。
5. 聚合步骤核对所需目标是否齐全，以及产物是否属于同一组上游/补丁/构建身份。
6. CI Qualification 把成功结果与准确的自定义提交和上游版本关联，供 Stable 流程消费。

构建脚本不得把失败伪装成成功；失败应保留足够的脱敏诊断信息，并归类到可排查的错误类别。

## 3. 验证层次

| 层次 | 验证对象 | 解决的问题 |
| --- | --- | --- |
| 仓库契约 | 目录、元数据、工作流边界和功能结构 | 仓库是否满足约定 |
| 上游兼容性 | 上游定义、补丁应用和构建接口 | 补丁是否适用于目标上游 |
| 准备源码验证 | SHA、补丁身份、子模块、工作区状态 | 构建输入是否可信 |
| 单目标构建 | 编译、平台配置和打包 | 单个目标是否能生成产物 |
| 产物验证 | ABI、包、校验和、build-info、来源 | 产物是否完整且身份正确 |
| 聚合与资格验证 | 必需目标集合及统一来源身份 | 是否达到 CI Qualification 门槛 |
| Stable 发布门禁 | 同一自定义提交和上游版本的资格记录 | 是否允许进入发布流程 |

## 4. 常用检查命令

仓库级契约：

~~~bash
python3 scripts/validation/repository_contract.py
~~~

针对改动区域，还应检查对应的契约脚本，例如：

~~~bash
python3 scripts/release/channel_contract.py
python3 scripts/release/qualification_contract.py
python3 scripts/release/production_contract.py
python3 scripts/build/config_mir_contract.py
python3 scripts/validation/native_config_contract.py
python3 scripts/signing/android_signing_contract.py
~~~

具体命令是否适用于当前分支，应以文件存在情况和脚本 CLI 为准；先查看脚本的参数说明，不要盲目执行发布或签名入口。

## 5. 如何理解“通过”

`upstream-main-compatibility.yml` 的官方分支解析和 CI 身份校验步骤均在各自步骤中使用现有只读 `github.token` 访问 GitHub API，避免后者退回匿名请求而触发共享 Runner 出口的限流。令牌只传入 API 调用步骤，不增加权限、不改变官方选源，也不绕过未知接口门禁。认证请求仍可能被限流；此改动不声称消除所有 403。

- 单个 Job 通过，不等于整个 Workflow 通过。
- 构建通过，不等于聚合和资格验证通过。
- CI Qualification 通过，不等于已创建 Draft 或正式发布。
- Android ABI 构建通过，不等于生产证书兼容性或应用覆盖安装升级已验证。
- 只有实际执行并成功的验证，才能标记为 PASS。

## Reviewed 1.5.1 CI interface

The upstream CI snapshot `1297da6d186e58d9096be24072ae3998cdbbf8fe` has
reviewed critical signature `fead600e14fce31e0d4f16df77bf86ab2166f01f80464c59b0714c05f53c96f2`.
Rust/Flutter/LLVM/vcpkg, bridge generation and the Windows helper pin are unchanged
from reviewed 1.5.0. The changed Windows job adds tests and opt-in update-metadata
steps. `build.rs` changes the non-Flutter Sciter branch; `build.py` updates the
optional DRM dependency. The custom workflow does not inherit upstream signing
or publication credentials. This is an interface review, not build/runtime proof.

`build_adapter_contract.py` checks that missing reviews, critical-file changes,
toolchain drift and unreviewed runners still fail closed. The separate unattended
workflow remains pinned to its own reviewed 1.5.0 DRM policy; this profile does not
authorize a new libdrmtap pin or new unattended packages.

The later reviewed snapshot `94c321d05ce02ee73304e6cf99187e2d4d96e409`
has exact build signature `ce995eb6df567c3c25d41a2322e1ce82f4adae3fbf9d0d05d80a3d1fb60e733c`.
Compared with `1297da6d`, its Windows Flutter job adds only three template steps
(signature validation, packing, artifact upload), each gated by upstream upload
and signing settings. All other critical inputs and toolchains are unchanged.
The separate Windows ARM64 recipe keeps the same bridge, Flutter version and
source-patch digest; its exact new parent signature is registered separately.
Linux/macOS/Android jobs and recipes are unchanged; their signatures change only
because Flutter package metadata increments `1.5.1+68` to `1.5.1+69`.
The custom workflow does not execute upstream template/signing jobs. These are
exact static interface reviews, not a relaxation of future-change checks or
evidence of native build/runtime success.

Windows ARM64 is a separate experimental lane on the native `windows-11-arm`
runner. It uses Flutter 3.44 and a same-source ARM64 bridge, validates the Dart,
Flutter engine, Rust output, helper DLL, EXE and MSI architecture, then emits
architecture-specific Standard/SOS installer assets. Tag and Nightly include this
lane by default; normal CI remains x86_64-only. Exact-run compilation and runtime
qualification are still needed before promoting it to supported.

## Public upstream test-key fixture during source preparation

Nightly run 40198211193 reached official bridge generation successfully but its
source scan rejected `libs/hbb_common/tests/data/websocket-key.pem`, an upstream
WebSocket TLS integration-test fixture. Reviewed upstream 1297da6d pins hbb_common
edefa08b; the fixture was introduced by upstream hbb_common commit 3aade011.
Source preparation permits only that source-relative path with complete SHA256
`95cf7a0a6890435c98bb3f644678d4fd20d80ff4a296d438a515802e233c6ec9`.
It does not exempt tests directories, PEM files, other paths or modified secret
content. Failures now identify only the filename and withhold the value.
The global production input/package/log scanner remains strict, without this
source-only exception. Regression contracts cover changed content, relocated keys
and ASCII/UTF-16 tokens.

## 1.5.1 native platform recipe review

Run 40199720676 passed prepared-source scanning, then Linux/macOS/Android stopped
at their independent platform adapter gates. The Windows/bridge profile approval
was not a platform recipe approval. `metadata/platform/adapter-profiles.json` now
records the exact native signatures for upstream 1297da6d, seven supported native
architecture profiles, baseline comparison, critical file hashes and review scope.
Linux/Android job definitions and toolchains remain unchanged; the global version
and shared source/build file fingerprints changed. macOS also adds conditional
tests, deployment-target export and opt-in official signing/update routing. Only
the named setup/build scripts are inherited; custom macOS packages remain unsigned.
The separate Wayland DRM policy is not expanded by this review. Signature approval
is not package/runtime validation; unknown future files/tools/recipes and disabled
jobs remain blocked, with regression tests for those cases.

### GitHub Action JavaScript runtimes

All current directly used JavaScript Actions declare Node.js 24. MSBuild uses
Microsoft's v3 commit `30375c66a4eea26614e0d39710365f22f8b0af57`. Flutter setup
uses `1a449444c387b1966244ae4d4f8c696479add0b2`, whose nested cache Action is v5
(Node.js 24), replacing the old composite's cache v3 (Node.js 16).

The LLVM installer is the narrowly maintained local copy documented in
[its provenance guide](../.github/actions/install-llvm/README.md), because upstream
v2.0.9 still declares Node.js 20. Its runtime declaration changes to Node.js 24;
its JavaScript, asset catalog and license stay unchanged and hash-verified.
No deprecation-warning suppression or insecure runtime opt-out is used.

The `Action runtime compatibility` workflow exercises actual Windows MSBuild and
LLVM installation without build credentials or production signing. The local
`python3 -m scripts.validation.action_runtime_contract` checks bundle integrity,
retired references and the Node.js 24 entry point. Recheck transitive composite
Action dependencies when upgrading their pinned revisions. Historical workflow
runs retain their original Action versions and annotations.


Windows ARM64 Flutter setup uses `FLUTTER_ROOT` from the pinned Flutter Action,
not its `CACHE-PATH` output (which may point to a parent cache directory). The
shared `scripts/build/prepare_windows_arm64_flutter.ps1` checks required SDK entry
points before changing its Dart cache, then verifies native ARM64 Dart and the
release engine. The credential-free Action runtime workflow exercises this same
script on `windows-11-arm`, rejects a parent cache directory and validates engine
and Python PE architecture. This verifies toolchain preparation, not a complete
RustDesk ARM64 package or real-device session.

## Exact bridge-comment interface review (2026-11-02)

Official SHA `6aec3069aec486ad7df07429a0a1ee411fc8d73a` changed three
`bridge.yml` comment lines relative to `94c321d05ce02ee73304e6cf99187e2d4d96e409`:
one YAML comment and two full-line Bash comments in the bridge dependency step.
Replacing exactly those three texts reproduces the new file byte-for-byte. YAML
parsing alone retains Bash comments as strings; the review compares the parsed
workflow after replacing only the two known Bash comment lines. The complete
Windows job, tools and other critical file digests are unchanged. The ARM64
source-patch header also changes comments; its complete executable body from
`set -euo pipefail` onward is byte-identical. Its new raw SHA-256 is registered
separately without relaxing source receipt verification. Both static x64 and native ARM64 profile checks were executed.

The exact new signature is `f13aa9d4edd1afa76be5803dd3c28cf01785c359bd393e3d2b090312797308a6`,
registered as `reviewed-151-6aec30`; its ARM64 recipe differs only by that parent
signature and the exact header-comment source-patch digest. [Archived evidence](upstream-interface-reviews/bridge-comments-20261102.json)
contains both original bridge files, the exact diff and complete critical inputs.
The adapter contract verifies these relationships and retains negative tests for
missing reviews, raw-file drift, toolchain drift and unknown runners. Production
hashing does not strip comments or normalize unknown interfaces. This review
changes no source resolution, patches, matrix, Wayland, signing or publication
authorization, and does not claim native package/runtime validation.

### Stable Draft attestation lookup

Stable reuse verifies both JSON metadata files by immutable GitHub asset ID, then verifies the manifest's Sigstore proof and exact installer inventory. Public checksum-only releases no longer satisfy this gate; historical Releases remain unchanged. See [Release attestation](release-attestation.md).

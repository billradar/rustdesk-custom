# 上游源码与补丁实现原理

## 1. 为什么不直接维护完整上游副本

仓库把自定义修改放入 `patchsets/`，把上游 RustDesk 当作独立来源。这样可以明确回答三个问题：构建基于哪个上游提交、应用了哪一代补丁、补丁内容是否与资格验证时一致。

## 2. 源码准备过程

核心入口位于 `scripts/source/`：

1. **解析上游身份**：发布/CI Channel 逻辑把请求的 tag 或 branch 解析为准确 commit SHA。
2. **获取固定提交**：`scripts/source/prepare.sh` 从官方 `rustdesk/rustdesk` 获取指定 ref，解析并验证最终 SHA；若提供了预期 SHA，二者必须一致。
3. **初始化子模块**：初始化递归子模块，并检查关键子模块提交是否与上游主仓库记录一致。
4. **选择补丁集**：`scripts/upstream/patchsets.py` 负责补丁集元数据、内容和哈希相关逻辑；具体调用方式以该脚本的 CLI 为准。
5. **应用补丁并生成准备源码**：`scripts/source/` 下的准备和验证逻辑将补丁应用到干净的上游树，并生成来源清单。
6. **拆分变体**：Standard 与 SOS 使用独立的准备源码树，避免一个变体的修改污染另一个变体。
7. **上传准备源码产物**：`prepare-source.yml` 将准备源码作为后续构建工作流的输入。

## 3. 关键不变量

- 准备源码目录必须是空目录，不能用脚本隐式重置用户已有工作区。
- 解析到的上游 SHA 必须与调用方锁定的 SHA 一致。
- 子模块必须与上游记录匹配，且工作区保持干净。
- 补丁集必须通过结构和内容校验；不允许在构建过程中临时修改补丁却继续沿用旧身份。
- Standard 与 SOS 的公共来源身份应一致，变体专属补丁则单独追踪。
- 所有来源清单和产物身份都应由实际脚本生成，不应人工编造。

## 4. 修改补丁的推荐步骤

1. 确认目标上游提交和当前 patchset。
2. 在独立工作分支中修改补丁或补丁集元数据。
3. 运行补丁集对应的校验，并执行仓库级契约：`python3 scripts/validation/repository_contract.py`。
4. 运行兼容性/构建 CI，确认变更确实适用于目标上游提交。
5. 检查来源清单、补丁哈希和构建产物的身份是否一致。
6. 通过 PR 审查后再合并；不要直接改写共享分支历史。

## 5. 什么时候需要重新验证

上游 SHA、补丁内容、patchset 选择、构建适配器、目标矩阵或来源清单结构发生变化时，都应重新运行相关验证。仅更新文档不应触发完整构建。

## 1.5.1 source compatibility

The 1.5.1 development snapshot `1297da6d186e58d9096be24072ae3998cdbbf8fe`
was validated with the pre-render-policy `v2` patch hash. Standard/SOS Rust configuration API compilation, bridge
generation, both Flutter analyses and CI qualification passed in run
[40175351746](https://github.com/billradar/rustdesk-custom/actions/runs/40175351746).
The exact evidence commit and upstream identity are recorded in the v2 manifest.
This is not a claim about an unobserved future 1.5.1 tag, native packages or real
remote-session behavior. A v3 generation is reserved for an actual incompatible
upstream API boundary, not a new version number alone.

## Hardware rendering policy in all custom builds

Both v1 and v2 Common helpers force `allow-always-software-render=N` through
`config::OVERWRITE_SETTINGS` after loading custom client settings. This overrides
persisted `Y` values and is inherited by Standard, SOS and the unattended Wayland
build flavor on every platform; it is not a new patch generation. On Linux the
normal upstream startup path consequently removes `LIBGL_ALWAYS_SOFTWARE`.
The setting cannot be re-enabled in these custom builds. Other rendering and
codec choices retain their existing behavior.

On the tested AX211/Intel+NVIDIA laptop, forcing software rendering crashed Mesa
when libdrmtap explicitly selected the Intel EGL device. Removing the setting
allowed EGL 1.5 initialization and a user-confirmed locked-screen remote session.
That is local configuration evidence for the previous package, not validation of
new packages. New Common hashes require fresh build/qualification evidence; old
validation entries remain explicitly historical.


## Connection manager background window

Common `0004-cm-background-window.patch` is shared by Standard and SOS in both
patch generations. It adds `approve-mode=password` as a default (saved approval
choices remain effective), and uses upstream's fixed-password/hide predicate
without requiring Pro or a renamed executable. An unknown IPC result keeps CM
hidden until the user opens it from the local tray.

The CM starts as a hidden native window. Its hide operation never minimizes it;
Windows creates it as a tool window, Linux realizes the Flutter GL view without
mapping the top-level window, and macOS gates order-in before Cocoa shows it.
The serialized Dart visibility policy blocks automatic show/focus from connection
and chat events. The main window's startup and tray Open action retain upstream
behaviour. The CM's custom close/minimize controls hide it without disconnecting;
per-session Disconnect buttons remain available after manual opening. OS/session
shutdown and automatic teardown after the last connection still use upstream
cleanup, rather than keeping an orphan CM alive.

With the service/tray running, use the new **Current connections** tray menu item
to show an existing CM. It sends local control IPC on a separate, unassociated
stream; it does not spawn a duplicate manager, bypass authentication, or accept a
pending session. Rust latches the request until the CM's timer consumes it, so
requests arriving during Flutter initialization are retained. No CM means there
is no current manager to show. If the desktop shell has no tray indicator, running `rustdesk --show-cm`
manually sends the same local request without opening the main window. Use the
installed executable name/path if it differs. Neither entry starts a new CM.

`allow-hide-cm` remains a default, not an enforced overwrite of saved preferences.
Settings changes apply to the next CM process; the settings checkbox reports the
effective configuration. A previously saved click-approval mode continues to show
the approval window. This is necessary to preserve the user's approval choice.
System permission dialogs and UAC are outside this CM window policy.

Validation commands:

```bash
python3 scripts/validation/cm_window_contract.py --source /path/to/prepared-source --dart dart
python3 scripts/validation/repository_contract.py
```

The compatibility workflow runs the prepared-source checks and the pure-Dart
policy sequences, and analyzes all changed Dart files. Native package/runtime
validation must separately cover cold start, first connection, reconnect,
multiple peers, incoming chat, tray open/hide/reopen, manual disconnect, last
session cleanup, and the main window remaining usable. Check both desktop and
taskbar visibility and focus, on Windows, Linux X11/Wayland and macOS. Passing
source checks is not evidence of zero-flash native-window behaviour.

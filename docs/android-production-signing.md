# Android 生产签名：原理与操作步骤

## 1. 目标与安全边界

Android Standard 的生产签名由专用硬件签名路径处理，与普通 CI 的编译和打包分离。普通 CI 不应访问生产签名 Environment、YubiKey、PKCS#11 设备或生产 PIN。

生产签名流程必须由明确授权的 Stable Workflow 触发，并满足工作流中的仓库、分支、事件、构建成功和资格验证条件。仅有构建成功不能触发生产签名。

## 2. 当前记录的身份

机器可读身份记录位于 \`metadata/signing/android-standard.json\`。当前文件记录：

- Android 包名：\`com.carriez.flutter_hbb\`
- 生产硬件身份：YubiKey PIV slot \`9C\`
- PKCS#11 object ID：\`02\`
- 生产证书 SHA-256：\`559c1ede0fbe3a01f29bcac9d0b34bd9691df3562c83e3019a930506fbc7b6f5\`

**重要：生产证书与记录中的 legacy 证书指纹不同。** 当前元数据将 legacy Android 签名身份标记为未恢复/未验证，升级兼容性也不能据此推断为通过。除非专门验证并更新证据，否则不能宣称新身份可无缝覆盖安装旧签名 APK。

## 3. 执行结构

1. 普通 Android build Job 生成待签名产物。
2. 独立的 \`android-sign\` Job 只在工作流定义的受限条件下运行。
3. Job 使用专用 self-hosted ARM64 Runner 标签组：\`self-hosted\`、\`linux\`、\`arm64\`、\`rustdesk-signing\`、\`android-signing\`、\`yubikey\`。
4. Job 进入 GitHub Environment：\`android-production-signing\`。
5. Environment Secret \`YUBIKEY_PIV_PIN\` 只注入需要它的预检/签名步骤，不应打印或传递给普通构建。
6. 签名辅助逻辑校验输入产物来源、包名、ABI、身份指纹和签名结果；任何不匹配都应失败关闭。
7. 签名完成后，结果进入后续聚合验证，不应绕过最终产物验证。

专用 Runner、Environment 和 PIN 的真实配置状态应在 GitHub 设置中核实；文档只能说明仓库要求，不能代替在线配置检查。

## 4. 操作前检查清单

- [ ] 确认正在运行的是仓库官方 Stable Release Pipeline，而不是普通 CI 或 Nightly。
- [ ] 确认目标自定义提交和上游 SHA 已通过对应资格验证。
- [ ] 确认工作流输入明确授权当前生产签名操作。
- [ ] 确认专用 Runner 在线且是预期的可信设备。
- [ ] 确认 Environment 审批和 Secret 配置符合仓库策略。
- [ ] 确认公开身份元数据中的证书指纹、slot 和 object ID 与真实硬件一致。
- [ ] 确认签名产物来源、ABI、包名和校验和可追溯。

## 5. 执行步骤

1. 在 GitHub Actions 中打开 Stable Release Pipeline。
2. 先核对当前分支、提交 SHA、上游版本和 release mode；生产签名只允许工作流实际定义的受限上下文执行。
3. 使用 dry-run 验证非破坏性的发布门禁；dry-run 不会替代真实硬件签名验证。
4. 只有所有资格、Runner、Environment 和授权条件满足时，才执行被明确授权的生产流程。
5. 检查签名 Job 的结果、证书指纹验证、产物上传和最终聚合结果。
6. 保存运行链接和非敏感验证摘要；不要保存 PIN 或可用于重放签名的敏感材料。

## 6. 安全禁止事项

- 不得将 \`YUBIKEY_PIV_PIN\` 放入仓库文件、命令行参数、日志、PR 评论或文档。
- 不得把生产 Secret 暴露给普通 build、Nightly 或不受信任的 PR。
- 不得使用软件密钥替代硬件身份以绕过失败门禁。
- 不得在身份、来源或 Runner 有疑问时继续签名。
- 不得将“签名工具可用”或“签名 Job 通过”直接等同于旧版本升级兼容性已验证。

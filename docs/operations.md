# 日常操作手册

## 1. 准备环境

基础仓库工具需要 Python 3 和 Git；完整构建还需要对应平台的 RustDesk、Flutter、Rust、Native 工具链及工作流配置的其他依赖。

~~~bash
git clone https://github.com/billradar/rustdesk-custom.git
cd rustdesk-custom
git checkout test/development
python3 -m pip install -r requirements.txt
~~~

## 2. 分支与 PR 约定

本仓库的两个长期分支是：

- `main`：受保护的稳定集成和发布基线。
- `test/development`：共享开发与集成分支。

常规修改直接在 `test/development` 上进行，完成检查后创建从 `test/development` 指向 `main` 的 PR。除非用户明确要求或平台限制确有必要，不创建 `feature/*`、`fix/*` 等临时分支。不要直接写入受保护的 `main`。

开始工作前检查两个分支的 HEAD、merge-base、ahead/behind 和相关提交。不要把文件树相同误认为 Git 历史相同。不得擅自重置、强推、rebase、删除或替换共享分支引用；任何破坏性历史操作都必须先获得明确授权并核对目标 SHA。

PR 已创建不代表已合并。合并后应核实合并提交和分支比较结果。

## 3. 修改前先理解边界

1. 找到实现所在的 `scripts/`、`.github/workflows/`、`.github/actions/` 或 `metadata/`。
2. 找到调用它的工作流和契约测试。
3. 确认当前权威配置，而不是先改 README 或复制一份配置。
4. 判断变更是纯文档还是功能变更。
5. 对涉及发布、签名、来源身份的变更，先列出安全边界和失败条件。

## 4. 本地验证

仓库级检查：

~~~bash
python3 scripts/validation/repository_contract.py
~~~

随后运行与变更相关的契约脚本，并检查退出码。需要构建的变更还必须通过 GitHub Actions 中实际使用的工具链完成兼容性、构建、产物和聚合验证。

仅修改文档时，不需要本地构建 RustDesk；文档 PR 应由轻量检查覆盖。不要为了让文档 PR 通过而修改功能契约或关闭检查。

## 5. 提交、PR 与验证记录

1. 在 `test/development` 完成范围明确的修改。
2. 检查完整 diff，确认没有无关功能变更、密钥材料或过期路径。
3. 执行相关验证，记录真实结果和运行链接。
4. 创建从 `test/development` 到 `main` 的 PR。
5. 检查所有必需 CI 结果、文档链接和 PR 描述。
6. 按授权进行审查与合并；不要把“已创建 PR”描述为“已合并”。
7. 合并后核实最终提交 SHA 和两个分支的实际状态。

## 6. 文档变更要求

- 当前规则只保留一个权威说明；其他文档链接到它。
- 文档中的文件路径、工作流名、输入名和命令必须在仓库中真实存在。
- 把“已实现”“已测试”“已发布”分开表述。
- 涉及时间变化的状态（例如某次 CI 结果）要附带具体运行链接或提交身份，避免将历史结果误写成当前状态。
- 工作流或接口发生变化时，搜索并修正所有失效引用。

## 7. 生产操作限制

生产发布和 Android 签名必须使用受保护的 GitHub Actions 路径。不要把 PIN、令牌、密钥材料、签名输入或完整敏感环境转储写入日志、Issue、PR 或文档。遇到身份不匹配、来源不明或 Runner 不可信时，应停止操作并调查。

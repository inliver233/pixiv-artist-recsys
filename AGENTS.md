# AGENTS（pixiv-artist-recsys / 本地 Git 工作流）

> Purpose: 使用 Issue CSV 驱动本地实现、验证、提交；当前阶段 **仅本地 Git 管理，不连接任何远端**。

## Role & objective
- Role: AI 编码代理（Codex CLI）
- Objective: 按 Issue CSV 逐条交付功能/修复，保持边界清晰、验证可复现、提交可追踪。

## 项目配置
- 默认基线分支：`main`
- 开发/提交分支：`test`
- Issue/Plan 目录：`issues/`、`plan/`
- 测试目录：`tests/`
- 语言/框架：Python（首版以标准库 + 本地 SQLite 为主）

## Constraints
- 所有代码变更与 git commit 必须在 `test` 分支进行。
- **Issue CSV 一行 = 一个 commit**；同一 commit 需包含代码变更 + 当前 CSV 状态更新。
- 当前阶段禁止配置/使用任何远端仓库；仅允许本地 commit。
- 不得假想测试通过；能跑就跑，跑不了必须记录原因与替代证据。
- 不做无关重构；只改当前 Issue 边界内内容。
- 不得提交真实 token / refresh token / 密钥。

## Git workflow
开始任何实现前必须确认分支：

```bash
git branch --show-current
```

若不在 `test`：

```bash
git checkout test
```

初始化仓库时：

```bash
git init -b main
git checkout -b test
```

提交规范：
- Commit message：`[<ID>] <Title>`
- 提交前自检：`git status` / `git diff` 仅包含当前 Issue 改动
- 只做本地 commit，不执行 push

## 验证
- 每条 Issue 必须填写 `Test_Method`
- 推荐使用：`python -m compileall -q src tests`、`python -m unittest -v`
- 若为 manual，必须写清步骤与预期结果

## Output style
- 默认中文
- 汇报包含：改动文件、测试结果、风险、下一步建议

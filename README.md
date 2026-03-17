# pixiv-artist-recsys

一个面向本地运行的 Pixiv 画师推荐 UID 获取系统。

## 当前阶段目标
- 建立可追踪的本地 Git / Plan / Issue CSV 工作流
- 生成基于既有仓库调查的能力矩阵与实施计划
- 搭建推荐系统首版代码骨架
- 使用本地 SQLite 作为首版存储后端

## 目标系统
输入：Pixiv refresh token、用户偏好配置。
输出：符合已关注审美的未关注画师 UID 列表，以及解释信息。

## 目录
- `.codex/`：本地工作流 prompt / skill 资产
- `plan/`：实施计划
- `issues/`：Issue CSV
- `docs/investigation/`：调查资料与矩阵
- `docs/architecture/`：架构说明
- `src/`：源码
- `tests/`：测试
- `data/`：本地数据目录（默认不提交运行时数据库）

## 本地开发
```powershell
python -m compileall -q src tests
python -m unittest -v
```

## Git 工作流
- 本地仓库基线：`main`
- 开发分支：`test`
- 当前阶段只做本地 commit，不配置 remote

## 下一步
后续将逐步落地：鉴权、代理、Pixiv client、关注同步、画像构建、候选召回、排序与反馈闭环。

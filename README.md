# Agent Interview Assistant

本项目是一个纯本机单用户的 Agent 开发面试题库和训练助手。Phase 1A 提供 Agent Topic/Tag、手动题目管理、中文与英文混合搜索、收藏/错题标记、规则驱动练习和 PracticeReview 历史。

## 开发环境

当前仓库按 `AGENTS.md` 使用已有 Conda 环境 `test` 开发；Conda 是本机开发约定，不是产品运行要求。若当前 zsh 尚未载入 Conda hook，只在当前终端载入：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate test
```

安装后端依赖：

```bash
cd backend
python -m pip install -r requirements.txt
```

前端使用 Node.js/npm：

```bash
npm --prefix frontend install
```

## 本机开发运行

Flask 只绑定回环地址。Vite 默认 origin 为 `http://localhost:5173`；设置 `APP_ALLOWED_ORIGINS` 允许 Vite 开发来源，然后在后端终端运行：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate test
export APP_ALLOWED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
cd backend
alembic upgrade head
flask --app app run --host 127.0.0.1 --port 5000
```

在另一个终端从仓库根目录启动 Vue：

```bash
npm --prefix frontend run dev
```

Vite 将 `/api` 代理到 `http://127.0.0.1:5000`。没有 `Origin` header 的本机请求允许通过；同源本机来源按请求 Host 校验；其他开发来源必须列入 `APP_ALLOWED_ORIGINS`。若 Vite 使用了不同端口，请在该配置中加入实际本机来源。

## 构建与 Flask 静态服务

构建前端：

```bash
npm --prefix frontend run build
```

构建结果位于 `frontend/dist`。该目录存在时，Flask 提供静态文件并将前端路由回退到 `index.html`；未知 `/api` 路径仍返回 JSON 404，不会回退成前端页面。

## 数据库与本机数据

数据库使用 SQLAlchemy 2.x + Alembic + SQLite。首次启动和升级后启动 Flask 前，都先在 `backend/` 目录运行：

```bash
alembic upgrade head
```

默认 SQLite 数据库位于 `platformdirs` 提供的平台应用数据目录，不存放在仓库中。可用 `APP_DATA_DIR` 更换本机数据目录，或用 `DATABASE_URL` 指定 SQLite URL。应用启动时会按稳定 Topic slug 幂等补充初始 Agent Topic，不覆盖用户对既有 Topic 的修改。

API 错误使用统一结构：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid question",
    "fields": {"text": "Question text is required"}
  }
}
```

## 测试

后端测试对每个用例使用 `tmp_path` 下的独立 SQLite 数据库，并通过 Alembic 创建 schema；不会访问真实应用数据目录。

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate test
(cd backend && pytest -q)
npm --prefix frontend test
npm --prefix frontend run build
```

Phase 1A 不包含截图/OCR、SavedAnswer、答案评分、复习调度、Project/Resume/Material、LLM、模拟面试、语音/视频、多 Agent 或社交平台采集。

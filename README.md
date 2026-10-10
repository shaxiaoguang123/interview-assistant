# Agent Interview Assistant

面试题库助手

本项目是一个纯本机单用户的 Agent 开发面试题库和训练助手。Phase 1A 提供 Agent Topic/Tag、手动题目管理、中文与英文混合搜索、收藏/错题标记、规则驱动练习和 PracticeReview 历史。

## Phase 2：保存回答

- 题目详情中点击“新建回答”，明确保存后进入回答库；同一规范题可保存多条独立回答。
- 编辑回答会追加新版本，原正文和旧评分保留；新版本默认未评分。
- 1–5 分表示答案质量，四级 PracticeReview 表示题目掌握程度，两者独立。
- “设为首选”替换当前归并组的置顶偏好；归并双方均有首选时，预览要求人工选择保留哪一条，回答不会删除。
- 完成练习自评后，临时正文继续保留，选择“保存本次回答”或“不保存，继续下一题”；最后一题完成后仍可保存。刷新后未保存草稿不保留。
- 回答保存带真实 SessionItem / PracticeReview 来源；回答编辑、评分与置顶不创建或修改掌握度事件。
- 归档隐藏回答但保留版本，可勾选“包含已归档”查看；规范题聚合子题回答并保留原始 question_id。

升级前按既有方式备份本机数据，运行 `alembic upgrade head`。`0005_saved_answers` 增量新增回答表和可选练习关联，不重建旧数据库。此阶段不包含 AI 回答或复习调度。

## Phase 3：练习与复习增强

- 练习设置支持随机、Topic、Tag、收藏、错题与到期复习，并展示实际可练习题数。
- 收藏按归并组标记聚合；错题包含手动标记或组内最新自评为「不会」的题目。
- 四级掌握度采用固定间隔：不会 1 天、模糊 2 天、基本会 7 天、熟练 14 天，以原始 `PracticeReview.reviewed_at` 为基准，统一 UTC 存储、按本地时间显示。
- 更正评价会重算摘要，但保留原 Review ID 和事件时间；归并只重算规范题摘要，不新增或改写历史事件。
- 到期队列只选择已到期的 active 规范题，按最早到期顺序排列；未复习题不会自动入队。保存回答、答案质量评分、收藏和错题标记不会改变复习日期。
- 题目详情展示最近练习、最近掌握度和下次复习；练习评分后仍可保存本次回答，包括会话最后一题。
- 「学习进度」分别展示掌握度次数、当前到期题、Topic 覆盖和回答质量分布。弱项默认统计最近 30 天，可切换 7/90 天；少于 3 次自评显示「练习记录不足」，不进行弱项排序。每个历史事件只计一次，Topic 使用规范题当前分类。
- 进度中的掌握度总次数包含全部历史事件；有效题、覆盖、收藏、错题、到期和回答数量限定当前有效题库。回答统计仅包含未归档回答的当前版本。

升级仍使用 `cd backend && alembic upgrade head`。`0006_phase3_review_schedule` 在 0005 上新增摘要字段并回填既有 Review，同时安全复制 PracticeSession 以扩展 SQLite CHECK；旧 SessionItem、Review、回答来源和 FTS 保留。迁移有事务及外键验证，失败会回滚；运行前按既有方式备份本机数据。当前不包含自适应复习算法或 AI 自动评分。

新增 API：`GET /api/v1/progress?window_days=30`、`GET /api/v1/practice-options`、`POST /api/v1/practice-sessions/preview`（mode、filters）；原创建练习接口接受六种模式。新会话 `selector_version=v2`，旧会话固定顺序不改变。

## 开发环境

当前仓库按 `AGENTS.md` 使用已有 Conda 环境 `test` 开发；Conda 是本机开发约定，不是产品运行要求。若当前 zsh 尚未载入 Conda hook，只在当前终端载入：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate test
```

安装后端依赖：

```bash
conda run -n test python -m pip install -r backend/requirements.txt
```

前端使用 Node.js/npm：

```bash
npm --prefix frontend install
```

## 本机开发运行

Phase 1B 使用 RapidOCR + ONNX Runtime CPU 进行本地 OCR。Flask 必须以单进程入口启动；请勿用 Flask CLI 或自动重载模式运行，否则重载子进程可能把仍在运行的任务误判为中断。

Flask 只绑定回环地址。Vite 默认 origin 为 `http://localhost:5173`；设置 `APP_ALLOWED_ORIGINS` 允许 Vite 开发来源，然后在后端终端运行：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate test
export APP_ALLOWED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
cd backend
alembic upgrade head
python run.py
```

`run.py` 是唯一受支持的服务器启动入口。它会在启动时执行一次中断 Job 和删除 tombstone 恢复，并始终设置 `use_reloader=False`；即使设置 `APP_DEBUG=1` 也不会启用自动重载。Phase 1B 不支持多个 Flask 服务进程。

默认监听 `127.0.0.1:5000`。若使用 Flask 内置静态前端且本机端口冲突，可从 `backend/` 通过 `APP_PORT=5017 python run.py` 指定另一个本地端口；仍须使用同一个 run.py 单进程入口。Vite 开发代理仍默认指向 5000。

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

### 本地 OCR 模型

OCR 运行时固定为 rapidocr==3.9.2 与 onnxruntime==1.30.0，模型为 RapidOCR 3.9.2 发布的 PP-OCRv6 small detection/recognition，以及 PP-OCRv4 mobile orientation classifier。默认目录：

~~~text
<应用数据目录>/ocr-models/rapidocr-3.9.2/ppocrv6-small/
  manifest.json
  PP-OCRv6_det_small.onnx
  PP-OCRv6_rec_small.onnx
  ch_ppocr_mobile_v2.0_cls_mobile.onnx
~~~

APP_DATA_DIR 未设置时使用本机平台应用数据目录。也可以通过 OCR_MODEL_DIR 指定其他本机目录，并用 OCR_MODEL_MANIFEST_PATH、OCR_DETECTION_MODEL_PATH、OCR_RECOGNITION_MODEL_PATH 和 OCR_CLASSIFICATION_MODEL_PATH 指定该目录内的文件。Manifest 必须声明 model_release=PP-OCRv6-small、RapidOCR/ONNX Runtime 版本以及三个文件名和 SHA-256；程序逐项校验固定摘要，不接受 manifest 自行改写固定摘要。

仅首次准备模型时下载到本机数据目录；正常运行 OCR 不会下载模型。以下命令使用 RapidOCR 3.9.2 的 ModelScope 发布文件：

~~~bash
MODEL_DIR="$HOME/Library/Application Support/AgentInterviewAssistant/ocr-models/rapidocr-3.9.2/ppocrv6-small"
mkdir -p "$MODEL_DIR"
curl --fail --location "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx" --output "$MODEL_DIR/PP-OCRv6_det_small.onnx"
curl --fail --location "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx" --output "$MODEL_DIR/PP-OCRv6_rec_small.onnx"
curl --fail --location "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx" --output "$MODEL_DIR/ch_ppocr_mobile_v2.0_cls_mobile.onnx"
shasum -a 256 "$MODEL_DIR"/*.onnx
~~~

将校验结果与固定版本对应的 SHA-256 清单比对后，创建 manifest.json，结构如下：

~~~json
{
  "model_release": "PP-OCRv6-small",
  "rapidocr_version": "3.9.2",
  "onnxruntime_version": "1.30.0",
  "files": {
    "det": {
      "filename": "PP-OCRv6_det_small.onnx",
      "sha256": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"
    },
    "rec": {
      "filename": "PP-OCRv6_rec_small.onnx",
      "sha256": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"
    },
    "cls": {
      "filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
      "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"
    }
  }
}
~~~

验证离线 CPU 运行时不下载模型：

~~~bash
(cd backend && conda run -n test python scripts/ocr_cpu_smoke.py --offline "../pic-test/小红书-Agent评测策略专家_1_泽华留学生求职_来自小红书网页版.jpg")
~~~

Smoke Test 输出 Python/macOS/架构、RapidOCR/ONNX Runtime 版本、provider、模型发布版本和摘要、识别文本块数及耗时。开发验收时的实测环境为 Python 3.12.15、macOS 27.0.1、arm64，RapidOCR 3.9.2、ONNX Runtime 1.30.0；固定依赖安装后 pip check 无冲突，provider 为 CPUExecutionProvider。对上述本机截图的禁网 Smoke Test 识别 14 个文本块，耗时约 1.08 秒。实际截图属于用户数据，不纳入 Git 自动化 fixtures。

模型缺失或校验失败只会让已领取的 OCR Job 以 OCR_MODEL_MISSING 或 OCR_MODEL_INVALID 结束；Flask、题库和练习页面仍可使用。模型初始化在 Job 领取后延迟执行，不会让 Job 留在 queued。运行时不会隐式下载模型或连接 OCR 服务。

### 来源归档与永久删除

来源归档只设置 archived_at，原图、OCRBlock 和 QuestionSource 保持可访问。有任意 QuestionSource、OCR 候选、OCRBlock 或已尝试 Job 历史时，永久删除返回 409 CONFLICT，请归档来源。仅上传后仍 queued 且没有历史引用的来源可永久删除。删除时临时将原图与方向校正预览移至应用数据目录下的 tombstone；数据库失败会恢复文件，重启时会按 SourceAsset 行是否还存在恢复或清理残留 tombstone。

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

当前实现范围是 Phase 0–3：题库、OCR、规则相似题审核与人工 Canonical Merge、保存回答和固定间隔复习。Phase 1B 不包含 VLM/LLM 自动提题或分类、自动语义归并、SavedAnswer、Project/Resume/Material、LLM 参考答案、模拟面试、语音/视频、多 Agent 或社交平台自动采集。


## 相似题审核与规范题归并（Phase 1C）

在题目详情或截图收件箱审核相似题。规则只提供建议：选择「确认为同题并归并」后才保存人工同题结论，并进入只读预览。

- 正式题可以选择任意一方作为规范题；OCR 待审核候选始终归并至已有正式题。
- 核对双方原文、原始 ID、来源/练习历史与分类。默认分类并集，停用分类可保留或移除。
- 只有点击「确认归并」才提交 canonical 指针。取消保留同题结论，可稍后继续或重新分类；候选在真正归并前仍待审核。
- 预览过期返回 409 时重新获取预览，再次核对分类并确认，界面不会自动重试旧 token。
- 原始 QuestionSource、OCRBlock、SessionItem、PracticeReview ID 保持不变。子题旧 URL 转至规范题，规范题提示可打开原始只读正文与聚合历史。
- 搜索子题原文只显示规范题，分类按规范题最终选择筛选；新练习只选规范题，旧练习可以继续完成。
- 「合并 OCR 候选区域」用于整理同一截图的候选边界，与跨题目的「归并为规范题」不同。

可选 LLM/VLM 建议、自动归并和多用户功能尚未实现。

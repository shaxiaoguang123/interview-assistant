# Agent 开发面试训练助手设计

> 状态：已完成产品方案确认，等待书面规格评审。

## 目标

为一个人建立可长期使用的 Agent 开发方向面试训练系统。系统以用户自己的截图和资料为主要输入，维护可追溯题库，记录每次作答，并根据用户选择的规则安排后续练习。

首版采用 Flask API 与 Vue 前端分离的本地单用户架构。LLM 辅助 OCR 复核、标签建议、参考答案、回答润色和 Rubric 评价；它不生成或决定下一道练习题。

## 已确认的产品约束

- 首版只在用户自己的电脑上运行，不做账号、云同步或多用户。
- 前端与后端分离开发：Vue 3 + TypeScript + Vite 调用 Flask REST API。
- Python 命令使用已有 Conda test 环境；前端使用 Node/npm。
- 截图是当前主要采集源。社交平台适配器后续增加，首版不做自动登录或爬取。
- 一道题可有多次回答；回答历史不可覆盖。用户可选择多份正式回答，其中最多一份是最佳回答。
- 回答默认展示顺序：最佳回答、其余正式回答按用户评分从高到低、再按时间；LLM 评分不改变正式/最佳标记或排序。
- LLM 生成的润色先作为草稿；只有用户保存后才形成一条新的回答记录。参考答案与用户作答分开保存。
- 简历和项目资料长期保留并支持版本；每次调用 LLM 时用户明确选择不使用资料、选一份或多份资料。
- 首版不做语音、视频、复杂模拟面试、多 Agent、多用户协作或跨设备同步。

## 用户与核心任务

主要用户是一名准备 Agent 开发岗位面试的工程师。核心任务是：

1. 把截图中的一题或多题可靠地整理进个人题库，并随时找回题目原始来源。
2. 按题目、主题、知识点、错误、收藏或复习时间主动选择训练范围。
3. 多次作答，保留回答演进过程，选出正式和最佳回答。
4. 在需要时借助 LLM，但始终能检查其使用了哪些资料、引用了什么证据。
5. 通过练习历史了解覆盖范围、弱项和长期变化。

## 信息架构与页面

| 页面 | 主要内容与操作 |
|---|---|
| 首页 /dashboard | 今日复习队列、最近练习、待复核截图、主题覆盖和个人评分趋势。 |
| 采集收件箱 /inbox | 上传截图、查看任务状态、原图与 OCR 区域、编辑候选题、确认来源/标签、拒绝或合并候选。 |
| 题库 /questions | 全文搜索、主题/知识点/难度/来源/收藏/错题过滤，批量编辑和选择题目进入练习。 |
| 题目详情 /questions/:id | 正文、来源截图和区域、题目标签、收藏/错题状态、回答历史、正式/最佳答案、参考答案。 |
| 练习设置 /practice | 选择随机、分类、知识点、错题、收藏、弱项或到期复习，并设置筛选条件。 |
| 练习会话 /practice/:sessionId | 逐题展示、文字回答、自评、可选 LLM 反馈、保存正式/最佳标记、查看入选原因。 |
| 个人资料 /materials | 简历、项目和文档列表、版本、解析/索引状态、删除和导出。 |
| 进度 /progress | 练习量、回答次数、主题覆盖、个人评分曲线、错误主题和到期分布。 |
| 设置 /settings | LLM provider/key、数据目录信息、数据库与原文件备份/恢复。 |

## 主要业务流程

### 截图导入

1. 上传图片并选择或补充来源信息；系统保留原始文件、哈希、采集时间、平台、可选 URL、标题和作者。
2. 创建 ingestion job。Worker 执行图像预处理和 OCR，保存 OCR block 的文本、bbox、阅读顺序及置信度。
3. 根据文本段落和版面生成待复核 Question 草稿。一张图可以生成零道、一道或多道题；每个草稿都关联来源区域和原始识别文本。
4. 可选 LLM 为边界、主题、知识点、难度提供建议。结构化输出必须经过 schema 校验，建议和置信度与原始识别分开保存。
5. 用户在原图高亮区域上编辑、拆分、合并、改标签或忽略候选。只有确认后题目状态才变为 active。
6. 文本完全匹配或高相似题只生成 duplicate candidate 关系；用户明确确认后才能合并，所有来源 occurrence 均保留。

### 练习与回答

1. 用户选择模式和可选筛选器。
2. Flask 的确定性 selector 从 active 题目中生成一组题目，记录筛选参数、selector 版本、题目顺序及每题入选原因。
3. 每次提交都创建一条新 AnswerAttempt，并保存题目文本快照、时间、个人评分和练习会话。
4. 用户可将多条回答标为正式，并最多将一条正式回答标为最佳。切换最佳回答是对标记状态的明确变更，历史正文不修改。
5. LLM 评分保存为独立 Evaluation；润色结果先作为草稿。用户点击保存后，以新 attempt 记录润色稿，并链接其来源回答。
6. 完成后更新题目状态和可重算的复习摘要。统计由实际 session/attempt 聚合产生。

### 参考答案与个人资料

1. 用户主动选择“不使用个人资料”“简历”“某个项目”或多份资料。
2. 系统只检索被选资料对应的版本和文本片段，将引用一并交给模型。
3. 生成内容保留资料引用及模型/prompt 版本。资料无法支持某段经历、指标或职责时，明确提示缺少依据，不补造事实。
4. 生成的参考答案属于 AssistantOutput；它不是用户回答，也不会自动成为正式/最佳答案。

## 数据模型

数据库采用 SQLite，单用户不设置 user_id。外键启用，时间统一按 ISO 8601 UTC 保存。文件内容不放入数据库大字段，数据库存受控相对路径。下表是逻辑模型，不要求第一阶段一次建完；某阶段的表随该阶段功能增加。review_state 是可重算缓存，数据量小的时候可直接从回答记录计算，确认性能需要后再物化。

| 表 | 主要字段与职责 |
|---|---|
| source_asset | id, kind, original_path, sha256, platform, source_url, title, author, captured_at, created_at。保存截图或以后新增的链接/视频来源元数据。 |
| ingestion_job | id, source_asset_id, status, stage, engine, engine_version, error, created_at, updated_at。跟踪 OCR/解析工作和重试。 |
| ocr_block | id, job_id, text, bbox_json, reading_order, confidence, block_type。坐标按原图尺寸归一化。 |
| question | id, text, normalized_hash, answer_type, difficulty, status, created_at, updated_at。status 至少含 pending_review, active, ignored, duplicate。 |
| question_source | question_id, source_asset_id, raw_text, bbox_json, ocr_block_ids_json, edit_note。题目与多处截图/来源的多对多关系。 |
| topic | id, track_key, parent_id, slug, name, sort_order。层级分类；首批 track_key=agent-development，后续可增加其他岗位方向。 |
| tag / question_tag | 用户可管理的交叉知识点标签及题目关联。分类和标签分开处理。 |
| question_relation | question_id, related_question_id, relation_type, status, confidence。记录 duplicate/related/prerequisite 候选；合并需显式确认。 |
| answer_attempt | id, question_id, session_item_id, answer_text, created_at, self_score, is_formal, is_best, origin_kind, based_on_attempt_id, question_text_snapshot。每次回答追加保存。 |
| answer_evaluation | id, attempt_id, evaluator_type, rubric_version, model, dimensions_json, evidence_json, feedback, created_at。机器评分与人工/自评分开。 |
| assistant_output | id, question_id, attempt_id, output_kind, content, model, prompt_version, created_at。保存 reference answer 和用户尚未保存的 polish 草稿。 |
| material / material_version | 稳定资料 ID 与不可变版本：kind, project_name, filename, sha256, path, parser, created_at。kind 为 resume/project/document。 |
| material_chunk | id, material_version_id, ordinal, page_number, heading, text, search_text。保存可引用片段；MVP 先用 SQLite FTS5。 |
| assistant_output_material | assistant_output_id, material_version_id, chunk_ids_json。保留生成时使用的资料版本和引用片段。 |
| practice_session | id, mode, filters_json, selector_version, started_at, completed_at。一轮练习的配置和状态。 |
| session_item | id, session_id, question_id, ordinal, selection_reason, status。固化队列顺序和选题原因。 |
| question_state | question_id, is_favorite, is_missed, user_note, updated_at。收藏、人工错题标记等用户状态。 |
| review_state | question_id, last_attempt_at, due_at, mastery_level, weak_dimensions_json, recalculated_at。从历史记录重算的复习摘要/缓存。 |

关键完整性约束：

- answer_attempt.is_best=1 时必须同时 is_formal=1；通过 SQLite partial unique index 保证每题最多一条最佳回答。
- 切换最佳回答在一个事务中完成，旧最佳标记先取消，再设置新最佳。
- question.normalized_hash 用于完全重复候选，不直接删除记录。
- Attempt、Evaluation、AssistantOutput、资料版本和来源 occurrence 不因题目编辑而级联删除。
- review_state 可从回答历史重建；它不是训练事实的唯一来源。

## 后端模块与目录建议

采用 Flask 模块化单体，而非微服务。开发时 Vite 通过 /api 代理 Flask；发布/本机运行时 Flask 提供 Vue 的静态构建文件，浏览器与 API 同源。

    backend/app/
      api/             # Flask blueprints 和 request/response schemas
      domain/          # SQLAlchemy models 和领域常量
      services/
        ingestion/     # 上传、OCR provider、候选整理、去重
        questions/     # CRUD、分类、检索、合并
        practice/      # selector、session、attempt、review
        materials/     # 文件版本、解析、chunk、检索
        assistant/     # LLM provider、引用拼装、润色、参考答案、评分
      storage/         # 本机数据目录和文件接口
      worker.py        # SQLite job queue 的单 worker 命令
      config.py

    frontend/src/
      pages/           # Dashboard, Inbox, Questions, Practice, Materials, Progress, Settings
      components/      # OCR region viewer, question editor, answer timeline, filters
      api/             # typed REST client
      stores/          # 仅跨页面需要的会话/设置状态

推荐 Flask、SQLAlchemy 2、Flask-Migrate/Alembic、Pydantic request schema；Vue 3、TypeScript、Vite、Vue Router。Python 运行依赖安装在 test；前端依赖由 npm 锁文件管理。选择 PaddleOCR 前先用自己的截图样本验证 Mac CPU 兼容与速度；OCR provider 必须可替换。

后台任务由一个独立本地 worker 进程领取 SQLite job。MVP 不用 Redis/Celery。进程异常后，超时的 processing job 可恢复为 queued/failed。小型 OCR/文本解析可重试，失败信息在收件箱明确显示。

### API 分组

- POST /api/v1/ingestions、GET /api/v1/ingestions/{id}、PATCH /api/v1/questions/{id}：导入状态、候选复核、确认/忽略。
- GET/POST /api/v1/questions、GET/PATCH /api/v1/questions/{id}：题库搜索、详情、题目编辑、标签和来源。
- POST /api/v1/practice-sessions、GET /api/v1/practice-sessions/{id}：按模式创建 session 和读取固化题目序列。
- POST /api/v1/questions/{id}/attempts、PATCH /api/v1/attempts/{id}/marks：创建回答、用户评分、正式/最佳标记。
- POST /api/v1/assistant/reference-answer、POST /api/v1/assistant/polish、POST /api/v1/assistant/evaluate：显式请求 LLM；传入 question/attempt ID 和被选 material version IDs。
- POST /api/v1/materials、GET /api/v1/materials、POST /api/v1/materials/{id}/versions：资料及版本管理。
- GET /api/v1/progress：练习量、分类覆盖、评分趋势和待复习聚合。

API 不接受浏览器传入任意本机文件路径；文件访问只通过服务器创建的 asset/material ID。

## 练习队列规则

所有 selector 均为 Flask 可测试的确定性服务：

- 随机：筛选符合条件的 active 题目，再对候选列表洗牌。
- 分类/知识点：按用户选择的 topic/tag 筛选。
- 错题/收藏：按 question_state 过滤。
- 弱项：根据个人低分、自标错题和低 Rubric 维度映射到 topic/tag，再筛题。
- 复习队列：按 due_at 从早到晚；未排程题可按主题和练习次数补入。
- 最近已练题可降权/暂时排除；每次 session_item 记录选择原因和 selector 版本。

LLM 不提供队列、不重排题目，也不以生成内容替代用户的实际掌握记录。初版 mastery_level 由用户自评、答题次数、个人评分和错题状态组成，规则公开且能重算。

## LLM 与资料使用边界

- Provider 封装为统一接口，具体供应商不写入领域服务；API key 只保存在本机配置/系统钥匙串，不提交 Git。
- 只有用户明确操作才调用模型；每个请求显示发送的资料范围。无资料模式不附加任何简历/项目内容。
- 个人资料检索先限定到所选版本，再做关键词/FTS 搜索；每个片段带 material/version/page/heading 引用。
- 参考答案/润色结果必须标明生成内容；用户事实型陈述须能对应到资料片段或标记为用户补充内容。
- 润色稿不覆盖原答案；机器评分带模型和 Rubric 版本，并提供依据片段。
- 没有来源支持的项目、业绩、数字和职责必须提示补充，不能推断为事实。

## 本地数据与安全

- Flask 绑定 127.0.0.1，只允许预期 Host/Origin；开发 Vite 使用明确代理来源，不配置宽松 wildcard CORS。
- 使用本机应用数据目录（如 macOS Application Support）存 SQLite、原图和个人资料；绝对路径不暴露给前端。
- 上传限制大小、扩展名与实际 MIME；原文件用生成 ID 命名并存于受控目录。
- 提供含 SQLite 和文件目录的备份/导出与恢复；API key 不进入备份。
- 删除资料有明确操作；被历史回答引用的资料版本标记为不可用或按用户确认清理，不悄悄改变已保存回答。

## MVP 阶段

| 阶段 | 交付 | 验收条件 |
|---|---|---|
| 0. 本机骨架 | Flask app factory、Vue/Vite、SQLite migration、本机数据目录、API health、localhost 运行方式。 | 在 Conda test 启动 Flask；npm 安装/构建 Vue；Vite /api 代理工作；上传路径与源码目录分离。 |
| 1. 手动题库 | Question、topic/tag、搜索过滤、来源字段、收藏、备份/导出。 | 用户可手动录入一道 Agent 题、编辑、检索、按主题筛选并导出数据。 |
| 2. 截图收件箱 | SourceAsset、job、OCR blocks、pending_review 题目、bbox 复核、多题拆分和来源绑定。 | 一张图可拆出多题；用户校正文案和来源；未确认题不进入练习；低置信度能看到并处理。 |
| 3. 回答闭环 | PracticeSession/Item、AnswerAttempt、个人评分、正式/最佳标记和历史时间线。 | 同题重复提交不覆盖历史；多个正式答案可留存；最佳唯一且置顶；排序遵循已确认规则。 |
| 4. 训练队列 | 随机、分类、知识点、错题、收藏、弱项、复习队列、统计。 | 同一筛选条件可解释地产生题目列表；每题显示入选原因；统计从 sessions/attempts 重算一致。 |
| 5. 资料库与 LLM | 资料版本、解析 chunk、选择上下文、引用答案、润色草稿、Rubric 评价。 | 支持零份/一份/多份资料；历史记录资料版本；润色原文仍在；无依据事实会被标记而非编造。 |
| 后续 | 官方/用户授权平台来源适配器；语音/视频和模拟面试。 | 单独评估平台接口、权限、成本和隐私后再排期。 |

## 非目标

首版不做登录、多租户、远程服务器、实时跨设备同步、公开社区、题目自动发布、自动抓取社交平台、向量数据库集群、微服务、Redis/Celery、多 Agent、语音/视频模拟面试。

## 取舍说明

- **本地单用户 + SQLite** 优先于云端 Postgres：数据量小、隐私边界清楚、备份简单；若未来需要多设备，届时再新增 sync/API 服务和冲突策略。
- **同一 Flask 部署 API 与静态前端** 优先于分布式部署：源代码仍前后端分离，运行时同源减少 CORS/认证复杂度。
- **OCR + 可复核候选** 优先于纯 VLM 自动入库：OCR/bbox 可追溯，LLM 负责语义辅助；用户对题目边界和重复合并保留决定权。
- **SQLite FTS5** 优先于向量库：MVP 先用精确/全文检索；只有真实资料检索样本证明必要时再增加 embedding。
- **Selector 规则** 优先于让 LLM 出题：可解释、可回放、符合用户明确要求。
- **阶段性增加 LLM** 优先于先构建模型工作流：手动题库和多次作答先形成可用产品，LLM 成为增强层而非依赖层。

## 研究依据

产品机制、OCR 候选、GitHub 项目及 Mac OCR 约束详见 [面试训练助手市场与开源项目调研](../../research/agent-interview-training-landscape-2026-10.md)。主要工程参考包括：

- [面试鸭 GitHub](https://github.com/liyupi/mianshiya)：题库筛选、标签、回答和管理功能；部分 README 功能明确标成实验/未来计划。
- [InterviewOps GitHub](https://github.com/AnkitParekh007/interviewOps)：本地 session packet、Rubric/provider 抽象；不照搬其 AI 生成题目模式。
- [Paku GitHub](https://github.com/loremcc/paku)：置信度门槛和人工复核队列；其垂直抽取器不等于通用面试题解析器。
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 与 [macOS 安装说明](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html)：OCR/版面解析能力和 Mac CPU/arm64 兼容范围；实际准确度仍需用个人截图集验证。
- [Anki FSRS 手册](https://docs.ankiweb.net/deck-options.html?highlight=FSRS)：从逐次复习记录安排复习；面试自由回答不直接等同闪卡记忆。

## 后续待确认项

实现前再确定：具体 LLM provider 及预算、原图/文档格式和单文件大小上限、个人评分量表、初始 topic 目录、OCR 引擎在当前 Mac 的实测速度与准确度。它们不改变本规格的模块边界。

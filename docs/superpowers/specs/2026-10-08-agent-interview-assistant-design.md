# Agent 开发面试训练助手设计

> 状态：根据产品评审意见修订，等待复核。

## 目标

为个人长期使用设计一个 Agent 开发方向面试训练助手。系统以截图为第一阶段题目来源，保存原始来源和题目定位；将人工确认的题目组织成可扩展题库；围绕用户主动保存的回答建立评分、置顶和复习闭环。

技术方向沿用 Flask API + Vue 前端分离、SQLite 和本地文件存储。LLM 只做用户主动请求的润色、参考答案或回答分析，不负责选题，也不改变用户评分、回答排序、置顶状态或复习掌握度。

## 已确认的产品规则

- 首版按个人使用设计，不做账号、多人协作、云同步。
- Flask 提供 REST API；Vue 3 + TypeScript + Vite 是独立前端，开发时通过 Vite 代理 API，发布时可由 Flask 同源提供静态文件。
- 一张截图可以拆出多道独立题目；题目在人工确认后才进入可练习题库。
- 原始图片、OCR 原文、题目区域和来源信息分开保留。来源定位采用通用结构；首版实现截图区域，未来可增加视频时间段、帖子图片序号等定位类型。
- 一次未保存的回答只是临时草稿，不创建长期回答记录。用户主动点“保存回答”才建立保存回答。
- 每题可以有多条保存回答。保存回答可编辑；每次编辑新建不可变版本，旧版本继续可查看。
- 用户评分是训练数据的主要依据。每个保存回答的当前版本可由用户评分；用户可将一条保存回答置顶/设为首选。默认排序为置顶优先，然后按当前版本的用户评分降序，再按更新时间排序；未评分回答排在已评分回答之后。
- 不设置“普通/正式/最佳”三层状态。所有进入回答库的记录都是用户主动保存的回答；“置顶/首选”是唯一额外优先标记。
- LLM 评分/分析是用户主动触发的辅助信息，不影响保存回答排序、题目掌握程度、复习时间或置顶选择。
- 简历和项目资料长期保存并保留版本。项目是独立实体，一个项目可关联多个资料；用户上下文选择以简历和 Project 为主，不要求逐个选择底层文件。
- Agent 分类从第一版开始提供，并可由用户增加、修改、停用。
- 首版练习模式为随机、分类、知识点、收藏、错题、复习队列。弱项训练采用透明的简单统计；数据不足时不显示复杂结论。
- 模拟面试、语音、视频、多 Agent 和社交平台自动采集后置，不属于当前 MVP。

## 用户与核心任务

用户主要准备 Agent 开发岗位面试，需要：

1. 从截图中提取多道题，校对识别结果并确认来源。
2. 按预设且可扩展的 Agent 开发分类管理和检索题目。
3. 练习时反复组织答案；不满意的草稿可直接重答，不进入历史。
4. 只保存自己愿意留下的回答，对保存回答评分、置顶和查看版本历史。
5. 用简历、一个或多个项目资料作为可选上下文生成或润色回答。
6. 根据用户评分、错题标记和简单到期规则继续训练。

## 信息架构与页面

| 页面 | 主要内容与操作 |
|---|---|
| 首页 /dashboard | 今日复习题、待处理截图、最近保存回答、分类覆盖和个人评分概况。数据不足时显示实际记录数，不推测准备度。 |
| 采集收件箱 /inbox | 上传截图、查看导入状态、原图与候选题所在区域、OCR 原文；编辑/拆分/合并候选后确认入库。 |
| 题库 /questions | 按 Agent 分类、知识点、难度、来源、收藏、错题筛选和搜索；展示疑似相似题供人工确认。 |
| 题目详情 /questions/:id | 题目正文、来源卡片和定位、分类/标签、保存回答列表、回答版本、置顶和个人评分。 |
| 练习设置 /practice | 选择随机、分类、知识点、收藏、错题、复习队列；弱项练习作为基于用户评分的简单可选过滤。 |
| 练习会话 /practice/:sessionId | 临时作答框；“重新回答”清空未保存草稿；“保存回答”才写入回答库。可选择润色、参考答案或分析。 |
| 项目与资料 /projects、/materials | 建立 Project；每个 Project 关联多份资料。简历等通用资料可单独保存；查看版本与解析状态。 |
| 进度 /progress | 保存回答数、练习题数、用户评分分布、分类覆盖、错题和到期队列。LLM 分析分数不计入这些统计。 |
| 设置 /settings | LLM provider 配置、存储目录信息、数据备份/恢复。 |

## 主要业务流程

### 截图导入与题目确认

1. 上传图片，记录原文件、哈希、采集时间和用户提供的来源信息；来源可包含平台、链接、作者/标题等元数据。
2. OCR 识别并保存原始文字块、阅读顺序、置信度和区域坐标。
3. 按版面和文字边界生成待复核题目。一张截图中的每道候选题单独建记录，并链接到该截图和对应定位。
4. 系统建议 Agent 分类、知识点、难度和相似题；建议与 OCR 原文分开，不直接自动定稿。
5. 用户在原图上核对区域与文字、拆分/合并题目、修改分类和标签。
6. 确认后题目进入练习题库；低置信度、疑似重复题留在待处理状态。
7. 精确或近似重复只生成候选关系。用户确认合并后，规范题保留所有来源定位。

### 练习和保存回答

1. 用户选择练习模式和筛选条件。题目队列由 Flask 的程序规则从可练习题库生成。
2. 每个题目展示时，创建 session item 以记录题目曾出现在该练习中；不记录未保存的回答文本，也不把重写草稿次数算成保存回答次数。
3. 作答文本在当前页面内作为临时草稿。用户可以清空后重答；离开页面或结束会话时，不保存草稿。
4. 点击“保存回答”时，创建 SavedAnswer 和第一个 SavedAnswerVersion。用户评分属于具体版本。
5. 对已保存回答编辑并保存时，追加新版本并将其设为当前版本；旧版本不修改。若要另存为一条独立回答，使用“保存为新回答”。
6. 每题最多一条置顶回答。置顶只改变展示优先级，不覆盖历史或改写用户评分。
7. session item 关联已保存的回答（如有）；无保存回答的题目仍可记录为已查看/跳过，但不显示成一次已保存作答。

### LLM 润色、参考答案和分析

1. 用户主动选择操作：润色草稿/已保存回答、生成参考答案，或分析答案的完整性、技术点遗漏和表达清晰度。
2. 用户选择上下文：不使用资料、指定简历、指定 Project，或简历与多个 Project 组合。Project 选择后展开其关联资料；高级选项可排除个别资料。
3. 检索只在被选 Project/资料版本中进行，并将引用来源交给模型。
4. 未保存的用户草稿和模型输出默认只在本次界面中使用。润色结果需用户明确选择“保存为新版本”或“保存为新回答”；参考答案需单独选择收藏或保存，才进入长期记录。
5. 资料没有提供的项目、指标或职责不能生成成用户事实。回答应指出缺少依据，允许用户补充。
6. LLM 分析单独呈现；不写入用户评分，不改变回答列表排序、置顶、错题/弱项状态或复习时间。

### Project 与资料关联

- Project 是用户经历中的项目实体，保存名称、简介、技术栈和用户备注。
- Material 是文件或摘录，例如简历、项目说明、README、架构文档、设计文档。一个 Project 可关联多份 Material。
- Material 每次重新上传或修订都新增 MaterialVersion；旧版本继续可追溯。
- 简历通常作为不归属于单一项目的通用 Material。用户选择“简历 + Project A”时，系统同时检索简历相关片段和 Project A 关联资料。
- 用户也可把从简历整理出的特定项目片段关联到相应 Project；不把整份简历错误地重复复制到每个 Project。
- 生成内容记录当时实际使用的 MaterialVersion 与片段引用；以后更新资料不追溯改写已生成内容。

## Agent 开发题目分类

第一版创建可编辑的层级分类。初始分类采用以下主题，不在代码中写成固定枚举：

| 分类组 | 初始主题 |
|---|---|
| LLM 与上下文 | LLM 基础、Prompt、Context Engineering |
| 工具与协议 | Function Calling / Tool Use、MCP |
| 检索与记忆 | RAG、Memory |
| Agent 框架与控制流 | LangChain、LangGraph、Multi-Agent |
| 质量与安全 | Agent Evaluation、Observability、Agent Security |
| 工程基础 | 部署、Python/后端 |
| 经历与实践 | 项目实践 |

Topic 允许新增、改名、移动层级、停用；题目通过关系表关联多个 Topic。Tags 用于同一分类之外的横向词条、技术名、版本、公司/来源等筛选。OCR/LLM 给出的分类只是建议，用户可确认或更改。

## 数据模型

采用 SQLite。每个逻辑表按功能阶段加入；第一版不建立用户/租户表，也不为了未来同步引入分布式 ID 服务。个人资料文件存本地应用数据目录，数据库存引用路径、哈希和元数据。

| 表 | 主要字段与职责 |
|---|---|
| source_asset | id, source_type, platform, source_url, external_id, title, author, captured_at, original_path, sha256, metadata_json。保存截图或未来网页/帖子/视频来源。 |
| ingestion_job | id, source_asset_id, status, stage, engine, engine_version, ocr_result_json, error, created_at, updated_at。ocr_result_json 保留原始文字块、顺序、置信度和区域；question_source 指向其中与题目对应的 block。截图阶段只引入简单状态记录，不预设复杂队列恢复系统。 |
| question | id, text, normalized_hash, answer_type, difficulty, status, created_at, updated_at。状态包括 pending_review, active, ignored, duplicate。 |
| question_source | id, question_id, source_asset_id, locator_type, locator_json, raw_ocr_text, confidence, ocr_block_ids_json。允许同一题在同一来源出现多个位置；locator 类型可扩展，截图区域是首版唯一实际实现的 locator。 |
| topic | id, track_key, parent_id, slug, name, sort_order, is_active。Agent 开发分类由数据库初始化数据提供并可编辑。 |
| tag / question_tag | 可编辑的横向标签及题目关联。 |
| question_relation | question_id, related_question_id, relation_type, status, confidence。记录 similar/duplicate 候选；合并需用户确认。 |
| project | id, name, summary, tech_stack, notes, created_at, updated_at。独立于文件的真实项目实体。 |
| material | id, kind, project_id nullable, title, original_filename, created_at。类型如 resume, project_brief, readme, architecture_doc, other。项目资料关联 Project；通用简历可不关联。 |
| material_version | id, material_id, version_no, path, sha256, parsed_at, created_at。每次修改/替换追加版本，不覆盖原版本；最高 version_no 为当前版本。 |
| material_chunk | id, material_version_id, project_id nullable, ordinal, page_number, heading, text。用于全文检索和给简历中的特定项目片段建立项目关联。 |
| saved_answer | id, question_id, source_session_item_id nullable, is_pinned, created_at, updated_at。代表用户主动保存的一条回答；每题最多一个 pinned。没有多层回答状态。 |
| saved_answer_version | id, saved_answer_id, version_no, content, self_rating nullable (1–5), self_rating_updated_at nullable, origin_kind, based_on_version_id, assistant_output_id nullable, created_at。正文是不可变版本；评分是该版本可更新的用户元数据；同一回答的 version_no 唯一且递增，最高版本号为当前版本。 |
| practice_session | id, mode, filters_json, selector_version, started_at, completed_at。保存练习条件和过程。 |
| session_item | id, session_id, question_id, ordinal, status, selection_reason, viewed_at, completed_at。只记录题目练习事件，不保存未保存草稿；多个 SavedAnswer 可通过 source_session_item_id 关联到同一题目展示事件。 |
| question_state | question_id, is_favorite, is_wrong, last_practiced_at, next_review_at nullable, user_note, updated_at。首版错题/收藏/简单到期状态。 |
| assistant_output | id, question_id, source_saved_answer_version_id nullable, output_type, content_text nullable, result_json nullable, provider, model, prompt_version, created_at。用户保存润色版本、收藏参考答案或选择保存分析时留存；未保存预览仅临时。 |
| assistant_output_source | assistant_output_id, material_version_id, chunk_ids_json。记录生成内容实际引用的资料版本和片段。 |

关键约束：

- 用户文本只有经“保存回答”动作后才写入 SavedAnswerVersion。
- 更新回答通过新增版本完成，禁止原地覆盖旧版本；需要撤回/删除时保留明确审计规则，默认不自动清理历史。
- 新版本初始不继承旧版本评分；用户需对当前版本重新评分。置顶属于 SavedAnswer 整体，可在编辑版本后保持置顶。
- 修改用户评分只更新对应版本的评分元数据和时间，不生成内容版本；列表按当前版本分数显示。
- 每个问题最多一条 pinned SavedAnswer；通过事务和 SQLite partial unique index 保证。
- 同一 SavedAnswer 的 version_no 唯一且递增；编辑只插入新版本，不更新已有版本正文。
- 回答列表以每条 SavedAnswer 的 current_version.self_rating 排序：置顶在先，其余已评分版本按分数降序，未评分版本在后，同分按回答更新时间排序。
- LLM output、分析分数和引用均不更新 question_state，也不参与回答排序或复习调度。
- 练习队列优先从 question_state、Topic 和用户评分派生；数据量少时不单独物化 mastery 或 review 模型。

### 通用来源定位

SourceAsset 表示原始内容或媒体；QuestionSource 表示某道题在该来源中的位置。locator 使用类型加 JSON 参数，不将 bbox 固定成所有平台的唯一来源结构：

- image_region：归一化 x/y/width/height，可关联 OCR block。
- video_interval：start_ms/end_ms。
- carousel_slide：image_index 或 slide_index。
- page_region：page_number 与区域位置。
- text_span：字符范围或原文锚点。

首版只写入 image_region 和截图 OCR 原文。未来来源平台按 source_type/platform 扩展；不把自动采集器列入 MVP。

## 后端模块与接口

Flask 保持模块化单体，Vue 独立开发与构建；发布后可由 Flask 同源提供静态前端。平台不需要认证 API，绑定本机回环地址，限制 Host/Origin，文件只能通过应用资源 ID 访问。

建议模块：

- api：Flask blueprints、输入校验和响应 schema。
- sources：文件保存、来源元数据、locator 编码/解码。
- ingestion：截图校验、OCR adapter、候选题拆分、分类/难度建议、相似题提示和人工确认状态。
- taxonomy/questions：Topic/Tag 管理、题目 CRUD、检索和相似题人工合并。
- answers：SavedAnswer、SavedAnswerVersion、评分/置顶/版本追加。
- practice：随机和过滤 selector、练习 session、session item、错题/收藏/到期队列。
- projects/materials：Project、Material、MaterialVersion、解析文本和选择上下文检索。
- assistant：显式请求润色、参考答案或可选分析；保存明确选择的输出及来源，不连接队列 selector。
- storage：跨平台本机数据目录、文件校验、备份/恢复。

SQLite FTS5 用于题目和资料全文搜索。MVP 不引入向量数据库；当真实资料检索效果不足时再评估 embedding。Worker 不进入零阶段骨架：截图 OCR 首版先用一个简单的导入任务状态；若 OCR 耗时影响页面响应，再在该阶段增加单个本地 worker 和手动重试，不做通用 job orchestration、自动恢复策略或 Celery/Redis。

### API 分组

- POST /api/v1/sources：上传截图和来源元数据；GET /api/v1/ingestions/{id}：查询 OCR/复核状态。
- GET /api/v1/questions：搜索/过滤；GET/PATCH /api/v1/questions/{id}：读取或编辑题目、分类、标签、来源。
- POST /api/v1/questions/{id}/saved-answers：显式保存一条回答并创建版本 1。
- GET /api/v1/questions/{id}/saved-answers、GET /api/v1/saved-answers/{id}/versions：读取回答列表和历史版本。
- POST /api/v1/saved-answers/{id}/versions：给已保存回答追加版本；PATCH /api/v1/saved-answer-versions/{id}/rating：设置用户评分。
- PATCH /api/v1/saved-answers/{id}/pin：置顶或取消置顶；服务保证每题最多一个置顶回答。
- PATCH /api/v1/questions/{id}/state：设置收藏/错题标记或手动调整复习日期。
- GET/POST/PATCH /api/v1/topics、GET/POST/PATCH /api/v1/tags：维护首版 Agent 分类和知识点标签。
- POST /api/v1/practice-sessions：创建练习队列；GET /api/v1/practice-sessions/{id}：读取队列和题目浏览/保存状态。
- POST /api/v1/assistant/polish、POST /api/v1/assistant/reference-answer、POST /api/v1/assistant/analyze：用户主动请求。上下文参数接受简历 material IDs 与 project IDs；服务展开 Project 资料后返回引用。
- POST/GET/PATCH /api/v1/projects、GET /api/v1/projects/{id}/materials：创建/编辑 Project 并查看其资料。
- POST/GET/PATCH /api/v1/materials、POST /api/v1/materials/{id}/versions：上传/编辑资料元数据、追加资料版本和列出关联资料。
- GET /api/v1/progress：保存回答、用户评分、Topic 覆盖、错题与到期状态汇总。

LLM endpoints 不提供 next-question 参数或题目生成队列。练习 session 创建后，题目顺序由程序 selector 固化。

## 练习模式与简单复习规则

首版支持随机、分类、知识点、收藏、错题、复习队列；弱项练习仅作为可选简单过滤：

- 随机：在当前筛选出的 active 题目中打乱顺序。
- 分类/知识点：按用户选择的 Topic/Tag。
- 收藏/错题：按 question_state 过滤。
- 复习队列：按 next_review_at 由早到晚；用户评分更新后用透明的固定间隔表更新到期时间，错题标记可将题目放回较早队列。
- 弱项：按最近一段时间保存回答的用户评分与错题标记按 Topic 汇总；每个 Topic 少于 3 条已评分的当前回答版本时显示“练习记录不足”，不进行排序或训练复杂模型。
- 每个 session item 保存 selector 版本和入选原因，方便解释和重算。LLM 分析不进入这些计算。

MVP 可先用 1–5 的用户自评分；评分含义在设置/提示中说明。复习队列用可配置的固定间隔映射，例如 1–2 分次日、3 分 3 天后、4 分 7 天后、5 分 14 天后；用户标记错题时优先安排次日复习。一个题目有多条回答时，复习时间依据最近一次更新的当前版本用户评分计算。具体映射在实现前确认，不固化为算法服务。

## LLM 与资料上下文

- 个人资料是长期资料库；Project 是首选的项目选择入口，Material 是关联到项目或独立保存的具体文档。
- 用户可以选择无资料、一个/多个简历、一个 Project 或多个 Project 与简历组合。选择 Project 会展开当前有效的项目资料；简历中的项目片段可通过 material_chunk.project_id 关联到相应 Project。
- 每次生成记录被选择的项目、资料版本和 chunk 引用，保证以后可追溯当时的上下文。
- 只把被选上下文的相关片段发给模型；生成内容引用到资料片段。不能由项目名称推断未提供的技术栈、职责、指标或结果。
- 润色可以针对未保存草稿或已保存版本。输出先是临时预览；用户可保存为新回答，或针对已有 SavedAnswer 保存为一个新版本。原文与旧版本始终保留。
- 参考答案与用户自己的回答分开。用户可选择收藏模型参考答案，或明确复制为自己的一条 SavedAnswer。
- LLM 分析只在用户主动触发时运行，关注完整性、技术点遗漏和表达清晰度。它可以生成文字建议；即使显示辅助分数，也不能用于用户排序、置顶、错题、复习日期或掌握程度。

API key 使用本机配置/系统安全存储，不提交仓库。调用远程模型前，页面说明将发送的问题和所选资料；无资料模式不附加任何个人文件。

## 技术选择与开发环境

- 前后端：Flask REST API + Vue 3/TypeScript/Vite。
- 数据：SQLite + SQLAlchemy/Alembic；本机文件目录存截图、文档和导出包。
- 搜索：SQLite FTS5；暂不加向量数据库。
- OCR：可替换 OCR adapter；首版通过自己的截图样本比较 PaddleOCR 与备选实现的准确度和速度。
- LLM：独立 provider adapter；仅通过 assistant 模块调用。
- 路径与文件类型通过跨平台库处理；Mac 或任何单一 OS 不属于产品运行限制。
- 当前工作区按 AGENTS.md 使用 Conda test 执行 Python 开发命令；这是仓库开发约定，不是最终用户运行产品的前置条件。

不采用微服务、Redis/Celery、认证服务、独立向量数据库或多 Agent 编排。单机数据量和任务量不足以支持这些复杂度。

## MVP 阶段

| 阶段 | 交付 | 验收点 |
|---|---|---|
| 0. 最小骨架 | Flask app、Vue/Vite、SQLite migration、同源/代理 API、跨平台应用数据目录。 | 两端能独立开发和构建；API health 可用；运行不依赖 Mac、Conda 或云服务。 |
| 1. Agent 题库 | 初始化上表分类；Topic/Tag 可增改停用；手动题目 CRUD、搜索、收藏、错题状态。 | 用户可以用真实 Agent 分类录入并检索题目；分类不是固定 enum。 |
| 2. 截图采集 | 上传截图、SourceAsset、OCR、待确认题、通用 locator 结构的 image_region 实现、来源和原 OCR 保存、相似题提示。 | 一张截图拆出多道独立题；每题可回看原图区域和 OCR 原文；只有人工确认后可练。处理状态简洁可见；如同步 OCR 确实阻塞，再增一个本地 worker。 |
| 3. 保存回答闭环 | 临时作答框、明确 Save Answer、SavedAnswer + immutable versions、自评分、唯一置顶、版本历史。 | 未保存草稿不入数据库/答题历史；重复保存才创建记录；编辑追加版本而不覆盖；列表顺序完全由置顶与当前版本用户评分决定。 |
| 4. 练习与复习 | 随机/分类/知识点/收藏/错题/到期复习；简单弱项汇总、学习进度。 | 练习队列确定且可解释；不保存草稿内容；复习只由用户评分、错题标记和简单日期规则决定。 |
| 5. Projects、资料与 LLM | Project CRUD、多个 Material/版本、资料解析/FTS、选择简历和一个/多个 Project；润色、参考答案、可选分析。 | Project 选择自动包含关联资料；生成结果能追溯版本和片段；不支持的事实明确提示；LLM 输出不改变训练排序/掌握度。 |
| 后续 | 抖音/B站/小红书授权来源适配器；模拟面试、语音、视频、多 Agent。 | 每项独立评估平台权限、隐私、成本和维护负担后再排期。 |

## 非目标与过度工程控制

首版不做登录、多租户、云同步、公开社区、自动社媒采集、复杂模拟面试、语音/视频、多 Agent、复杂自适应算法、LLM 自动评分管线、微服务、Redis/Celery、独立向量库或通用任务编排器。

Background task 只在实际耗时证明必要时引入；Evaluation 不作为核心实体；用户评分和作答保存记录是真实训练数据；管理面板只覆盖个人维护题库、Project 和资料所需的操作。

## 取舍说明

- 本地单用户 + SQLite 适合个人规模、离线使用和简单备份；未来需要多设备时再设计同步和冲突解决。
- 前后端源代码分离，但首版运行同源，可减少 CORS 和部署复杂度。
- OCR 先读图并提供可复核草稿，模型不直接发布题目；原图和定位永远可以追溯。
- SavedAnswer 与版本历史区分“多条独立回答”和“编辑同一条回答”：评分属于版本，置顶属于回答条目。
- Project 与 Material 区分项目上下文和文件：用户主要选择 Project，系统再展开项目资料；简历仍可独立选择。
- 随机/分类/收藏/错题/复习由规则和题库状态决定；弱项先用用户自评分做简单汇总。
- 参考答案、润色和分析只有主动调用；分析评价永不覆盖用户评分或重排答案。

## 研究依据

商业产品和开源项目的对比详见 [面试训练助手市场与开源项目调研](../../research/agent-interview-training-landscape-2026-10.md)。对本设计有直接参考价值的工程模式包括：

- 面试鸭的分类、标签、搜索、收藏和题目管理。
- Paku 的置信度门槛和人工复核队列；其主题抽取器不是通用面试题解析器。
- PaddleOCR 的文本/版面识别能力；实际准确度需用个人截图集验证。
- Anki 的逐次用户评分和复习队列；此处只采用透明简单规则，不照搬 FSRS 自适应模型。
- NotebookLM/Open Notebook 的资料选择和来源引用；不照搬完整知识库平台。

## 待实现阶段再确认

开始实现前再确定：所选 OCR engine、LLM provider 与费用上限、单文件大小限制、个人 1–5 分的具体量表、固定复习间隔数值、导入支持格式和本地备份交互。这些决定不改变本设计的总体方向。

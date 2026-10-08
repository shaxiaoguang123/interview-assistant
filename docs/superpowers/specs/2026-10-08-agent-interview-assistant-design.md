# Agent 开发面试训练助手设计

> 状态：规格冻结，可开始按 MVP 阶段开发。新增需求优先根据实际使用反馈评估，不在编码前继续扩展架构。

## 目标

为个人长期使用设计一个 Agent 开发方向面试训练助手。系统以截图为第一阶段题目来源，保存原始来源和题目定位；将人工确认的题目组织成可扩展题库；围绕用户主动保存的回答建立评分、置顶和复习闭环。

技术方向沿用 Flask API + Vue 前端分离、SQLite 和本地文件存储。OCR/多模态模型可在题目导入时提供识别建议；其他 LLM 能力由用户主动触发。LLM 不负责生成练习题或选择下一题，也不改变用户评分、回答排序、置顶状态或 PracticeReview 掌握度。

## 已确认的产品规则

- 首版按个人使用设计，不做账号、多人协作、云同步。
- Flask 提供 REST API；Vue 3 + TypeScript + Vite 是独立前端，开发时通过 Vite 代理 API，发布时可由 Flask 同源提供静态文件。
- 一张截图可以拆出多道独立题目；题目在人工确认后才进入可练习题库。
- 原始图片、OCR 原文、题目区域和来源信息分开保留。来源定位采用通用结构；首版实现截图区域，未来可增加视频时间段、帖子图片序号等定位类型。
- 一次未保存的回答只是临时草稿，不创建长期回答记录。用户主动点“保存回答”才建立保存回答。
- 每题可以有多条保存回答。保存回答可编辑；每次编辑新建不可变版本，旧版本继续可查看。
- SavedAnswer 的用户评分表示这份答案写得好不好，只用于回答列表排序和答案管理。用户可将一条保存回答置顶/设为首选。默认排序为置顶优先，然后按当前版本的用户评分降序，再按更新时间排序；未评分回答排在已评分回答之后。
- PracticeReview 单独记录某次练习时对题目掌握程度的自评。掌握度、弱项统计和复习时间只依据 PracticeReview，不从 SavedAnswer 评分或错题筛选标记推导；is_wrong 只用于错题练习筛选。
- 不设置“普通/正式/最佳”三层状态。所有进入回答库的记录都是用户主动保存的回答；“置顶/首选”是唯一额外优先标记。
- 编辑/润色/重新评分 SavedAnswer 不构成一次复习，也不改变 next_review_at。
- LLM 不生成练习题、不选下一题、不重排队列、不修改用户评分、PracticeReview、掌握度、复习时间或置顶状态。
- 截图采集阶段可以让 OCR/多模态模型建议题目边界、Agent 分类、标签、难度或相似程度；结果必须待用户确认，不自动入正式题库或合并。
- 简历和项目资料长期保存并保留版本。项目是独立实体，一个项目可关联多个资料；用户上下文选择以简历和 Project 为主，不要求逐个选择底层文件。
- Project 的简介、技术栈、个人职责、难点、成果和亮点由用户在“编辑项目”中维护。系统在保存这些事实字段时自动生成/更新系统管理的 Project Profile MaterialVersion；用户不需要重复维护一份 Project Profile 文件。LLM 的事实证据仍只来自该版本化 Material/MaterialChunk，不直接读取可变的 Project 字段。
- Material 有效状态与 include_in_context 开关；选择 Project 时只纳入当前有效且允许进入上下文的资料。
- Agent 分类从第一版开始提供，并可由用户增加、修改、停用。
- 首版练习模式为随机、分类、知识点、收藏、错题、复习队列。弱项训练采用透明的简单统计；数据不足时不显示复杂结论。
- 模拟面试、语音、视频、多 Agent 和社交平台自动采集后置，不属于当前 MVP。
- Question、SavedAnswer、Project、Material 和 SourceAsset 首版支持归档；永久删除仅覆盖没有历史依赖的 SourceAsset/Material。复杂依赖清理后续分阶段实现。多张截图可批量上传，但逐张独立处理，不引入复杂批处理编排。

## 用户与核心任务

用户主要准备 Agent 开发岗位面试，需要：

1. 从截图中提取多道题，校对识别结果并确认来源。
2. 按预设且可扩展的 Agent 开发分类管理和检索题目。
3. 练习时反复组织答案；不满意的草稿可直接重答，不进入历史。
4. 只保存自己愿意留下的回答，对保存回答评分、置顶和查看版本历史。
5. 用简历、一个或多个项目资料作为可选上下文生成或润色回答。
6. 根据 PracticeReview 掌握度评价、错题筛选标记和简单到期规则继续训练。

## 信息架构与页面

| 页面 | 主要内容与操作 |
|---|---|
| 首页 /dashboard | 今日复习题、待处理截图、最近保存回答；分开展示 PracticeReview 掌握度/复习状态与 SavedAnswer 质量评分。数据不足时显示实际记录数，不推测准备度。 |
| 采集收件箱 /inbox | 上传截图、查看导入状态、原图与候选题所在区域、OCR 原文；编辑/拆分/合并候选后确认入库。 |
| 题库 /questions | 按 Agent Topic、知识点、难度、来源、收藏、错题筛选和中英文混合搜索；展示相似/重复候选及归并后的历史。 |
| 题目详情 /questions/:id | 题目正文、来源卡片和通用定位、分类/标签、保存回答列表和版本、置顶和答案质量评分；另列 PracticeReview 掌握度历史与复习状态。 |
| 练习设置 /practice | 选择随机、分类、知识点、收藏、错题、复习队列；弱项练习按 PracticeReview 简单统计。 |
| 练习会话 /practice/:sessionId | 临时作答框；“重新回答”清空未保存草稿；完成练习时独立选择四级掌握度并记录 PracticeReview；保存答案是另一个可选动作。可选择润色、参考答案或分析。 |
| 项目与资料 /projects、/materials | 建立 Project 并管理关联的多个 Material/版本；通用简历可单独保存；设置资料是否有效、是否纳入上下文。 |
| 进度 /progress | 分开展示保存回答数/答案质量评分，以及 PracticeReview 练习次数/掌握度分布/分类覆盖/错题与到期队列。LLM 分析分数不计入这些统计。 |
| 设置 /settings | LLM provider 配置、存储目录信息、数据备份/恢复和归档/永久删除入口。 |

## 主要业务流程

### 截图导入与题目确认

1. 一次可上传一张或多张截图；批量上传只是逐图建立 SourceAsset 和处理状态，不引入通用批处理编排。
2. OCR 识别并保存原始文字块、阅读顺序、置信度和区域坐标。每个 OCRBlock 有稳定 UUID；重新识别创建新的 IngestionJob/OCRBlock，不覆盖旧 block。
3. 按版面和文字边界生成待复核题目。一张截图中的每道候选题单独建记录，并通过 question_source_ocr_block 链接原图区域和稳定 OCRBlock ID。
4. OCR/多模态模型可以辅助判断题目数量与边界、建议 Agent 分类/知识点/难度，并将相似题候选标为 same_question、related_question 或 different_question。建议与 OCR 原文分开，不直接自动定稿或合并。
5. 用户在原图上核对区域与文字、拆分/合并题目、修改分类和标签。
6. 确认后题目进入练习题库；低置信度、疑似重复题留在待处理状态。
7. 精确或近似重复只生成候选关系。用户确认合并后，规范题保留所有来源定位。

### 练习和保存回答

1. 用户选择练习模式和筛选条件。题目队列由 Flask 程序规则从 canonical active 题库生成；不调用 LLM 选题。
2. 展示题目时创建 SessionItem。用户可反复重写临时回答；草稿和重写次数不进入长期回答历史。
3. 真正完成一次练习时，用户选择“不会、模糊、基本会、熟练”之一。该动作创建独立 PracticeReview；用户不保存答案也可以完成并记录练习。
4. 用户可选择“保存回答”。只有此时才创建 SavedAnswer 和 SavedAnswerVersion；该版本的答案质量评分单独设置，可选关联本次 PracticeReview。若在完成练习后保存，SavedAnswer 保留首个 source_session_item_id；该 SavedAnswerVersion 记录 source_session_item_id/source_practice_review_id，并回填 PracticeReview.saved_answer_version_id。
5. SavedAnswer.source_session_item_id 记录这条回答最初从哪次练习创建；SavedAnswerVersion.source_session_item_id/source_practice_review_id 记录这个具体版本在哪次练习产生。详情页编辑产生的版本允许两字段为空。
6. 对已保存回答编辑并保存时，追加新版本并将最高版本号设为当前版本；旧正文和旧评分保留。若要另存为一条独立回答，使用“保存为新回答”。
7. 每题最多一条置顶 SavedAnswer。回答排序只用置顶状态和当前版本的用户答案质量评分。
8. PracticeReview 的掌握度是复习调度的唯一评分输入；SavedAnswer 的答案质量评分、编辑和置顶均不改变 next_review_at。

### LLM 润色、参考答案和分析

1. 用户主动选择操作：润色草稿/已保存回答、生成参考答案，或分析完整性、遗漏的技术点和表达清晰度。
2. 用户选择上下文：不使用资料、简历、一个 Project，或多个 Project 与简历组合。Project 选择后只展开 is_active 且 include_in_context 的关联资料；用户可排除具体资料。
3. Project 名称、简介、技术栈、职责、难点、成果和亮点由用户在“编辑项目”中维护。新建 Project 时系统创建唯一的系统管理 Project Profile Material；保存 Project 表单时自动序列化并追加其 MaterialVersion。用户不需要单独创建或重复编辑 Profile 文件；只有该版本化 Material 才作为 LLM 事实证据。
4. 检索只在所选 Project/资料当前版本中进行，向模型传送引用片段。历史输出记录实际使用的 MaterialVersion 和 chunk。
5. 参考答案默认与用户 SavedAnswer 分开。流程是“查看/收藏参考答案 → 用户重新组织自己的回答 → 主动保存”。用户直接保存 AI 原文时 origin_kind=ai_generated；用户自己组织措辞但受参考答案辅助时可标 ai_assisted 并记录 assistant_output_id；未使用 AI 创作时为 user_written。AI 润色保存为 ai_assisted，并记录 based_on_version_id 和 assistant_output_id。
6. 未保存的用户草稿和模型输出默认只在本次界面使用。资料没有提供的项目、指标或职责必须指出缺少证据，不得生成成用户事实。
7. LLM 输出和可选分析不修改 SavedAnswer 用户评分、PracticeReview、掌握度、复习时间、选题队列或置顶状态。

### Project 与资料关联

- Project 是用户项目的管理实体，用户只需编辑一个项目表单，字段包括名称、简介、技术栈、个人职责、难点、成果、亮点和备注。Project 字段用于界面管理，不直接作为事实证据发送给 LLM。
- 保存/编辑 Project 中的事实字段时，系统自动维护唯一的 kind=project_profile Material 并追加 MaterialVersion；Profile 正文由项目名称、简介、技术栈、个人职责、难点、成果和亮点组成，备注仅用于管理，不默认提供给 LLM。UI 仍只提供一个“编辑项目”表单，不显示重复的 Profile 文件编辑入口。
- 其他事实资料保存在 Material/MaterialVersion，例如简历、项目说明、README、架构文档。一个 Project 可关联多份 Material，每份 Material 可有多个版本。
- 简历通常作为独立通用 Material；从简历中整理出的项目片段可按用户确认关联到相应 Project。选择“简历 + Project A”时，分别检索所选简历和 Project A 的有效资料。
- 用户选择整个 Project 时，只使用其中 is_active=true 且 include_in_context=true 的 Material 当前版本；历史版本保留但不默认检索。
- 生成内容记录当时实际使用的 Project ID、MaterialVersion 与片段引用；以后更新资料不追溯改写已生成内容。
- Profile Material 由系统创建、版本化和维护；唯一性以 Project ID + kind=project_profile 约束。Project 表单保存与 Profile MaterialVersion 追加在同一事务中完成，用户不手动维护第二份资料。

### 相似题判断与归并

- normalized_hash 完全相同的题目直接形成候选；其他疑似重复由 n-gram/trigram 先筛选，可选 LLM 做三分类建议。same_question 仍需用户确认才合并；related_question/different_question 不合并。
- 合并 Question B 到 A 时只设置 B.status=merged 和 B.merged_into_question_id=A，不删除 B 或搬迁其关系。题库默认只列规范题；A 的详情通过归并关系聚合显示 B 的来源、回答、PracticeReview、SessionItem 和 AssistantOutput。
- 合并时将指针直接指向规范题并校验无环；历史行仍保留原始 question_id。归档 canonical 题时明确说明关联子题会一起退出活动题库；未来实现永久删除时，先展示归并子题和历史依赖。

## Agent 开发题目分类

第一版创建可编辑的层级分类。初始分类采用以下主题，不在代码中写成固定枚举：

| 分类组 | 初始主题 |
|---|---|
| LLM 与上下文 | LLM 基础、Prompt、Structured Output、Context Engineering |
| 工具与协议 | Function Calling / Tool Use、MCP |
| 检索与记忆 | RAG、Memory |
| Agent 框架与控制流 | LangChain、LangGraph、Multi-Agent |
| Agent 设计模式 | ReAct、Plan-and-Execute、Reflection、Router、Supervisor、Workflow vs Agent、Human-in-the-loop |
| 质量与安全 | Agent Evaluation、Observability、Agent Security |
| 工程基础 | 部署、Python/后端 |
| 经历与实践 | 项目实践 |

Topic 允许新增、改名、移动层级、停用；题目通过关系表关联多个 Topic。Tags 用于同一分类之外的横向词条、技术名、版本、公司/来源等筛选。OCR/LLM 给出的分类只是建议，用户可确认或更改。

## 数据模型

采用 SQLite。每个逻辑表按功能阶段加入；第一版不建立用户/租户表，也不为了未来同步引入分布式 ID 服务。个人资料文件存本地应用数据目录，数据库存引用路径、哈希和元数据。

| 表 | 主要字段与职责 |
|---|---|
| source_asset | id, source_type, platform, source_url, external_id, title, author, captured_at, original_path, sha256, metadata_json, archived_at。保存截图或未来网页/帖子/视频来源。 |
| ingestion_job | id, source_asset_id, status, stage, engine, engine_version, error, created_at, updated_at。记录每张截图处理状态；OCRBlock 以 ingestion_job_id 关联；首版不需要通用任务恢复框架。 |
| ocr_block | id (UUID), ingestion_job_id, text, bbox_json, reading_order, confidence, block_type, created_at。每次 OCR job 产生新的稳定 block ID；旧 job/block 不覆写。 |
| question | id, text, normalized_text, search_text, normalized_hash, answer_type, difficulty, status, suggestion_json nullable, merged_into_question_id nullable, archived_at, created_at, updated_at。pending_review 时 suggestion_json 存分类/标签/难度/边界候选；确认后只把用户接受的值写入正式关联。 |
| question_source | id, question_id, source_asset_id, locator_type, locator_json, raw_ocr_text, confidence, created_at。允许同一题在同一来源有多个定位；不将 bbox 固定为唯一 locator。 |
| question_source_ocr_block | question_source_id, ocr_block_id (composite primary key)。通过稳定 ID 关联题目来源与 OCR 原文块，不依赖 JSON 数组下标。 |
| topic | id, track_key, parent_id, slug, name, sort_order, is_active。Agent 开发分类由数据库初始化数据提供并可编辑。 |
| question_topic | question_id, topic_id。题目与多个正式 Topic 的多对多关联；待确认建议不写入此表。 |
| tag / question_tag | 可编辑的横向标签及题目关联。 |
| question_relation | question_id, related_question_id, relation_type (same_question/related_question/different_question), decision_status, suggested_by, confidence。decision_status 为 suggested/accepted/rejected；记录规则、LLM 或用户的判断，合并需用户确认。 |
| project | id, name, summary, tech_stack, personal_role, challenges, outcomes, highlights, notes, is_active, archived_at, created_at, updated_at。用户编辑单一 Project 表单；保存事实字段时自动追加对应 profile 版本。 |
| material | id, kind, project_id nullable, title, original_filename, is_active, include_in_context, is_system_managed, archived_at, created_at。类型如 resume, project_profile, project_brief, readme, architecture_doc, other。一个 Project 可关联多份资料；每个 Project 最多一个 UI 隐藏的系统管理 Project Profile；通用简历可不关联。 |
| material_version | id, material_id, version_no, path, sha256, parsed_at, created_at。每次修改/替换追加版本，不覆盖原版本；最高 version_no 为当前版本。Project Profile 由保存 Project 表单时自动序列化生成版本。 |
| material_chunk | id, material_version_id, project_id nullable, ordinal, page_number, heading, text。用于全文检索和给简历中的特定项目片段建立项目关联。 |
| saved_answer | id, question_id, source_session_item_id nullable, is_pinned, archived_at, created_at, updated_at。代表用户主动保存的一条回答；每题最多一个 pinned。 |
| saved_answer_version | id, saved_answer_id, version_no, content, source_session_item_id nullable, source_practice_review_id nullable, self_rating nullable (1–5), self_rating_updated_at nullable, origin_kind (user_written/ai_assisted/ai_generated), based_on_version_id nullable, assistant_output_id nullable, created_at。正文版本不可覆写；评分只表示答案质量。同一回答的 version_no 唯一递增，最高版本号为当前版本。 |
| practice_session | id, mode, filters_json, selector_version, started_at, completed_at。保存练习条件和过程。 |
| session_item | id, session_id, question_id, ordinal, status (shown/skipped/completed), selection_reason, viewed_at, completed_at。只记录题目展示/跳过/完成事件，不保存未保存草稿。 |
| practice_review | id, question_id, session_item_id unique, saved_answer_version_id nullable, review_rating (dont_know/vague/basic/proficient), reviewed_at, updated_at。四级掌握度事件；不要求关联 SavedAnswer。 |
| question_state | question_id, is_favorite, is_wrong, last_reviewed_at, last_review_rating nullable, next_review_at nullable, user_note, updated_at。is_favorite/is_wrong 保留在原题；只有 canonical root 缓存由该 root 和所有 merged descendants 的 PracticeReview 聚合出的最近复习/next_review_at。merged child 不单独排期。 |
| assistant_output | id, question_id, source_saved_answer_version_id nullable, output_type, origin_kind, selected_context_json, content_text nullable, result_json nullable, provider, model, prompt_version, created_at。显式保存的参考答案/分析或被 SavedAnswerVersion 引用的润色结果；预览默认临时。 |
| assistant_output_source | assistant_output_id, material_version_id nullable (ON DELETE SET NULL), material_id_snapshot, material_version_id_snapshot, chunk_ids_json nullable, source_title_snapshot, version_no_snapshot, sha256_snapshot, source_deleted_at nullable。正常时通过 material_version_id/chunk_ids_json 回溯事实来源；永久删除资料时置空版本外键和 chunk_ids_json，只保留必要 ID 与来源元数据快照。 |

关键约束：

- 用户文本只有经“保存回答”动作后才写入 SavedAnswerVersion；一次练习是否保存答案，与是否建立 PracticeReview 无关。
- 更新回答通过新增版本完成，禁止原地覆盖旧版本；需要撤回/删除时保留明确审计规则，默认不自动清理历史。
- 新版本初始不继承旧版本答案质量评分；用户需对当前版本重新评分。置顶属于 SavedAnswer 整体，可在编辑版本后保持置顶。
- SavedAnswer.source_session_item_id 记录答案条目的首次来源；SavedAnswerVersion 的 source_session_item_id/source_practice_review_id 记录每个内容版本的实际来源，详情页编辑时可为空。
- SavedAnswerVersion.source_session_item_id 和 source_practice_review_id 分别记录该版本产生时的练习项和掌握度事件；题目详情页编辑的版本两者均可为空。若设置 source_practice_review_id，它必须属于相同 SessionItem 和 canonical question。PracticeReview.saved_answer_version_id 是该次练习可选关联的回答版本；它不改写版本原有的来源记录。
- 若 SavedAnswerVersion 通过一次已完成的练习产生，source_session_item_id 与 source_practice_review_id 必须同时填写，并指向同一次练习；纯题目详情页编辑时两者同时为空。保存动作不能为了补全来源而创建 PracticeReview。
- 修改用户评分只更新对应版本的评分元数据和时间，不生成内容版本；列表按当前版本分数显示。
- 用户评分更新时同步更新 SavedAnswer.updated_at，用于回答排序的同分时间顺序；该更新不改 PracticeReview/复习摘要。
- 每个问题最多一条 pinned SavedAnswer；通过事务和 SQLite partial unique index 保证。
- 同一 SavedAnswer 的 version_no 唯一且递增；编辑只插入新版本，不更新已有版本正文。
- 每个 Project 最多一个系统管理的 kind=project_profile Material，通过 SQLite partial unique index 保证；material_version 的 (material_id, version_no) 唯一。保存 Project 表单与新增 Profile 版本在同一事务完成。
- 回答列表以每条 SavedAnswer 的 current_version.self_rating 排序：置顶在先，其余已评分版本按分数降序，未评分版本在后，同分按回答更新时间排序。
- PracticeReview.session_item_id 唯一，且必须指向已完成的同题 SessionItem；跳过题目不创建 PracticeReview，一条 PracticeReview 可以没有 saved_answer_version_id。review_rating 只使用四级枚举：dont_know、vague、basic、proficient。
- PracticeReview 与 SavedAnswerVersion 的可选关联不自动创建另一方；PracticeReview.saved_answer_version_id 可以指向同一 canonical question 的既有回答版本。若新版本是在该次练习中产生，则其 source_session_item_id/source_practice_review_id 记录该次来源；用户先完成 PracticeReview、后保存答案时，可在保存事务中将该版本关联到 PracticeReview。后续练习复用既有版本时只更新该次 PracticeReview 的关联，不改写版本来源。此操作不改变 review_rating 或复习时间。
- review_rating 必须由用户在完成本次练习后选择；LLM 分析不能代填或改写 PracticeReview。
- SavedAnswerVersion.self_rating 只表示答案质量并用于回答列表；只有 PracticeReview.review_rating 能更新 question_state 的掌握度摘要和 next_review_at。question_state 是可重算摘要，不是独立训练事实。
- PracticeReview.session_item_id 和 saved_answer_version_id（若提供）必须解析到相同 canonical question；原始 question_id 仍各自保留。更正 review_rating 只修正该事件并重新计算摘要，不创建答案版本。
- PracticeReview 永远保留创建时的原始 question_id；canonical selector 以 root 聚合同一 canonical group 的 PracticeReview。归并时可重建 root 的派生复习摘要，但输入只取该组按 reviewed_at 最新的有效 PracticeReview 及其 review_rating；合并本身不创建或改写复习事件，也不引入新的调度规则。child 不单独排期或生成重复复习项。
- 合并时保留所有 QuestionTopic/QuestionTag 原始关系；不迁移历史关联。合并确认页将 A 与 B 的 Topic/Tag 并集作为 A 的初始规范分类，确认后把分类值写入 A 的直接关联；B 的原关联仍保留用于历史。之后编辑 A 的分类只改 A；再次合并子题时预览新并集，不静默改写已整理的规范分类。
- canonical A 的收藏状态按 A 或任一 merged descendant 被收藏的 OR 规则聚合。is_wrong 原标记保留在各自题目；错题练习以 canonical 为单位，只要 A 或任一 merged descendant 被标错/最近 PracticeReview 为 dont_know，队列就包含 A 一次。归并完成后立即从整个 group 的最新 PracticeReview 重算 A 的 due state；收藏、错题和复习 selector 均对 A 去重。
- 题库默认列表、搜索结果和所有 selector 只返回 status=active 且 merged_into_question_id 为空的 canonical question。merged child 永远不能作为单独题进入新队列。
- pinned 唯一性按 canonical group 检查。合并两题若都有 pinned SavedAnswer，确认步骤要求用户选一个保留为规范题置顶，另一条仅取消置顶，不删除回答。
- 重新评分、编辑或润色 SavedAnswer 不能创建 PracticeReview，也不能改 next_review_at。
- 正文来源必须清楚区分 user_written、ai_assisted、ai_generated；润色版本记录 based_on_version_id 和 assistant_output_id，直接保存的 AI 参考答案标为 ai_generated。
- LLM output、分析分数和引用均不更新 PracticeReview、question_state，也不参与回答排序或复习调度。
- question.merged_into_question_id 只指向 canonical active question；合并时校验无环并将后续合并直接指向 canonical，不删除题目或迁移历史行。
- Project 的可变管理字段不作为模型事实来源。Project Profile Material 对每个 Project 唯一且系统管理；保存用户编辑的事实字段时，在同一事务追加 MaterialVersion 与检索片段，旧版本和历史 AssistantOutput 引用保持不变。
- assistant_output.selected_context_json 只记录用户选择的 Project/MaterialVersion/Chunk ID 和生成选项，不存储检索正文或完整 provider 请求；应用日志不写入 prompt 和资料全文。
- 只有用户确认的 same_question 关系能设置 merged_into_question_id；LLM/规则产生的 suggested 关系不得直接改变题目状态。
- 每次 OCR 运行使用新的 ingestion_job 和新的不可变 OCRBlock ID；question_source_ocr_block 只引用明确 ID，不引用数组下标。
- Archive 是首版的完整清理能力。Permanent Delete 仅开放给无历史依赖的 SourceAsset/Material；题目、回答、项目以及有引用资料先归档，后续再实现完整依赖清理。

### 相似题判断与合并

1. 先对文本做 Unicode/空白/标点归一化并计算 hash，完全相同的题直接进入候选列表。
2. 近似题用轻量字符 n-gram/trigram 相似度筛候选，例如“**MCP 和 Function Calling 有什么区别？**”与“**Function Calling 与 MCP 的区别是什么？**”。搜索和去重都不默认依赖向量库。
3. 可选 LLM 辅助分类候选为 same_question、related_question 或 different_question；LLM 只给建议，不执行合并。
4. 用户确认 same_question 后选择规范题 A，将题目 B 标成 merged 并设置 B.merged_into_question_id=A。只有用户明确选择后才合并。
5. 合并确认页展示 A 与 B 及其所有 merged descendants 的 Topic/Tag 并集。用户可在同一界面整理规范题最终分类；确认后把最终集合写入 A 的 question_topic/question_tag 直接关联，子题的原关联仍保留用于历史。这是复制 taxonomy 值，不迁移训练历史。之后编辑 A 的分类只改 A；再次合并子题时预览新并集，不静默改写已整理的规范分类。
6. 题库列表、检索结果和所有 selector 只返回 status=active 且 merged_into_question_id 为空的 canonical question。merged child 永不作为独立题再次进入队列；检索命中 merged child 时重定向到 canonical。收藏状态按 A/所有归并子题任一被收藏聚合；错题队列按 A/归并子题的 is_wrong 或最新 PracticeReview 聚合，原始标记留在各自题目上。
7. 查看 A 时，聚合显示 A 与所有 merged descendants 的来源、SavedAnswer、PracticeReview、SessionItem 和 AssistantOutput；这些记录仍保留原 question_id，不批量搬迁。PracticeReview 与 SavedAnswerVersion 通过 canonical question 校验归属。
8. 相关题保持独立题目，只建立 related_question 关系。例如“MCP 的通信流程是什么？”与“Function Calling 和 MCP 的区别是什么？”是相关题，不能因此合并。
9. canonical 关系无环；再次合并时直接指向最终规范题。归档或永久删除规范题时先展示关联 merged 题和历史记录。

### 归档与永久删除

- Archive 是首版完整实现的主要清理方式：Question、SavedAnswer、Project、Material 和 SourceAsset 均可归档，历史仍可查但不再默认进入列表、练习队列或 Project 上下文。
- 首个可用版本的永久删除只覆盖没有其他历史引用的 SourceAsset/Material；有引用的对象显示“存在历史依赖，建议归档”，暂不提供级联永久删除，不因此阻塞题库和训练功能。
- 后续完整永久删除流程需通过二次确认，并展示将移除的题目、回答版本、PracticeReview、SessionItem、来源定位、资料版本和文件数量。
- 完整永久删除 Question 时，要处理 merged canonical 与子题关系；首版对有历史引用的 Question 只归档，不能静默级联。
- 后续完整删除 SavedAnswer 时需处理其版本、来源关系、PracticeReview 可选版本引用及 AssistantOutput 来源引用；首版对有历史引用的 SavedAnswer 只归档。
- Project 归档会从默认上下文中排除其 profile 和关联资料但保留文件。首版不硬删仍有关联资料的 Project；后续删除时默认解除资料关联并保留文件，逐份资料另行确认是否永久删除。
- 永久删除 Material 会删除文件、版本、MaterialChunk、FTS/其他索引和处理缓存。AssistantOutputSource 的 material_version_id 外键置空、chunk_ids_json 清空，只保留 material/version 必要 ID 快照、标题/版本/hash 等元数据，不保存 chunk 正文或完整 prompt；selected_context_json 和应用日志不含检索正文；历史输出明确显示“原始证据资料已被用户永久删除，正文不可恢复”。
- 若历史 AssistantOutput 的生成答案由用户明确保存，可保留该答案本身；这不授权保留原始资料正文、完整模型请求 payload 或隐式副本。
- 截图 SourceAsset 归档默认保留原图。有历史引用的截图首版只支持归档；无引用的 SourceAsset 可提供带确认的永久删除。

### 通用来源定位

SourceAsset 表示原始内容或媒体；QuestionSource 表示某道题在该来源中的位置。locator 使用类型加 JSON 参数，不将 bbox 固定成所有平台的唯一来源结构：

- image_region：归一化 x/y/width/height，通过 question_source_ocr_block 关联稳定 OCR block ID。
- video_interval：start_ms/end_ms。
- carousel_slide：image_index 或 slide_index。
- page_region：page_number 与区域位置。
- text_span：字符范围或原文锚点。

首版只写入 image_region 和截图 OCR 原文。未来来源平台按 source_type/platform 扩展；不把自动采集器列入 MVP。

### 中文和中英文混合搜索

题目文本同时保留原文和用于搜索的 normalized_text；归一化只做大小写、全半角、空白和常见标点处理，不删除技术词。主要查询会是“LangGraph 持久化”“MCP 通信协议”“Function Calling”等中文与英文技术词混合内容。

SQLite FTS5 可以作为 MVP 基线，但不能假设默认 tokenizer 的中文效果足够。阶段 1 用真实题库样本比较 unicode61、内置 trigram tokenizer 和轻量中文分词生成 search_text 的命中结果；短中文词和英文短词也要检查。按精度/召回结果选择最小实现，可使用 FTS5 + normalized_hash 的混合搜索。不为此引入独立向量数据库。

## 后端模块与接口

Flask 保持模块化单体，Vue 独立开发与构建；发布后可由 Flask 同源提供静态前端。平台不需要认证 API，绑定本机回环地址，限制 Host/Origin，文件只能通过应用资源 ID 访问。

建议模块：

- api：Flask blueprints、输入校验和响应 schema。
- sources：文件保存、来源元数据、locator 编码/解码。
- ingestion：多图上传、截图校验、OCRBlock 持久化、候选题拆分、分类/难度建议和人工确认状态。
- taxonomy/questions：可编辑 Topic/Tag、题目 CRUD、中英文搜索、轻量相似候选和安全合并。
- answers：SavedAnswer、SavedAnswerVersion、评分/置顶/版本追加。
- practice：程序 selector、PracticeReview 四级掌握度事件、错题/收藏/到期队列及简单弱项汇总。
- projects/materials：Project、Material 状态/版本、Project Profile Material、解析文本和按 Project 展开的上下文检索。
- assistant：显式请求润色、参考答案或可选分析；保存明确选择的输出及来源，不连接队列 selector。
- storage：跨平台本机数据目录、文件校验、备份/恢复。

SQLite FTS5 用于题目和资料全文搜索，但阶段 1 必须用中文/英文混合样本验证 tokenizer。MVP 不引入向量数据库；当真实资料检索效果不足时再评估 embedding。Worker 不进入零阶段骨架：截图 OCR 首版先用一个简单的导入任务状态；若 OCR 耗时影响页面响应，再在该阶段增加单个本地 worker 和手动重试，不做通用 job orchestration、自动恢复策略或 Celery/Redis。

### API 分组

- POST /api/v1/sources：一次上传一张或多张截图，为每张图建立来源和处理状态；GET /api/v1/ingestions/{id} 与 GET /api/v1/ingestions/{id}/ocr-blocks：读取任务和稳定 OCRBlock。
- GET /api/v1/questions：搜索/过滤；GET/PATCH /api/v1/questions/{id}：读取或编辑题目、分类、标签、来源和归档状态。
- GET /api/v1/questions/{id}/similar-candidates：查看 hash/n-gram/可选 LLM 建议；POST /api/v1/questions/{canonical_id}/merge：用户确认后将 source_question_id 合并到规范题。
- GET /api/v1/questions/{id}/history：规范题聚合自身及 merged children 的来源、SavedAnswer、PracticeReview、SessionItem 和 AssistantOutput。
- POST /api/v1/questions/{id}/saved-answers：显式保存一条回答并创建版本 1；已完成练习中保存时同时附 source_session_item_id 和 source_practice_review_id，详情页保存则两者为空。练习来源字段必须成对且同题；若提供 source_practice_review_id，事务内同时将该版本关联到 PracticeReview.saved_answer_version_id。保存动作不会创建 PracticeReview。
- GET /api/v1/questions/{id}/saved-answers、GET /api/v1/saved-answers/{id}/versions：读取回答列表和历史版本。
- POST /api/v1/saved-answers/{id}/versions：给已保存回答追加版本并可附带本版本的 source_session_item_id/source_practice_review_id；PATCH /api/v1/saved-answer-versions/{id}/rating：设置用户答案质量评分。写入时校验练习事件和题目属于同一 canonical question。
- PATCH /api/v1/saved-answers/{id}/pin：置顶或取消置顶；服务保证每题最多一个置顶回答。
- POST /api/v1/session-items/{id}/review：记录 review_rating 和可选 saved_answer_version_id；即使没有保存回答也有效。若关联答案版本，校验其属于同一 canonical question；如果版本由本次练习产生，其 source_session_item_id/source_practice_review_id 还必须与本次事件相符。PATCH /api/v1/practice-reviews/{id} 只用于用户更正这次自评并重算 next_review_at，不会创建或编辑 SavedAnswerVersion。
- GET /api/v1/questions/{id}/practice-reviews：读取练习掌握度历史。
- PATCH /api/v1/questions/{id}/state：设置收藏/错题筛选标记；此接口不修改掌握度或 next_review_at。
- GET/POST/PATCH /api/v1/topics、GET/POST/PATCH /api/v1/tags：维护首版 Agent 分类和知识点标签。
- POST /api/v1/practice-sessions：创建练习队列；GET /api/v1/practice-sessions/{id}：读取队列和题目浏览/保存状态。
- POST /api/v1/assistant/polish、POST /api/v1/assistant/reference-answer、POST /api/v1/assistant/analyze：用户主动请求。上下文参数接受简历 material IDs 与 project IDs；服务展开 Project 资料后返回引用。
- POST/GET/PATCH /api/v1/projects、GET /api/v1/projects/{id}/materials：创建/编辑、归档 Project 并查看其资料；Project 更新服务同时维护隐藏的 Profile MaterialVersion。
- POST/GET/PATCH /api/v1/materials、POST /api/v1/materials/{id}/versions：上传/编辑普通资料元数据、设置 is_active/include_in_context、追加资料版本和列出关联资料；拒绝直接修改系统管理的 Project Profile。
- POST /api/v1/{resource}/{id}/archive：Question、SavedAnswer、Project、Material、SourceAsset 的首版常规清理操作。GET /api/v1/{resource}/{id}/deletion-impact 返回依赖摘要；首版 DELETE 仅开放给没有 QuestionSource/活动导入任务引用的 SourceAsset，以及没有 AssistantOutputSource/其他历史引用的 Material，并要求显式确认。存在依赖或资源类型不在首版范围时返回 409，提示归档。
- GET /api/v1/progress：分别汇总 SavedAnswer 质量评分和 PracticeReview 掌握度、Topic 覆盖、错题集合与到期状态；不将两类评分混算。

LLM endpoints 不提供 next-question 参数或题目生成队列。练习 session 创建后，题目顺序由程序 selector 固化。

## 练习模式与简单复习规则

首版支持随机、分类、知识点、收藏、错题、复习队列；弱项练习仅作为可选简单过滤：

- 随机：在当前筛选出的 active 题目中打乱顺序。
- 分类/知识点：按用户选择的 Topic/Tag。
- 收藏：按 question_state.is_favorite 过滤。错题：按 question_state.is_wrong 或最近 PracticeReview.review_rating=dont_know 过滤；手动错题标记本身不改掌握度或到期时间。
- 复习队列：只按最近 PracticeReview.review_rating 计算 next_review_at 并由早到晚展示。SavedAnswer.self_rating 和 is_wrong 标记不参与到期时间计算。
- 弱项：只按最近一段时间的 PracticeReview.review_rating 按 Topic 汇总；每个 Topic 少于 3 条 PracticeReview 时显示“练习记录不足”，不进行排序或训练复杂模型。is_wrong 只决定错题练习集合。
- 每个 session item 保存 selector 版本和入选原因，方便解释和重算。LLM 分析不进入这些计算。

SavedAnswerVersion 的答案质量评分可用 1–5 分，含义在回答页提示；它只影响回答展示顺序。PracticeReview 使用独立四级评价，首版固定间隔建议为：不会 1 天、模糊 2 天、基本会 7 天、熟练 14 天。一个题目的 next_review_at 只由最近 PracticeReview 更新；编辑/润色/重评 SavedAnswer、修改 is_wrong 和 LLM 分析都不改变它。间隔值可配置，不引入自适应算法。

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
- 路径与文件类型通过跨平台库处理，不绑定特定桌面操作系统。
- 当前工作区按 AGENTS.md 使用 Conda test 执行 Python 开发命令；这是开发机约定，不是最终用户安装或运行产品的要求。

不采用微服务、Redis/Celery、认证服务、独立向量数据库或多 Agent 编排。单机数据量和任务量不足以支持这些复杂度。

## MVP 阶段

| 阶段 | 交付 | 验收点 |
|---|---|---|
| 0. 最小骨架 | Flask app、Vue/Vite、SQLite migration、同源/代理 API、跨平台应用数据目录。 | 两端能独立开发和构建；API health 可用；产品运行说明与开发机环境分开。 |
| 1A. 基础 Agent 题库 | 初始化 Agent Topic、Topic/Tag 管理、手动题目 CRUD/归档、列表/详情、收藏/错题标记、基础中英文搜索、PracticeSession/SessionItem、随机/分类/知识点练习和四级 PracticeReview。 | 不依赖 OCR/LLM，用户可完整维护并练习 Agent 题库；练习可不保存答案；题目掌握度由 PracticeReview 独立记录。Question Archive 已可用。 |
| 1B. 截图采集 | 单张/多张截图上传、SourceAsset、IngestionJob、稳定 OCRBlock ID、基础 OCR、多题候选拆分、image_region、原图/OCR/来源保存、人工确认/拆分/合并/修改文字和分类。 | 上传真实截图能生成候选题，用户确认后进入现有题库；每题能回看原图、OCR 原文和区域；重跑 OCR 不破坏旧引用。SourceAsset Archive 已可用；无引用 SourceAsset 可永久删除。 |
| 1C. 智能导入增强 | 多模态边界识别建议、Agent Topic/Tag/难度建议、normalized hash 完全重复、n-gram/trigram 相似候选、可选 LLM 三分类、用户确认归并及 canonical 聚合。 | 所有智能结果均可关闭且只是建议；same_question 必须用户确认；归并保留历史；merged child 不独立进队列。 |
| 2. 保存回答闭环 | 临时回答、明确保存、SavedAnswer/SavedAnswerVersion、答案质量评分、置顶、source_session_item/source_practice_review 关系、origin_kind、SavedAnswer Archive。 | 未保存草稿不入库；SavedAnswer 不自动创建/修改 PracticeReview；编辑只追加版本；版本来源可追溯或为空。 |
| 3. 练习与复习增强 | 错题/收藏/到期队列、canonical 聚合选题、固定间隔复习调度、简单弱项汇总和进度统计。 | 只有 PracticeReview.review_rating 更新 next_review_at；答案评分、编辑、LLM、is_wrong 不改复习时间；canonical question 每队列最多出现一次。 |
| 4. Project、资料与 LLM | Project 单一编辑表单自动生成 Profile 版本；多份 Material/Version、上下文开关、按简历/Project 选择上下文；润色、参考答案和主动分析；Project/Material Archive。 | Project 修改生成新 Profile 版本；旧 AssistantOutput 仍引用旧版本；排除资料不会发送；无证据经历不编造。无历史依赖 Material 可永久删除；有引用则提示归档。 |
| 后续 | 授权平台来源适配器；模拟面试、语音、视频、多 Agent；有历史依赖对象的复杂永久删除。 | 根据真实使用反馈独立评估，不阻塞题库和训练闭环。 |

首版数据清理以 Archive 为完整能力。Question、SavedAnswer、Project、Material 和 SourceAsset 都可归档；Permanent Delete 限于无历史依赖的 SourceAsset/Material。SourceAsset 若无 QuestionSource 和活动导入任务引用，可连同其 OCR job/block 一并删除；Material 若无 AssistantOutputSource 等历史引用，可删除正文、版本、chunks 与索引。有 PracticeReview、SavedAnswer、归并关系或 AssistantOutput 等历史引用的对象只提示“存在历史依赖，建议归档”，不实现复杂级联清理；后续再扩展，不让删除逻辑阻塞训练功能。

## 必须通过的业务不变量测试

以下为自动化测试验收清单；测试随所属阶段加入，发布该阶段前必须通过。涉及未来依赖清理的测试在该删除能力加入前不阻塞当前 MVP。后端用 Conda test 下的 pytest 和临时 SQLite 库测试约束/事务；LLM/OCR 使用 fake provider 和固定 fixture，不调用真实外网或模型。前端至少用组件/API mock 测试按钮动作不触发未授权保存。

### 回答保存与评分

1. 编辑草稿、反复重写、刷新或离开练习页均不创建 SavedAnswer/SavedAnswerVersion；只有显式点击“保存回答”才写入。
2. 完成一次练习可不保存回答；系统仍可保存 PracticeReview。
3. 创建或编辑 SavedAnswer/SavedAnswerVersion 不自动创建、覆盖或修改 PracticeReview。
4. 修改 SavedAnswerVersion.self_rating 只影响该问题的回答排序/答案管理，不改变任何 PracticeReview、掌握度或 next_review_at。
5. 编辑 SavedAnswer 创建新版本，旧版本正文、评分和来源不变；不创建 PracticeReview。SavedAnswer.source_session_item_id 保留该答案首次保存来源；每个 SavedAnswerVersion.source_session_item_id/source_practice_review_id 要么同时为空（详情页编辑），要么记录同一次已完成练习；关联该 PracticeReview 时其 saved_answer_version_id 指向新版本。可从 PracticeSession → SessionItem → PracticeReview → SavedAnswerVersion 追溯，历史版本来源不被后续复用改写。
6. LLM polish 不创建 PracticeReview、不改变复习时间；保存润色版必须是 ai_assisted，并设置 based_on_version_id 与 assistant_output_id。
7. LLM analyze 不改变 user score、PracticeReview、is_wrong、掌握度、next_review_at 或置顶状态。
8. 只有用户创建或更正 PracticeReview.review_rating 能改变实际复习日期；canonical 合并时可从未改写的 PracticeReview 重建聚合视图，但不能创建复习事件或更改其日期。LLM provider/API 没有写练习队列或复习日期的入口。
9. 直接把参考答案保存为 SavedAnswer 时 origin_kind=ai_generated；用户据参考答案重新组织内容后保存为 ai_assisted；独立手写为 user_written。

### PracticeReview 与复习调度

10. PracticeReview 允许 saved_answer_version_id 为空；若非空，该版本必须属于同一 canonical question。
11. PracticeReview 的 session_item_id 唯一且必须指向已完成、同题的 SessionItem；跳过题目不能创建 PracticeReview。
12. PracticeReview 的四个评价值仅为不会、模糊、基本会、熟练；复习间隔只读取最新有效 PracticeReview.review_rating。
13. 修改答案评分、编辑/润色回答、置顶回答、设置/取消 is_wrong 均不修改 next_review_at；更正 PracticeReview 会重算到期日期。

### 截图/OCR 与人工确认

14. 一张包含多道题的截图能生成多个候选，各自保留原图 locator、OCR 原文和稳定 OCRBlock UUID；数据库引用不得使用 OCR 数组下标。
15. 对同一 SourceAsset 重跑 OCR 创建新的 IngestionJob/OCRBlock ID；旧 QuestionSource 仍可访问旧 block，除非用户显式重建关联。
16. 候选题未人工确认前不能进入 active 题库或任何练习 selector；OCR/多模态/LLM 的题数、边界、Topic、Tag、难度和相似建议不会自动定稿。
17. 多张截图上传可逐张建 job 并报告各自状态；一个文件失败不丢失其他图片和已完成结果。

### 相似题与 canonical 聚合

18. 规范化文本 hash 相同时生成 same_question 候选；轻量相似算法和 LLM 只能给建议，LLM 三分类需区分 same_question、related_question、different_question。
19. 没有用户确认时 Question B 不会变成 merged；确认后只设置 B.merged_into_question_id=A，不删除 B，也不迁移 SavedAnswer/PracticeReview/SessionItem/Source/AssistantOutput。
20. 新练习、分类/标签/收藏/错题/复习 selectors 只返回 canonical active question；B 不会再次单独出现。
21. A 的详情可聚合 A 及所有 merged descendants 的来源、回答、Review、SessionItem、AssistantOutput；原始 question_id 保留，聚合读不导致重复计数。
22. 合并确认预览分类/标签并集；提交后 canonical 最终 Topic/Tag 可编辑，子题原始分类关系保留供历史查看。
23. merged child 被收藏时 canonical 在收藏练习中出现一次；任一子题 is_wrong 或最新 PracticeReview=dont_know 时 canonical 在错题队列中出现一次；原错题标记不被迁移或覆盖。
24. 合并前后 canonical 复习摘要均取 A 与所有 merged descendants 中 reviewed_at 最新的 PracticeReview；due selector 只产出 A 一次，答案自评分、收藏和 is_wrong 不重算 next_review_at。
25. canonical 题被置顶回答最多一个；合并两道都已置顶的题时要求用户选择 canonical 保留哪一个置顶，其余回答仍保留。

### Project 证据、归档删除和搜索

26. Project 表单事实字段变更自动生成新 Project Profile MaterialVersion；历史 AssistantOutput 继续引用旧版本，永不自动切换到新版本。
27. 用户关闭 Material.include_in_context 后，选择整个 Project 不会把该 MaterialVersion/Chunk 放进模型请求；Project 的可变管理字段不会绕过 Profile/Material 证据链直接发送。
28. 当后续阶段支持删除有历史引用的 Material 时，正文、MaterialChunk、FTS/其他索引、缓存、selected_context_json 和日志中不再存在该原始资料全文；AssistantOutputSource 只剩必要 ID、标题/版本/hash 等元数据快照，UI 显示“原始证据资料已被用户永久删除，正文不可恢复”。测试禁止为审计保留隐藏正文副本。
29. 首版无依赖 SourceAsset/Material 可永久删除；有 QuestionSource/活动导入或 AssistantOutputSource/其他历史引用时只允许 Archive 并明确提示依赖；Question、SavedAnswer、Project 首版只支持 Archive。
30. Archive 后对象不进入默认列表、上下文或 selector，但归档视图仍可追溯已有记录。
31. 中文/英文混合搜索 fixture 至少覆盖“LangGraph 持久化”“MCP 通信协议”“Function Calling”“RAG 检索重排”；测试比较 FTS5 tokenizer/trigram/轻量中文分词方案，不能因 FTS5 编译选项缺失而静默关闭搜索。

## 非目标与过度工程控制

首版不做登录、多租户、云同步、公开社区、自动社媒采集、复杂模拟面试、语音/视频、多 Agent、复杂自适应算法、LLM 自动评分管线、微服务、Redis/Celery、独立向量库或通用任务编排器。

Background task 只在实际耗时证明必要时引入；不建立复杂 Evaluation/Rubric 评分流水线。PracticeReview 是掌握度事实来源，SavedAnswerVersion.self_rating 是答案质量数据；管理面板只覆盖个人维护题库、Project 和资料所需的操作。

## 取舍说明

- 本地单用户 + SQLite 适合个人规模、离线使用和简单备份；未来需要多设备时再设计同步和冲突解决。
- 前后端源代码分离，但首版运行同源，可减少 CORS 和部署复杂度。
- OCR 先读图并提供可复核草稿，模型不直接发布题目；原图和定位永远可以追溯。
- SavedAnswer 与版本历史区分“多条独立回答”和“编辑同一条回答”：评分属于版本，置顶属于回答条目。
- Project 与 Material 区分项目上下文和文件：用户主要选择 Project，系统再展开项目资料；简历仍可独立选择。
- 随机/分类/收藏/错题/复习由规则和题库状态决定；弱项从 PracticeReview 汇总，不使用 SavedAnswer 评分。
- 参考答案、润色和分析只有主动调用；分析评价永不覆盖用户评分或重排答案。

## 核心闭环与不变量

截图采集 → OCR/多模态辅助识别 → 人工确认 → Agent Topic 分类 → 题库 → 程序规则选题 → 实际练习 → 创建 PracticeReview 记录本次掌握程度 → 用户可选择保存自己的回答 → SavedAnswer 多版本、答案质量自评分与置顶 → 可选 LLM 润色/参考答案/分析 → 可选择简历和 Project 作为长期上下文 → 只根据 PracticeReview 安排后续复习。

实现和验收始终遵守以下分离原则：

| 不能混为一谈 | 数据和行为边界 |
|---|---|
| 回答质量与题目掌握程度 | SavedAnswerVersion.self_rating 只排序和管理答案；PracticeReview.review_rating 才影响掌握度、弱项统计和 next_review_at。 |
| 保存回答与完成练习 | 保存回答写 SavedAnswer/Version；完成练习写 PracticeReview。任何一个都可以单独发生。 |
| LLM 辅助与训练决策 | LLM 输出可被忽略/修改；程序和题库状态决定题目队列及复习，LLM 不写入这些状态。 |
| Project 管理信息与事实证据 | Project 字段用于管理/显示；模型依据只能来自选中的 MaterialVersion/MaterialChunk。 |
| AI 输出与用户来源 | 每个保存版本记录 user_written、ai_assisted 或 ai_generated，以及派生版本和输出引用。 |

## 研究依据

商业产品和开源项目的对比详见 [面试训练助手市场与开源项目调研](../../research/agent-interview-training-landscape-2026-10.md)。对本设计有直接参考价值的工程模式包括：

- 面试鸭的分类、标签、搜索、收藏和题目管理。
- Paku 的置信度门槛和人工复核队列；其主题抽取器不是通用面试题解析器。
- PaddleOCR 的文本/版面识别能力；实际准确度需用个人截图集验证。
- Anki 的逐次用户评分和复习队列；此处只采用透明简单规则，不照搬 FSRS 自适应模型。
- NotebookLM/Open Notebook 的资料选择和来源引用；不照搬完整知识库平台。

## 实施阶段的配置项

以下值在对应 MVP 阶段选择并通过样本验证，不构成新增架构范围：OCR 引擎与单文件大小上限、LLM provider/预算、个人 1–5 分解释、四级 PracticeReview 的固定间隔参数、首版导入格式和备份交互。

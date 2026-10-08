# Agent Interview Assistant Phase 0 and 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local Flask/Vue foundation and Phase 1A Agent question bank so the user can create, classify, search, archive, and practice questions without OCR or LLM services.

**Architecture:** Use a Flask app factory with a small set of versioned SQLite migrations and direct `sqlite3` repositories. Keep the Vue 3 + TypeScript + Vite client separate in development, proxy API requests to Flask, and serve the built client from Flask for local production use. Keep question selection deterministic and record each completed practice as a `PracticeReview`.

**Tech Stack:** Python, Flask, SQLite, pytest, Vue 3, TypeScript, Vite, Vitest, native browser `fetch`.

**Spec:** `docs/superpowers/specs/2026-10-08-agent-interview-assistant-design.md` (Phase 0 and Phase 1A only)

## Global Constraints

- 首版按个人使用设计，不做账号、多人协作、云同步。
- Flask 提供 REST API；Vue 3 + TypeScript + Vite 是独立前端，开发时通过 Vite 代理 API，发布时可由 Flask 同源提供静态文件。
- 题目掌握程度由 PracticeReview 独立记录；SavedAnswer 答案质量评分和掌握程度不得混用。
- 练习题目由 Flask 程序规则从 active 题库生成；Phase 1A 不调用 LLM 选题。
- Phase 1A 不实现 OCR、截图采集、SavedAnswer、Project 资料或 LLM 功能。
- 使用 SQLite 和本地文件/应用数据目录；不引入微服务、Redis/Celery、认证服务或向量数据库。
- 当前开发环境按 `AGENTS.md` 使用 Conda `test`；这只是开发约定，不写成产品的 macOS 或 Conda 运行限制。
- 对归档题目，默认题库、搜索结果和练习 selector 不返回；归档用于个人数据维护，不删除其练习历史。

## Review Focus

- **空白或超长题目文本：**拒绝空白内容，限制合理请求大小，并返回可显示的字段错误；由 Task 4 覆盖。
- **混合中英文搜索：**“LangGraph 持久化”“MCP 通信协议”“Function Calling”“RAG 检索重排”应能命中对应题目；由 Task 5 覆盖。
- **停用或不存在的分类/标签：**筛选和题目写入不能静默接受无效 ID；由 Task 3 和 Task 4 覆盖。
- **归档题目：**归档后不出现在默认列表、搜索和新练习队列，但历史题目数据仍可读取；由 Task 4 和 Task 6 覆盖。
- **练习会话边界：**跳过题不能生成 PracticeReview；同一 SessionItem 不能重复完成或重复写 Review；由 Task 6 和 Task 7 覆盖。

---

## File Structure

```text
backend/
  app/
    __init__.py                 # create_app、blueprint 注册和环境配置
    config.py                   # 本地数据目录、SQLite 路径、运行模式
    db.py                       # sqlite3 连接、事务和迁移
    migrations/                 # 按版本排序的 SQL schema
    api/v1/                     # health、topics、tags、questions、practice 路由
    repositories/               # 仅负责 SQLite 读写
    services/                    # 题目校验、规范化、selector 和 Review 规则
  tests/
    conftest.py                 # 临时数据库和 Flask client
    api/                        # API 行为测试
    services/                   # selector、规范化、复习事件测试
  requirements.txt
  run.py
frontend/
  src/
    api/client.ts               # fetch 封装及统一错误处理
    router/index.ts             # Question Bank、Topic 管理、Practice 路由
    pages/                      # 题库、题目详情、分类管理、练习设置、练习会话
    components/                 # QuestionForm、TopicTagPicker、PracticeRating
    types/                      # API 类型
  tests/
  package.json
  vite.config.ts
README.md                       # Conda test、前端依赖和本机启动说明
```

Keep this structure small: do not introduce a generic repository framework, worker, event bus, or frontend state-management package for Phase 1A.

## Task 1: Local App Skeleton

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/local_security.py`
- Create: `backend/app/api/v1/health.py`
- Create: `backend/run.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/api/test_health.py`
- Create: `backend/tests/test_local_security.py`
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/tests/health.spec.ts`

**Interfaces:**
- Produces: `create_app(test_config: dict | None = None) -> Flask`; `GET /api/v1/health -> {"status":"ok"}`; Vite `/api` proxy to the local Flask API; Flask binds to loopback and rejects non-local Host/Origin values.
- Test configuration may override the SQLite path and must not touch the user's normal data directory.

- [ ] **Step 1: Write failing tests** `test_health_returns_ok_with_temp_data_dir`, `test_non_local_host_is_rejected`, `test_non_local_origin_is_rejected`, and the frontend `renders_app_title_and_health` smoke test.
- [ ] **Step 2: Run the focused tests and confirm they fail.** Activate `test`, then run `(cd backend && pytest tests/api/test_health.py tests/test_local_security.py -q)` and `npm --prefix frontend test -- tests/health.spec.ts` from the repository root.
- [ ] **Step 3: Implement the Flask app factory, safe local config, loopback/Host/Origin checks, health blueprint, and run entry point.** Use `platformdirs` for the default application data directory; allow `APP_DATA_DIR` override for development and tests.
- [ ] **Step 4: Add the minimal Vite/Vue/TypeScript/Vitest setup, `test: vitest run` script, and `/api` proxy; run `npm --prefix frontend install` to create the lockfile, then rerun both focused tests and confirm they pass.**
- [ ] **Step 5: Commit** as `chore: scaffold local Flask and Vue app`.

## Task 2: SQLite Migrations and Initial Agent Topics

**Files:**
- Create: `backend/app/db.py`
- Create: `backend/app/migrations/001_phase1a_core.sql`
- Create: `backend/app/taxonomy/initial_topics.py`
- Create: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `create_app` test configuration from Task 1.
- Produces: `get_db()`, `init_db()`, and `apply_migrations()`; SQLite tables for `topic`, `tag`, `question`, `question_topic`, `question_tag`, `question_state`, `practice_session`, `session_item`, and `practice_review`.

- [ ] **Step 1: Write `test_migration_creates_core_tables`, `test_foreign_keys_enabled`, `test_migrations_are_idempotent`, and `test_initial_topic_tree_contains_phase_1a_topics`** for the schema, constraints, repeatable startup, and seed content.
- [ ] **Step 2: Run them with `conda activate test`, then `cd backend && pytest tests/test_migrations.py -q`; confirm they fail.**
- [ ] **Step 3: Implement versioned SQL migrations and per-request SQLite connections.** Enable `PRAGMA foreign_keys=ON`; use transactions for multi-row question/topic updates; do not add an ORM.
- [ ] **Step 4: Seed the initial topic tree as database rows** with stable slugs and parent links.
- [ ] **Step 5: Run `conda activate test`, then `cd backend && pytest tests/test_migrations.py -q`; confirm schema and seed tests pass in a temporary database.**
- [ ] **Step 6: Commit** as `feat: add Phase 1A SQLite schema and Agent topics`.

## Task 3: Editable Topics and Tags

**Files:**
- Create: `backend/app/repositories/taxonomy.py`
- Create: `backend/app/services/taxonomy.py`
- Create: `backend/app/api/v1/topics.py`
- Create: `backend/app/api/v1/tags.py`
- Create: `backend/tests/api/test_topics.py`
- Create: `backend/tests/api/test_tags.py`
- Create: `frontend/src/pages/TaxonomyPage.vue`
- Create: `frontend/tests/taxonomy.spec.ts`
- Modify: `frontend/src/router/index.ts`

**Interfaces:**
- Produces: `GET/POST/PATCH /api/v1/topics`, `GET/POST/PATCH /api/v1/tags`; topic JSON includes `id,parent_id,slug,name,sort_order,is_active`, tag JSON includes `id,name,is_active`.
- Invalid parent/topic/tag references return 400 with field-level errors; missing resources return 404.

- [ ] **Step 1: Write `test_topic_crud_and_reparent`, `test_topic_parent_cycle_is_rejected`, `test_tag_crud`, and `test_inactive_taxonomy_links_are_preserved`** for topic hierarchy, edits, and tag state.
- [ ] **Step 2: Run `conda activate test`, then `cd backend && pytest tests/api/test_topics.py tests/api/test_tags.py -q`; confirm they fail.**
- [ ] **Step 3: Implement repository and service functions** with parent-cycle validation and deterministic sort order; deactivation must preserve existing question links.
- [ ] **Step 4: Write `renders_taxonomy_and_submits_create_or_rename`** with mocked API calls and run `npm --prefix frontend test -- tests/taxonomy.spec.ts`; confirm it fails before the page exists.
- [ ] **Step 5: Implement the minimal taxonomy management page; run `(cd backend && pytest tests/api/test_topics.py tests/api/test_tags.py -q)` and `npm --prefix frontend test -- tests/taxonomy.spec.ts`; confirm both pass.**
- [ ] **Step 6: Commit** as `feat: add editable Agent topics and tags`.

## Task 4: Manual Question Bank, State, and Archive

**Files:**
- Create: `backend/app/repositories/questions.py`
- Create: `backend/app/services/questions.py`
- Create: `backend/app/api/v1/questions.py`
- Create: `backend/app/api/v1/question_state.py`
- Create: `backend/tests/api/test_questions.py`
- Create: `frontend/src/pages/QuestionBankPage.vue`
- Create: `frontend/src/pages/QuestionDetailPage.vue`
- Create: `frontend/src/components/QuestionForm.vue`
- Create: `frontend/src/components/TopicTagPicker.vue`
- Create: `frontend/tests/questions.spec.ts`
- Modify: `frontend/src/router/index.ts`

**Interfaces:**
- Produces: `POST/GET /api/v1/questions`, `GET/PATCH /api/v1/questions/{id}`, `POST /api/v1/questions/{id}/archive`, and `PATCH /api/v1/questions/{id}/state` for `is_favorite`/`is_wrong`.
- Question creation/edit accepts `text`, `difficulty`, `topic_ids[]`, and `tag_ids[]`; returns the persisted question and direct topic/tag associations.
- Default list only includes active questions; archived records are available through an explicit `include_archived=true` view.

- [ ] **Step 1: Write `test_question_crud_with_topics_and_tags`, `test_question_state_flags_are_independent`, `test_archive_hides_question_but_preserves_record`, and `test_invalid_question_fields_are_rejected`** for lifecycle and state rules.
- [ ] **Step 2: Run `conda activate test`, then `cd backend && pytest tests/api/test_questions.py -q`; confirm they fail.**
- [ ] **Step 3: Implement normalized text/hash generation and transactional question writes.** Keep duplicate detection and OCR-only pending-review states out of this phase; manual questions enter as active.
- [ ] **Step 4: Write `creates_edits_and_archives_question` and `renders_topic_tag_and_state_controls`** with mocked API calls; run `npm --prefix frontend test -- tests/questions.spec.ts` and confirm it fails before the pages exist.
- [ ] **Step 5: Implement the list/detail/form pages with explicit save/archive actions; run `(cd backend && pytest tests/api/test_questions.py -q)` and `npm --prefix frontend test -- tests/questions.spec.ts`; confirm both pass.**
- [ ] **Step 6: Commit** as `feat: add manual Agent question bank`.

## Task 5: Chinese and Mixed-Language Search

**Files:**
- Create: `backend/app/migrations/002_question_search.sql`
- Create: `backend/app/services/search.py`
- Create: `backend/tests/services/test_search.py`
- Modify: `backend/app/api/v1/questions.py`
- Modify: `frontend/src/pages/QuestionBankPage.vue`
- Modify: `frontend/tests/questions.spec.ts`

**Interfaces:**
- Produces: `search_questions(query: str, filters: QuestionFilters) -> list[Question]`; `GET /api/v1/questions?q=...` searches active canonical rows and combines with topic/tag/favorite/wrong filters.
- Search results use stable relevance ordering with question ID as the final tie-breaker; empty query returns the filtered list without a search join.

- [ ] **Step 1: Add fixture questions and failing tests** `test_mixed_chinese_english_queries`, `test_case_insensitive_english`, and `test_short_terms_fallback` for the required example queries and short terms; add frontend test `search_submits_query_and_renders_matches`.
- [ ] **Step 2: Run `conda activate test`, then `(cd backend && pytest tests/services/test_search.py -q)` and `npm --prefix frontend test -- tests/questions.spec.ts`; confirm they fail before indexing and search UI are implemented.**
- [ ] **Step 3: Compare SQLite FTS5 `unicode61` and `trigram` on the fixture and select the smallest implementation that returns every expected question in the top 10.** If a tokenizer is unavailable or short terms fail, add the lightest local fallback (normalized terms/substring) and keep it behind the same `search_questions` interface; do not add a vector database.
- [ ] **Step 4: Implement the FTS migration and filtered query path**; keep `normalized_text` and search index updates in the same question write transaction.
- [ ] **Step 5: Add the search field and test result rendering; after activating `test`, run `(cd backend && pytest tests/services/test_search.py -q)` and `npm --prefix frontend test -- tests/questions.spec.ts`; each fixture query must return its expected question.**
- [ ] **Step 6: Commit** as `feat: add mixed Chinese and English question search`.

## Task 6: Deterministic Practice Sessions

**Files:**
- Create: `backend/app/repositories/practice.py`
- Create: `backend/app/services/practice_selector.py`
- Create: `backend/app/api/v1/practice_sessions.py`
- Create: `backend/tests/services/test_practice_selector.py`
- Create: `backend/tests/api/test_practice_sessions.py`
- Create: `frontend/src/pages/PracticeSetupPage.vue`
- Create: `frontend/src/pages/PracticeSessionPage.vue`
- Create: `frontend/tests/practice-session.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `create_practice_session(mode: str, filters: dict, limit: int) -> PracticeSession`; `POST /api/v1/practice-sessions`; `GET /api/v1/practice-sessions/{id}`; `POST /api/v1/session-items/{id}/skip`.
- Phase 1A modes are `random`, `topic`, and `tag`; `favorite`, `wrong`, `due`, and `weak` selectors are reserved for Phase 3.
- Session creation materializes and stores ordered `SessionItem` rows; later question edits do not reorder that session.

- [ ] **Step 1: Write `test_random_uses_active_pool`, `test_topic_and_tag_filters`, `test_archived_question_is_excluded`, `test_empty_pool_returns_empty_session`, and `test_session_order_is_stored`** for selector behavior.
- [ ] **Step 2: Run `conda activate test`, then `cd backend && pytest tests/services/test_practice_selector.py -q`; confirm they fail.**
- [ ] **Step 3: Implement the selector** using SQL filters and a single in-process shuffle; persist the final item order and `selection_reason` before returning.
- [ ] **Step 4: Write `test_create_and_read_session`, `test_skip_marks_item_without_review`, and `renders_session_setup_and_question_order`.**
- [ ] **Step 5: Run `conda activate test`, then `(cd backend && pytest tests/api/test_practice_sessions.py -q)` and `npm --prefix frontend test -- tests/practice-session.spec.ts`; confirm they fail before routes/views exist.**
- [ ] **Step 6: Implement session routes and Vue setup/session views; run `(cd backend && pytest tests/services/test_practice_selector.py tests/api/test_practice_sessions.py -q)` and `npm --prefix frontend test -- tests/practice-session.spec.ts`; confirm queue order and skip behavior.**
- [ ] **Step 7: Commit** as `feat: add deterministic practice sessions`.

## Task 7: Four-Level PracticeReview Events

**Files:**
- Create: `backend/app/services/practice_review.py`
- Create: `backend/app/api/v1/practice_reviews.py`
- Create: `backend/tests/api/test_practice_reviews.py`
- Create: `frontend/src/components/PracticeRating.vue`
- Modify: `frontend/src/pages/PracticeSessionPage.vue`
- Modify: `frontend/tests/practice-session.spec.ts`

**Interfaces:**
- Produces: `record_practice_review(session_item_id: str, review_rating: str) -> PracticeReview`; `POST /api/v1/session-items/{id}/review`; `GET /api/v1/questions/{id}/practice-reviews`.
- Accepted values are exactly `dont_know`, `vague`, `basic`, and `proficient`; the UI labels are “不会、模糊、基本会、熟练”.
- Creating a review marks its SessionItem completed. No answer text or SavedAnswer is required or created; Phase 1A does not calculate `next_review_at` scheduling.

- [ ] **Step 1: Write `test_each_review_rating_is_accepted`, `test_practice_completes_without_answer`, `test_duplicate_review_is_rejected`, `test_skipped_item_cannot_be_reviewed`, and `test_archived_question_review_history_remains_readable`** for event creation, item ownership, and archived history.
- [ ] **Step 2: Run `conda activate test`, then `cd backend && pytest tests/api/test_practice_reviews.py -q`; confirm they fail.**
- [ ] **Step 3: Implement review creation in one SQLite transaction** with canonical-safe question checks already provided by the stored session item; do not add mastery scoring from answer text.
- [ ] **Step 4: Write `completion_requires_user_selected_rating`** asserting the page requires a chosen rating and submits only the review request; run `npm --prefix frontend test -- tests/practice-session.spec.ts` and confirm it fails before the control is implemented.
- [ ] **Step 5: Add the four-choice rating control and question review history panel; run `(cd backend && pytest tests/api/test_practice_reviews.py -q)` and `npm --prefix frontend test -- tests/practice-session.spec.ts`.**
- [ ] **Step 6: Commit** as `feat: record four-level practice reviews`.

## Task 8: Phase 1A Acceptance and Runbook

**Files:**
- Create: `README.md`
- Create: `backend/tests/api/test_phase_1a_flow.py`
- Modify: `backend/app/__init__.py`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Produces: a local runbook, production static serving when a Vite build exists, and one end-to-end API acceptance path for question creation through review history.

- [ ] **Step 1: Write `test_phase_1a_question_to_review_flow`** that creates a question, assigns Topic/Tag, finds it by mixed-language search, creates a practice session, records a review without a SavedAnswer, and reads it back from question review history.
- [ ] **Step 2: Run `conda activate test`, then `cd backend && pytest tests/api/test_phase_1a_flow.py -q`; confirm it exposes any missing integration.**
- [ ] **Step 3: Add the minimal production static-file fallback and consistent error responses** without changing the development Vite proxy.
- [ ] **Step 4: Document setup and run commands**: activate Conda `test`, install backend requirements, install frontend dependencies, start Flask and Vite separately, and build the Vue client. State that product data lives in the platform application-data directory, not in the repository.
- [ ] **Step 5: Run `conda activate test`, then `(cd backend && pytest -q)` and `npm --prefix frontend test`; verify the acceptance path against a fresh temporary database.**
- [ ] **Step 6: Commit** as `docs: document local Phase 1A setup and acceptance`.

## Scope Boundary

Phase 1A ends with a usable manually maintained Agent question bank and basic practice history. Screenshot ingestion/OCR, smart import and duplicate merge, SavedAnswer history/ratings, review scheduling and weak-item queues, Project/Material context, and LLM features remain in their later spec phases.

## Plan Self-Review

- **Spec coverage:** Tasks 1–8 cover the Phase 0 skeleton and Phase 1A requirements: local Flask/Vue operation, SQLite, initial editable Agent Topics, Tag management, manual question lifecycle, mixed-language search, favorite/wrong state, deterministic random/topic/tag practice, and independent four-level PracticeReview events. Later phases are explicitly excluded.
- **Step scan:** Each task has focused failing tests, a minimal implementation, passing verification, and a task-level Git commit. No worker, OCR, SavedAnswer, LLM, or generalized evaluation system is introduced.
- **Type consistency:** `SessionItem.id` is passed to `record_practice_review`; topic/tag selectors pass IDs; route names and payloads use the same `review_rating` enum as the spec.
- **Review Focus:** The five cases above map to Tasks 3–7; archive visibility is checked in both question listing and selector tests.
- **Proportion:** The plan covers one runnable first slice and keeps all future subsystems outside this implementation plan.

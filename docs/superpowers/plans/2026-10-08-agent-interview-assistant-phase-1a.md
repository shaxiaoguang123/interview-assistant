# Agent Interview Assistant Phase 0 and 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently runnable local Flask/Vue application and the Phase 1A Agent question bank, so the user can manage Agent topics, enter and search questions, mark favorites/wrong questions, practice by rules, and retain practice history.

**Architecture:** Flask app factory with thin versioned API blueprints; SQLAlchemy 2.x models, sessions, and repositories; Alembic migrations; business validation and state transitions in focused services. Vue 3 + TypeScript + Vite remains a separate development client, with API proxying in development and Flask static serving for a production build. Practice selectors use program rules, and each created session persists its final `SessionItem` order.

**Tech Stack:** Python, Flask, SQLAlchemy 2.x, Alembic, SQLite, pytest, Vue 3, TypeScript, Vite, Vitest, native browser `fetch`.

**Spec:** `docs/superpowers/specs/2026-10-08-agent-interview-assistant-design.md` (Phase 0 and Phase 1A only)

## Global Constraints

- 首版按个人使用设计，不做账号、多人协作、云同步。
- Flask 提供 REST API；Vue 3 + TypeScript + Vite 是独立前端，开发时通过 Vite 代理 API，发布时可由 Flask 同源提供静态文件。
- 使用 SQLAlchemy 2.x + Alembic + SQLite；Alembic 是正式 schema migration，不维护自定义 migration runner。
- `db.py` 仅负责 SQLAlchemy Base、engine、request-scoped Session 初始化；Model 定义表和约束，Repository 负责持久化查询，Service 负责业务规则，API 不承载复杂数据库逻辑。
- 不引入 BaseRepository、DDD、通用 Unit of Work、微服务、Redis/Celery、认证服务、向量数据库或复杂后台任务。
- 测试使用独立临时 SQLite 数据库，不访问默认应用数据目录或用户真实数据库；运行本地产品前先执行 Alembic upgrade。
- PracticeSession 选题由规则驱动，不由 LLM 决定；Phase 1A 不包含任何 LLM/OCR/SavedAnswer 业务入口。
- PracticeReview 是题目掌握程度的事实记录；Phase 1A 不计算 `next_review_at`、不运行弱项算法。
- Question `status` 表示业务生命周期；`archived_at` 是独立归档维度，归档不改变 `status`。
- 新题和新 Session 只使用 `status=active AND archived_at IS NULL` 的 Question；后续 Phase 1C 增加合并后，再加 `merged_into_question_id IS NULL` 条件。
- 当前开发环境按 `AGENTS.md` 使用 Conda `test`；此约定不成为产品永久运行要求，也不把 macOS 写成产品限制。
- 在本机 zsh 中调用 Python 前，若 `conda activate` 提示需初始化，只在该命令进程执行 `source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate test`；不要运行 `conda init` 或修改用户 Shell 配置。

## Review Focus

- **SQLite/Alembic 初始化：**空库可升级、foreign keys 开启、测试库与真实数据目录隔离、seed 可重复执行；Task 2 覆盖。
- **输入边界和统一错误：**无效 Host/Origin、题目字段校验、inactive taxonomy、重复 Review 都使用稳定错误 envelope；Tasks 1、3、4、6、7 覆盖。
- **归档后历史：**归档题目不进入新列表/搜索/Session，但已有 SessionItem/Review 保留且可继续完成；Tasks 4、6、7 覆盖。
- **练习状态转换：**review 与 skip 互斥；终态不可逆；最后一个 item 终结时 Session 原子完成；Tasks 6、7 覆盖。
- **混合语言搜索：**中文、英文、短技术词、组合筛选可搜到目标且无 join 重复；Task 5 覆盖。

---

## File Structure

```text
backend/
  app/
    __init__.py                 # create_app、blueprint、error handler 注册
    config.py                   # 本地数据目录、数据库 URL、允许的本机 Origin
    db.py                       # Declarative Base、engine、Session 初始化/销毁
    errors.py                   # API 错误类型和统一响应格式
    local_security.py           # loopback Host/Origin 校验
    models/
      taxonomy.py               # Topic、Tag 和关联
      question.py               # Question、QuestionState 和关联
      practice.py               # PracticeSession、SessionItem、PracticeReview
    repositories/               # 只封装 SQLAlchemy 持久化查询
    services/                   # taxonomy、question、search、selector、review 业务规则
    api/v1/                     # health、topics、tags、questions、practice 路由
  migrations/
    env.py
    versions/                   # Alembic revisions；FTS 必要 SQL 也放这里
  alembic.ini
  tests/
    conftest.py                 # 临时 SQLite、Alembic upgrade、Flask client
    api/
    services/
    test_migrations.py
  requirements.txt
  run.py
frontend/
  src/
    api/client.ts               # ApiError、fetch 封装
    router/index.ts
    pages/                      # Question Bank、详情、taxonomy、练习设置/会话
    components/                 # QuestionForm、TopicTagPicker、PracticeRating
    types/
  tests/
  package.json
  vite.config.ts
README.md                       # Conda test、Alembic、前后端本机启动说明
```

不要增加通用 repository/base class、worker、event bus、前端状态管理框架或 Phase 1A 不使用的业务模块。

## Task 1: Local App Skeleton and Error Contract

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/app/errors.py`
- Create: `backend/app/local_security.py`
- Create: `backend/app/api/v1/health.py`
- Create: `backend/run.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/api/test_health.py`
- Create: `backend/tests/test_errors.py`
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
- Create: `frontend/tests/api-client.spec.ts`

**Interfaces:**
- `create_app(test_config: dict | None = None) -> Flask` creates no business tables. `init_db(app) -> None` creates a SQLAlchemy 2.x engine and request-scoped Session factory; it does not call `create_all()`. `get_session() -> Session` reuses the request Session from Flask `g`; teardown closes it and rolls back any uncommitted transaction.
- `backend/requirements.txt` uses `Flask>=3.1,<4`, `SQLAlchemy>=2.0,<3`, `alembic>=1.13,<2`, `platformdirs>=4,<5`, and `pytest>=9,<10`; do not add Flask-SQLAlchemy or a second database layer.
- `GET /api/v1/health -> {"status":"ok"}`.
- API errors always use `{"error":{"code":"...","message":"...","fields":{...}}}`; `fields` may be empty/omitted. Supported mappings: 400 `VALIDATION_ERROR`, 404 `NOT_FOUND`, 409 `CONFLICT`, 413 `PAYLOAD_TOO_LARGE`, 500 `INTERNAL_ERROR`.
- Backend `ApiError(status_code: int, code: str, message: str, fields: dict | None = None)` is the one application exception type. Frontend exports `ApiError` with `code`, `message`, optional `fields`, and `request<T>(path: string, init?: RequestInit) -> Promise<T>`; all requests use it for non-2xx responses.
- Server binds to loopback. Host accepts `localhost`, `127.0.0.1`, and `::1`; a missing Origin is allowed. A present Origin is allowed only if it matches the request's same-origin local address or an exact configurable `ALLOWED_ORIGINS` entry. The guard does not hardcode the Vite port; development origins are configuration values.
- Default application data directory uses `platformdirs`; `DATABASE_URL` resolves into that directory. Tests inject their own `DATABASE_URL` under pytest `tmp_path`, assert it differs from the configured user-data path, and disable startup seeding until the migration fixture exists.

- [ ] **Step 1: Write failing tests** `test_health_returns_ok`, `test_404_uses_error_envelope`, `test_409_413_and_500_use_error_envelope`, `test_non_local_host_is_rejected_with_error_envelope`, `test_no_origin_localhost_is_allowed`, `test_same_origin_local_request_is_allowed`, `test_configured_local_origin_is_allowed`, `test_ipv6_loopback_host_is_allowed`, `test_external_origin_is_rejected_with_error_envelope`, plus frontend `parses_api_error_code_message_and_fields` and `renders_app_title_and_health`. Add minimal test-runner config and `requirements.txt`/`package.json` dependencies (`@vue/test-utils`, `jsdom`, Vitest).
- [ ] **Step 2: Run RED.** Activate `test`, install `backend/requirements.txt`, run `npm --prefix frontend install`, then run `(cd backend && pytest tests/api/test_health.py tests/test_errors.py tests/test_local_security.py -q)` and `npm --prefix frontend test -- tests/health.spec.ts tests/api-client.spec.ts`; confirm the missing route/handlers/client parsing cause failure.
- [ ] **Step 3: Implement the Flask app factory, SQLAlchemy engine/Session initialization without schema creation, health route, common `ApiError` handlers, and loopback/Host/Origin checks.** Configure `DATABASE_URL`, default user-data directory, and `ALLOWED_ORIGINS`; do not put a development port in the Host/Origin guard. An invalid Host/Origin returns a standard 400 `VALIDATION_ERROR`; missing Origin remains valid for curl, pytest, and local tools. Do not expose exception details in 500 responses.
- [ ] **Step 4: Implement the Vue/Vite/TypeScript/Vitest shell, `test: vitest run` script, native fetch client, and `/api` proxy.** The prior dependency-install step creates `package-lock.json`.
- [ ] **Step 5: Run the focused tests and the complete current backend/frontend suites** (`(cd backend && pytest -q)` and `npm --prefix frontend test`); confirm health, error envelope, security boundary, and ApiError parsing pass.
- [ ] **Step 6: Commit** as `chore: scaffold local Flask and Vue app`.

## Task 2: SQLAlchemy Models, Alembic, and Initial Agent Topics

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/taxonomy.py`
- Create: `backend/app/models/question.py`
- Create: `backend/app/models/practice.py`
- Create: `backend/app/services/topic_seed.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_phase1a_core.py`
- Create: `backend/tests/test_migrations.py`
- Create: `backend/tests/test_models.py`
- Create: `backend/tests/test_topic_seed.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/__init__.py`
- Modify: `backend/app/db.py`

**Interfaces:**
- SQLAlchemy 2.x declarative models use `Mapped`/`mapped_column`; Alembic is the only schema migration path. No custom migration runner and no `metadata.create_all()`.
- Models: `Topic`, `Tag`, `Question`, `QuestionTopic`, `QuestionTag`, `QuestionState`, `PracticeSession`, `SessionItem`, `PracticeReview`.
- `Topic`: `id`, `track_key`, nullable `parent_id`, unique `slug`, `name`, `sort_order`, `is_active`, `created_at`, `updated_at`. `Tag`: `id`, unique `name`, `is_active`, timestamps.
- `Question`: `id`, `text`, `normalized_text`, `search_text`, indexed non-unique `normalized_hash`, nullable `answer_type`, nullable `difficulty`, `status`, nullable `archived_at`, timestamps. Initially `search_text=normalized_text`; FTS indexes `search_text`. Phase 1A does not add screenshot suggestion fields or merge pointers.
- `QuestionTopic` and `QuestionTag` use composite primary keys and restrictive foreign keys. `QuestionState` is one row per Question with `is_favorite`, `is_wrong`, `user_note`, and `updated_at`.
- `PracticeSession`: `id`, `mode`, `filters_json`, `selector_version`, nullable `selection_seed`, `started_at`, nullable `completed_at`. `SessionItem`: `id`, `session_id`, `question_id`, 1-based `ordinal`, `status`, `selection_reason`, `viewed_at`, nullable `completed_at`, unique `(session_id, ordinal)` and `(session_id, question_id)`. `PracticeReview`: `id`, `question_id`, unique `session_item_id`, `review_rating`, `reviewed_at`, `created_at`, `updated_at`.
- `Question.status` is constrained to `pending_review|active|merged`; Phase 1A manual questions default to `active`. `archived_at` is nullable and independent of `status`; archive never adds an `archived` status value.
- Every field-validation failure, including an unknown/inactive taxonomy ID, uses the single 400 code `VALIDATION_ERROR`; the specific field name and reason go in `error.fields` (do not create a second `FIELD_VALIDATION_ERROR` code).
- `normalized_hash` has a normal non-unique index. Duplicate hashes are allowed.
- `SessionItem.status` is constrained to `shown|completed|skipped`; `completed` and `skipped` are terminal. `PracticeReview.session_item_id` has a unique constraint.
- `PracticeReview` stores immutable `question_id`, `session_item_id`, `review_rating`, `reviewed_at`, `created_at`, and mutable `updated_at`.
- SQLite engine connect event runs `PRAGMA foreign_keys=ON` for every connection.
- `alembic.ini`/`migrations/env.py` read the configured `DATABASE_URL`; Alembic upgrades an empty test database without invoking `create_all()`.
- After Alembic upgrade, normal app startup idempotently seeds Topics by stable unique `slug`; insert missing rows only and never overwrite user edits. Health-only tests set `SEED_TOPICS_ON_STARTUP=False` because they intentionally have no business schema.

- [ ] **Step 1: Write failing tests** `test_alembic_upgrades_empty_database_to_head`, `test_test_database_is_outside_real_data_directory`, `test_sqlite_foreign_keys_are_enabled`, `test_sqlite_rejects_foreign_key_violation`, `test_duplicate_normalized_hash_is_allowed`, `test_normalized_hash_index_is_not_unique`, and `test_initial_topic_seed_is_idempotent_across_app_restarts`.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/test_migrations.py tests/test_models.py tests/test_topic_seed.py -q)`; confirm missing models/revisions/seed behavior fail.
- [ ] **Step 3: Implement SQLAlchemy models and `db.py` engine/session setup.** Keep Phase 1A QuestionState to `is_favorite`, `is_wrong`, and `user_note`; do not implement `next_review_at` scheduling fields/logic in this phase. Set `SEED_TOPICS_ON_STARTUP=True` after migrations are installed; `create_app` test configs can disable it before the schema exists.
- [ ] **Step 4: Create Alembic `env.py` and the initial revision.** `config.py` exposes the same `DATABASE_URL` resolver to Flask and Alembic; tests override the Alembic URL to a fresh `tmp_path`. The revision creates the listed models, foreign keys, status checks, unique `slug`, unique `SessionItem` Review, ordinary `normalized_hash` index, and other lookup indexes. It must not add `UNIQUE(normalized_hash)`.
- [ ] **Step 5: Implement the idempotent Agent topic seed.** Seed the editable tree: LLM basics, Prompt, Structured Output, Context Engineering, Function Calling/Tool Use, MCP, RAG, Memory, LangChain, LangGraph, Multi-Agent, Agent Design Patterns (ReAct, Plan-and-Execute, Reflection, Router, Supervisor, Workflow vs Agent, Human-in-the-loop), Agent Evaluation, Observability, Agent Security, deployment, Python/backend, and project practice. Use stable slugs and preserve changed names on later starts.
- [ ] **Step 6: Run focused migration/model/seed tests and the complete backend/frontend suites** (`(cd backend && pytest -q)` and `npm --prefix frontend test`) against fresh `tmp_path` databases; verify Alembic upgrade from empty, FK violation rejection, duplicate hash acceptance, and repeated app creation without duplicate Topic rows.
- [ ] **Step 7: Commit** as `feat: add SQLAlchemy models and Alembic core schema`.

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
- `GET/POST/PATCH /api/v1/topics` and `GET/POST/PATCH /api/v1/tags`; request failures reuse Task 1 error envelope.
- `validate_active_topic_ids(session, ids) -> list[Topic]` and `validate_active_tag_ids(session, ids) -> list[Tag]` reject unknown or inactive IDs with 400 `VALIDATION_ERROR` and `error.fields` (the single standard validation code).
- Deactivation only sets `is_active=false`; it never deletes QuestionTopic/QuestionTag links. Existing detail views display inactive links with an inactive marker.

- [ ] **Step 1: Write failing tests** `test_topic_crud_and_reparent`, `test_topic_parent_cycle_is_rejected`, `test_tag_crud`, `test_deactivating_topic_preserves_existing_question_links`, `test_deactivating_tag_preserves_existing_question_links`, and service tests for unknown/inactive ID validation.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/api/test_topics.py tests/api/test_tags.py -q)`; confirm expected routes/services are absent.
- [ ] **Step 3: Implement focused SQLAlchemy repositories and taxonomy services.** Validate parent existence and prevent cycles; use transactions; preserve linked Question taxonomy rows when deactivated.
- [ ] **Step 4: Write frontend test** `renders_taxonomy_and_marks_inactive_entries`; run `npm --prefix frontend test -- tests/taxonomy.spec.ts` and confirm it fails before the page exists.
- [ ] **Step 5: Implement the minimal taxonomy management page.** Run focused tests plus the complete backend/frontend suites (`(cd backend && pytest -q)` and `npm --prefix frontend test`); verify inactive entries remain visible and marked.
- [ ] **Step 6: Commit** as `feat: add editable Agent topics and tags`.

## Task 4: Manual Question Bank, Validation, State, and Archive

**Files:**
- Create: `backend/app/repositories/questions.py`
- Create: `backend/app/services/questions.py`
- Create: `backend/app/api/v1/questions.py`
- Create: `backend/tests/api/test_questions.py`
- Create: `backend/tests/services/test_question_text.py`
- Create: `frontend/src/pages/QuestionBankPage.vue`
- Create: `frontend/src/pages/QuestionDetailPage.vue`
- Create: `frontend/src/components/QuestionForm.vue`
- Create: `frontend/src/components/TopicTagPicker.vue`
- Create: `frontend/tests/questions.spec.ts`
- Modify: `frontend/src/router/index.ts`

**Interfaces:**
- `POST/GET /api/v1/questions`, `GET/PATCH /api/v1/questions/{id}`, `POST /api/v1/questions/{id}/archive`, and `PATCH /api/v1/questions/{id}/state` for `is_favorite`/`is_wrong`.
- Create accepts `text`, nullable `answer_type`/`difficulty`, `topic_ids[]`, and `tag_ids[]`; patch is partial and only replaces topic/tag links when the corresponding array is supplied.
- `MAX_QUESTION_TEXT_LENGTH = 10_000` is the single validation constant. Store `Question.text = input.strip()`; reject blank/whitespace-only text and values over the limit with 400 `VALIDATION_ERROR` and `error.fields.text`.
- `normalized_text` is a separate search/hash field built with Unicode NFKC, case normalization, whitespace folding, and a small common punctuation map. `search_text` is initially set to `normalized_text`. Preserve technical punctuation and meaning (`C++`, `C#`, `GPT-4.1`, `LangGraph`, `MCP`, `Function Calling`). `Question.text` is never replaced with normalized text.
- PATCH is partial: omitted `topic_ids`/`tag_ids` retain current associations; a supplied array replaces that relation set and every submitted ID must exist and be active. Inactive existing associations remain stored/displayed until the user explicitly removes or replaces them.
- Archive sets `archived_at` only; it does not change `status`, delete relations, SessionItems, or Reviews. No restore endpoint in Phase 1A.
- Default GET/list filters `status=active AND archived_at IS NULL`; `include_archived=true` exposes archived active questions. Direct history/detail lookup by ID remains possible for archived questions.

- [ ] **Step 1: Write failing tests** `test_question_crud_with_topics_and_tags`, `test_question_rejects_unknown_topic_id`, `test_question_rejects_inactive_topic_id`, `test_question_rejects_unknown_tag_id`, `test_question_rejects_inactive_tag_id`, `test_archive_hides_question_but_preserves_record`, `test_manual_question_defaults_active_and_unarchived`, and text tests for empty, spaces, limit, valid Chinese/English, trim-only storage, normalized/raw separation, and technical punctuation.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/api/test_questions.py tests/services/test_question_text.py -q)`; confirm validation/lifecycle behavior is missing.
- [ ] **Step 3: Implement question normalization and services.** Use one shared 10,000-character constant; calculate SHA-256 of `normalized_text`; keep `normalized_hash` non-unique; reject unknown/inactive taxonomy IDs; preserve existing links omitted from PATCH.
- [ ] **Step 4: Implement question repository/API CRUD, `QuestionState` updates, and archive.** Default list filters must apply consistently to list, topic/tag filters, and future search. Archive must only set `archived_at`.
- [ ] **Step 5: Write frontend tests** `creates_edits_and_archives_question`, `renders_inactive_taxonomy_links`, and `renders_question_validation_errors`; run `npm --prefix frontend test -- tests/questions.spec.ts` and confirm RED.
- [ ] **Step 6: Implement list/detail/form views.** Show inactive existing taxonomy clearly; do not silently resubmit inactive IDs. Run focused tests plus the complete backend/frontend suites (`(cd backend && pytest -q)` and `npm --prefix frontend test`); confirm tests pass.
- [ ] **Step 7: Commit** as `feat: add manual Agent question bank`.

## Task 5: FTS5 Chinese and Mixed-Language Search

**Files:**
- Create: `backend/migrations/versions/0002_question_search.py`
- Create: `backend/app/services/search.py`
- Create: `backend/tests/services/test_search.py`
- Modify: `backend/app/api/v1/questions.py`
- Modify: `frontend/src/pages/QuestionBankPage.vue`
- Modify: `frontend/tests/questions.spec.ts`

**Interfaces:**
- `search_questions(session, query, filters) -> list[Question]` and `GET /api/v1/questions?q=...` combine text, Topic, Tag, favorite, wrong, and archive filters.
- Multiple IDs within Topic or Tag use OR; Topic filters, Tag filters, text query, favorite, and wrong conditions combine with AND. Unknown/inactive IDs return 400 rather than silently producing no rows.
- Search returns distinct Question rows, ordered by relevance then stable question ID. Empty `q` returns the filtered list.
- Alembic creates the SQLite FTS5 `unicode61` table/triggers using raw SQL. The planned substring fallback remains active for CJK and short ASCII terms such as `MCP`/`RAG`, so short-term search does not depend on trigram support. No ORM abstraction for FTS; FTS5 unavailability is an actionable migration failure, never a silently disabled search feature.

- [ ] **Step 1: Add fixture questions and failing tests** `test_mixed_chinese_english_queries`, `test_case_insensitive_english`, `test_mcp_and_rag_short_term_fallback`, `test_short_term_fallback_does_not_require_trigram`, `test_archived_question_excluded_by_default_search`, `test_topic_tag_favorite_wrong_filters_combine_with_query`, `test_inactive_or_unknown_search_filter_is_rejected`, and `test_many_to_many_filters_do_not_duplicate_question`.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/services/test_search.py -q)`; run `npm --prefix frontend test -- tests/questions.spec.ts`; confirm the search cases fail before implementation.
- [ ] **Step 3: Probe SQLite FTS5 `unicode61`, `trigram`, and normalized substring fallback against the fixture.** Select the smallest path that finds every expected question in the top 10, including `LangGraph 持久化`, `MCP 通信协议`, `Function Calling`, `RAG 检索重排`, `MCP`, and `RAG`. Keep the short-term/CJK substring fallback regardless of trigram availability; do not skip search tests or add an external search service.
- [ ] **Step 4: Implement Alembic FTS5 SQL and search service.** Keep index writes synchronized transactionally (FTS triggers are acceptable); use the chosen tokenizer for normal terms and substring matching for CJK/short terms; use `EXISTS` or `DISTINCT` to prevent many-to-many duplicate rows; apply archive and taxonomy filters to every search path.
- [ ] **Step 5: Add the search input/result state to QuestionBankPage.** Run focused tests plus the complete backend/frontend suites (`(cd backend && pytest -q)` and `npm --prefix frontend test`); all example terms, filter combinations, archive exclusion, and deduplication must pass.
- [ ] **Step 6: Commit** as `feat: add mixed Chinese and English question search`.

## Task 6: Rule-Based Practice Sessions and Skip Lifecycle

**Files:**
- Create: `backend/app/repositories/practice.py`
- Create: `backend/app/services/practice_selector.py`
- Create: `backend/app/services/practice_session.py`
- Create: `backend/app/api/v1/practice_sessions.py`
- Create: `backend/tests/services/test_practice_selector.py`
- Create: `backend/tests/api/test_practice_sessions.py`
- Create: `frontend/src/pages/PracticeSetupPage.vue`
- Create: `frontend/src/pages/PracticeSessionPage.vue`
- Create: `frontend/tests/practice-session.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- `create_practice_session(session, mode, filters, limit, selection_seed=None) -> PracticeSession`; `POST /api/v1/practice-sessions`; `GET /api/v1/practice-sessions/{id}`; `POST /api/v1/session-items/{id}/skip`.
- Modes are exactly `random`, `topic`, `tag`. Unknown mode, invalid `limit`, missing mode filter, and unknown/inactive Topic/Tag return 400 `VALIDATION_ERROR` with field errors. `limit` defaults to 10 and must be 1–100.
- `topic` requires one or more active `topic_ids`; `tag` requires one or more active `tag_ids`. A valid filter with zero candidate questions returns a completed empty `PracticeSession` with `items=[]`, not a validation error.
- Multiple IDs within the selected Topic or Tag mode match any selected ID (OR); invalid/inactive IDs are validated before candidate queries and cannot become an empty Session.
- New-session candidates require `status=active AND archived_at IS NULL`; Phase 1C will add `merged_into_question_id IS NULL`. Every candidate Question appears at most once.
- Random mode generates a 32-bit `selection_seed` when absent; request-supplied seeds must be integers in `[0, 2^32-1]`. Persist `selector_version="v1"`, seed, final ordered 1-based `SessionItem.ordinal`, and `selection_reason`. Stable hash ordering sorts SHA-256 of `f"{selector_version}:{selection_seed}:{question_id}"`, so the same candidate IDs/version/seed replay the same order; different seeds can produce different order. Topic/tag modes use stable ID order and null seed unless an explicit future shuffle is added.
- `SessionItem` starts `shown`; skip transaction permits only shown → skipped, sets `completed_at`, checks session terminal state, and returns 409 for terminal/repeated transitions.
- Once created, SessionItem order and question IDs never change. GET of an existing session includes archived Questions for those items; archiving a Question only excludes it from new sessions.
- Session `completed_at` is set when all items are completed/skipped; empty sessions are complete at creation. A session with any `shown` item remains incomplete and can be reopened after application restart.

- [ ] **Step 1: Write failing selector tests** `test_same_seed_replays_same_random_order`, `test_different_seed_can_change_random_order`, `test_invalid_seed_is_rejected`, `test_topic_and_tag_filters`, `test_invalid_selector_mode_is_rejected`, `test_topic_selector_rejects_unknown_topic`, `test_topic_selector_rejects_inactive_topic`, `test_tag_selector_rejects_unknown_tag`, `test_tag_selector_rejects_inactive_tag`, `test_limit_is_validated`, `test_empty_pool_returns_completed_empty_session`, `test_random_session_has_no_duplicate_question`, and `test_archived_question_is_excluded_from_new_session`.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/services/test_practice_selector.py -q)`; confirm selectors and validation are missing.
- [ ] **Step 3: Implement the rule-based selector.** Validate inputs before querying candidates, never convert invalid IDs into an empty pool, and persist the final SessionItem order in one transaction. Selection has no LLM dependency or next-question API.
- [ ] **Step 4: Write failing tests** `test_create_and_read_session`, `test_open_session_can_resume_after_app_restart`, `test_created_order_survives_question_edit`, `test_archived_question_remains_in_existing_session`, `test_skip_marks_item_without_review`, `test_last_skip_completes_session`, `test_session_with_shown_item_stays_incomplete`, `test_skipped_item_cannot_be_skipped_again`, and frontend `renders_session_setup_and_question_order`.
- [ ] **Step 5: Run RED.** Activate `test`, then `(cd backend && pytest tests/api/test_practice_sessions.py -q)` and `npm --prefix frontend test -- tests/practice-session.spec.ts`; confirm lifecycle tests and view test fail before routes/views exist.
- [ ] **Step 6: Implement `skip_session_item` in one SQLAlchemy transaction** and the Vue setup/session views. Retrieval of an old Session must not re-filter its items by current Question archive state.
- [ ] **Step 7: Run focused tests and the complete backend/frontend suites** (`(cd backend && pytest -q)` and `npm --prefix frontend test`); confirm selection replay, validation, fixed ordering, archive behavior, and skip lifecycle pass.
- [ ] **Step 8: Commit** as `feat: add rule-based practice sessions`.

## Task 7: Atomic PracticeReview Creation, Correction, and Session Completion

**Files:**
- Create: `backend/app/services/practice_review.py`
- Create: `backend/app/api/v1/practice_reviews.py`
- Create: `backend/tests/api/test_practice_reviews.py`
- Create: `backend/tests/services/test_practice_review.py`
- Create: `frontend/src/components/PracticeRating.vue`
- Modify: `backend/app/services/practice_session.py`
- Modify: `backend/app/api/v1/practice_sessions.py`
- Modify: `frontend/src/pages/PracticeSessionPage.vue`
- Modify: `frontend/tests/practice-session.spec.ts`

**Interfaces:**
- `POST /api/v1/session-items/{id}/review` accepts exactly `review_rating` in `dont_know|vague|basic|proficient`.
- `PATCH /api/v1/practice-reviews/{id}` accepts only `review_rating`; it may not change `question_id`, `session_item_id`, `reviewed_at`, or `created_at`. It updates `updated_at` only when rating changes.
- `GET /api/v1/questions/{id}/practice-reviews` returns history, including for archived Questions.
- Review creation uses one SQLAlchemy transaction: fetch the SessionItem and Session; 404 if missing; 409 if skipped, already completed, Session is completed, or Review already exists; validate rating; set item completed and timestamp; insert Review; set `PracticeSession.completed_at` iff all items are terminal; commit. Any failure rolls back all state changes. Do not rely on SQLite `SELECT FOR UPDATE`; the unique SessionItem constraint protects duplicate Reviews.
- Skip and Review are mutually exclusive; completed/skipped are terminal. The Session is never completed by page exit.
- Phase 1A never stores an answer body or infers mastery from text; no SavedAnswer endpoint/model is added.
- Review row preserves `reviewed_at` and `created_at`; PATCH changes only `review_rating` and `updated_at`. No `next_review_at` exists/is computed in Phase 1A.

- [ ] **Step 1: Write failing tests** `test_each_review_rating_is_accepted`, `test_practice_completes_without_answer`, `test_invalid_rating_returns_400`, `test_missing_review_returns_404`, `test_duplicate_review_returns_409`, `test_skipped_item_cannot_be_reviewed`, `test_completed_item_cannot_be_reviewed_again`, `test_completed_item_cannot_be_skipped`, `test_review_insert_failure_rolls_back_item_completion`, `test_last_review_completes_session`, `test_review_with_shown_item_keeps_session_incomplete`, `test_archived_question_in_existing_session_can_be_reviewed`, `test_patch_changes_rating_without_new_review`, `test_patch_rejects_immutable_fields`, `test_patch_does_not_change_question_session_or_reviewed_time`, and `test_review_history_returns_updated_rating`.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/api/test_practice_reviews.py tests/services/test_practice_review.py -q)`; confirm endpoints and atomic lifecycle are missing.
- [ ] **Step 3: Implement `record_practice_review` using one `Session.begin()` transaction.** Validate before writes; rely on the unique SessionItem constraint for duplicate races; map `IntegrityError` to 409 `CONFLICT`; update Session completion in the same transaction after flush; let exceptions roll back item, Review, and Session together.
- [ ] **Step 4: Implement PATCH and history routes.** Reject extra immutable fields with 400; return 404 for an unknown Review; preserve `created_at`, `reviewed_at`, `question_id`, and `session_item_id`; update `updated_at`; do not create another Review or scheduling state.
- [ ] **Step 5: Write frontend test** `completion_requires_user_selected_rating_and_sends_review_only`; run `npm --prefix frontend test -- tests/practice-session.spec.ts` and confirm RED.
- [ ] **Step 6: Add four rating choices and the question review history panel.** A click submits only the review request; no answer save call exists.
- [ ] **Step 7: Run focused tests and the complete backend/frontend suites** (`(cd backend && pytest -q)` and `npm --prefix frontend test`); confirm creation, rollback, terminal transitions, PATCH, and history pass.
- [ ] **Step 8: Commit** as `feat: add atomic practice review lifecycle`.

## Task 8: Phase 1A Acceptance, Production Static Serving, and Runbook

**Files:**
- Create: `README.md`
- Create: `backend/tests/api/test_phase_1a_flow.py`
- Create: `backend/tests/test_error_contract.py`
- Modify: `backend/app/__init__.py`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Production Flask serves the built Vue app when `frontend/dist` exists; development remains Vite + `/api` proxy.
- The full acceptance flow runs against a fresh temporary SQLite database after Alembic upgrade; it never reads or writes the real application-data directory.
- App-wide errors preserve the Task 1 envelope; Task 8 verifies consistency and does not introduce a second error implementation.

- [ ] **Step 1: Write `test_phase_1a_question_to_review_flow`**: create Question, assign active Topic/Tag, search it, toggle favorite/wrong, create random/topic/tag sessions, record a Review without answer text, and read Review history. Add tests for archive/search/session integration and the single error envelope.
- [ ] **Step 2: Run RED.** Activate `test`, then `(cd backend && pytest tests/api/test_phase_1a_flow.py tests/test_error_contract.py -q)`; confirm the missing end-to-end/static/error-contract cases fail.
- [ ] **Step 3: Implement only production static-file fallback and any cross-task wiring required by the acceptance path.** Do not add OCR, answer storage, due scheduling, or other later-phase behavior.
- [ ] **Step 4: Write the runbook** with: activate Conda `test`; install backend requirements; run `alembic upgrade head`; start Flask bound to `127.0.0.1`; configure `APP_ALLOWED_ORIGINS` for the local Vite origin (same-origin production requests are allowed); install/build/start the Vue client; explain persistent platform application-data storage and test DB isolation.
- [ ] **Step 5: Run fresh-database migration and acceptance tests.** Run `conda activate test`, then `(cd backend && pytest -q)`; run `npm --prefix frontend test` and `npm --prefix frontend run build`; perform the documented fresh temporary DB flow and verify production static serving from the resulting `frontend/dist`.
- [ ] **Step 6: Commit** as `docs: document local Phase 1A setup and acceptance`.

## Phase 1A Invariants / Acceptance Rules

1. Manually created Question defaults to `status=active` and `archived_at=NULL`.
2. Archived Question is absent from default list, default search, taxonomy-filter results, and every new PracticeSession.
3. Archive does not delete historical SessionItem or PracticeReview.
4. If a Question is archived after a Session is created, it remains visible in that existing Session and may still be reviewed/skipped there.
5. `normalized_hash` is indexed but not unique; duplicate hashes can be stored. Phase 1A does not create duplicate candidates or merge questions.
6. Inactive Topic/Tag cannot be attached to a new/updated Question relation.
7. Deactivating Topic/Tag preserves existing QuestionTopic/QuestionTag links and displays them as inactive.
8. OCR, VLM, SavedAnswer, answer versions, answer ratings, LLM, and merge workflows do not exist in Phase 1A business/API flow.
9. Session item order is persisted at creation and is not changed by later Question edits/archives.
10. In random mode, same candidate IDs + `selector_version` + seed replay the same order; seed is returned/stored.
11. Skipped SessionItem cannot create PracticeReview.
12. Each SessionItem has at most one PracticeReview.
13. Review creation and transition to `completed` occur in the same database transaction; failure leaves the item unchanged.
14. Session becomes complete iff every SessionItem is `completed` or `skipped`; remaining `shown` items keep `completed_at=NULL`.
15. PATCH Review corrects one `review_rating`; it never inserts a second Review.
16. Phase 1A does not infer mastery from answer text or require answer text.
17. Favorite and wrong are QuestionState flags; they do not alter PracticeReview or due scheduling.
18. Search never returns a Question twice because of Topic/Tag many-to-many joins.
19. All API errors use the shared `error.code/message/fields` envelope.
20. Test config always uses a temporary database and cannot reach the user's real application-data directory.

## Scope Boundary

Phase 1A includes only:

- Local Flask/Vue skeleton, SQLAlchemy 2.x, Alembic, SQLite, and local application-data storage.
- Editable Agent Topic/Tag.
- Manual Question create/edit/list/detail/archive, normalized text/hash, favorite/wrong flags.
- SQLite FTS5 mixed Chinese/English search with the planned short-term fallback.
- Rule-based random/Topic/Tag PracticeSession.
- SessionItem lifecycle, four-level PracticeReview creation/correction/history.
- README, migrations, and automated Phase 1A tests.

Do not implement: screenshot upload/OCR/VLM, automatic question extraction, duplicate candidate detection/merge, SavedAnswer/versioning/scoring, `next_review_at`, due/weak algorithms, Project/Resume/Material/RAG, LLM, mock interview, multi-agent, audio/video, social platform ingestion, Redis/Celery, vector databases, or a complex background task system.

The acceptance path is: open the local app → manage Agent topics → manually add an interview question → assign Topic/Tag → search → favorite/mark wrong → start random/Topic/Tag practice → view the question → self-rate “不会/模糊/基本会/熟练” → persist PracticeReview → read practice history → restart the app and find the data intact.

## Plan Self-Review

- **Phase scope:** tasks cover only Phase 0/1A; all future systems are explicitly excluded.
- **Database consistency:** SQLAlchemy 2.x models + Alembic only; no `sqlite3` repositories or custom migration runner. FTS-specific SQL is confined to Alembic revisions.
- **Archive semantics:** `status` and `archived_at` are independent; default active queries exclude archives, while old sessions/history load by stored IDs without active filters.
- **Transactions:** skip and review transitions each use one SQLAlchemy transaction; review insert and item/session updates roll back together.
- **Taxonomy validation:** missing/inactive IDs return 400 with field errors in Question and selector flows; deactivation preserves old links.
- **Review correction:** PATCH `review_rating` is explicitly tested; event identity and original time fields remain immutable.
- **Hash uniqueness:** ordinary index only, with a migration test proving duplicate normalized hashes are accepted.
- **Errors/security:** one response envelope starts in Task 1; absent Origin is accepted; configured local Origin and all three loopback hosts are supported.
- **Task execution:** every Task 1–8 has isolated deliverables, TDD RED/GREEN commands, and an individual commit; Task 8 only integrates/verifies existing contracts.

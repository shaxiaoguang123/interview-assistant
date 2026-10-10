# Agent Interview Assistant Phase 1C Smart Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add rule-based duplicate review and user-confirmed canonical Question merging while preserving question evidence, historical practice identifiers, and the existing Phase 0/1A/1B contracts.

**Architecture:** Extend the existing Flask modular monolith, SQLAlchemy/Alembic schema, and Vue pages. Reuse the current Unicode normalizer and Question/OCR/provenance models; add a small pure-Python similarity service, a focused canonical merge service, and a reusable review panel. Rule and optional model results remain suggestions; only an explicit user-confirmed merge changes canonical membership.

**Tech Stack:** Flask, SQLAlchemy 2.x, Alembic, SQLite/FTS5, Vue 3, TypeScript, Vitest, pytest.

**Implementation Method:** Native implementation in this worktree, one task at a time with TDD. Do not delegate the schema/transaction work across independent implementations.

**Spec:** docs/superpowers/specs/2026-10-08-agent-interview-assistant-design.md, especially “相似题判断与归并”, canonical constraints, APIs, Phase 1C and invariants 18–25.

## Global Constraints

- Keep single-user, local-first Flask/Vue/SQLite architecture.
- Keep normalized_hash indexed and non-unique; duplicate Questions remain storable and become review candidates.
- Only the user can confirm same_question and choose the canonical Question.
- Rule and LLM suggestions never change Question.status, merged_into_question_id, QuestionSource, OCRBlock, PracticeReview, or SessionItem.
- Preserve QuestionSource and OCR snapshots/locators and every historical question_id.
- New list, search and practice selection include only active, unarchived canonical Questions.
- Do not add SavedAnswer, Project/Material, later review scheduling, Redis/Celery, vector databases, accounts, or general task orchestration.
- Keep OCR and similarity tests local, deterministic, fake-backed, and independent of personal screenshots.
- Add schema only through a new Alembic revision; do not edit 0001–0003 migrations.
- Run Python project commands in Conda test and run frontend checks with the existing package versions.

## Review Focus

- Two Questions with identical normalized_hash produce a suggestion only; no status or source row changes until user action.
- A trigram neighbor that is related or different can be explicitly classified without merging.
- A pending OCR candidate that appears duplicate stays out of active search/practice until confirmed as distinct or explicitly merged.
- A pending OCR candidate with same_question accepted but no completed merge remains pending; it can be reclassified, rejected as a false positive, or left for later, but cannot be confirmed as a standalone Question.
- A merge of one canonical group into another keeps all original source and practice question_ids, and redirects every child pointer directly to the final root.
- A Question text edit invalidates unmerged relation decisions made against old normalized hashes; an already completed merge relation remains untouched.
- A query matching only a merged child returns its canonical Question once and applies the canonical root’s final Topic/Tag filters.
- Group favorite/wrong true and false filters, merged-child direct routes, stale merge previews, and existing SessionItems behave predictably.

## Audited Main Baseline

At the time this plan was prepared, the new worktree was at c3c4012842f70ed9819329af08dca120e5171fd2, equal to origin/main. The existing Question model already stores normalized_text and a non-unique normalized_hash; normalize_question_text in backend/app/services/questions.py performs NFKC, casefold, punctuation normalization, and whitespace folding. Question.status already permits merged, but there is no merged_into_question_id or QuestionRelation model.

The current repositories filter status=active and archived_at but do not filter a canonical pointer. Search filters state flags per Question. PracticeSession supports random/topic/tag only and persists SessionItem.question_id. PracticeReview history is currently exact-question only. QuestionSource and QuestionSourceOCRBlock are immutable provenance facts; the OCR candidate merge/split lineage in Phase 1B is a separate workflow and must not be reused for canonical merges. Phase 1C-1/2 should not implement saved-answer aggregation because SavedAnswer/AssistantOutput models and APIs do not exist yet.

QuestionDetailPage currently loads Question, Topic/Tag, and exact-question PracticeReview rows, then separately loads exact-question sources. The existing GET /questions/{id}/sources and GET /questions/{id}/practice-reviews therefore do not provide canonical-group history. Phase 1C adds a grouped history endpoint for the detail page while keeping those existing endpoints and their response shapes exact-question scoped. The history response will retain each QuestionSource.question_id, PracticeReview.question_id, and SessionItem.question_id; it will not rewrite the underlying rows.

## File Structure

**Create**

- backend/migrations/versions/0004_question_relations.py — additive canonical pointer, relation table, indexes, exact-hash suggestion backfill.
- backend/app/services/question_similarity.py — deterministic character-trigram candidate scoring and rule suggestion refresh.
- backend/app/services/question_merge.py — canonical resolution, merge preview, transactional merge and canonical history queries.
- backend/tests/services/test_question_similarity.py — normalization reuse, exact/trigram candidates and suggestion state.
- backend/tests/services/test_question_merge.py — merge, taxonomy, provenance, history and rollback invariants.
- frontend/src/components/QuestionRelationReview.vue — reusable similar-question review panel.
- frontend/src/components/QuestionMergeDialog.vue — canonical choice, taxonomy preview and explicit merge confirmation.

**Modify**

- backend/app/models/question.py and backend/app/models/__init__.py — merged pointer and QuestionRelation model.
- backend/app/repositories/questions.py — canonical root/group, state aggregation, history and canonical list/search queries.
- backend/app/services/questions.py — scan/decision integration with manual Question create/edit and group state writes.
- backend/app/services/ingestion.py and backend/app/services/ingestion_candidates.py — run rule checks for OCR candidates and keep candidate confirmation/revision semantics intact.
- backend/app/services/search.py — preserve current search behavior while delegating canonical filters.
- backend/app/services/practice_selector.py — make every current mode select only canonical roots.
- backend/app/services/practice_review.py and backend/app/repositories/practice.py — canonical-group review/history reads; never rewrite stored review question_id.
- backend/app/api/v1/questions.py — similar-candidate, merge-preview, merge, and history endpoints; expose canonical id for merged children.
- backend/app/api/v1/ingestions.py and backend/app/__init__.py only if the chosen endpoint registration requires it.
- backend/tests/test_migrations.py, backend/tests/api/test_questions.py, backend/tests/api/test_ingestions.py, backend/tests/api/test_practice_reviews.py, backend/tests/services/test_search.py, backend/tests/services/test_practice_selector.py.
- frontend/src/pages/InboxPage.vue, frontend/src/pages/QuestionDetailPage.vue, frontend/src/pages/QuestionBankPage.vue.
- frontend/tests/inbox.spec.ts and frontend/tests/questions.spec.ts.

Do not touch the original worktree’s uncommitted frontend/tests/inbox.spec.ts. All implementation and plan work stays in the Phase 1C worktree.

## Interfaces

- question_similarity.normalize_pair(left_id: int, right_id: int) -> tuple[int, int] stores each undirected relation once in ascending id order.
- question_similarity.character_trigrams(value: str) -> set[str] and question_similarity.trigram_jaccard(left: str, right: str) -> float are pure functions with no new dependency.
- QuestionRelation stores a SHA-256 snapshot of the exact persisted Question.text for each endpoint in ascending question_id order. These digests record the exact text version reviewed without copying text into the relation table; normalized_hash remains the similarity key.
- question_similarity.refresh_rule_suggestions(session: Session, question_id: int) -> list[QuestionRelation] updates/deletes stale relations for unmerged pairs after a text change, resets still-relevant decisions to suggested, and never changes a relation whose pair is already merged.
- question_merge.resolve_canonical(session: Session, question_id: int) -> Question returns the active root or a stable 404/409 for invalid legacy state.
- question_merge.canonical_member_ids(session: Session, canonical_id: int) -> list[int] returns root plus direct descendants.
- question_merge.preview_question_merge(session: Session, canonical_id: int, source_question_id: int) -> dict returns both canonical groups, taxonomy union including inactive labels, candidate_revision when applicable, and a state-derived preview_token.
- question_merge.merge_question(session: Session, canonical_id: int, payload: dict) -> Question performs the final user-confirmed merge in one transaction.
- GET /api/v1/questions/{id}/similar-candidates reads persisted current suggestions.
- POST /api/v1/questions/{id}/similar-candidates/scan refreshes rule suggestions for pre-existing Questions and OCR candidates.
- PATCH /api/v1/question-relations/{id} accepts only relation_type and decision_status. In the 1C-1 deliverable it can reject a false positive or accept related_question/different_question; accepted same_question becomes available only with the 1C-2 merge preview/execute path.
- GET /api/v1/questions/{canonical_id}/merge-preview?source_question_id={id} returns a preview without writes.
- POST /api/v1/questions/{canonical_id}/merge accepts source_question_id, relation_id, preview_token, final topic_ids/tag_ids, and expected_candidate_revision when source is a pending OCR candidate.
- GET /api/v1/questions/{id}/history returns canonical_question_id, member_question_ids, and the existing source/review/session item shapes with their original question_id. Existing /sources and /practice-reviews endpoints stay exact-question scoped and unchanged.
- GET /api/v1/questions/{merged_child_id} remains readable and returns canonical_question_id plus the child’s stored status. PATCH/state/archive on a merged child return 409 with the canonical target; they never silently mutate the root.

## Task 1: Add canonical schema without changing Phase 1A/1B history

**Files:**
- Create backend/migrations/versions/0004_question_relations.py
- Modify backend/app/models/question.py and backend/app/models/__init__.py
- Test backend/tests/test_migrations.py and backend/tests/test_phase1b_models.py

**Interfaces:**
- Add nullable Question.merged_into_question_id -> question.id, ON DELETE RESTRICT, with self-reference protection and an index.
- Add QuestionRelation with canonical pair IDs, relation_type in same_question/related_question/different_question, decision_status in suggested/accepted/rejected, suggested_by in rule/llm/user, confidence nullable in [0,1], exact Question.text SHA-256 snapshots for both endpoints, timestamps, unique ascending pair and self-pair rejection.
- Preserve legacy rows; the migration must not rewrite Question.text/hash/status, QuestionSource, OCRBlock, QuestionState, SessionItem, PracticeReview, FTS rows, or triggers.
- Backfill only exact-hash candidates between active, unarchived legacy Questions as suggested_by=rule, relation_type=same_question, decision_status=suggested, confidence=1.0. Never backfill an accepted relation or a merge.
- If a pre-existing row has status=merged but no canonical pointer, fail the migration before schema changes with a clear diagnostic; do not guess its target.
- Downgrade must refuse while relation rows or merged pointers exist rather than discard reviewed or merged data.

- [ ] Write test_phase1c_migration_preserves_phase1b_history_and_fts: upgrade a populated 0003_phase1b_sources database containing QuestionSource, OCRBlock/link, QuestionState, SessionItem and PracticeReview; assert all original rows/IDs/snapshots survive, FTS5 and all three question_fts triggers remain, and PRAGMA foreign_key_check/integrity_check report no issue. Update one existing question’s search_text after upgrade and prove the FTS update trigger still replaces its indexed term.
- [ ] Write test_phase1c_migration_backfills_only_suggested_exact_hash_relations: add two equal normalized_hash Questions before 0004, then assert one suggested relation with exact-text SHA-256 snapshots and no merge pointer.
- [ ] Run backend test_migrations.py and test_phase1b_models.py; first prove the new migration/model assertions fail against current main.
- [ ] Add the model and 0004 migration, then rerun the focused tests and inspect SQLite PRAGMA foreign_key_list/index_list/check constraints.
- [ ] Test empty-database upgrade, downgrade refusal with merge/relation data, and safe downgrade when the new tables contain no user rows.

## Task 2: Implement deterministic similarity suggestions and wire Question/OCR text paths

**Files:**
- Create backend/app/services/question_similarity.py and backend/tests/services/test_question_similarity.py
- Modify backend/app/services/questions.py, backend/app/services/ingestion.py, backend/app/services/ingestion_candidates.py

**Interfaces:**
- Reuse prepare_question_text/normalize_question_text; do not implement a second normalizer or make normalized_hash unique.
- Generate exact matches by normalized_hash. Generate near candidates with whitespace-free Unicode character trigrams and Jaccard similarity; use 0.25 as a proposed threshold only if positive English and Chinese/English fixtures pass and related-topic negative fixtures stay below it. Record the score for boundary fixtures, test both sides of the threshold, and revise the constant if those fixtures show false positives. Sort by descending score then id and return at most 20 candidates.
- Store every rule result as suggested relation_type=same_question with confidence equal to 1.0 for exact matches or the measured score for trigram matches. The UI must label these as hypotheses, not semantic decisions.
- Compare one changed Question against active, unarchived canonical Questions. An OCR candidate may be the source while pending; pending/rejected/superseded candidates are never targets and pending-pending pairs are left to the existing Phase 1B candidate merge workflow.
- Refresh suggestions on manual Question create/text edit, OCR job persistence, manual OCR-block candidate creation, candidate text edit/split/merge, and first confirmation of an older candidate. Store exact-text SHA-256 snapshots for both endpoints. If either persisted text changes before merge—even when the normalizer produces the same normalized_hash—re-evaluate the pair in the same transaction: update the snapshots and reset a still-similar unmerged relation to suggested, or remove it from the current candidate set if it no longer meets the rule. Never reset or delete the relation for an already merged pair. The merge service independently rejects accepted same_question rows whose text snapshots no longer match current Question.text.
- A pending OCR candidate with suggested or accepted same_question relations cannot be confirmed as a standalone Question until those relations are explicitly rejected/reclassified or the candidate is merged into a selected canonical root.

- [ ] Add failing service tests for normalized punctuation duplicates, positive English and Chinese/English trigram fixtures, a related-topic negative fixture, two near-threshold score fixtures, archived/merged exclusion, deterministic top-20 ordering, and idempotent refresh. Treat any negative fixture above the proposed 0.25 threshold as a reason to tune the threshold, not weaken the negative test.
- [ ] Add failing text-change tests: accepted same_question becomes suggested again when an unmerged endpoint changes but remains similar; a text edit that preserves normalized_hash still invalidates the old decision; stale no-longer-similar relation is no longer returned; completed merged-pair relation stays accepted; a merge using an old text snapshot returns 409.
- [ ] Add failing candidate tests proving exact duplicate OCR candidates remain pending and cannot enter Question search or a new PracticeSession before relation review, while explicit related/different/rejected decisions permit normal confirmation.
- [ ] Run the focused similarity and ingestion tests and verify the missing model/service/behavior causes RED.
- [ ] Implement the pure scorer and transactional relation refresh, calling it only at the listed create/edit/import lifecycle points.
- [ ] Rerun similarity, ingestion, candidate, question CRUD and migration tests; inject a failure and assert relation writes roll back with OCR candidate persistence.

## Task 3: Add relation decisions and a review interface

**Files:**
- Modify backend/app/api/v1/questions.py and backend/app/api/v1/ingestions.py
- Create frontend/src/components/QuestionRelationReview.vue
- Modify frontend/src/pages/InboxPage.vue, frontend/src/pages/QuestionDetailPage.vue and their Vitest suites.

**Interfaces:**
- GET similar-candidates returns the relation, score, other Question summary, canonical id, and OCR candidate disposition without exposing filesystem paths or OCR model internals.
- POST scan is idempotent and scoped to one Question; it cannot modify Question status, taxonomy, candidate revision, QuestionSource or OCR snapshots.
- PATCH relation validates pair membership and enum values; accept/reject changes only QuestionRelation.
- Inbox displays candidate matches before its confirm control. Question detail displays matches for active Questions. Explicit same_question acceptance leads to merge preview; it never directly merges.
- Candidate confirmation continues to use expected_revision. In 1C-1 it returns 409 while a same_question relation is suggested. In 1C-2 it also returns 409 while same_question is accepted but not merged. An accepted related_question, accepted different_question, or explicitly rejected false-positive relation no longer blocks standalone confirmation.
- Staged-flow boundary: before Task 4/6 supplies merge preview and merge execution, Task 3 must not expose an action that leaves an OCR candidate at accepted same_question with no merge path. In the 1C-1 UI the candidate can remain suggested for later or the user can explicitly classify/reject the match and then confirm. Once 1C-2 is present, accepting same_question opens preview and offers both merge and reclassification/cancel actions.
- Keep the relation table as the current adjudication state, not an event-sourcing subsystem.

- [ ] Add failing API tests for scan/read, wrong relation ID, invalid labels, accepted related/different rows without merge, same_question acceptance being unavailable before merge support, and suggested same_question confirmation returning 409.
- [ ] Add failing staged-flow tests proving every 1C-1 candidate state has an available action: keep suggested for later, reject a false positive, classify as related/different and confirm; assert the 1C-1 UI cannot accept same_question before merge preview is available.
- [ ] Add failing Vitest for Inbox candidate match display, relation classification, candidate remaining pending, no-action dead ends, and Question detail scan/retry/error states.
- [ ] Run the focused API and Vitest tests and confirm RED.
- [ ] Implement the small route handlers and reusable review panel; keep API code thin and business rules in services.
- [ ] Verify decisions do not create a merge pointer or alter candidate revision, source snapshot, OCR block or formal topic/tag association.

## Task 4: Implement canonical merge preview and atomic user-confirmed merge

**Files:**
- Create backend/app/services/question_merge.py and backend/tests/services/test_question_merge.py
- Modify backend/app/api/v1/questions.py, backend/app/services/ingestion_candidates.py and candidate API tests.

**Interfaces:**
- Merge target must be an active, unarchived canonical root. Source must be another active canonical root or a still-pending OCR candidate from a succeeded job.
- Merge requires an accepted same_question relation connecting the selected active canonical target to the source active root or pending OCR candidate; neither a suggested relation nor a related/different/rejected relation is sufficient.
- The relation’s stored exact-text SHA-256 snapshots must equal both current Question.text digests. A stale accepted decision returns 409 and requires relation review again, including when a text edit leaves normalized_hash unchanged. A relation already associated with a completed Merge is historical and is never reset by later text edits.
- Preview returns the groups and the Topic/Tag union, including inactive taxonomy labels. The request supplies the final root topic_ids/tag_ids; newly selected IDs must be active. If an inactive union member is omitted, that is an explicit user choice; the source Question’s original links stay intact.
- If source is a pending OCR candidate, require its current expected_candidate_revision; atomically mark its candidate disposition confirmed while marking its Question status merged.
- Set every source-group member to status=merged and merged_into_question_id=the selected target root directly. Reject self-merge, archived roots, stale candidate revisions, non-root targets, invalid relation membership and cycles.
- The only taxonomy rows changed are the selected canonical root’s direct QuestionTopic/QuestionTag rows. Do not move/delete source taxonomy or any source/history rows.
- Merge preview returns a required preview_token computed from current state: target/source canonical IDs and member IDs; each member’s status, archive state, canonical pointer, exact text digest, normalized_hash and updated_at; candidate_revision where applicable; relation ID/type/decision/timestamps/text snapshots; and each member’s Topic/Tag IDs plus taxonomy active/name state.
- POST merge recomputes that token inside the merge transaction and compares it before any write. Any changed Question text/status/archive, group membership, relation decision, OCR candidate revision, Topic/Tag link, or taxonomy name/active state returns 409 MERGE_PREVIEW_STALE. No schema revision counter is needed because the token fingerprints the rows the preview actually displays.
- The transaction boundary includes preview-token validation, relation snapshot/decision validation, candidate confirmation when applicable, target taxonomy replacement, status changes and direct pointers.

- [ ] Add failing service/API tests for both merge orientations, a source group with existing descendants, OCR pending-candidate merge-and-confirm, wrong/stale relation, stale exact-text snapshot, stale candidate revision, cycle/self-merge and archived question rejection.
- [ ] Add failing 1C-2 API tests proving accepted same_question remains pending and cannot standalone-confirm; the user can either complete Merge or reclassify/reject the relation and then use the normal candidate confirmation flow.
- [ ] Add failing stale-preview tests for Question text edits, target/source Topic or Tag edits, taxonomy active/name changes, relation decision changes, and changed group membership; assert 409 and assert the newer state is not overwritten.
- [ ] Add a rollback test that injects a failure after taxonomy replacement and proves root taxonomy, all status/pointer fields, candidate disposition/revision and relation state are unchanged.
- [ ] Add direct-child API tests: GET returns the stored merged child plus canonical_question_id; PATCH text/state and archive return 409 without mutating either child or root.
- [ ] Run focused merge tests and verify current implementation fails the new assertions.
- [ ] Implement preview and merge inside one SQLAlchemy transaction; do not reuse candidate Split/Merge mutation code.
- [ ] Rerun merge, ingestion candidate lifecycle and model constraint tests.

## Task 5: Make read/query/state behavior canonical while retaining historical IDs

**Files:**
- Modify backend/app/repositories/questions.py, backend/app/repositories/practice.py, backend/app/services/search.py, backend/app/services/questions.py, backend/app/services/practice_selector.py, backend/app/services/practice_review.py, backend/app/api/v1/questions.py and backend/app/api/v1/practice_reviews.py.
- Test backend/tests/api/test_questions.py, backend/tests/api/test_practice_reviews.py, backend/tests/services/test_search.py, backend/tests/services/test_practice_selector.py and migration/API history tests.

**Interfaces:**
- Question list/search return status=active, unarchived rows with merged_into_question_id IS NULL; a stale direct request for a child exposes canonical_question_id so the frontend can route to the root.
- Search tests both root text and every merged descendant’s historical text. A child-only text hit resolves to the active canonical root, deduplicates multiple hits in the same group, and returns the canonical Question once.
- Search topic_ids/tag_ids filters are applied to the canonical root’s final direct taxonomy associations selected during merge. Child taxonomy stays available in history but does not broaden canonical search after the user removes a child category from the previewed union.
- Root favorite/wrong response and filters are OR aggregates across the root and all merged descendants. The merge itself does not rewrite QuestionState. A user explicitly turning a group flag off clears that flag on group members in one transaction; turning it on sets the root flag. The UI labels the action as applying to the canonical group.
- GET canonical history aggregates QuestionSource, PracticeReview and SessionItem rows, each with its original question_id and stable row id. Missing QuestionState rows count as false for group OR semantics.
- Preserve the current GET /questions/{id}/sources and GET /questions/{id}/practice-reviews behavior and response shape as exact-Question queries. QuestionDetailPage stops making those two calls and uses GET /questions/{id}/history for the canonical group. The history response embeds the existing source fields (including locator, OCR snapshots, blocks and image URLs) and existing review fields, adding only canonical_question_id/member_question_ids/session_items as needed; every embedded row keeps its original question_id.
- QuestionDetailPage continues to PATCH /practice-reviews/{review_id}; the response and local row retain the original review.question_id. QuestionSource.question_id and PracticeReview.question_id are never rewritten. Existing exact-question endpoints remain available for other callers.
- GET a merged child directly returns its historical Question representation with canonical_question_id; the frontend replaces the route with the canonical root. PATCH text/state and archive on the child return 409 rather than silently redirecting the write to the root.
- Random/Topic/Tag selectors create only canonical active SessionItems. Existing SessionItems keep their old child question_id and remain readable/completable after merge.
- Do not add favorite/wrong/due modes or next_review_at in this phase; implement the canonical predicates around modes currently supported.

- [ ] Add failing search tests where only the child historical text matches, root and multiple children all match, and the query is filtered by a root-final Topic/Tag that differs from an unselected child taxonomy link.
- [ ] Add failing is_favorite/is_wrong filters for both true and false. For each field, cover root-only true, child-only true, all false/missing state, and mixed true/false members; each canonical root appears once.
- [ ] Add failing backend history/API tests for unchanged exact-question sources/reviews endpoint payloads and aggregate history endpoint, including all OCR source fields and original QuestionSource/PracticeReview/SessionItem question_ids.
- [ ] Add failing direct-child tests for GET, PATCH, state PATCH and archive behavior; verify 409 writes do not mutate the root or the merged child.
- [ ] Add failing tests for review correction without reparenting, current selectors producing only roots, and an already-created child SessionItem remaining unchanged and completable.
- [ ] Run focused search, selector, review and API tests to prove RED.
- [ ] Add canonical member query helpers and use them from search, history and state filters; keep existing active/archive behavior.
- [ ] Run focused tests and ensure FTS child-text matching, update triggers, canonical taxonomy filters and many-to-many result de-duplication still pass.

## Task 6: Complete Vue merge/review workflow and regression acceptance

**Files:**
- Create frontend/src/components/QuestionMergeDialog.vue
- Modify frontend/src/components/QuestionRelationReview.vue, frontend/src/pages/InboxPage.vue, frontend/src/pages/QuestionDetailPage.vue and frontend/src/pages/QuestionBankPage.vue.
- Test frontend/tests/inbox.spec.ts and frontend/tests/questions.spec.ts.

- [x] Add failing Vitest for similar-candidate display, explicit relation choice, no dead-end OCR review states, accepted-same candidate staying pending until Merge, preview token refresh after a 409, previewed canonical root, Topic/Tag union, inactive taxonomy warning, no writes before final confirmation, pending OCR candidate merge becoming read-only history, aggregate source/review history retaining original IDs, and route redirection from a merged child.
- [x] Add failing QuestionDetailPage tests proving it calls the grouped history API once, maps its full source rows into SourceImageViewer, maps PracticeReview rows into existing controls, does not make duplicate exact-history requests, and preserves the original question_id after a review PATCH. Task 5 backend tests own compatibility assertions for the legacy exact-question APIs.
- [x] Add failing UI tests for merged-child direct navigation and refusal of edit/archive controls; show a link/redirect to the canonical root rather than applying the child write to that root.
- [x] Run questions.spec.ts and inbox.spec.ts to prove RED.
- [x] Implement the review panel and merge dialog by reusing current page/API patterns; preserve SourceImageViewer and candidate expected_revision flow.
- [x] Verify retryable errors, stale preview conflicts, and job/question navigation cannot apply a stale relation/preview response to another selected Question or Job.
- [x] Run frontend Vitest, npm run type-check, npm run build, backend Pytest and pip check after the full workflow is integrated.
- [x] Perform browser acceptance with a temporary database and synthetic screenshot: import, review a duplicate, merge it, open canonical history, search, and start a new PracticeSession; verify no child appears in new results and existing SessionItems remain intact.

## Phase 1C-3 Optional Suggestion Gate

This gate is independent of Phases 1C-1/1C-2 and is not required to ship their rule workflows. No LLM or multimodal provider, API-key setting, suggestion_json column, or provider dependency currently exists in the audited code. Do not select a vendor or add an SDK by assumption.

Before implementation, decide the provider/model, local secret storage, whether screenshot images may be sent remotely, user consent text, budget/timeout, and whether suggestions are requested automatically or by an explicit action. With no configuration, all rule-based functionality must remain fully usable and no outbound model request may occur.

If approved later, implement through a small optional SuggestionProvider seam and a separate additive Alembic revision for question suggestion data. Agent Topic/Tag/difficulty output, LLM same/related/different classification and multimodal boundaries are stored as suggestions only. A user must review them; LLM cannot set accepted, confirm an OCR candidate, change Question status, create a merge pointer, edit OCRBlock/QuestionSource evidence, or write training/history records. Tests use fake providers and assert zero requests when configuration is absent.

## Final Phase 1C Acceptance

- Upgrade a populated 0003 database without data loss; keep FTS5, all question_fts triggers, old QuestionSource/OCRBlock links and snapshots, QuestionState, SessionItem, PracticeReview and foreign keys intact; verify PRAGMA integrity_check and foreign_key_check.
- Exact hash pairs and trigram matches appear only as suggested relationships; user decisions persist and are not silently overwritten.
- No pending OCR candidate enters active search or a new session before an explicit relation exclusion plus standalone confirmation, or an explicit user-confirmed canonical merge. An accepted same_question relation without a completed merge remains pending.
- Text changes invalidate accepted unmerged relation decisions and old merge preview tokens; completed historical Merge relations are not reset.
- A historical-text search hit on a merged child resolves to the canonical root, returns that root once, and applies only the root’s final Topic/Tag filter semantics.
- Merge is atomic, cannot create cycles, and leaves source snapshots, OCR blocks, PracticeReview.question_id, SessionItem.question_id and child taxonomy links intact.
- Merge previews reject stale OCR candidate revisions and stale ordinary Question/taxonomy/relation/group state before writing. Group favorite/wrong true and false filters return each canonical root at most once.
- Canonical list/search/current selectors contain a Question group at most once; QuestionDetailPage uses the grouped history API while the legacy exact-question source/review endpoints remain compatible.
- Phase 1A Question CRUD, active/inactive taxonomy validation, mixed-language FTS, random/Topic/Tag sessions, and Phase 1B upload/OCR/edit/split/merge/confirm/provenance tests all pass.
- Frontend Vitest, Vue/TypeScript type-check and production build pass; browser acceptance uses only temporary local data and generated/de-identified content.
- No SavedAnswer, Project/Material, new review algorithm, new OCR engine or remote AI dependency is added in Phases 1C-1/2.

## Plan Self-Review

- **Spec coverage:** normalized hash, trigram candidates, relation states, optional LLM triage, user-confirmed canonical choice, Topic/Tag merge preview, direct pointers, cycle prevention, original source/history preservation, canonical state aggregation, search and selector exclusion are assigned above. SavedAnswer/AssistantOutput aggregation is explicitly deferred until those models exist.
- **Migration safety:** 0004 is additive; old hashes remain non-unique; exact candidates and their endpoint hash snapshots are backfilled as suggestions only; FTS5/triggers and historical source/review/session rows remain intact; downgrade refuses destructive loss.
- **Transaction safety:** OCR evidence confirmation and canonical merge use a single short database transaction; injected failures must roll back category, status, relation and candidate disposition changes.
- **Text/decision consistency:** accepted same_question can merge only while both exact-text SHA-256 snapshots still match the reviewed text; text edits requeue unmerged relations even when normalized_hash stays equal; completed merges are immutable.
- **Preview consistency:** preview_token covers ordinary Question content/status/archive, group membership, taxonomy links/active state, relation decision/snapshots and OCR candidate_revision, then is checked again in the merge transaction.
- **Type/API consistency:** all merge calls identify canonical_id, source_question_id, relation_id and preview_token; OCR sources additionally include expected_candidate_revision. Existing exact /sources and /practice-reviews APIs remain unchanged, while /history is group-aware and preserves original ids.
- **Review focus:** exact/near threshold positives and false positives, text invalidation, accepted-same OCR gating, stale previews, canonical-text search, group state true/false filters, merged-child direct APIs, legacy endpoint compatibility and existing sessions each have dedicated tests.
- **Proportion:** the required 1C-1/2 work reuses the current Question, taxonomy, candidate, search and practice layers. Optional 1C-3 is gated and adds no baseline dependency.

**Self-review note:** The 0.25 trigram threshold is provisional; the English and CJK/English positive fixtures and related-topic negative fixtures must determine whether it is retained. The favorite/wrong uncheck operation is an explicit canonical-group action and the UI must communicate its scope. The database upgrade intentionally stops if it encounters legacy status=merged rows with no pointer, because the correct canonical target cannot be inferred safely. The 1C-1 OCR UI cannot expose accepted-same as a terminal choice before 1C-2 provides the merge path.

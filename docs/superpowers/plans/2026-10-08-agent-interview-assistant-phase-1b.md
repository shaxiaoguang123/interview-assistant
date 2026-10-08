# Agent Interview Assistant Phase 1B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local screenshot upload, OCR, reviewable multi-question candidates, and user confirmation into the existing Phase 1A question bank, while preserving original images and every OCR run as traceable evidence.

**Architecture:** Extend the current Flask app and SQLAlchemy/Alembic schema with `SourceAsset`, `IngestionJob`, immutable `OCRBlock` rows, and source locators. A replaceable adapter normalizes OCR output before persistence; deterministic text/geometry rules propose candidate boundaries. Reuse `Question.status=pending_review` until the user confirms a candidate. One image job runs synchronously per request; the frontend advances a batch one image at a time and displays each result. No general worker/task framework is added.

**Tech Stack:** Existing Flask, Vue 3 + TypeScript + Vite, SQLAlchemy 2.x, Alembic, SQLite, Conda `test`, pytest, and Vitest. OCR default candidate from the sample benchmark: RapidOCR 3.9.2 with PP-OCRv6 small ONNX models and ONNX Runtime 1.30.0 CPU provider. Pillow validates and orients raster images.

**Spec:** `docs/superpowers/specs/2026-10-08-agent-interview-assistant-design.md` (Phase 1B only). Existing implementation baseline: local `main` at `35419d9` as inspected on 2026-10-08.

## Global Constraints

- Keep the local single-user Flask/Vue architecture and existing `create_app`, SQLAlchemy session, Alembic, API error envelope, Topic/Tag validation, Question search, and PracticeSession selector.
- Create no accounts, remote storage, social-platform collectors, OCR web service, Redis/Celery, general job orchestration, or LLM/VLM integration.
- Screenshot pixels and OCR text stay local. Never send an image, OCR text, source filename, or source metadata to an OCR/model service or application log.
- Store generated relative paths under the configured application data directory; never use a user-supplied filename as a path or serve a path supplied by a request.
- Store each original image byte-for-byte with SHA-256. SHA-256 is an ordinary index, not a unique constraint; uploading the same image twice remains valid.
- Every OCR attempt creates a new `IngestionJob` and new UUID `OCRBlock.id` values. Existing jobs, blocks, source snapshots, and `QuestionSource` references are immutable and remain readable after reprocessing. Each OCR-created Question keeps a nullable-for-manual `origin_ingestion_job_id` and an explicit candidate disposition so history remains queryable after confirmation, rejection, or candidate absorption.
- OCR block coordinates are normalized `(x, y, width, height)` in `[0,1]`, with `(0,0)` at the top-left of the orientation shown in the viewer. OCR confidence is advisory and never auto-confirms a candidate.
- OCR-derived candidates use the existing `Question.status='pending_review'`; only explicit confirmation changes one to `active`. Existing manual question creation continues to default to `active`.
- The current Question list, search, and practice selectors remain `status='active' AND archived_at IS NULL`; add regression tests rather than changing those completed contracts.
- Topic and Tag choices are manual. Reuse `validate_active_topic_ids` and `validate_active_tag_ids`; do not add automatic topic/tag/difficulty suggestions, similarity candidates, or canonical question merging.
- Batch upload and OCR failures are isolated per image. A failed image leaves its original file and failed job state available for review; retry always creates a new job and cannot roll back a different image that succeeded. A queued job is claimed with one conditional database update; duplicate run requests receive `409 CONFLICT`.
- Use the shared `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`, `PAYLOAD_TOO_LARGE`, and `INTERNAL_ERROR` API envelope. Per-image validation/OCR failures are returned as per-file results or persisted job state; they do not turn a successful sibling into a failed batch request.
- Automated tests use `tmp_path`, temporary SQLite databases, and an injected fake OCR adapter. They never download models or process the user’s real screenshots.
- Develop on a new `codex/phase-1b-screenshot-ocr` branch from `main`; complete RED → GREEN and a commit for each task. This revision is the final Phase 1B execution plan; do not expand scope before real use feedback.

## OCR Sample Benchmark and Decision

The user-provided `pic-test` contains two 1080×1800 JPG screenshots (about 0.24 and 0.27 MiB): one numbered list of four questions and one continuation containing questions 3–14. Both contain Chinese text and English terms such as `Agent`, `LLM`, `Prompt`, `Query`, `Plan Agent`, `Execute Agent`, `ReAct`, `Multi-Agent`, and `Single-Agent`.

I manually transcribed the visible text and compared case-folded, NFKC-normalized text with whitespace and punctuation removed. This is a small, high-contrast sample, not a general accuracy claim.

| Engine and runtime | Normalized CER, Xiaohongshu / Byte sample | Numbered questions found | Technical terms found | Warm OCR time, Xiaohongshu / Byte |
|---|---:|---:|---:|---:|
| RapidOCR 3.9.2, PP-OCRv6 small, ONNX Runtime CPU | 0/187 / 0/307 | 4/4 and 12/12 | 3/3 and 7/7 | 1.17s / 1.26s |
| PaddleOCR 3.7.0, PP-OCRv6 medium, PaddlePaddle 3.3.1 CPU | 0/187 / 0/307 | 4/4 and 12/12 | 3/3 and 7/7 | 11.93s / 15.13s |
| macOS Vision, `zh-Hans` + `en-US` | 1/187 / 0/307 | 4/4 and 12/12 | 3/3 and 7/7 | 0.24s / 0.68s after warm-up |

Each engine returned 14 and 17 OCR blocks respectively. Multiline questions are split across blocks, so a separate candidate grouping step is necessary. RapidOCR and direct PaddleOCR matched the manual reference on both supplied screenshots. RapidOCR is the Phase 1B default candidate: its CPU result matched the direct PaddleOCR result, it completed each image in about 1.2 seconds, and the small ONNX model set occupied about 30 MiB versus about 141 MiB cached for the direct PaddleOCR medium pipeline. RapidOCR’s project describes its models as PaddleOCR-derived ONNX conversions ([RapidOCR](https://github.com/RapidAI/RapidOCR)); direct PaddleOCR was separately exercised as a CPU baseline.

Sample 1 is `pic-test/小红书-Agent评测策略专家_1_泽华留学生求职_来自小红书网页版.jpg`; sample 2 is `pic-test/字节agent开发(抖音开发)一面面经_2_熊掌与鱼🐟_来自小红书网页版.jpg`. The source files remain user-provided, untracked files and are not copied into the application or test fixtures.

**GPU finding:** `pt` has PyTorch 2.14.1 with MPS available; a real tensor multiply ran on `mps:0`. RapidOCR’s PyTorch detector, classifier, and recognizer also ran on MPS and returned the same text, but took about 11.6s and 3.4s per image after a 6.8s initialization/model download, slower than ONNX CPU. ONNX Runtime’s CoreML provider was available and selected, but did not improve sample latency; that run does not prove which CoreML hardware units executed each operator. Official PaddlePaddle macOS support is CPU-only ([PaddlePaddle macOS install](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html)). Keep CPU as the Phase 1B default. MPS/CoreML are not an acceptance requirement; evaluate them again only if later real workloads show a speed benefit.

## Review Focus

- **Unconfirmed candidates:** a pending OCR question must not appear in default list, search, favorite/wrong results, or a new PracticeSession; confirmation must publish exactly that question.
- **Reprocessing and evidence:** retry/re-OCR creates a new job and OCRBlock UUIDs; the job-owned candidate list includes pending, confirmed, rejected, and superseded candidates without changing prior blocks or source snapshots.
- **Image input safety and partial batch errors:** invalid, oversized, spoofed, or decompression-bomb files must not escape the storage root or prevent valid siblings from being saved and processed.
- **Coordinate fidelity:** EXIF-oriented images and normalized top-left coordinates must highlight the same visible image region in the browser.
- **Candidate boundaries:** numbered questions split across OCR lines must form one candidate each; titles must not become questions when numbered questions follow; ambiguous text remains editable and never auto-publishes. Same-block multi-question text may need manual split but raw OCR remains visible.
- **Job races and interruption:** duplicate run requests cannot start duplicate OCR; a timeout checks persisted status; a terminated process cannot leave a permanently running job.

---

## File Structure

```text
backend/
  app/
    ocr/
      adapter.py                       # engine-neutral protocol and detection DTO
      rapidocr_adapter.py              # RapidOCR/ONNX implementation only
    models/ingestion.py                # SourceAsset, IngestionJob, OCRBlock, QuestionSource
    repositories/sources.py            # source file metadata and safe reference queries
    repositories/ingestion.py          # jobs, immutable blocks, candidate queries
    services/source_storage.py         # file validation, atomic local write/read/delete
    services/ingestion.py              # per-image job run, status, explicit retry
    services/candidate_builder.py      # deterministic OCRBlock grouping
    services/ingestion_candidates.py  # candidate edit, split, merge, archive, confirm
    api/v1/sources.py                  # upload and source metadata/image routes
    api/v1/ingestions.py               # job, OCRBlock, and candidate routes
  migrations/versions/0003_phase1b_sources.py
  tests/services/test_source_storage.py
  tests/services/test_ingestion.py
  tests/services/test_candidate_builder.py
  tests/api/test_sources.py
  tests/api/test_ingestions.py
  tests/api/test_ingestion_candidates.py
  tests/api/test_question_sources.py
  tests/api/test_phase_1b_flow.py
  tests/api/test_source_deletion.py
frontend/src/
  pages/InboxPage.vue
  components/SourceUpload.vue
  components/SourceImageViewer.vue        # oriented display preview and SVG content-box overlay
  components/IngestionCandidateEditor.vue
frontend/tests/inbox.spec.ts
```

## Shared Data and API Contracts

- SourceAsset keeps source_type=image for this phase, nullable platform/source_url/external_id/title/author/captured_at for extensible source metadata, original filename as metadata, detected original MIME and byte size, raw original dimensions, EXIF-oriented display dimensions, generated relative original and display-preview paths, SHA-256, metadata_json, archive time, and timestamps. Platform fields are never fetched or used to access remote content. The preview is a lossless PNG made from EXIF-transposed decoded pixels; it is never a replacement for the byte-for-byte original.
- IngestionJob has source_asset_id, status queued/running/succeeded/failed, stage, failure_stage, engine and engine_version, sanitized error code/message, candidate_count, created/started/completed/updated timestamps. One SourceAsset has append-only attempts; a retry creates a new job.
- OCRBlock has an immutable UUID primary key, ingestion_job_id, raw text, normalized top-left bbox, reading_order, nullable confidence, block_type, and created_at. All locator coordinates refer to the EXIF-oriented display preview, with finite x/y/width/height values in [0,1] and x+width and y+height no greater than 1.
- Question gains nullable origin_ingestion_job_id (FK to IngestionJob, RESTRICT), nullable ingestion_candidate_state, and candidate_revision (integer, initially 0). Phase 1A manual questions keep both null. OCR candidates use pending_review, confirmed, rejected, or superseded as the candidate state while the existing Question.status remains pending_review or active; Question.status=merged remains reserved for the later Phase 1C canonical merge. A nullable superseded_by_candidate_id may point only to another candidate from the same job and is for inbox-correction lineage only.
- Candidate state mapping: a new OCR candidate is Question.status=pending_review and ingestion_candidate_state=pending_review; confirmation changes it atomically to Question.status=active and state=confirmed; reject/archive keeps Question.status=pending_review, sets archived_at, and state=rejected; a candidate consumed by a manual same-job merge remains as an archived row with state=superseded and a link to the pending survivor. None of these rows are deleted.
- QuestionSource links Question to SourceAsset and stores extensible locator_type (image_region in Phase 1B; future locator types are not implemented now), locator_json as the immutable original locator, nullable locator_correction_json for a user-adjusted display box, immutable source_text_snapshot (the exact OCR excerpt attributed to this candidate), immutable raw_ocr_text_snapshot (the full text of its cited OCRBlocks), confidence, and created_at. QuestionSourceOCRBlock links stable OCRBlock IDs. Manual Question.text edits never rewrite those snapshots or OCRBlocks.
- Initial candidate grouping may use several OCRBlocks; split may make multiple candidates cite the same block. Each resulting QuestionSource keeps the exact attributed excerpt and the full raw OCR text, and candidate boxes are based on the referenced block geometry. A merge adds evidence links to the survivor and leaves the original candidates and source links available in the job history. Every absorbed row records superseded_by_candidate_id and increments its revision; the survivor revision also increments.
- Candidate job ownership is authoritative: all OCR-created Questions have origin_ingestion_job_id. GET /api/v1/ingestions/{id}/candidates returns all candidate rows for that job by default, including pending, confirmed, rejected, and superseded rows, with state and sources. A status query accepts all, pending_review, confirmed, rejected, superseded, or archived. Phase 1A manual Questions are never returned by this endpoint.
- POST /api/v1/sources accepts repeated multipart files and optional metadata JSON; each file gets an independent SourceAsset and queued IngestionJob transaction. Its HTTP 200 response has one input-ordered result per file: stored entries include source/job IDs, rejected entries include the shared error code/message/fields, and one rejection does not roll back siblings. GET /sources, GET/PATCH /sources/{id}, archive, GET /sources/{id}/original, and GET /sources/{id}/display use opaque IDs; neither original_path nor preview_path is serialized. The original route returns exact stored bytes; display returns the EXIF-normalized lossless preview.
- POST /api/v1/ingestions/{id}/run is accepted only when an atomic conditional update changes queued to running. A second request for the same job gets 409 CONFLICT and starts no OCR. After a network timeout, the UI queries GET /ingestions/{id}; it never re-runs that job. A user retry creates a new job with POST /sources/{id}/ingestions.
- Job state sequence: queued → running/recognizing → running/building_candidates → running/persisting_results → succeeded/completed. For normal failures, status becomes failed and failure_stage records recognizing, building_candidates, or persisting_results; stage is not overwritten, so the failed phase remains visible. For startup recovery, failure_stage copies the persisted running stage and error_code is INGESTION_INTERRUPTED. Only OCR recognition and in-memory candidate grouping happen outside a database transaction. One final transaction writes all OCRBlocks, candidate Questions, QuestionSources, OCRBlock links, candidate_count, and succeeded status. A zero-detection OCR result is a valid succeeded job with zero candidates. Any OCR/grouping/persistence error leaves no partial OCRBlock or candidate result set, then records failed plus failure_stage and a sanitized error in a separate short transaction. If that failure update also cannot commit, the startup recovery marks the leftover running job interrupted.
- The run endpoint does not report success until candidate persistence commits. Adapter, runtime, model manifest release/checksum, and CPU provider are recorded at claim time so failed as well as successful attempts identify the attempted OCR stack. Candidate creation has a conditional running/stage guard; a succeeded job cannot generate candidates again. A successful response includes persisted job status/count; known OCR failures return persisted failed state. Invalid job states and duplicate execution use the common error envelope.
- No worker is introduced. The local app runs one Flask server process. On server startup, a small reconciliation changes jobs still marked running by a previous process to failed, copies the last persisted stage into failure_stage, and records sanitized INGESTION_INTERRUPTED. It does not delete artifacts. Users inspect the old run and create a new retry job; the old job is never reset or reused.
- OCR adapter contract: OCRDetection(id: UUID, text, bbox, confidence, reading_order, block_type), OCRAdapter.name/version/recognize(image). UUIDs are assigned before candidate grouping; groups reference UUIDs, never array indexes. RapidOCR types remain in the adapter only. RapidOCR 3.9.2 + ONNX Runtime 1.30.0 + PP-OCRv6 small model files are pinned. Configure OCR_ENGINE=rapidocr_onnx, OCR_MODEL_DIR (default APP_DATA_DIR/ocr-models/rapidocr-3.9.2/ppocrv6-small), OCR_DETECTION_MODEL_PATH, OCR_RECOGNITION_MODEL_PATH, and optional OCR_CLASSIFICATION_MODEL_PATH. An adjacent manifest.json records the model release and SHA-256 of each exact file. The runtime validates paths/checksums and never downloads models implicitly. The job records adapter, runtime, model release/checksum, and CPU provider.
- Split, merge, edit, archive, and confirm check Question.status=pending_review, no archive time, and the expected job ownership. Every submitted OCRBlock UUID must belong to the request's IngestionJob and its SourceAsset. Candidate merges are only same-job inbox edits, not canonical Question merges. Locator corrections must be finite normalized values with positive width/height and right/bottom edges at most 1.
- Each candidate operation is one database transaction. Confirm, merge, and archive use conditional status updates and row-count checks; a concurrent winner causes the other request to return 409 without overwriting state. Database exceptions roll back Question, QuestionSource, topic/tag links, and block-link rows together.
- GET /api/v1/questions/{id}/sources returns source metadata, immutable raw/excerpt snapshots, original and corrected locator, and stable OCRBlock IDs/text. An archived SourceAsset remains readable while cited.
- Permanent SourceAsset deletion is limited to assets with no QuestionSource, no Question with origin_ingestion_job_id, and no attempted OCR history. An untouched queued job may be removed together with its source. A running/succeeded/failed job, OCRBlock, candidate, or source citation blocks deletion with 409; archive is the normal cleanup action.
- Original image bytes, OCRBlock text/bbox, OCR excerpts, and original locator are immutable. Candidate correction is stored separately in Question.text, locator_correction_json, and operation-specific QuestionSource rows; edited text or box never rewrites OCR evidence.

## Task 1: Phase 1B Schema and Candidate Provenance Migration

**Files:**
- Create: backend/app/models/ingestion.py
- Create: backend/migrations/versions/0003_phase1b_sources.py
- Create: backend/tests/test_phase1b_models.py
- Modify: backend/app/models/__init__.py
- Modify: backend/app/models/question.py
- Modify: backend/tests/test_migrations.py
- Modify: backend/tests/conftest.py

**Interfaces and database changes:**
- **Consumes:** Phase 1A SQLAlchemy Base, Question fields/status check, Alembic revision 0002, SQLite FK configuration, and isolated tmp_path fixtures.
- **Produces:** SourceAsset, IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock; Question.origin_ingestion_job_id, Question.ingestion_candidate_state, candidate_revision, and optional superseded_by_candidate_id; one Alembic revision 0003.
- SourceAsset stores source metadata, generated original/display paths, original and EXIF-oriented dimensions, MIME, size, hash, archive time, and timestamps. IngestionJob stores status/stage/failure_stage, engine metadata, candidate_count, and lifecycle timestamps. OCRBlock ID is a stable UUID. QuestionSource stores immutable OCR excerpt/raw text/original locator plus optional locator correction.
- All new question provenance FKs are nullable only where Phase 1A manual rows require it. Candidate mutation requests include expected_revision; a conditional update increments candidate_revision and returns 409 on a stale revision. Existing Questions remain unchanged on upgrade. Source/job/question provenance uses RESTRICT where deleting the row would erase history; explicitly validated no-history source cleanup is the only cascade path.
- Candidate state is nullable for manual questions and constrained to pending_review/confirmed/rejected/superseded for OCR candidates. candidate_revision starts at 0 and increments on every candidate mutation; mutation APIs require expected_revision. Do not add Question.status=archived or overload status=merged for inbox candidate merge. SHA-256 and normalized_hash use ordinary indexes, never UNIQUE.
- Migration must preserve the existing 1A FTS virtual table/triggers, Questions, taxonomy, PracticeSessions, SessionItems, PracticeReviews, and normalized_hash index.

**Acceptance:** fresh and existing 1A databases upgrade to head; manual questions keep null provenance and current status; OCR provenance columns/constraints exist; duplicate image and question hashes remain legal; FK violation is rejected; fixture data remains in tmp_path.

- [ ] **Step 1: Write failing tests** `test_phase1b_migration_upgrades_existing_1a_database_without_data_loss`, `test_phase1b_tables_and_foreign_keys_exist`, `test_manual_question_keeps_null_ingestion_provenance`, `test_candidate_state_constraints_and_supersession_fk`, `test_candidate_revision_defaults_and_increments`, `test_ocr_block_uses_stable_uuid_primary_key`, `test_source_sha256_and_question_normalized_hash_are_not_unique`, and `test_source_storage_root_is_under_configured_app_data_dir`.
- [ ] **Step 2: Run RED.** Use Conda test and run `(cd backend && conda run -n test pytest tests/test_migrations.py tests/test_phase1b_models.py -q)`; expected schema/constraint assertions fail.
- [ ] **Step 3: Implement SQLAlchemy models and Alembic revision 0003.** Preserve 1A defaults and existing rows. Add indexes for origin_ingestion_job_id, job/source/status lookups, and OCRBlock reading order; add checks for candidate state and confidence.
- [ ] **Step 4: Run GREEN.** Run `(cd backend && conda run -n test pytest -q)` plus focused migration/model tests against temporary databases; verify an existing 1A Question, QuestionState, SessionItem, and PracticeReview survive the upgrade.
- [ ] **Step 5: Commit** as `feat: add Phase 1B source and OCR provenance schema`.

## Task 2: Safe Local Source Storage and Partial Batch Upload

**Files:**
- Create: backend/app/repositories/sources.py
- Create: backend/app/services/source_storage.py
- Create: backend/app/api/v1/sources.py
- Create: backend/tests/services/test_source_storage.py
- Create: backend/tests/api/test_sources.py
- Modify: backend/requirements.txt
- Modify: backend/app/__init__.py
- Modify: backend/app/config.py

**Interfaces:**
- **Consumes:** Task 1 SourceAsset/IngestionJob models, shared ApiError, local Host/Origin checks, and APP_DATA_DIR.
- **Produces:** `save_source_file(file_storage, storage_root, metadata) -> SourceAsset`, multipart upload, source metadata/image routes, and one independently committed result per file.
- Configure 10 images per batch, 20 MiB per image, 50 MiB request body, and 40 million decoded pixels per image in one place each. Validate actual decoded JPEG/PNG/WebP bytes with Pillow; do not trust filename or request MIME. Generate all paths; never accept or serialize filesystem paths.
- Store original bytes exactly and compute SHA-256. Create a lossless PNG display preview from EXIF-transposed pixels with generated path and oriented dimensions. OCR and browser overlay use the same oriented pixel coordinate space; the original bytes remain unchanged and separately retrievable.
- Store each valid file and queued IngestionJob in its own transaction. A DB failure removes that file's temporary/original/preview files; other batch items continue. Temporary files are atomically renamed only after validation. Preserve optional source metadata as metadata, never fetch platform URLs.
- GET /sources/{id}/original returns byte-for-byte original content; GET /sources/{id}/display serves only the generated oriented preview. Both resolve by opaque ID and verify paths remain under SOURCE_STORAGE_DIR. Original/preview paths are never returned.

**Acceptance:** byte/hash equality for the original, EXIF-normalized preview dimensions, no filename path control, rejection of MIME/extension spoof and decompression bombs, independent per-file DB/storage rollback, and safe retrieval through asset ID only.

- [ ] **Step 1: Write failing storage/API tests** `test_upload_preserves_original_bytes_and_sha256`, `test_upload_path_does_not_use_user_filename`, `test_upload_rejects_extension_and_mime_spoof`, `test_upload_rejects_invalid_image_and_pixel_bomb`, `test_upload_creates_exif_normalized_lossless_display_preview`, `test_upload_rejects_oversized_file`, `test_multi_upload_keeps_valid_files_when_sibling_is_invalid`, `test_database_failure_removes_only_that_files_original_and_preview`, `test_batch_request_limit_returns_standard_413`, and `test_original_and_display_routes_use_source_id_only`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/services/test_source_storage.py tests/api/test_sources.py -q)`; confirm storage and endpoint behavior is missing.
- [ ] **Step 3: Add Pillow>=11,<13 and implement safe atomic storage and per-file transactions.** Never log bytes, OCR content, paths, or source URLs. Make the oriented preview a separate generated artifact, not a mutation of the original.
- [ ] **Step 4: Run GREEN.** Re-run focused and full backend suites; verify valid siblings remain available after invalid/failed siblings and all test paths are below tmp_path.
- [ ] **Step 5: Commit** as `feat: add safe screenshot source upload`.

## Task 3: Replaceable OCR Adapter, Atomic Job Lifecycle, and Retry

**Files:**
- Create: backend/app/ocr/__init__.py
- Create: backend/app/ocr/adapter.py
- Create: backend/app/ocr/rapidocr_adapter.py
- Create: backend/app/repositories/ingestion.py
- Create: backend/app/services/ingestion.py
- Create: backend/app/services/candidate_builder.py with a conservative one-detection-per-candidate baseline
- Create: backend/app/api/v1/ingestions.py
- Create: backend/tests/services/test_ingestion.py
- Create: backend/tests/api/test_ingestions.py
- Modify: backend/requirements.txt
- Modify: backend/app/__init__.py
- Modify: backend/app/config.py
- Modify: backend/run.py for startup recovery only
- Create: backend/scripts/ocr_cpu_smoke.py

**Interfaces:**
- **Consumes:** Task 1 provenance models and Task 2 validated original/display storage.
- **Produces:** OCRAdapter/OCRDetection, lazy get_ocr_adapter(app), conditional claim, a complete run pipeline, job/status/block reads, explicit new-job retry, and a minimal conservative grouping seam refined in Task 4.
- Pin RapidOCR 3.9.2 and ONNX Runtime 1.30.0. Configure OCR_ENGINE=rapidocr_onnx, OCR_MODEL_DIR (default APP_DATA_DIR/ocr-models/rapidocr-3.9.2/ppocrv6-small), OCR_DETECTION_MODEL_PATH, OCR_RECOGNITION_MODEL_PATH, and optional OCR_CLASSIFICATION_MODEL_PATH. An adjacent manifest.json names the PP-OCRv6 small release and SHA-256 for every exact model file. Validate all files at startup/use. The adapter never invokes model download helpers; absent/changed files return a sanitized OCR_MODEL_MISSING or OCR_MODEL_INVALID job failure. Record adapter, runtime, model version/checksum, and CPU provider on each job. No GPU/MPS/CoreML path is implemented.
- The adapter opens the EXIF-oriented display pixels; it maps detector polygons to finite, normalized top-left xywh boxes and nullable confidence. The preview is generated once at upload so OCR and browser display use the same orientation. Only the adapter imports RapidOCR libraries.
- Claim queued work using one SQL conditional update where id matches and status=queued, setting running/stage=recognizing/started_at and recording adapter/runtime/model/provider metadata; commit before OCR. Exactly one concurrent request may claim it. A zero-row update reads current state and returns 409 CONFLICT; succeeded, failed, or already-running jobs are never rerun.
- Run image decode/OCR and pure candidate grouping outside a SQLite write transaction. Persist stage changes in short transactions. Finalization opens one explicit transaction guarded by status=running and stage=persisting_results; it inserts OCRBlocks, Questions with origin job and pending candidate state, QuestionSources, block links, and then sets candidate_count and succeeded/completed. A zero-detection result writes zero blocks/candidates and succeeds. Any grouping or finalization error rolls back all result rows and then records failed/failure_stage/sanitized error separately.
- This task's baseline grouping emits one editable candidate per detection so the run lifecycle can be exercised end to end. Task 4 replaces only grouping quality with tested multi-block/numbered rules; the atomic persistence and status contract stays unchanged.
- POST /sources/{id}/ingestions always creates a new queued attempt. GET /ingestions/{id}, GET /ocr-blocks, and GET /candidates expose state. Re-run is not a retry. The client timeout path is GET/poll only.
- Startup recovery in the single-process local runner changes leftover running jobs to failed, copies their persisted stage into failure_stage, records sanitized INGESTION_INTERRUPTED, and does not delete or reset data. No background worker, lease service, or broker is added.

**Acceptance:** one of two simultaneous run requests claims the job and the other gets 409; the full OCR result persists atomically with success; empty OCR succeeds; OCR/group/persist failure cannot leave blocks/candidates or a succeeded job; process interruption is recoverable; retry appends a new job and never mutates prior records.

- [ ] **Step 1: Write failing tests** `test_run_claim_is_atomic_under_two_requests`, `test_non_queued_run_returns_conflict`, `test_ocr_job_persists_engine_runtime_model_and_cpu_provider`, `test_empty_ocr_result_succeeds_with_zero_candidates`, `test_ocr_failure_records_stage_and_sanitized_error`, `test_candidate_group_failure_does_not_mark_job_succeeded`, `test_finalization_failure_rolls_back_blocks_questions_and_sources`, `test_retry_creates_new_job_and_new_block_ids`, `test_retry_preserves_old_question_source`, `test_startup_marks_orphaned_job_failed_and_preserves_last_stage`, `test_adapter_is_lazy_and_reused`, and `test_missing_model_fails_without_network_download`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/services/test_ingestion.py tests/api/test_ingestions.py -q)`; expected adapter, CAS, pipeline, and recovery assertions fail.
- [ ] **Step 3: Implement OCR adapter and job lifecycle with the conservative candidate-builder seam.** Keep recognition and grouping outside the final persistence transaction. Use short separate transactions only for claim/stage/failure; never commit partial OCRBlock/candidate results.
- [ ] **Step 4: Run GREEN.** Use FakeOCRAdapter for automated tests and the pinned local adapter using `(cd backend && conda run -n test python scripts/ocr_cpu_smoke.py IMAGE_PATH)` for a CPU smoke run. Verify no test downloads or network calls and failure responses contain no source text, path, traceback, or provider secret.
- [ ] **Step 5: Commit** as `feat: add atomic local OCR ingestion jobs`.

## Task 4: Rule-Based Multi-Question Candidate Building and Job History

**Files:**
- Modify: backend/app/services/candidate_builder.py
- Modify: backend/app/services/ingestion.py
- Modify: backend/app/repositories/ingestion.py
- Modify: backend/app/api/v1/ingestions.py
- Create: backend/tests/services/test_candidate_builder.py
- Modify: backend/tests/api/test_ingestions.py
- Create: backend/tests/fixtures/ocr/ with de-identified JSON OCR detections only

**Interfaces:**
- **Consumes:** Task 3 CandidateDraft/OCRDetection seam and atomic result persistence.
- **Produces:** build_candidate_groups(detections) and complete history query; all candidates for a job are returned, independent of their current review state.
- Candidate grouping is pure and rule-based. Sort detections by their assigned reading_order, using top-left geometry as a stable tie-breaker rather than input-array position. Numbered markers at the start of OCR text start groups; continuation blocks attach to the preceding question. When no numbered marker exists, split only when the vertical gap between adjacent blocks exceeds 1.8 times the median block height; otherwise keep a conservative combined candidate. When numbered groups exist, leading headers/titles remain visible OCRBlocks but do not become candidates. Ambiguous blocks are retained in an editable candidate rather than discarded. Multiple questions inside one OCR block may remain one imperfect candidate for human split. No AI/VLM, classification, difficulty, or duplicate logic is introduced.
- A Question is attributable to exactly one origin job. Candidate response includes candidate_state, candidate_revision, Question.status/archived_at, source asset ID, current/original locator, source_text_snapshot, raw OCR text, and stable OCRBlock IDs. Every candidate mutation request supplies expected_revision from this response. Default listing is all states; optional filters select pending_review, confirmed, rejected, superseded, or archived. Invalid filter is 400.
- A failed Job has no result rows because Task 3's final transaction rolls back as a unit. A successful empty job has zero OCRBlocks and zero candidates. Reprocessing creates another job; no candidate from an earlier job is changed.
- Fixtures cover numbered multi-question screenshot; one question across multiple OCR blocks; no numbering; title plus question text; Chinese/English technical terms; multiple questions within a single OCR block; a long screenshot; zero detected text; and out-of-order OCR blocks. For the latter, shuffle input-array order while keeping assigned reading_order correct and use geometry only as a stable tie-breaker. Include expected candidate count, full text, ordering, and bbox/source references. Fixtures contain no user screenshots or identifiable content.

**Acceptance:** candidate count/text/boundaries and regions pass all fixture cases; no OCR text disappears if grouping is uncertain; every successful job lists all original candidates after later state changes; candidate job ownership is stable; failed builds cannot claim success.

- [ ] **Step 1: Write failing tests** `test_numbered_multiline_questions_make_one_candidate_each`, `test_header_does_not_become_a_numbered_candidate`, `test_no_numbered_questions_use_conservative_spatial_groups`, `test_same_block_multiple_questions_remain_recoverable_for_manual_split`, `test_chinese_english_terms_are_preserved`, `test_long_screenshot_preserves_candidate_order_and_regions`, `test_empty_ocr_has_zero_candidates_and_succeeds`, `test_out_of_order_blocks_use_reading_order_and_geometry`, `test_candidate_query_includes_pending_confirmed_rejected_and_superseded`, `test_unconfirmed_candidate_is_absent_from_default_list_search_and_practice`, `test_candidate_status_filter`, `test_candidate_response_contains_original_source_and_stable_blocks`, and `test_candidate_query_is_scoped_by_origin_ingestion_job_id`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/services/test_candidate_builder.py tests/api/test_ingestions.py -q)`; verify each uncovered boundary fails for the expected reason.
- [ ] **Step 3: Implement rule-based grouping and all-state history query.** Do not edit OCRBlock, source snapshots, or previously persisted candidates while improving grouping for future jobs.
- [ ] **Step 4: Run GREEN.** Run fixture tests plus `(cd backend && conda run -n test pytest -q)`; verify all cited block IDs belong to the job/source and uncertain text remains visible.
- [ ] **Step 5: Commit** as `feat: group OCR blocks into traceable review candidates`.

## Task 5: Screenshot Inbox, Job Recovery UI, and Region Viewer

**Files:**
- Create: frontend/src/pages/InboxPage.vue
- Create: frontend/src/components/SourceUpload.vue
- Create: frontend/src/components/SourceImageViewer.vue
- Create: frontend/tests/inbox.spec.ts
- Modify: frontend/src/router/index.ts
- Modify: frontend/src/App.vue
- Modify: frontend/src/api/client.ts only for shared multipart/blob/status polling helpers

**Interfaces:**
- **Consumes:** Task 2 upload/original/display routes and Task 3–4 status, OCRBlock, and all-state candidate APIs.
- **Produces:** /inbox, per-source upload/job history, safe polling after request timeout, and image/highlight viewer consumed by Task 6 candidate actions.
- Batch upload shows one result per file. Queued jobs start sequentially. If POST run times out, query the same job and poll persisted status; do not infer failure and do not POST run again. A failed run's explicit retry creates a new job ID; earlier runs remain selectable.
- Reopening any historical job shows all candidate dispositions, source image preview, raw OCR text, and referenced blocks. Confirmed/rejected candidates remain available even when they are not in the default question bank.
- Viewer uses the generated oriented display preview. The selected candidate frame uses locator_correction_json when present, otherwise the immutable union of its OCRBlock boxes; individual OCRBlock outlines remain selectable by UUID. The overlay is positioned over the actual image content box, not the outer card/container. If object-fit: contain leaves letterbox space, compute the content rectangle and offsets from the rendered/natural dimensions; normalized bbox math uses only that content rectangle. Stable OCRBlock UUIDs, never array indexes, key the boxes.
- Original-byte retrieval remains available separately. The UI identifies the displayed image as an orientation-normalized view of the unchanged original evidence.

**Acceptance:** single/multi upload, per-image failure isolation, retry via new job, timeout status recovery, historical all-candidate view, raw text, and accurate region overlay across EXIF and container aspect ratios.

- [ ] **Step 1: Write failing Vue/API mock tests** `renders_single_and_multi_file_upload`, `shows_each_file_result_independently`, `continues_ocr_queue_after_one_job_fails`, `request_timeout_queries_job_without_rerunning`, `retries_with_new_job_id_only_after_explicit_action`, `shows_all_candidates_for_historical_job`, `renders_original_and_ocr_evidence`, `highlights_by_stable_block_id`, `maps_boxes_to_content_rect_with_contain_letterboxing`, `maps_boxes_after_exif_orientation`, `handles_portrait_image_in_wide_and_tall_containers`, and `shows_source_metadata`.
- [ ] **Step 2: Run RED.** `npm --prefix frontend test -- tests/inbox.spec.ts`; confirm route, polling, history, and overlay cases fail.
- [ ] **Step 3: Implement the minimal Inbox and viewer.** Use FormData without overriding multipart boundaries; calculate image-content bounds from actual rendered geometry and ResizeObserver/image load; retain per-file outcomes.
- [ ] **Step 4: Run GREEN.** Run focused tests and frontend build. Include component tests for EXIF-rotated JPEG, ordinary PNG, 1080×1800 portrait screenshot, and contain letterboxing in wide/tall containers.
- [ ] **Step 5: Commit** as `feat: add screenshot inbox and source region viewer`.

## Task 6: Candidate Edit, Split/Merge, Confirm, and Question Sources

**Files:**
- Create: backend/tests/api/test_ingestion_candidates.py
- Create: backend/tests/api/test_question_sources.py
- Modify: backend/app/repositories/ingestion.py
- Modify: backend/app/repositories/questions.py
- Modify: backend/app/services/ingestion_candidates.py
- Modify: backend/app/api/v1/ingestions.py
- Modify: backend/app/api/v1/questions.py
- Create: frontend/src/components/IngestionCandidateEditor.vue
- Modify: frontend/src/pages/InboxPage.vue
- Modify: frontend/src/pages/QuestionDetailPage.vue
- Modify: frontend/tests/inbox.spec.ts
- Modify: frontend/tests/questions.spec.ts

**Interfaces:**
- **Consumes:** Task 1 provenance/disposition fields, Task 4 all-state history query, Task 5 viewer, and Phase 1A active Topic/Tag validation.
- **Produces:** transactional edit/split/same-job candidate merge/reject/confirm APIs and Question source-history display.
- Every mutation request includes the revision from the candidate response as expected_revision and validates candidate origin job, Question.status=pending_review, archived_at is null, and ingestion_candidate_state=pending_review. Confirm additionally requires job status=succeeded. A conditional UPDATE matches the expected revision and prior state, then increments candidate_revision for edit, split, merge, reject, and confirm; a concurrent or repeated operation returns 409 and cannot replace a confirmed or edited result.
- PATCH edits Question.text, active Topic/Tag associations, and locator_correction_json only. It rejects locator values that are nonnumeric, nonfinite, outside [0,1], nonpositive in width/height, or whose right/bottom edge exceeds 1. It never rewrites OCRBlock, source_text_snapshot, raw_ocr_text_snapshot, or original locator_json.
- Split requires two or more nonempty parts. Every OCRBlock UUID must belong to the path job and its SourceAsset and must be evidence on the source candidate. The same OCRBlock may appear in more than one part. The request source_text_snapshot must be an excerpt of the selected raw OCR blocks; edited Question.text remains separate. The transaction creates/updates all parts and QuestionSource rows, stores each exact excerpt plus full original OCR text and the immutable locator computed from block geometry, and keeps optional locator_correction_json separate. The original candidate lineage remains visible.
- Merge accepts pending candidates whose origin_ingestion_job_id equals the path job. It cannot call or reuse canonical Question merge. In one transaction, survivor text/evidence is updated, source snapshots and block links are added, and each absorbed candidate remains as an archived superseded row pointing to the survivor. Cross-job/cross-source block references are 400; changed/confirmed participants are 409.
- Exact mutation bodies: PATCH /ingestion-candidates/{id} accepts expected_revision and optional text/topic_ids/tag_ids/locator_correction_json; POST /ingestions/{job_id}/candidates/{candidate_id}/split accepts expected_revision and parts[{text, ocr_block_ids, source_text_snapshot, locator_correction_json}]; POST /ingestions/{job_id}/candidates/merge accepts survivor_id, candidates[{id, expected_revision}], and final_text; candidate archive/confirm POSTs accept expected_revision. Candidate read responses include revision. A 409 makes the UI refresh current state before another action.
- Reject/archive preserves the Question and source relations, sets archived_at and candidate state rejected. Confirm validates text and active Topic/Tag IDs, ensures QuestionState exists, and atomically changes Question.status to active plus candidate state confirmed. Neither action deletes OCR evidence.
- GET /questions/{id}/sources returns metadata, immutable source excerpt/raw snapshots, original locator, optional correction, and stable block text/IDs. Archived assets remain available because the source route is ID-based.
- Each edit/split/merge/archive/confirm service owns exactly one SQLAlchemy transaction. No API route performs multi-step database writes directly. Any failure rolls back Question, taxonomy links, sources, block links, disposition, and status together.

**Acceptance:** every mutation is pending-only and same-job scoped; all locator/block ownership checks work; confirm/reject/merge remain visible in job history; concurrent state changes return 409; a DB error leaves no orphan Question/QuestionSource/block association; confirmed Questions use existing search and PracticeSession paths.

- [ ] **Step 1: Write failing backend tests** `test_edit_rejects_non_pending_or_wrong_job_candidate`, `test_stale_candidate_revision_returns_conflict`, `test_candidate_revision_increments_on_edit`, `test_edit_validates_finite_normalized_locator`, `test_split_rejects_block_from_other_job`, `test_split_rejects_excerpt_not_present_in_raw_ocr`, `test_split_allows_shared_block_and_keeps_excerpt_raw_text_and_original_locator`, `test_merge_rejects_cross_job_candidate`, `test_merge_and_confirm_race_has_one_winner_and_stale_revision_conflicts`, `test_repeated_confirm_returns_conflict`, `test_candidate_mutation_failure_rolls_back_all_relations`, `test_candidate_edit_does_not_mutate_ocrblock_or_source_snapshot`, `test_confirmed_and_rejected_candidates_remain_in_job_history`, `test_superseded_candidate_remains_in_job_history`, `test_confirmed_question_returns_to_search_and_practice`, and `test_question_source_history_opens_original_and_display_images`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/api/test_ingestion_candidates.py tests/api/test_question_sources.py -q)`; run `npm --prefix frontend test -- tests/inbox.spec.ts tests/questions.spec.ts`.
- [ ] **Step 3: Implement transactional candidate services.** Reuse Question text normalization and Topic/Tag validation. Use CAS/rowcount and same-job/source ownership checks; never update OCR evidence fields.
- [ ] **Step 4: Write failing UI tests** `edits_candidate_without_changing_ocr_snapshot`, `splits_selected_candidate_with_source_excerpt`, `merges_only_candidates_from_one_job`, `requires_explicit_confirm`, `shows_confirmed_rejected_and_superseded_history`, and `shows_confirmed_source_in_question_detail`.
- [ ] **Step 5: Implement the editor and source history panel.** Show editable question text beside immutable OCR source excerpt; expose manual classification, locator correction, split/merge/reject/confirm controls.
- [ ] **Step 6: Run GREEN.** Focused tests, `(cd backend && conda run -n test pytest -q)`, `npm --prefix frontend test`, and frontend build; verify only confirmed active questions appear in 1A search/practice.
- [ ] **Step 7: Commit** as `feat: edit and confirm OCR question candidates`.

## Task 7: Phase 1B Acceptance, Source Cleanup, and Runbook

**Files:**
- Create: backend/tests/api/test_phase_1b_flow.py
- Create: backend/tests/api/test_source_deletion.py
- Modify: backend/app/services/source_storage.py
- Modify: backend/app/api/v1/sources.py
- Modify: backend/run.py or a focused startup recovery service
- Modify: frontend/tests/inbox.spec.ts
- Modify: README.md

**Interfaces and safety rules:**
- **Consumes:** complete SourceAsset, ingestion, candidate, confirmation, and source-history contracts from Tasks 1–6.
- **Produces:** full Phase 1B acceptance flow, small tombstone consistency/recovery, no-history source deletion, local OCR setup/runbook, and manual real-browser visual verification.
- DELETE /sources/{id} is allowed only when there are no QuestionSources, no Questions with origin_ingestion_job_id, and no attempted OCR job/history. An untouched queued job can be removed with its source. Running/succeeded/failed jobs, OCRBlocks, candidate history, and any citation return 409; use archive instead.
- For allowed deletion, write a small tombstone journal containing generated asset ID and relative original/preview paths, move both files to same-filesystem tombstones, and delete the guarded DB rows in one transaction. On DB failure, roll back and restore both originals immediately. On startup, reconcile residual journal entries: if SourceAsset still exists, restore the files; if the DB delete committed and the row is gone, remove tombstones/journal. Never overwrite an unexpected existing file; report a sanitized consistency error and preserve both copies for manual recovery. This is a narrow SourceAsset mechanism, not a generic filesystem transaction framework.
- README documents Conda test, pinned runtime packages, how to prepare/copy the exact PP-OCRv6 small model files and verify manifest SHA-256, OCR_ENGINE/OCR_MODEL_DIR and explicit model paths, no-download behavior, initialization, the offline command `(cd backend && conda run -n test python scripts/ocr_cpu_smoke.py IMAGE_PATH)`, storage location/limits, queue timeout handling, retry creates new job, interrupted job recovery, and data backup. Tests never access pic-test or real data directories.
- Automated OCR segmentation tests use de-identified OCR detection fixtures and FakeOCRAdapter. User-provided pic-test images remain untracked and are used only for manual acceptance. Manual acceptance checks both supplied images and additional representative local samples without adding them to Git.
- Real-browser visual check loads an EXIF-rotated JPEG, ordinary PNG, and tall screenshot in wide and narrow viewer containers. Inspect highlighter edges against actual question text at 100% zoom; record pass/fail in the task checklist. Component tests alone do not satisfy this visual acceptance.

**Acceptance:** fresh 1A→1B migration; full upload → local OCR → candidate edit/split/merge/reject/confirm → existing search/practice; no lost/replaced history; per-image isolation; restart recovery; source deletion consistency; offline model verification; backend/frontend tests and manual browser overlay inspection.

- [ ] **Step 1: Write failing end-to-end/deletion/recovery tests** `test_phase1b_upload_ocr_review_confirm_and_practice_flow`, `test_batch_upload_failure_does_not_affect_other_image`, `test_upload_timeout_queries_job_and_does_not_duplicate_run`, `test_retry_does_not_overwrite_old_blocks_or_confirmed_source`, `test_archived_source_keeps_question_image_access`, `test_delete_source_with_candidate_or_question_source_returns_409`, `test_delete_source_with_attempted_job_history_returns_409`, `test_unreferenced_queued_source_delete_removes_generated_files_and_rows`, `test_db_failure_restores_original_and_preview_from_tombstone`, `test_restart_recovers_tombstone_when_row_exists`, and `test_restart_cleans_tombstone_after_committed_delete`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/api/test_phase_1b_flow.py tests/api/test_source_deletion.py -q)`; run frontend inbox tests.
- [ ] **Step 3: Implement only guarded no-history deletion and focused recovery.** Keep archive as the normal cleanup path. Do not add dependency-wide Question/history deletion.
- [ ] **Step 4: Run automated GREEN.** Fresh Alembic database, `(cd backend && conda run -n test pytest -q)`, `npm --prefix frontend test`, and `npm --prefix frontend run build`; verify temporary DB/files stay under tmp_path and 1A behavior remains intact.
- [ ] **Step 5: Run manual real-image and browser acceptance.** Process the two supplied pic-test screenshots with the configured local CPU model; review candidate counts/text and source locators. Additional segmentation cases are covered by the de-identified fixtures. In a real browser inspect EXIF rotation, normal PNG, portrait long screenshot, and letterboxing in different container ratios; verify boxes cover the intended visible text. Do not commit those source screenshots.
- [ ] **Step 6: Write and verify README runbook.** Follow its exact setup, model checksum, offline smoke, app restart, batch, and retry commands using Conda test.
- [ ] **Step 7: Commit** as `feat: add source cleanup recovery and OCR runbook`.

## Phase 1B Invariants / Acceptance Rules

1. Original upload bytes and SHA-256 never change; the display preview is a separate EXIF-normalized lossless rendering.
2. OCRBlock UUID, text, bbox, reading order, source excerpt, raw OCR snapshot, and original locator are immutable after persistence.
3. Every OCR candidate, including split/merged/rejected/confirmed rows, keeps origin_ingestion_job_id; Phase 1A manual questions keep it null.
4. Reopening an OCR Job returns all its candidate rows by default, including pending, confirmed, rejected, and superseded; status filters do not remove history from storage.
5. Re-OCR/retry creates a new Job and new OCRBlock UUIDs and never mutates old candidates or QuestionSources.
6. Job status succeeded means OCR, candidate grouping, and atomic persistence all finished. Empty OCR is a valid succeeded result with zero candidates.
7. OCRBlocks, Questions, QuestionSources, block links, candidate_count, and succeeded state commit in one transaction; a failed group/persist leaves no partial result rows or false success.
8. Only one concurrent request can claim a queued Job. Duplicate execution is 409; a browser timeout queries the same Job and never reruns it.
9. A process-interrupted running Job is marked failed/interrupted on startup; recovery preserves old data and retry creates a new Job.
10. Split/Merge block UUIDs must belong to the same Job and SourceAsset. Candidate Merge remains an inbox correction and never sets Question.status=merged or invokes canonical Question Merge.
11. Candidate edit/split/merge/reject/confirm operates only on the still-pending unarchived candidate at the expected revision and is transactional; racing actions cannot overwrite a winner.
12. A split may cite one OCRBlock from multiple candidates while retaining each excerpt, full raw OCR text, original locator, and stable block ID.
13. Locator correction accepts only finite normalized x/y/width/height, positive dimensions, all values in range, and edges no greater than 1; it never overwrites the original locator.
14. Pending, rejected, superseded, and archived OCR candidates remain excluded from the default 1A Question list, search, and all new PracticeSessions.
15. Only explicit confirmation makes a candidate active and eligible for existing Question search and PracticeSession. Every candidate mutation uses expected_revision and increments candidate_revision.
16. Batch item upload/OCR failure is isolated; one failed image cannot roll back successful siblings.
17. Source deletion is possible only before any OCR attempt/candidate/source citation; tombstone failure or process exit restores consistency without deleting evidence. Archive never deletes evidence.
18. OCR model versions/checksums are recorded; missing or changed local models fail clearly without network download. Automated tests use FakeOCRAdapter.
19. EXIF orientation used for OCR, preview rendering, and browser overlay is identical. Overlay coordinates scale to visible image content, excluding contain letterbox padding.
20. Test databases and source files are isolated under tmp_path; real user screenshots remain untracked.
21. Existing Phase 1A API/error schema, taxonomy validation, FTS, Question search, favorite/wrong state, and PracticeSession selector keep working unchanged.

## Scope Boundary

Phase 1B implements only: local image upload; SourceAsset metadata and original file storage; one IngestionJob per image/run; replaceable local OCR adapter; stable OCRBlock IDs and normalized regions; rule-based multi-question candidate grouping; Inbox view with source image/highlights; manual candidate text correction, split/merge/archive, manual Topic/Tag selection, and explicit confirmation; Question source history; source archive and no-reference delete; Phase 1B tests and runbook.

Do not implement Phase 1C: VLM/LLM boundary detection, automatic Topic/Tag/difficulty suggestions, duplicate hash candidates, n-gram/trigram similarity, same/related/different semantic decisions, Question B→A canonical merge, or automatic merge. Also do not implement social-platform collection, SavedAnswer, Project/Resume/Material, reference answers, mock interview, general workers, Celery/Redis, vector databases, or GPU as a requirement.

## Plan Self-Review

- **Phase boundary:** Tasks 1–7 add only local screenshots, source files, OCR, rule-based candidate grouping, candidate review, confirmation, and traceable history. No Phase 1C auto-classification, LLM/VLM, semantic duplicate merge, SavedAnswer, Project/Material, mock interview, social collection, GPU, Redis/Celery, or vector database is scheduled.
- **Phase 1A compatibility:** Migration adds nullable provenance for old manual Questions; it preserves Question.status, archived_at, FTS, taxonomy, search, and PracticeSession contracts. Pending/rejected candidate rows remain excluded until explicit confirmation.
- **Job state and atomicity:** queued is claimed by one conditional update; OCR/grouping happen outside long transactions; OCRBlocks, candidates, sources, links, and succeeded status commit together. Empty detection succeeds with count zero. Failures retain stage and sanitized error. Startup recovery handles stranded running jobs without resetting them.
- **Historical query:** origin_ingestion_job_id remains on every OCR candidate. Candidate API defaults to all states and filters without losing old rows. Candidate split/merge keeps source snapshots and block UUIDs; retry creates new job/block IDs.
- **Concurrency and lifecycle:** duplicate run, duplicate confirm, Confirm/Merge races, and stale candidate updates are covered by conditional updates and 409 responses. Every candidate mutation is one transaction with rollback tests. Startup recovery only runs in the single local server process entrypoint, not every Flask app-factory invocation.
- **Image coordinates:** original bytes are immutable; a lossless EXIF-normalized preview is used by OCR and browser. Viewer math uses the actual image-content rectangle and tests letterbox offsets, portrait images, EXIF rotation, and real-browser overlay alignment.
- **OCR quality:** retain the two supplied screenshot benchmarks and add de-identified fixture coverage for nine segmentation cases. FakeOCRAdapter keeps automated tests offline; no user screenshot is checked in.
- **Model operations:** exact RapidOCR/ONNX/model versions, local paths, checksums, no-download behavior, offline startup, and CPU smoke are documented. CPU remains the sole supported execution path for this phase.
- **File/DB consistency:** permanent delete is limited to never-attempted, unreferenced uploads; a narrow tombstone journal restores files after DB rollback or startup interruption. Archive stays the expected cleanup operation.
- **Task readiness:** each Task has named files/interfaces, RED/GREEN commands, acceptance tests, and one commit. Task 3 defines the complete atomic lifecycle seam; Task 4 improves grouping without changing success semantics. Task 7 verifies all cross-task behavior and 1A regression.

**Self-review result:** no remaining planned gap was found in OCR state semantics, transaction boundaries, concurrent execution, candidate provenance, image orientation, sample coverage, local model deployment, delete recovery, or Phase 1A compatibility. This document is the frozen Phase 1B execution version; implementation must follow Tasks 1–7 in order and use real usage feedback before expanding scope.

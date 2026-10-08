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
- **Job races and interruption:** duplicate run requests cannot start duplicate OCR; a timeout checks persisted status; a terminated process cannot leave a permanently running job. Startup recovery runs once only in the supported non-reloading entrypoint.
- **Existing API bypasses:** a pending OCR candidate cannot be edited, archived, or assigned QuestionState through generic Phase 1A routes; confirmed/manual active Questions retain their existing API behavior.

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
- Question gains nullable origin_ingestion_job_id (FK to IngestionJob, RESTRICT), nullable ingestion_candidate_state, candidate_revision (integer, initially 0), nullable split_from_candidate_id, and nullable superseded_by_candidate_id. Phase 1A manual questions keep provenance and lineage fields null. OCR candidates use pending_review, confirmed, rejected, or superseded as candidate disposition while existing Question.status remains pending_review or active; Question.status=merged remains reserved for Phase 1C canonical merge. Both lineage fields are self-FKs with RESTRICT, cannot point to the same Question, and require a non-null origin job; candidate services enforce that parent/supersession rows share the same job.
- Candidate state mapping: new OCR candidates are pending_review; confirmation atomically changes Question.status to active and disposition to confirmed; reject/archive keeps Question.status=pending_review and sets archived_at plus disposition=rejected. On Split A→B,C, A remains Question.status=pending_review, archived, and superseded with no single superseded_by link, while new B and C are pending Questions with split_from_candidate_id=A. On Merge B→A, B remains Question.status=pending_review, archived/superseded with superseded_by_candidate_id=A and A remains pending. Neither operation sets Question.status=merged; no lineage row is deleted.
- QuestionSource links Question to SourceAsset and stores extensible locator_type (image_region in Phase 1B; future locator types are not implemented now), locator_json as the immutable original locator, nullable locator_correction_json for a user-adjusted display box, immutable source_text_snapshot (the exact OCR excerpt attributed to this candidate), immutable raw_ocr_text_snapshot (the full text of its cited OCRBlocks), confidence, and created_at. QuestionSourceOCRBlock links stable OCRBlock IDs. Manual Question.text edits never rewrite those snapshots or OCRBlocks.
- Initial candidates may cite several OCRBlocks; split children may share one block. Split creates a new QuestionSource for each child with its excerpt, raw OCR snapshot, block links, and original locator; the parent’s QuestionSource rows remain untouched. Merge creates new QuestionSource rows on the survivor by copying the absorbed candidate’s source snapshots, original/corrected locators, and OCRBlock associations; it never changes an old QuestionSource.question_id or deletes it. Split/merge lineage is returned in the existing job candidate query through split_from_candidate_id, child IDs, and superseded_by_candidate_id; no event log or version-history subsystem is added.
- Candidate job ownership is authoritative: all OCR-created Questions have origin_ingestion_job_id. GET /api/v1/ingestions/{id}/candidates returns every row for that job by default, including pending, confirmed, rejected, and superseded rows, source rows, split parent/children, and superseded target. A status query accepts all, pending_review, confirmed, rejected, superseded, or archived. Phase 1A manual Questions are never returned by this endpoint.
- POST /api/v1/sources accepts repeated multipart files and optional metadata JSON; each file gets an independent SourceAsset and queued IngestionJob transaction. Its HTTP 200 response has one input-ordered result per file: stored entries include source/job IDs, rejected entries include the shared error code/message/fields, and one rejection does not roll back siblings. GET /sources, GET/PATCH /sources/{id}, archive, GET /sources/{id}/original, and GET /sources/{id}/display use opaque IDs; neither original_path nor preview_path is serialized. The original route returns exact stored bytes; display returns the EXIF-normalized lossless preview.
- POST /api/v1/ingestions/{id}/run is accepted only when an atomic conditional update changes queued to running. A second request for the same job gets 409 CONFLICT and starts no OCR. After a network timeout, the UI queries GET /ingestions/{id}; it never re-runs that job. A user retry creates a new job with POST /sources/{id}/ingestions.
- Job state sequence: queued → running/initializing_adapter → running/recognizing → running/building_candidates → running/persisting_results → succeeded/completed. For normal failures, status becomes failed and failure_stage records recognizing, building_candidates, or persisting_results; stage is not overwritten, so the failed phase remains visible. For startup recovery, failure_stage copies the persisted running stage and error_code is INGESTION_INTERRUPTED. Only OCR recognition and in-memory candidate grouping happen outside a database transaction. One final transaction writes all OCRBlocks, candidate Questions, QuestionSources, OCRBlock links, candidate_count, and succeeded status. A zero-detection OCR result is a valid succeeded job with zero candidates. Any OCR/grouping/persistence error leaves no partial OCRBlock or candidate result set, then records failed plus failure_stage and a sanitized error in a separate short transaction. If that failure update also cannot commit, the startup recovery marks the leftover running job interrupted.
- The run endpoint does not report success until candidate persistence commits. create_app registers only a lazy OCR adapter factory; it never loads or validates OCR models during Flask app startup. After queued→running is committed, adapter/model initialization occurs at stage initializing_adapter. Missing files or manifest/checksum errors set status=failed, failure_stage=initializing_adapter, and OCR_MODEL_MISSING/OCR_MODEL_INVALID in a short transaction, so the job cannot remain queued/running and question-bank/health routes stay usable. Adapter, runtime, model manifest release/checksum, and CPU provider are recorded at claim time so failed as well as successful attempts identify the attempted OCR stack. Candidate creation has a conditional running/stage guard; a succeeded job cannot generate candidates again. A successful response includes persisted job status/count; known OCR failures return persisted failed state. Invalid job states and duplicate execution use the common error envelope.
- No worker is introduced. The only supported app entrypoint is backend/run.py in one Flask process. It invokes startup reconciliation exactly once inside the main entrypoint before serving, with use_reloader=False in normal and debug modes. create_app and Flask CLI imports do not run reconciliation. Startup changes jobs left running by a prior process to failed, copies the last persisted stage into failure_stage, and records sanitized INGESTION_INTERRUPTED. It does not delete artifacts. Users inspect the old run and create a new retry job; the old job is never reset or reused.
- OCR adapter contract: OCRDetection(id: UUID, text, bbox, confidence, reading_order, block_type), OCRAdapter.name/version/recognize(image). UUIDs are assigned before candidate grouping; groups reference UUIDs, never array indexes. RapidOCR types remain in the adapter only. RapidOCR 3.9.2 + ONNX Runtime 1.30.0 + PP-OCRv6 small model files are pinned. Configure OCR_ENGINE=rapidocr_onnx, OCR_MODEL_DIR (default APP_DATA_DIR/ocr-models/rapidocr-3.9.2/ppocrv6-small), OCR_DETECTION_MODEL_PATH, OCR_RECOGNITION_MODEL_PATH, and optional OCR_CLASSIFICATION_MODEL_PATH. An adjacent manifest.json records the model release and SHA-256 of each exact file. The runtime validates paths/checksums and never downloads models implicitly. The job records adapter, runtime, model release/checksum, and CPU provider.
- Candidate Split and Merge accept only same-job, unarchived candidates with Question.status=pending_review, disposition=pending_review, and the supplied current expected_revision. A parent/loser becomes superseded, so repeating its Split/Merge conflicts; a pending merge survivor may accept a later intentional merge only with its latest revision. Every submitted OCRBlock UUID must belong to the request Job and SourceAsset. Candidate merge is inbox correction, not canonical Question merge. Locator corrections must be finite normalized values with positive width/height and right/bottom edges at most 1. A locator correction names its QuestionSource ID and may change only that row’s locator_correction_json.
- Each candidate operation is one database transaction. Split, merge, edit, reject, and confirm use expected_revision plus conditional state updates; a concurrent or duplicate request returns 409 without overwriting state. Database exceptions roll back Question, QuestionSource, topic/tag links, and block-link rows together.
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
- **Produces:** SourceAsset, IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock; Question.origin_ingestion_job_id, Question.ingestion_candidate_state, candidate_revision, split_from_candidate_id, and superseded_by_candidate_id; Alembic revision 0003.
- Add nullable self-FKs split_from_candidate_id and superseded_by_candidate_id on Question with RESTRICT; add indexes, nonnegative candidate_revision check, and checks that lineage cannot self-reference and requires an origin_ingestion_job_id. Do not add a lineage/history table. Phase 1A manual Questions migrate with both lineage fields and OCR provenance null.
- Candidate services verify that split parent and superseded target have the same origin_ingestion_job_id. A Split child may also later become superseded by a same-job Merge survivor, so split_from_candidate_id and superseded_by_candidate_id may both be populated on a child.
- Candidate state is nullable for manual questions and constrained to pending_review/confirmed/rejected/superseded for OCR candidates. Question.status remains pending_review/active/merged; inbox Split/Merge never uses status=merged. candidate_revision defaults to 0, cannot be negative, and increments on each candidate mutation. SHA-256 and normalized_hash are ordinary non-unique indexes.
- Preserve existing 1A FTS virtual table/triggers, Questions, taxonomy, PracticeSessions, SessionItems, PracticeReviews, and normalized_hash index. New QuestionSource rows have their own IDs and restrictive source/block FKs so Split/Merge can add evidence without repointing old rows.

**Acceptance:** fresh and existing 1A databases upgrade to head; manual Questions keep null OCR provenance/lineage; parent/child and superseded FKs exist; self-links are rejected; duplicate hashes remain legal; FK violations are rejected; test data remains under tmp_path.

- [ ] **Step 1: Write failing tests** `test_phase1b_migration_upgrades_existing_1a_database_without_data_loss`, `test_question_lineage_columns_have_nullable_restrictive_fks`, `test_manual_question_keeps_null_ingestion_provenance_and_lineage`, `test_candidate_revision_defaults_to_zero_and_cannot_be_negative`, `test_candidate_lineage_rejects_self_reference`, `test_ocr_block_uses_stable_uuid_primary_key`, `test_source_sha256_and_question_normalized_hash_are_not_unique`, and `test_source_storage_root_is_under_configured_app_data_dir`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/test_migrations.py tests/test_phase1b_models.py -q)`; expect missing schema/constraint assertions to fail.
- [ ] **Step 3: Implement SQLAlchemy models and Alembic revision 0003.** Keep same-job checks in candidate services; preserve 1A status/defaults and existing data. Add indexes for origin job, split parent, superseded target, job/source, and OCR reading order.
- [ ] **Step 4: Run GREEN.** Run the focused migration/model tests and backend suite against temporary databases; verify existing 1A Question, QuestionState, SessionItem, and PracticeReview rows survive.
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
- Create: backend/scripts/ocr_cpu_smoke.py
- Modify: backend/requirements.txt
- Modify: backend/app/__init__.py
- Modify: backend/app/config.py
- Modify: backend/run.py for the single supported startup and one-time recovery

**Interfaces:**
- **Consumes:** Task 1 provenance models and Task 2 validated original/display storage.
- **Produces:** OCRAdapter/OCRDetection, lazy get_ocr_adapter(app), conditional claim, complete run pipeline, status/block reads, explicit new-job retry, local runtime compatibility report, and CPU smoke command.
- Keep RapidOCR 3.9.2, ONNX Runtime 1.30.0, and PP-OCRv6 small unchanged unless the pinned versions fail a reproducible compatibility/smoke check. Configure OCR_ENGINE, OCR_MODEL_DIR and explicit detector/recognizer paths; validate local manifest/checksums. Runtime never downloads models implicitly. Current inspection of Conda test reports Python 3.12.15, macOS 27.0.1, arm64; RapidOCR and ONNX Runtime are not installed there, so this plan does not claim that this environment has passed compatibility or offline OCR yet.
- The CPU smoke command reports Python version, macOS version, CPU architecture, RapidOCR/ONNX Runtime versions, available ONNX providers, model release/checksum, and OCR completion against a supplied local image. It runs using only explicit local model paths and contains no downloader. If the pinned stack is incompatible, record the actual import/wheel/provider error and stop before changing the pin; only evidence from this check can justify a version adjustment.
- OCRAdapter factory registration is lazy: create_app stores a callable/config only and does not import or initialize model runtimes. POST /ingestions/{id}/run first atomically claims and commits the Job, persists stage=initializing_adapter, then calls get_ocr_adapter. Missing files map to OCR_MODEL_MISSING; manifest/checksum mismatch maps to OCR_MODEL_INVALID. Both are caught after claim and persist status=failed, failure_stage=initializing_adapter, sanitized error, and completed_at. Health and Phase 1A question APIs remain usable without OCR models.
- After initialization, stage advances to recognizing and recognition runs outside a DB write transaction. Grouping and final persistence retain Task 3’s existing atomic contract. A missing model must never leave a Job queued or running. An initialized adapter is cached and reused within the process.
- Supported app startup is only `conda run -n test python run.py` from backend. run.py calls interrupted-job recovery exactly once inside its main entrypoint before serving and always uses use_reloader=False. create_app and import through Flask CLI do not run recovery. Flask CLI/automatic reloader and multiple server processes are unsupported. If debug mode is enabled through run.py, use_reloader remains false. No distributed lock, lease, worker, or broker is added.
- Startup recovery only marks jobs left running by a prior server process as failed; it copies the last committed stage into failure_stage and sets INGESTION_INTERRUPTED. It is idempotent and is not called by each app-factory invocation or a reload child.

**Acceptance:** one of two simultaneous requests claims a queued Job; model initialization failure after claim persists a failed Job with the right error; app/health/question bank start and work without models; the recovery hook runs once only in the supported entrypoint; current environment details are recorded; the pinned stack completes one actual offline CPU smoke test before accepting the OCR runtime.

- [ ] **Step 1: Write failing tests** `test_run_claim_is_atomic_under_two_requests`, `test_non_queued_run_returns_conflict`, `test_ocr_job_persists_engine_runtime_model_and_cpu_provider`, `test_empty_ocr_result_succeeds_with_zero_candidates`, `test_finalization_failure_rolls_back_blocks_questions_and_sources`, `test_retry_preserves_old_question_source`, `test_create_app_does_not_initialize_ocr_models`, `test_app_starts_and_question_api_works_without_models`, `test_model_initialization_failure_after_claim_marks_job_failed`, `test_missing_and_invalid_models_use_expected_error_codes`, `test_app_factory_does_not_run_startup_recovery`, and `test_supported_runner_recovers_once_with_reloader_disabled`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/services/test_ingestion.py tests/api/test_ingestions.py -q)`; confirm the adapter, post-claim failure, and startup-boundary tests fail for the expected reasons.
- [ ] **Step 3: Implement adapter and lifecycle.** Catch model initialization after atomic claim; use short transactions for stage/error updates; never commit partial OCRBlock/candidate results.
- [ ] **Step 4: Run GREEN and runtime compatibility check.** Record sys.version, macOS release, arm64/x86_64, RapidOCR/ONNX Runtime versions and CPUExecutionProvider. With configured local model files and network unavailable, run `(cd backend && conda run -n test python scripts/ocr_cpu_smoke.py --offline IMAGE_PATH)` and verify OCR completes on CPU without download. Keep existing version pins if this passes.
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

- [ ] **Step 1: Write failing tests** `test_numbered_multiline_questions_make_one_candidate_each`, `test_header_does_not_become_a_numbered_candidate`, `test_no_numbered_questions_use_conservative_spatial_groups`, `test_same_block_multiple_questions_remain_recoverable_for_manual_split`, `test_chinese_english_terms_are_preserved`, `test_long_screenshot_preserves_candidate_order_and_regions`, `test_empty_ocr_has_zero_candidates_and_succeeds`, `test_out_of_order_blocks_use_reading_order_and_geometry`, `test_candidate_query_includes_pending_confirmed_rejected_and_superseded`, `test_candidate_query_returns_split_parent_children_and_superseded_target`, `test_unconfirmed_candidate_is_absent_from_default_list_search_and_practice`, `test_candidate_status_filter`, and `test_candidate_query_is_scoped_by_origin_ingestion_job_id`.
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
- **Consumes:** Task 2 upload/display routes and Task 3–4 job status, OCRBlock, and all-state candidate APIs.
- **Produces:** /inbox, per-source/job history, timeout-safe polling, source selection, and image/highlight viewer.
- Batch upload shows one result per image; queued jobs run sequentially. A POST timeout triggers GET/poll of that same job and never repeats /run. Explicit retry creates a new job ID.
- A candidate may hold several QuestionSources, including multiple regions in one screenshot. Show a source-row selector keyed by question_source_id; group rows by source_asset_id and show that asset’s oriented preview. Each row displays its immutable original locator and current correction. Selecting a row focuses its locator and cited OCRBlocks. The candidate’s default highlight is the union of all effective locators for the currently displayed SourceAsset; do not union coordinates from different assets.
- Overlay uses the actual displayed image content box, not the outer card. For object-fit:contain, account for letterbox offsets and use only the rendered image rectangle. UUIDs, never list indexes, key OCRBlock boxes. Original bytes remain separately viewable/retrievable.

**Acceptance:** upload, per-image progress/failure, retry, timeout recovery, historical job/candidate view, multi-QuestionSource selection, selected-region highlight, and candidate-wide union highlight all work across EXIF and container aspect ratios.

- [ ] **Step 1: Write failing tests** `renders_single_and_multi_file_upload`, `continues_ocr_queue_after_one_job_fails`, `request_timeout_queries_job_without_rerunning`, `shows_all_candidates_for_historical_job`, `selects_question_source_by_id`, `switches_source_asset_for_selected_source`, `highlights_selected_question_source_region`, `candidate_highlight_unions_effective_regions_for_one_asset`, `candidate_highlight_does_not_union_different_assets`, `highlights_by_stable_block_id`, `maps_boxes_to_content_rect_with_contain_letterboxing`, `maps_boxes_after_exif_orientation`, and `handles_portrait_image_in_wide_and_tall_containers`.
- [ ] **Step 2: Run RED.** `npm --prefix frontend test -- tests/inbox.spec.ts`; confirm history, source selection, polling, and overlay assertions fail.
- [ ] **Step 3: Implement the Inbox/viewer.** Compute content bounds from rendered image geometry and ResizeObserver/image load; keep source IDs and candidate IDs distinct.
- [ ] **Step 4: Run GREEN.** Run focused tests/build and component cases for EXIF JPEG preview, ordinary PNG, portrait 1080×1800 screenshot, and contain letterboxing.
- [ ] **Step 5: Commit** as `feat: add screenshot inbox and source region viewer`.

## Task 6: Candidate Edit, Split/Merge, Confirm, and Question Sources

**Files:**
- Create: backend/tests/api/test_ingestion_candidates.py
- Create: backend/tests/api/test_question_sources.py
- Modify: backend/app/repositories/ingestion.py
- Modify: backend/app/repositories/questions.py
- Modify: backend/app/services/ingestion_candidates.py
- Modify: backend/app/services/questions.py
- Modify: backend/app/api/v1/ingestions.py
- Modify: backend/app/api/v1/questions.py
- Modify: backend/tests/api/test_questions.py
- Create: frontend/src/components/IngestionCandidateEditor.vue
- Modify: frontend/src/pages/InboxPage.vue
- Modify: frontend/src/pages/QuestionDetailPage.vue
- Modify: frontend/tests/inbox.spec.ts
- Modify: frontend/tests/questions.spec.ts

**Interfaces:**
- **Consumes:** Task 1 lineage/revision fields, Task 4 all-state lineage query, Task 5 source selector/viewer, and Phase 1A taxonomy validation.
- **Produces:** protected generic Question operations, revision-checked source-specific candidate editing, transactional Split/Merge/reject/confirm, lineage/source history.
- Generic API protection: update_question, archive_question, and update_question_state return 409 if Question.status=pending_review OR if origin_ingestion_job_id is non-null and ingestion_candidate_state is not confirmed. Return the existing 409 CONFLICT envelope before changing text/taxonomy, archived_at/disposition, or creating QuestionState. Do not weaken routes or response contracts for manual active Questions or OCR candidates already confirmed active: they continue using Phase 1A PATCH/archive/state APIs unchanged. OCR candidates may change protected review fields only through Candidate APIs.
- Candidate mutations include expected_revision from the GET candidate result. Every conditional update checks origin job, status=pending_review, candidate_state=pending_review, archived_at is null, and expected_revision, then increments candidate_revision. A stale/duplicate action returns 409. Confirm additionally requires succeeded Job.
- Candidate PATCH body: expected_revision plus optional text/topic_ids/tag_ids and source_locator_corrections, an array of {question_source_id, locator_correction_json}. Each listed QuestionSource must belong to this Question, its origin IngestionJob, and that Job’s SourceAsset; its OCRBlock links must belong to the same job/source. Validate every ID and every finite normalized bbox before writing. In one transaction, update only the named rows’ locator_correction_json; never change another locator, locator_json, OCRBlock, source_text_snapshot, raw_ocr_text_snapshot, or source relation. Null correction clears only that named row’s correction. Any invalid ID, coordinate, or stale revision rolls back all changes.
- Split accepts only an unarchived pending candidate with current expected_revision in the path job. It requires two or more parts; every block must be cited by the parent and belong to that Job/SourceAsset. source_text_snapshot must be an excerpt of those immutable raw OCR blocks. In one transaction, preserve parent A’s QuestionSource/OCRBlock/snapshot/locator rows unchanged; keep A.status=pending_review, mark it archived/superseded, and increment its revision; create new pending Questions B/C with split_from_candidate_id=A; and create independent QuestionSource rows and OCRBlock links per part with exact excerpt, full raw block text, and locator union derived from those blocks. Multiple children may cite the same OCRBlock. Failed Split rolls back the parent disposition/revision, all children, and all source/block relations.
- Merge accepts only distinct, unarchived pending candidates from the same job, with expected_revision for every participant. The survivor remains pending; each absorbed candidate remains status=pending_review, becomes archived/superseded, increments revision, and points to survivor with superseded_by_candidate_id. For every source row on an absorbed candidate, create a new QuestionSource on survivor with copied immutable excerpt/raw text/original locator/correction/confidence plus newly inserted OCRBlock link rows. Keep the old QuestionSource rows and their old Question IDs untouched. Never repoint or delete old source records; never call canonical Question Merge.
- Lineage rules: a superseded Split parent or Merge loser cannot be split, merged, edited, rejected, or confirmed again. Repeating the same request with the old expected_revision conflicts. A pending child may later be split or merged as a new action; a pending Merge survivor may intentionally absorb additional same-job candidates with its latest revision. GET /ingestions/{job_id}/candidates returns all rows with split parent ID, child IDs, superseded target, current disposition, source rows, and OCRBlock IDs, so ancestry and merges are reconstructable without event sourcing.
- Reject/archive keeps the Question and sources, sets archived_at and disposition=rejected. Confirm validates text/active taxonomy, creates QuestionState if absent, and atomically sets Question.status=active and disposition=confirmed. Both require expected_revision; neither deletes evidence.
- Generic and Candidate APIs share text preparation and active Topic/Tag validation. A QuestionSource history response includes source row ID, SourceAsset ID, original/corrected locator, immutable snapshots, and UUID block references.
- Every generic guard and candidate mutation occurs in its service transaction. Conditional row counts/version checks enforce races; DB errors roll back all Question, lineage, QuestionSource, OCRBlock relation, taxonomy, archive/disposition, and revision changes.

**Acceptance:** Phase 1A generic edits/archive/state still work for manual active and confirmed active Questions; no generic endpoint mutates unconfirmed OCR candidates; Split is traceable one-to-many and preserves parent evidence; Merge copies evidence while retaining loser evidence; targeted locator edits are unambiguous; duplicate/stale/concurrent operations conflict; all multi-row failures roll back.

- [ ] **Step 1: Write failing tests** `test_generic_question_patch_rejects_pending_ocr_candidate_without_mutation`, `test_generic_archive_preserves_pending_candidate_disposition`, `test_generic_question_state_does_not_create_pending_candidate_state`, `test_manual_active_and_confirmed_active_questions_keep_phase1a_api_behavior`, `test_split_creates_parent_child_lineage`, `test_split_and_merge_keep_question_status_pending_review`, `test_split_preserves_parent_question_sources_and_ocr_blocks`, `test_split_child_has_independent_excerpt_and_source_rows`, `test_repeat_split_on_superseded_parent_conflicts`, `test_split_and_confirm_race_has_one_winner`, `test_split_failure_rolls_back_parent_children_and_sources`, `test_merge_copies_sources_without_repointing_loser_evidence`, `test_merge_loser_points_to_survivor_and_remains_queryable`, `test_repeat_merge_with_stale_revision_conflicts`, `test_candidate_query_returns_split_and_merge_lineage`, `test_candidate_merge_rejects_cross_job_rows`, `test_locator_correction_changes_only_named_question_source`, `test_locator_correction_rejects_source_not_owned_by_candidate`, `test_invalid_locator_or_stale_revision_rolls_back_all_corrections`, `test_confirmed_question_uses_existing_search_and_practice`, and `test_question_source_history_opens_original_and_display_images`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/api/test_ingestion_candidates.py tests/api/test_question_sources.py tests/api/test_questions.py -q)` and `npm --prefix frontend test -- tests/inbox.spec.ts tests/questions.spec.ts`; confirm each new guard and lineage assertion fails first.
- [ ] **Step 3: Implement generic-service guards and transactional candidate services.** Add the guard before any field mutation, archive timestamp assignment, or QuestionState creation. Preserve active Question behavior. Use fresh QuestionSource IDs and copied OCRBlock links for Merge.
- [ ] **Step 4: Write failing UI tests** source-row selector, per-source locator correction payload, candidate-wide union highlight, split lineage labels, merge source-history preservation, and generic confirmed-question controls.
- [ ] **Step 5: Implement the candidate editor and source panel.** Source locator edits always include question_source_id and expected_revision; 409 refreshes the candidate/source list.
- [ ] **Step 6: Run GREEN.** Run backend/frontend focused and full suites/build; verify only explicitly confirmed active candidates appear in Phase 1A search/practice.
- [ ] **Step 7: Commit** as `feat: edit and confirm OCR question candidates`.

## Task 7: Phase 1B Acceptance, Source Cleanup, and Runbook

**Files:**
- Create: backend/tests/api/test_phase_1b_flow.py
- Create: backend/tests/api/test_source_deletion.py
- Modify: backend/app/services/source_storage.py
- Modify: backend/app/api/v1/sources.py
- Modify: backend/run.py
- Modify: frontend/tests/inbox.spec.ts
- Modify: frontend/tests/questions.spec.ts
- Modify: README.md

**Interfaces and safety rules:**
- **Consumes:** source, OCR, candidate, lineage, generic API guard, and locator contracts from Tasks 1–6.
- **Produces:** full acceptance flow, focused tombstone recovery, no-history SourceAsset deletion, offline runtime verification, supported startup runbook, and final browser visual check.
- Preserve Task 7’s existing no-history source deletion rule and narrow tombstone journal. Do not add cascading deletion of referenced candidate/source history.
- README’s only supported server start is `(cd backend && conda run -n test python run.py)`. run.py performs recovery once in its main entrypoint and always disables Flask reloader. Do not document `flask --app ... run` or an auto-reloading command as supported. If debug is enabled through run.py, use_reloader remains false. Document single-process local service only.
- README/runbook records the observed test environment and actual smoke result. Current planning inspection found Python 3.12.15, macOS 27.0.1, arm64, but RapidOCR/ONNX Runtime are absent from Conda test, so runtime compatibility remains unverified until Task 3 installs the unchanged pins and the offline CPU smoke passes. The smoke report must record Python/macOS/architecture, package versions, CPUExecutionProvider, model-manifest release/checksum, and actual completion. Do not claim compatibility or upgrade versions without that evidence.
- End-to-end regression covers generic Question PATCH/archive/state protection, Split parent-child history, Merge copied-source history, source-targeted locator correction, missing-model app availability and Job failure, one-time startup recovery/no-reloader, upload/OCR/retry, and existing Phase 1A search/practice.
- User screenshots remain untracked; automated tests use de-identified OCR fixtures and FakeOCRAdapter. Real-browser acceptance checks EXIF JPEG, PNG, portrait screenshot, multiple source regions, and letterboxing.

**Acceptance:** Phase 1A API compatibility; all OCR candidates can be traced through split/merge ancestry and original sources; multiple QuestionSource corrections target only the selected row; application remains usable without OCR models; interrupted OCR is recovered only at the supported single-process startup; fixed OCR versions pass an offline local CPU smoke test; full suites and browser visual check pass.

- [ ] **Step 1: Write failing end-to-end/recovery tests** `test_phase1b_upload_ocr_review_confirm_and_practice_flow`, `test_phase1b_pending_candidate_cannot_be_changed_by_generic_question_routes`, `test_phase1b_split_lineage_and_parent_source_history`, `test_phase1b_merge_copies_question_sources_and_preserves_loser`, `test_phase1b_locator_patch_targets_only_selected_source`, `test_phase1b_missing_models_leave_app_available_and_fail_claimed_job`, `test_phase1b_startup_recovery_runs_once_without_reloader`, `test_retry_does_not_overwrite_old_blocks_or_confirmed_source`, `test_db_failure_restores_original_and_preview_from_tombstone`, and `test_restart_reconciles_tombstone_consistently`.
- [ ] **Step 2: Run RED.** `(cd backend && conda run -n test pytest tests/api/test_phase_1b_flow.py tests/api/test_source_deletion.py tests/api/test_questions.py -q)` and `npm --prefix frontend test`; confirm the intended regressions fail.
- [ ] **Step 3: Implement only guarded no-history deletion and final entrypoint/runbook wiring.** Keep archive as normal cleanup; do not add general recovery or worker infrastructure.
- [ ] **Step 4: Run automated GREEN.** Fresh Alembic database, full backend and frontend suites/build, tmp_path isolation, and Phase 1A API compatibility.
- [ ] **Step 5: Run actual offline compatibility and visual acceptance.** In Conda test run the local CPU smoke with network unavailable; record Python/macOS/architecture and exact pinned package/provider/model checksums. Start the app only via run.py; if debug is exercised, verify reloader is disabled and interrupted-job recovery executes once. In a real browser inspect source selections/union highlights and EXIF/PNG/tall-image letterboxing. Do not commit user screenshots.
- [ ] **Step 6: Write and verify README.** Follow only the supported single-process startup command, model preparation/checksum/offline smoke, archive/delete boundary, and retry/recovery steps.
- [ ] **Step 7: Commit** as `feat: add source cleanup recovery and OCR runbook`.

## Phase 1B Invariants / Acceptance Rules

1. Original upload bytes and SHA-256 never change; the display preview is a separate EXIF-normalized lossless rendering.
2. OCRBlock UUID, text, bbox, reading order, source excerpt, raw OCR snapshot, and original locator are immutable after persistence.
3. Every OCR candidate, including split/merged/rejected/confirmed rows, keeps origin_ingestion_job_id; Phase 1A manual questions keep it null. Split children expose split_from_candidate_id; Merge losers expose superseded_by_candidate_id.
4. Reopening an OCR Job returns all its candidate rows by default, including pending, confirmed, rejected, and superseded; status filters do not remove history from storage.
5. Re-OCR/retry creates a new Job and new OCRBlock UUIDs and never mutates old candidates or QuestionSources.
6. Job status succeeded means OCR, candidate grouping, and atomic persistence all finished. Empty OCR is a valid succeeded result with zero candidates.
7. OCRBlocks, Questions, QuestionSources, block links, candidate_count, and succeeded state commit in one transaction; a failed group/persist leaves no partial result rows or false success.
8. Only one concurrent request can claim a queued Job. Duplicate execution is 409; a browser timeout queries the same Job and never reruns it.
9. A process-interrupted running Job is marked failed/interrupted on startup; recovery preserves old data and retry creates a new Job.
10. Split/Merge block UUIDs must belong to the same Job and SourceAsset. Candidate Merge remains an inbox correction and never sets Question.status=merged or invokes canonical Question Merge.
11. Candidate edit/split/merge/reject/confirm operates only on the still-pending unarchived candidate at the expected revision and is transactional; racing actions cannot overwrite a winner. Generic Question PATCH/archive/state rejects unconfirmed OCR candidates with 409 and leaves disposition unchanged; confirmed/manual active Question APIs remain compatible.
12. A Split marks parent A superseded/archived and creates pending children with split_from_candidate_id=A. Parent source rows remain unchanged; children get their own excerpt, raw text, locator, and stable block links. Repeating Split on the superseded parent conflicts.
13. Merge marks each loser superseded and points it to the survivor. It creates new survivor QuestionSource rows and OCRBlock links; old loser source rows remain attached to the loser. Repeating the old Merge request conflicts; later intentional survivor merges require the latest revision.
14. Locator corrections name question_source_id, verify ownership by candidate/job/source, check expected_revision, and update only the targeted locator_correction_json. Default highlight unions effective locator regions only within the displayed SourceAsset. Corrections never overwrite original locators.
15. Pending, rejected, superseded, and archived OCR candidates remain excluded from the default 1A Question list, search, and all new PracticeSessions.
16. Only explicit confirmation makes a candidate active and eligible for existing Question search and PracticeSession. Every candidate mutation uses expected_revision and increments candidate_revision.
17. Batch item upload/OCR failure is isolated; one failed image cannot roll back successful siblings.
18. Source deletion is possible only before any OCR attempt/candidate/source citation; tombstone failure or process exit restores consistency without deleting evidence. Archive never deletes evidence.
19. OCR model versions/checksums are recorded; missing or changed local models fail clearly without network download. Automated tests use FakeOCRAdapter.
20. EXIF orientation used for OCR, preview rendering, and browser overlay is identical. Overlay coordinates scale to visible image content, excluding contain letterbox padding.
21. Test databases and source files are isolated under tmp_path; real user screenshots remain untracked.
22. Existing Phase 1A API/error schema, taxonomy validation, FTS, Question search, favorite/wrong state, and PracticeSession selector keep working unchanged.
23. Generic Question PATCH/archive/state returns 409 for unconfirmed OCR candidates before any mutation; manual active and confirmed active Questions retain Phase 1A behavior.
24. A locator correction names one QuestionSource, verifies candidate/job/source ownership and expected_revision, and changes only that row; invalid or stale requests make no partial changes.
25. Missing/invalid local OCR models do not prevent app startup or question-bank use; after a Job is claimed, initialization errors persist a failed Job and sanitized model error.
26. Startup recovery executes once only from the supported single-process run.py entrypoint; reloader is disabled, and multi-process OCR is unsupported.
27. Conda test Python/macOS/architecture and the pinned RapidOCR/ONNX Runtime CPU provider are recorded and verified by one offline local CPU smoke test before Phase 1B acceptance.

## Scope Boundary

Phase 1B implements only: local image upload; SourceAsset metadata and original file storage; one IngestionJob per image/run; replaceable local OCR adapter; stable OCRBlock IDs and normalized regions; rule-based multi-question candidate grouping; Inbox view with source image/highlights; manual candidate text correction, split/merge/archive, manual Topic/Tag selection, and explicit confirmation; Question source history; source archive and no-reference delete; Phase 1B tests and runbook.

Do not implement Phase 1C: VLM/LLM boundary detection, automatic Topic/Tag/difficulty suggestions, duplicate hash candidates, n-gram/trigram similarity, same/related/different semantic decisions, Question B→A canonical merge, or automatic merge. Also do not implement social-platform collection, SavedAnswer, Project/Resume/Material, reference answers, mock interview, general workers, Celery/Redis, vector databases, or GPU as a requirement.

## Plan Self-Review

- **Phase 1A API boundary:** actual Phase 1A update_question, archive_question, and update_question_state do not currently check OCR candidate disposition. Task 6 adds a service-level conflict guard before any write, while tests preserve manual/confirmed active behavior.
- **Split/Merge lineage:** a nullable self-FK split_from_candidate_id represents one-to-many children; superseded_by_candidate_id represents a Merge loser. Split preserves parent source rows; Merge clones evidence into new survivor rows and leaves loser evidence attached. Existing candidate query returns all lineage IDs.
- **Source locator scope:** locator correction carries QuestionSource ID plus expected_revision and validates candidate/job/source ownership before one transaction. Viewer can select a row and unions only current-asset effective regions.
- **OCR startup boundary:** adapter/model initialization occurs only after job claim and is lazy, so missing models fail the Job without taking down app startup. Only run.py performs startup recovery once, with Flask reloader disabled; no multi-process OCR support is added.
- **Runtime verification:** this plan revision observed Python 3.12.15, macOS 27.0.1, arm64; the test environment lacks RapidOCR/ONNX Runtime, so compatibility and offline CPU smoke are explicitly pending Task 3/7 evidence. Existing pins are retained.
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

**Self-review result:** the plan now covers the four reviewed boundaries across schema, services, UI, integration tests, and runbook. The current Conda test runtime is not yet compatible-verified because RapidOCR/ONNX Runtime are absent; the offline CPU smoke is an explicit Task 3/7 acceptance, not a claimed pass. Existing pins remain unchanged pending that evidence. This is the frozen Phase 1B execution version; implement Tasks 1–7 in order and use real usage feedback before expanding scope.

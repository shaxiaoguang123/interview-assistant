# SDD ledger — plan: docs/superpowers/plans/2026-10-08-agent-interview-assistant-phase-1b.md

## Setup
- Branch: codex/phase-1b-screenshot-ocr; starting HEAD c40d539; branch base/merge-base: 35419d9.
- Baseline backend: conda run -n test pytest -q -> 100 passed.
- Baseline frontend: npm --prefix frontend test -> 5 files, 18 tests passed.
- Conda test: Python 3.12.15, macOS 27.0.1, arm64; RapidOCR and ONNX Runtime are not installed yet. Task 3 requires pinned install, local model preparation, and actual offline CPU smoke before acceptance.
- Preserved existing untracked user content: .gitignore, AGENTS.md, docs/research/, pic-test/. Do not stage them unless a task explicitly adds a new tracked file beneath an existing path.

## Pre-flight interfaces
- Task 1 -> Task 2: SourceAsset/IngestionJob models and SOURCE_STORAGE_DIR/config feed per-file upload transactions.
- Task 1 + Task 2 -> Task 3: IngestionJob/OCRBlock/provenance schema plus validated oriented local image storage feed the claimed OCR pipeline.
- Task 1 + Task 3 -> Task 4: Question/QuestionSource/OCRBlock provenance and CandidateDraft/OCRDetection pipeline feed rule-based grouping and all-state history.
- Task 2 + Task 3 + Task 4 -> Task 5: source upload/display routes, job/status/block API, and all-state candidate API feed Inbox polling and viewer.
- Task 1 + Task 4 + Task 5 -> Task 6: lineage/revision schema, candidate query, and source selector/viewer feed guarded candidate mutations and UI.
- Tasks 1–6 -> Task 7: complete models, APIs, viewer, mutation flow, and evidence contracts feed integration, source cleanup, startup runbook, and acceptance.
- Pre-flight result: interfaces align; no plan/spec conflict found. No ruling required.

## Task progress
- Task 1 ruling: The accepted brief tests SOURCE_STORAGE_DIR under APP_DATA_DIR, but its file list omitted backend/app/config.py and the real Phase 1A config has no source-root setting. Add the minimal default APP_DATA_DIR/sources in Task 1 and list config.py; Task 2 consumes it. This resolves the test/interface gap without adding a new layer. Cost if wrong: moving one config line between task commits.
Task 1: complete (commits c40d539..0f0562a, tests: bash -lc 'cd backend && conda run -n test pytest -q' → 110 passed in 5.81s)
Task 2: complete (commits 0f0562a..700d320, tests: bash -lc 'cd backend && conda run -n test pytest -q' → 128 passed in 6.73s)
Task 3: complete (commits 700d320..bfedd90, tests: bash -lc 'cd backend && conda run -n test pytest -q' → 147 passed in 9.10s)
- Task 3 runtime acceptance: Conda test Python 3.12.15, macOS 27.0.1, arm64; rapidocr 3.9.2 and onnxruntime 1.30.0 installed with pip check clean. ModelScope PP-OCRv6 small detection/recognition plus PP-OCRv4 mobile classifier files matched the pinned SHA-256 manifest. Offline socket-blocked smoke on pic-test 小红书 sample used CPUExecutionProvider, returned 14 OCR blocks in 1.082s.
Task 4: complete (commits bfedd90..f4999a3, tests: bash -lc 'cd backend && conda run -n test pytest -q' → 162 passed in 10.63s)
Task 5: complete (commits f4999a3..c94b69f, tests: npm --prefix frontend test →    Duration  1.66s (environment 53%, transform 24%, tests 15%, import 7%, worker 1%))
Task 6: complete (commits c94b69f..d3c5f78, tests: bash -lc 'cd backend && conda run -n test pytest -q' → 188 passed in 12.70s)
- Task 3 one transient observation: one full pytest process once exited 134 after reporting all 162 tests passed with libc++ `recursive_mutex lock failed`; reruns with `PYTHONFAULTHANDLER=1` and a plain full-suite run both exited 0 (162 passed). No root cause established; later Task 5/6 full backend runs also exited 0. Keep this as a note, not a code deviation.
- Task 7 ruling: Adding tombstone recovery to the already-supported runner changes its Task 3 contract, so update `backend/tests/api/test_ingestions.py::test_supported_runner_recovers_once_with_reloader_disabled` to provide SOURCE_STORAGE_DIR and assert both recovery hooks run once before serving. This is the narrowest regression-test update for the actual single-entrypoint lifecycle; cost if wrong: moving that assertion into the Task 7 integration test instead.
- Task 7 ruling: macOS ControlCenter already listens on port 5000 in this host, so the prescribed run.py entrypoint cannot serve the browser QA app there. Add an APP_PORT environment override to run.py, preserving 5000 as the default and no-reloader single-process semantics; this permits the same supported entrypoint to run at 5017 for isolated visual acceptance. Cost if wrong: one optional local runtime configuration value.
- Task 7 acceptance record: user pic-test screenshots produced 4 and 12 candidates; a local PNG copy and correctly EXIF-oriented JPEG each produced 4. In Codex in-app browser at 1200x900 and 600x900, visually checked Q1/Q2 overlays and same-asset union after merging two candidates into separate QuestionSource rows; selected-source switching changed the red focus box and editor source selection, while the other region stayed yellow. DOM geometry at 600px viewport: stage 584x630, oriented image content 378x630 with 103px left letterbox offset; SVG overlay x/size matched the content box and region math. Temporary browser DB and image copies were removed; original pic-test files remain untracked and unchanged.
- Task 7 final automated verification before commit: backend pytest 198 passed; frontend Vitest 38 passed; Vite production build passed; pip check clean; offline CPU smoke 14 blocks, 0.896s, RapidOCR 3.9.2 / ONNX Runtime 1.30.0 / CPUExecutionProvider with fixed model hashes.
- Task 7 visual finding/fix: real browser showed the per-upload summary stayed at queued after persisted Job completion. Added a failing assertion, updated setJob to refresh the upload result row, reran inbox tests and full frontend suite successfully.
Task 7: complete (commits d3c5f78..22b35d5, tests: bash -lc 'cd backend && PYTHONFAULTHANDLER=1 conda run -n test pytest -q && cd .. && npm --prefix frontend test && npm --prefix frontend run build && conda run -n test python -m pip check && cd backend && conda run -n test python scripts/ocr_cpu_smoke.py --offline "../pic-test/小红书-Agent评测策略专家_1_泽华留学生求职_来自小红书网页版.jpg"' → elapsed_seconds=1.186)

## Final review follow-up
- Inbox lifecycle findings reproduced with failing Vitest cases: queued jobs persisted across reload now expose a resume action that reads server state before deciding whether to run or poll; out-of-order history responses are ignored using a request revision. Focused RED: both new cases failed for the reported behavior; GREEN: both passed. Full frontend suite: 40 passed; Vite build passed.
- Tombstone recovery ID-reuse finding reproduced with a failing pytest: after committed deletion and simulated cleanup interruption, SQLite reused the old integer ID and startup recovery restored the deleted image as an orphan. Recovery now restores only when both generated storage paths still match the journal; otherwise it discards the committed-deletion tombstone. Focused test passed; full backend suite: 199 passed.
- Lower-priority review notes deferred without broadening this fix pass: candidate refresh currently resets selection to the first row; split/merge lineage is returned by the API but not visibly labeled in the Inbox. Existing tests do not assert visible lineage labels.

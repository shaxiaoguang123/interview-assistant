export interface IngestionJob {
  id: number;
  source_asset_id: number;
  status: string;
  stage: string;
  failure_stage: string | null;
  engine: string | null;
  engine_version: string | null;
  error_code: string | null;
  error_message: string | null;
  candidate_count: number;
}

export interface SourceAsset {
  id: number;
  source_type: string;
  title: string | null;
  original_filename: string | null;
  mime_type: string;
  byte_size: number;
  original_width: number;
  original_height: number;
  display_width: number;
  display_height: number;
  sha256: string;
  archived_at: string | null;
  ingestion_jobs: IngestionJob[];
}

export interface UploadResult {
  status: "stored" | "rejected";
  source?: SourceAsset;
  job?: IngestionJob;
  error?: { code: string; message: string; fields: Record<string, string> };
  filename?: string;
}

export interface IngestionOCRBlock {
  id: string;
  text: string;
  bbox: { x: number; y: number; width: number; height: number };
  reading_order: number;
  confidence: number | null;
}

export interface IngestionTaxonomyItem {
  id: number;
  name: string;
  is_active: boolean;
}

export interface IngestionCandidate {
  id: number;
  text: string;
  difficulty: string | null;
  status: string;
  archived_at: string | null;
  candidate_state: string;
  candidate_revision: number;
  canonical_question_id: number | null;
  split_from_candidate_id: number | null;
  split_child_ids: number[];
  superseded_by_candidate_id: number | null;
  topics: IngestionTaxonomyItem[];
  tags: IngestionTaxonomyItem[];
  sources: Array<{
    question_source_id: number;
    source_asset_id: number;
    locator_json: { x: number; y: number; width: number; height: number };
    locator_correction_json: { x: number; y: number; width: number; height: number } | null;
    source_text_snapshot: string;
    raw_ocr_text_snapshot: string;
    confidence: number | null;
    ocr_blocks: Array<{
      id: string;
      text: string;
      bbox: { x: number; y: number; width: number; height: number };
      reading_order: number;
    }>;
  }>;
}

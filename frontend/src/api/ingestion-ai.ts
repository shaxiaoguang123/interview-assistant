import { request } from "./client";

export interface IngestionAiTaxonomyItem {
  id: number;
  name: string;
  is_active: boolean;
}

export interface IngestionAiBlock {
  id: string;
  text: string;
  reading_order: number;
  bbox: { x: number; y: number; width: number; height: number };
}

export interface IngestionAiSource {
  question_source_id: number;
  source_text_snapshot: string;
  raw_ocr_text_snapshot: string;
  ocr_blocks: IngestionAiBlock[];
}

export interface IngestionAiCandidate {
  id: number;
  text: string;
  difficulty?: string | null;
  candidate_revision: number;
  topics: IngestionAiTaxonomyItem[];
  tags: IngestionAiTaxonomyItem[];
  sources: IngestionAiSource[];
}

export interface IngestionAiSplitPart {
  text: string;
  ocr_block_ids: string[];
  source_text_snapshot: string;
}

export interface IngestionAiSuggestion {
  candidate_id: number;
  candidate_revision: number;
  original_text: string;
  suggested_text: string;
  topic_ids: number[];
  tag_ids: number[];
  difficulty: "easy" | "medium" | "hard" | null;
  reason: string;
  warnings: string[];
  split_parts: IngestionAiSplitPart[];
}

export function suggestIngestionCandidate(
  candidateId: number,
  expectedRevision: number,
): Promise<IngestionAiSuggestion> {
  return request<IngestionAiSuggestion>(
    `/api/v1/ingestion-candidates/${candidateId}/ai-suggestions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  );
}

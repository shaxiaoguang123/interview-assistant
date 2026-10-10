export type ReviewRating = "dont_know" | "vague" | "basic" | "proficient";
export interface PracticeReviewItem {
  saved_answer_version_id?:number|null;
  id: number; question_id: number; session_item_id: number;
  review_rating: ReviewRating; reviewed_at: string; created_at: string; updated_at: string;
}
export interface Locator { x: number; y: number; width: number; height: number }
export interface QuestionSourceItem {
  question_source_id: number; question_id: number; source_asset_id: number;
  source_title: string | null; original_filename: string | null;
  display_width: number; display_height: number;
  source_text_snapshot: string; raw_ocr_text_snapshot: string;
  locator_json: Locator; locator_correction_json: Locator | null;
  ocr_block_ids: string[];
  ocr_blocks: Array<{id: string; text: string; bbox: Locator; reading_order: number; confidence: number | null}>;
  original_image_url: string; display_image_url: string;
}
export interface HistorySessionItem {
  id: number; question_id: number; session_id: number; ordinal: number;
  status: "shown" | "completed" | "skipped";
}
export interface CanonicalHistory {
  saved_answers?:import('./saved-answers').SavedAnswer[];
  canonical_question_id: number; member_question_ids: number[];
  sources: QuestionSourceItem[]; practice_reviews: PracticeReviewItem[];
  session_items: HistorySessionItem[];
}

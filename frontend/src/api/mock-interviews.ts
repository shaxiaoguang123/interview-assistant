import { request } from "./client";

export interface MockInterviewContextSelection {
  project_ids: number[];
  material_ids: number[];
  exclude_material_ids: number[];
}

export interface MockInterviewOptions {
  topics: Array<{ id: number; name: string }>;
  topic_question_counts: Record<number, number>;
  projects: Array<{ id: number; name: string }>;
  materials: Array<{
    id: number;
    title: string;
    kind: string;
    project_id: number | null;
    version_no: number;
    is_system_managed: boolean;
  }>;
  available_question_count: number;
  llm_configured: boolean;
}

export interface MockInterviewQuestion {
  id: number;
  text: string;
  ordinal: number;
}

export interface MockInterviewSource {
  material_id: number;
  material_version_id: number;
  project_id: number | null;
  title: string;
  version_no: number;
  sha256: string;
  chunk_ids: number[];
}

export interface MockInterviewTurn {
  id?: number;
  ordinal: number;
  question_id: number;
  question_text: string;
  kind: "question" | "answer" | "follow_up";
  text: string;
  sources: MockInterviewSource[];
  created_at: string;
  answer_export?: MockInterviewAnswerExport | null;
}

export interface MockInterviewAnswerExport {
  saved_answer_id: number;
  saved_answer_version_id: number;
  version_no: number;
  question_id: number;
  self_rating: number | null;
  created_at: string | null;
}

export interface MockInterviewAnswerSource {
  mock_interview_id: number;
  mock_interview_title: string;
  turn_id: number;
  question_id: number;
  question_text: string;
}

export interface MockInterviewAnswerExportResult {
  saved_answer: { id: number; question_id: number; is_pinned: boolean; archived_at: string | null };
  version: {
    id: number;
    saved_answer_id: number;
    version_no: number;
    content: string;
    self_rating: number | null;
    origin_kind: string;
  };
  source: MockInterviewAnswerSource;
  already_exported: boolean;
}

export interface MockInterviewSummary {
  overview: string;
  items: Array<{
    question_id: number;
    question_text: string;
    answer_summary: string;
    missing_points: string[];
    technical_concerns: string[];
    next_directions: string[];
  }>;
  recommendations: Array<{ question_id: number; question_text: string; reason: string }>;
}

export interface MockInterviewState {
  id: string;
  revision: number;
  status: "active" | "ended";
  topic_id: number | null;
  topic_name: string;
  question_count: number;
  current_index: number;
  questions: MockInterviewQuestion[];
  current_question: MockInterviewQuestion | null;
  turns: MockInterviewTurn[];
  context_selection: MockInterviewContextSelection;
  context_sources: MockInterviewSource[];
  llm_configured: boolean;
  started_at: string;
  ended_at: string | null;
  summary: MockInterviewSummary | null;
  summary_sources: MockInterviewSource[];
  saved_record_id: number | null;
}

export interface SavedMockInterview {
  id: number;
  title: string;
  topic_id: number | null;
  topic_name: string | null;
  question_count: number;
  started_at: string | null;
  ended_at: string | null;
  created_at: string | null;
  context_selection: MockInterviewContextSelection;
  summary: MockInterviewSummary | null;
  summary_sources: MockInterviewSource[];
  provider: string | null;
  model: string | null;
  turns?: MockInterviewTurn[];
}

const json = (method: string, payload: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

export const getMockInterviewOptions = () => request<MockInterviewOptions>("/api/v1/mock-interviews/options");
export const startMockInterview = (payload: {
  topic_id: number | null;
  question_count: number;
  context: MockInterviewContextSelection;
}) => request<MockInterviewState>("/api/v1/mock-interviews", json("POST", payload));
export const getMockInterview = (id: string) => request<MockInterviewState>(`/api/v1/mock-interviews/${id}`);
export const askMockInterviewFollowUp = (id: string, answer: string, expectedRevision: number) =>
  request<{ session: MockInterviewState; follow_up: string; sources: MockInterviewSource[] }>(
    `/api/v1/mock-interviews/${id}/follow-up`,
    json("POST", { answer, expected_revision: expectedRevision }),
  );
export const moveToNextMockQuestion = (id: string, answer: string, expectedRevision: number) =>
  request<MockInterviewState>(`/api/v1/mock-interviews/${id}/next`, json("POST", { answer, expected_revision: expectedRevision }));
export const finishMockInterview = (id: string, answer: string, expectedRevision: number) =>
  request<MockInterviewState>(`/api/v1/mock-interviews/${id}/finish`, json("POST", { answer, expected_revision: expectedRevision }));
export const generateMockInterviewSummary = (id: string) =>
  request<{ session: MockInterviewState; summary: MockInterviewSummary; sources: MockInterviewSource[] }>(
    `/api/v1/mock-interviews/${id}/summary`,
    json("POST", {}),
  );
export const saveMockInterview = (id: string, title: string) =>
  request<{ record: SavedMockInterview }>(`/api/v1/mock-interviews/${id}/save`, json("POST", { title }));
export const listSavedMockInterviews = () => request<SavedMockInterview[]>("/api/v1/mock-interviews/saved");
export const getSavedMockInterview = (id: number) => request<SavedMockInterview>(`/api/v1/mock-interviews/saved/${id}`);
export const exportMockInterviewAnswer = (
  recordId: number,
  turnId: number,
  payload: { save_mode: "new_answer" | "append_version"; saved_answer_id?: number; content: string; self_rating: number | null },
) => request<MockInterviewAnswerExportResult>(
  `/api/v1/mock-interviews/saved/${recordId}/answers/${turnId}/export`,
  json("POST", payload),
);

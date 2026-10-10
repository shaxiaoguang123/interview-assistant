import { request } from "./client";

export type RelationType = "same_question" | "related_question" | "different_question";
export type DecisionStatus = "suggested" | "accepted" | "rejected";

export interface QuestionRelationItem {
  id: number;
  question_id: number;
  related_question_id: number;
  relation_type: RelationType;
  decision_status: DecisionStatus;
  suggested_by: "rule" | "llm" | "user";
  confidence: number | null;
  match_kind: "exact" | "trigram";
  review_token: string;
  other_question: {
    id: number;
    text: string;
    status: string;
    canonical_question_id: number | null;
    candidate_state: string | null;
  };
}

export interface SimilarityResult {
  question_id: number;
  canonical_question_id: number | null;
  candidate_state: string | null;
  total_count: number;
  unresolved_count: number;
  confirmation_blocked: boolean;
  scan_required: boolean;
  candidates: QuestionRelationItem[];
}

export interface RelationReviewState {
  questionId: number;
  contextKey: string;
  canConfirm: boolean;
}

export function getSimilarCandidates(questionId: number, scan = false): Promise<SimilarityResult> {
  return request<SimilarityResult>(`/api/v1/questions/${questionId}/similar-candidates${scan ? "/scan" : ""}`, scan ? { method: "POST" } : {});
}

export function reviewRelation(
  questionId: number, relation: QuestionRelationItem, relationType: RelationType, decisionStatus: DecisionStatus,
): Promise<QuestionRelationItem> {
  return request<QuestionRelationItem>(`/api/v1/question-relations/${relation.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question_id: questionId,
      relation_type: relationType,
      decision_status: decisionStatus,
      expected_review_token: relation.review_token,
    }),
  });
}

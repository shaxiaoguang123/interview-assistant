import { request } from './client';

export interface MergeTaxonomy { id: number; name: string; is_active: boolean }
export interface MergeMember {
  id: number; text: string; status: string; topic_ids: number[]; tag_ids: number[];
  candidate_state: string | null; candidate_revision: number;
}
export interface MergePreview {
  canonical_id: number; source_question_id: number; preview_token: string;
  canonical_question: MergeMember; source_question: MergeMember;
  target_members: MergeMember[]; source_members: MergeMember[];
  topic_union: MergeTaxonomy[]; tag_union: MergeTaxonomy[];
  available_topics: MergeTaxonomy[]; available_tags: MergeTaxonomy[];
  relation: { id: number };
  expected_candidate_revision: number | null;
}
export interface MergeOutcome { canonicalId: number; sourceId: number }
export function getMergePreview(canonicalId: number, sourceId: number) {
  return request<MergePreview>(`/api/v1/questions/${canonicalId}/merge-preview?source_question_id=${sourceId}`);
}
export function mergeQuestions(preview: MergePreview, topicIds: number[], tagIds: number[]) {
  return request<{id: number}>(`/api/v1/questions/${preview.canonical_id}/merge`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({canonical_id:preview.canonical_id, source_question_id:preview.source_question_id,
      relation_id:preview.relation.id, preview_token:preview.preview_token, topic_ids:topicIds, tag_ids:tagIds,
      ...(preview.expected_candidate_revision !== null ? {expected_candidate_revision:preview.expected_candidate_revision} : {}),
    }),
  });
}

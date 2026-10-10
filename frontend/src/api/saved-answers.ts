import { request } from './client';

export interface AnswerVersion {
  id:number; saved_answer_id:number; version_no:number; content:string; self_rating:number|null;
  self_rating_updated_at:string|null; origin_kind:string; source_session_item_id:number|null;
  source_practice_review_id:number|null; based_on_version_id:number|null; assistant_output_id:number|null; created_at:string;
}
export interface SavedAnswer {
  id:number; question_id:number; source_session_item_id:number|null; is_pinned:boolean;
  archived_at:string|null; created_at:string; updated_at:string; version_count:number; current_version:AnswerVersion;
}
export interface AnswerInput {
  content:string; self_rating?:number|null; source_session_item_id?:number; source_practice_review_id?:number;
}
const json = (method:string, body:unknown) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export const getSavedAnswers = (id:number, archived=false) => request<SavedAnswer[]>(`/api/v1/questions/${id}/saved-answers${archived?'?include_archived=1':''}`);
export const createSavedAnswer = (id:number, input:AnswerInput) => request<SavedAnswer>(`/api/v1/questions/${id}/saved-answers`,json('POST',input));
export const getAnswerVersions = (id:number) => request<AnswerVersion[]>(`/api/v1/saved-answers/${id}/versions`);
export const appendAnswerVersion = (id:number, content:string) => request<AnswerVersion>(`/api/v1/saved-answers/${id}/versions`,json('POST',{content}));
export const rateAnswer = (id:number, rating:number|null) => request<AnswerVersion>(`/api/v1/saved-answer-versions/${id}/rating`,json('PATCH',{self_rating:rating}));
export const pinAnswer = (id:number, pinned:boolean) => request<SavedAnswer>(`/api/v1/saved-answers/${id}/pin`,json('PATCH',{is_pinned:pinned}));
export const archiveAnswer = (id:number) => request<SavedAnswer>(`/api/v1/saved-answers/${id}/archive`,{method:'POST'});

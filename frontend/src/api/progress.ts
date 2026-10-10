import { request } from './client';
import type { ReviewRating } from './question-history';
export type PracticeMode = 'random' | 'topic' | 'tag' | 'favorite' | 'wrong' | 'due';
export interface ReviewSchedule {
  last_reviewed_at?: string | null;
  last_review_rating?: ReviewRating | null;
  next_review_at?: string | null;
  is_due?: boolean;
}
export interface TopicProgress {
  id: number; name: string; question_count: number; reviewed_question_count: number;
  review_count: number; mastery_counts: Record<ReviewRating,number>;
  has_enough_records: boolean; weak_ratio: number | null;
}
export interface ProgressData {
  as_of: string; window_days: number; active_question_count: number; reviewed_question_count: number;
  practice_review_count: number; mastery_counts: Record<ReviewRating,number>;
  due_question_count: number; future_question_count: number; favorite_question_count: number;
  wrong_question_count: number; saved_answer_count: number; rated_answer_count: number;
  answer_quality_counts: Record<string,number>; topics: TopicProgress[];
  due_questions: Array<ReviewSchedule & {id:number;text:string}>; due_list_limit: number;
}
export const getProgress = (windowDays=30) => request<ProgressData>(`/api/v1/progress?window_days=${windowDays}`);
export const masteryLabels:Record<ReviewRating,string> = {dont_know:'不会',vague:'模糊',basic:'基本会',proficient:'熟练'};
export function formatReviewTime(value?:string|null):string {
  if(!value)return '尚未复习';
  return new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value));
}

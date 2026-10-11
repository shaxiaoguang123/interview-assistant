import { request } from "./client";

export interface DashboardAnswer {
  id: number;
  question_id: number;
  question_text: string;
  updated_at: string | null;
  is_pinned: boolean;
  version_id: number | null;
  preview: string;
  self_rating: number | null;
}

export interface DashboardSession {
  id: number;
  mode: string;
  started_at: string | null;
  completed_at: string | null;
  item_count: number;
  completed_count: number;
}

export interface DashboardMaterial {
  id: number;
  project_id: number | null;
  version_id: number;
  title: string;
  kind: string;
  updated_at: string | null;
  version_no: number;
  is_system_managed: boolean;
}

export interface DashboardOutput {
  id: number;
  question_id: number;
  output_type: string;
  created_at: string | null;
  preview: string;
}

export interface DashboardData {
  as_of: string;
  due_question_count: number;
  pending_candidate_count: number;
  active_project_count: number;
  recent_answers: DashboardAnswer[];
  recent_sessions: DashboardSession[];
  recent_materials: DashboardMaterial[];
  recent_ai_outputs: DashboardOutput[];
}

export const getDashboard = () => request<DashboardData>("/api/v1/dashboard");

export function formatDashboardTime(value?: string | null): string {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export const practiceModeLabels: Record<string, string> = {
  random: "随机练习",
  topic: "Topic 练习",
  tag: "Tag 练习",
  favorite: "收藏练习",
  wrong: "错题练习",
  due: "到期复习",
};

export const materialKindLabels: Record<string, string> = {
  resume: "简历",
  project_profile: "项目事实 Profile",
  project_brief: "项目说明",
  readme: "README",
  architecture_doc: "架构文档",
  other: "其他资料",
};

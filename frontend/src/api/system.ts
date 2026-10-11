import { request } from "./client";

export interface SystemStatus {
  application: "agent-interview-assistant";
  backend: { ready: boolean; state: string };
  python: { version: string; supported: boolean };
  database: {
    ready: boolean;
    state: "ready" | "not_initialized" | "upgrade_required" | "unavailable" | string;
    current_revision: string | string[] | null;
    latest_revision: string | string[];
    migration_required: boolean;
  };
  ocr: { ready: boolean; state: string; message: string };
  llm: { configured: boolean };
  storage: { configured: boolean; location: "default" | "custom" };
}

export const getSystemStatus = () => request<SystemStatus>("/api/v1/system/status");

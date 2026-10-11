import { ApiError, request } from "./client";

export interface BackupInspection {
  valid: true;
  backup_format_version: number;
  created_at: string | null;
  schema_revision: string;
  data_counts: Record<string, number>;
  file_count: number;
  total_bytes: number;
}

export async function downloadBackup(): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch("/api/v1/backups/export");
  if (!response.ok) {
    let message = "无法导出本地备份。";
    let code = "BACKUP_EXPORT_FAILED";
    try {
      const payload = await response.json();
      message = payload?.error?.message ?? message;
      code = payload?.error?.code ?? code;
    } catch {
      // The response may be an empty proxy error.
    }
    throw new ApiError(code, message, response.status);
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const filename = decodeURIComponent(encoded ?? plain ?? "agent-interview-backup.zip").split(/[\\/]/).pop() || "agent-interview-backup.zip";
  return { blob: await response.blob(), filename };
}

export function inspectBackup(file: File): Promise<BackupInspection> {
  const body = new FormData();
  body.set("file", file, file.name);
  return request<BackupInspection>("/api/v1/backups/inspect", { method: "POST", body });
}

export function formatBackupBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "未知大小";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

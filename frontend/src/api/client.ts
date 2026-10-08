export type ApiErrorFields = Record<string, string>;

interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    fields?: ApiErrorFields;
  };
}

export class ApiError extends Error {
  readonly code: string;
  readonly fields: ApiErrorFields;
  readonly status: number;

  constructor(code: string, message: string, status: number, fields: ApiErrorFields = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.fields = fields;
    this.status = status;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }

    const error = body?.error;
    throw new ApiError(
      error?.code ?? "INTERNAL_ERROR",
      error?.message ?? "Request failed",
      response.status,
      error?.fields ?? {},
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

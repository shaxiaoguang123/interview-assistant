import { describe, expect, it, vi } from "vitest";

describe("API client errors", () => {
  it("parses error code, message, and field details", async () => {
    const clientModules = import.meta.glob("../src/api/client.ts", { eager: true });
    const clientModule = clientModules["../src/api/client.ts"] as
      | { request?: (path: string, init?: RequestInit) => Promise<unknown>; ApiError?: unknown }
      | undefined;
    expect(clientModule, "missing feature: frontend/src/api/client.ts").toBeDefined();
    const { request, ApiError } = clientModule!;

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({
          error: {
            code: "VALIDATION_ERROR",
            message: "Invalid question",
            fields: { text: "Question text is required" },
          },
        }),
      }),
    );

    await expect(request!("/api/v1/questions", { method: "POST" })).rejects.toMatchObject({
      code: "VALIDATION_ERROR",
      message: "Invalid question",
      fields: { text: "Question text is required" },
    });
    expect(ApiError).toBeTypeOf("function");
  });
});

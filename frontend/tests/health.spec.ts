import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import { createAppRouter } from "../src/router";

describe("local app shell", () => {
  it("renders the app title and backend health", async () => {
    const appModules = import.meta.glob("../src/App.vue", { eager: true });
    const appModule = appModules["../src/App.vue"] as { default?: object } | undefined;
    expect(appModule, "missing feature: frontend/src/App.vue").toBeDefined();
    const App = appModule!.default;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const body = path === "/api/v1/health" ? { status: "ok" } : path === "/api/v1/dashboard" ? {
          as_of: "2026-10-11T00:00:00Z", due_question_count: 0, pending_candidate_count: 0,
          active_project_count: 0, recent_answers: [], recent_sessions: [], recent_materials: [], recent_ai_outputs: [],
        } : [];
        return { ok: true, status: 200, json: async () => body } as Response;
      }),
    );
    const router = createAppRouter(createMemoryHistory());
    const wrapper = mount(App!, { global: { plugins: [router] } });
    await router.isReady();
    await flushPromises();

    expect(wrapper.text()).toContain("Agent Interview Workspace");
    expect(wrapper.text()).toContain("后端已连接");
  });
});

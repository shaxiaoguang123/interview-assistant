import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";

describe("rule-based practice", () => {
  it("renders random, Topic, and Tag setup modes", async () => {
    const setupModules = import.meta.glob("../src/pages/PracticeSetupPage.vue", { eager: true });
    const setupModule = setupModules["../src/pages/PracticeSetupPage.vue"] as
      | { default?: object }
      | undefined;
    expect(setupModule, "missing feature: PracticeSetupPage.vue").toBeDefined();
    const SetupPage = setupModule!.default;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const value = path === "/api/v1/topics" ? [] : [];
        return { ok: true, status: 200, json: async () => value } as Response;
      }),
    );

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/practice", component: SetupPage! }],
    });
    await router.push("/practice");
    await router.isReady();
    const wrapper = mount(SetupPage!, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("随机练习");
    expect(wrapper.text()).toContain("分类练习");
    expect(wrapper.text()).toContain("知识点练习");
  });

  it("renders SessionItems in their stored order", async () => {
    const sessionModules = import.meta.glob("../src/pages/PracticeSessionPage.vue", { eager: true });
    const sessionModule = sessionModules["../src/pages/PracticeSessionPage.vue"] as
      | { default?: object }
      | undefined;
    expect(sessionModule, "missing feature: PracticeSessionPage.vue").toBeDefined();
    const SessionPage = sessionModule!.default;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          id: 5,
          mode: "random",
          selector_version: "v1",
          selection_seed: 123,
          started_at: "2026-10-08T00:00:00Z",
          completed_at: null,
          items: [
            { id: 51, question_id: 2, ordinal: 1, status: "shown", question: { id: 2, text: "First stored question" } },
            { id: 52, question_id: 1, ordinal: 2, status: "shown", question: { id: 1, text: "Second stored question" } },
          ],
        }),
      }),
    );
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/practice/sessions/:id", component: SessionPage! }],
    });
    await router.push("/practice/sessions/5");
    await router.isReady();
    const wrapper = mount(SessionPage!, { global: { plugins: [router] } });
    await flushPromises();

    const rendered = wrapper.text();
    expect(rendered.indexOf("First stored question")).toBeLessThan(rendered.indexOf("Second stored question"));
    expect(wrapper.find("textarea").exists()).toBe(true);
  });
});

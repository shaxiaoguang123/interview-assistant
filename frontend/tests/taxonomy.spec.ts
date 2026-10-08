import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";


describe("taxonomy management", () => {
  it("registers the taxonomy management route", () => {
    const routerModules = import.meta.glob("../src/router/index.ts", { eager: true });
    const routerModule = routerModules["../src/router/index.ts"] as
      | { createAppRouter?: (history?: ReturnType<typeof createMemoryHistory>) => ReturnType<typeof import("vue-router").createRouter> }
      | undefined;
    expect(routerModule, "missing feature: frontend/src/router/index.ts").toBeDefined();

    const router = routerModule!.createAppRouter!(createMemoryHistory());
    expect(router.getRoutes().some((route) => route.path === "/taxonomy")).toBe(true);
  });

  it("renders active/inactive topics and tags and submits a new tag", async () => {
    const pageModules = import.meta.glob("../src/pages/TaxonomyPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/TaxonomyPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule, "missing feature: TaxonomyPage.vue").toBeDefined();
    const Page = pageModule!.default;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/topics") {
        return {
          ok: true,
          status: 200,
          json: async () => [
            { id: 1, parent_id: null, slug: "agent", name: "Agent", sort_order: 1, is_active: true },
            { id: 2, parent_id: 1, slug: "prompt", name: "Prompt", sort_order: 1, is_active: false },
            { id: 4, parent_id: 1, slug: "memory", name: "Memory", sort_order: 2, is_active: true },
          ],
        } as Response;
      }
      if (path === "/api/v1/tags" && !init?.method) {
        return {
          ok: true,
          status: 200,
          json: async () => [{ id: 3, name: "Agent Security", is_active: false }],
        } as Response;
      }
      if (path === "/api/v1/tags" && init?.method === "POST") {
        return {
          ok: true,
          status: 201,
          json: async () => ({ id: 4, name: "RAG", is_active: true }),
        } as Response;
      }
      if (path === "/api/v1/topics/2" && init?.method === "PATCH") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 2,
            parent_id: 4,
            slug: "prompt",
            name: "Prompt",
            sort_order: 1,
            is_active: false,
          }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(Page!);
    await flushPromises();

    expect(wrapper.text()).toContain("Agent");
    expect(wrapper.text()).toContain("Prompt");
    expect(wrapper.text()).toContain("停用");
    expect(wrapper.text()).toContain("Agent Security");

    await wrapper.get("select[aria-label='Topic 父级 prompt']").setValue("4");
    await wrapper.get("button[aria-label='保存 Topic prompt']").trigger("click");
    await flushPromises();

    await wrapper.get("input[aria-label='新建标签']").setValue("RAG");
    await wrapper.get("form[aria-label='新建标签表单']").trigger("submit.prevent");
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/topics/2",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ name: "Prompt", parent_id: 4 }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/tags",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "RAG" }),
      }),
    );
  });
});

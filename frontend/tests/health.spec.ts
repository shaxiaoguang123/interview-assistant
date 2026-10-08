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
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ status: "ok" }),
      }),
    );
    const router = createAppRouter(createMemoryHistory());
    const wrapper = mount(App!, { global: { plugins: [router] } });
    await router.isReady();
    await flushPromises();

    expect(wrapper.text()).toContain("Agent Interview Assistant");
    expect(wrapper.text()).toContain("ok");
  });
});

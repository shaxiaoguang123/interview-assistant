import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import { createAppRouter } from "../src/router";

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

  it("requires a user rating and sends the Review without the answer draft", async () => {
    const sessionModules = import.meta.glob("../src/pages/PracticeSessionPage.vue", { eager: true });
    const sessionModule = sessionModules["../src/pages/PracticeSessionPage.vue"] as
      | { default?: object }
      | undefined;
    expect(sessionModule).toBeDefined();
    const SessionPage = sessionModule!.default;
    let completed = false;
    const requests: Array<{ path: string; method: string; body?: string }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      requests.push({ path, method, body: typeof init?.body === "string" ? init.body : undefined });
      if (path === "/api/v1/practice-sessions/5" && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 5,
            mode: "random",
            selector_version: "v1",
            selection_seed: 123,
            started_at: "2026-10-08T00:00:00Z",
            completed_at: completed ? "2026-10-08T00:01:00Z" : null,
            items: [
              {
                id: 51,
                question_id: 2,
                ordinal: 1,
                status: completed ? "completed" : "shown",
                question: { id: 2, text: "Rate this practice answer", status: "active", archived_at: null },
              },
            ],
          }),
        } as Response;
      }
      if (path === "/api/v1/session-items/51/review" && method === "POST") {
        completed = true;
        return {
          ok: true,
          status: 201,
          json: async () => ({ id: 90, session_item_id: 51, review_rating: "basic" }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${method} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/practice/sessions/5");
    await router.isReady();
    const wrapper = mount(SessionPage!, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("textarea[aria-label='临时回答']").setValue("Never sent as an answer record");
    await wrapper.get("button[aria-label='自评基本会']").trigger("click");
    await flushPromises();

    const reviewRequest = requests.find(
      (item) => item.path === "/api/v1/session-items/51/review" && item.method === "POST",
    );
    expect(reviewRequest).toBeDefined();
    expect(JSON.parse(reviewRequest!.body ?? "{}" )).toEqual({ review_rating: "basic" });
    expect(requests.some((item) => item.path.includes("saved-answers"))).toBe(false);
    expect(wrapper.text()).toContain("本次练习已完成");
  });

  it("disables rating while a skip request is pending", async () => {
    const sessionModules = import.meta.glob("../src/pages/PracticeSessionPage.vue", { eager: true });
    const sessionModule = sessionModules["../src/pages/PracticeSessionPage.vue"] as
      | { default?: object }
      | undefined;
    expect(sessionModule).toBeDefined();
    const SessionPage = sessionModule!.default;
    let itemStatus: "shown" | "skipped" = "shown";
    let finishSkip: (() => void) | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/practice-sessions/5" && (init?.method ?? "GET") === "GET") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 5,
            mode: "random",
            selector_version: "v1",
            selection_seed: 123,
            started_at: "2026-10-08T00:00:00Z",
            completed_at: itemStatus === "skipped" ? "2026-10-08T00:01:00Z" : null,
            items: [
              {
                id: 51,
                question_id: 2,
                ordinal: 1,
                status: itemStatus,
                question: { id: 2, text: "Skip in progress", status: "active", archived_at: null },
              },
            ],
          }),
        } as Response;
      }
      if (path === "/api/v1/session-items/51/skip" && init?.method === "POST") {
        return await new Promise<Response>((resolve) => {
          finishSkip = () => {
            itemStatus = "skipped";
            resolve({ ok: true, status: 200, json: async () => ({}) } as Response);
          };
        });
      }
      throw new Error(`Unexpected request: ${String(init?.method ?? "GET")} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/practice/sessions/5");
    await router.isReady();
    const wrapper = mount(SessionPage!, { global: { plugins: [router] } });
    await flushPromises();
    const skipButton = wrapper.findAll("button").find((button) => button.text().includes("跳过此题"));
    await skipButton!.trigger("click");
    await flushPromises();

    const ratingButtons = wrapper.findAll("fieldset[aria-label='本次掌握程度'] button");
    expect(ratingButtons).toHaveLength(4);
    expect(ratingButtons.every((button) => (button.element as HTMLButtonElement).disabled)).toBe(true);

    finishSkip?.();
    await flushPromises();
    expect(wrapper.text()).toContain("本次练习已完成");
  });

  it("keeps rating controls available after a Review request error", async () => {
    const sessionModules = import.meta.glob("../src/pages/PracticeSessionPage.vue", { eager: true });
    const sessionModule = sessionModules["../src/pages/PracticeSessionPage.vue"] as
      | { default?: object }
      | undefined;
    expect(sessionModule).toBeDefined();
    const SessionPage = sessionModule!.default;
    let completed = false;
    let reviewAttempts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/practice-sessions/5" && (init?.method ?? "GET") === "GET") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 5,
            mode: "random",
            selector_version: "v1",
            selection_seed: 123,
            started_at: "2026-10-08T00:00:00Z",
            completed_at: completed ? "2026-10-08T00:01:00Z" : null,
            items: [
              {
                id: 51,
                question_id: 2,
                ordinal: 1,
                status: completed ? "completed" : "shown",
                question: { id: 2, text: "Retry Review", status: "active", archived_at: null },
              },
            ],
          }),
        } as Response;
      }
      if (path === "/api/v1/session-items/51/review" && init?.method === "POST") {
        reviewAttempts += 1;
        if (reviewAttempts === 1) {
          return {
            ok: false,
            status: 500,
            json: async () => ({ error: { code: "INTERNAL_ERROR", message: "Temporary failure" } }),
          } as Response;
        }
        completed = true;
        return { ok: true, status: 201, json: async () => ({}) } as Response;
      }
      throw new Error(`Unexpected request: ${String(init?.method ?? "GET")} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/practice/sessions/5");
    await router.isReady();
    const wrapper = mount(SessionPage!, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("button[aria-label='自评基本会']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("Temporary failure");
    expect(wrapper.find("button[aria-label='自评基本会']").exists()).toBe(true);
    await wrapper.get("button[aria-label='自评基本会']").trigger("click");
    await flushPromises();

    expect(reviewAttempts).toBe(2);
    expect(wrapper.text()).toContain("本次练习已完成");
  });

  it("offers a retry after the initial session request fails", async () => {
    const sessionModules = import.meta.glob("../src/pages/PracticeSessionPage.vue", { eager: true });
    const sessionModule = sessionModules["../src/pages/PracticeSessionPage.vue"] as
      | { default?: object }
      | undefined;
    expect(sessionModule).toBeDefined();
    let sessionAttempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        sessionAttempts += 1;
        if (sessionAttempts === 1) {
          return {
            ok: false,
            status: 500,
            json: async () => ({ error: { code: "INTERNAL_ERROR", message: "Temporary failure" } }),
          } as Response;
        }
        return {
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
              {
                id: 51,
                question_id: 2,
                ordinal: 1,
                status: "shown",
                question: { id: 2, text: "Retry this session load", status: "active", archived_at: null },
              },
            ],
          }),
        } as Response;
      }),
    );

    const router = createAppRouter(createMemoryHistory());
    await router.push("/practice/sessions/5");
    await router.isReady();
    const wrapper = mount(sessionModule!.default!, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("Temporary failure");
    await wrapper.get("button[aria-label='重试加载练习']").trigger("click");
    await flushPromises();

    expect(sessionAttempts).toBe(2);
    expect(wrapper.text()).toContain("Retry this session load");
  });

  it("corrects a review in place without creating another Review", async () => {
    const detailModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const detailModule = detailModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(detailModule, "missing feature: PracticeReview history panel").toBeDefined();
    const DetailPage = detailModule!.default;
    let rating = "vague";
    const requests: Array<{ path: string; method: string; body?: string }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      requests.push({ path, method, body: typeof init?.body === "string" ? init.body : undefined });
      if (path === "/api/v1/questions/1") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 1,
            text: "Review history question",
            answer_type: null,
            difficulty: null,
            status: "active",
            archived_at: null,
            topics: [],
            tags: [],
            state: { is_favorite: false, is_wrong: false, user_note: null },
          }),
        } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions/1/practice-reviews") {
        return {
          ok: true,
          status: 200,
          json: async () => [
            {
              id: 21,
              question_id: 1,
              session_item_id: 51,
              review_rating: rating,
              reviewed_at: "2026-10-08T00:00:00Z",
              created_at: "2026-10-08T00:00:00Z",
              updated_at: rating === "vague" ? "2026-10-08T00:00:00Z" : "2026-10-08T00:01:00Z",
            },
          ],
        } as Response;
      }
      if (path === "/api/v1/practice-reviews/21" && method === "PATCH") {
        rating = JSON.parse(String(init?.body)).review_rating;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 21,
            question_id: 1,
            session_item_id: 51,
            review_rating: rating,
            reviewed_at: "2026-10-08T00:00:00Z",
            created_at: "2026-10-08T00:00:00Z",
            updated_at: "2026-10-08T00:01:00Z",
          }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${method} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(DetailPage!, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("select[aria-label='更正掌握度 21']").setValue("basic");
    await wrapper.get("button[aria-label='保存自评 21']").trigger("click");
    await flushPromises();

    const patch = requests.find((item) => item.path === "/api/v1/practice-reviews/21");
    expect(JSON.parse(patch?.body ?? "{}" )).toEqual({ review_rating: "basic" });
    expect(requests.filter((item) => item.path === "/api/v1/questions/1/practice-reviews")).toHaveLength(1);
    expect(wrapper.findAll("[data-review-id='21']")).toHaveLength(1);
    expect(wrapper.text()).toContain("基本会");
  });
});

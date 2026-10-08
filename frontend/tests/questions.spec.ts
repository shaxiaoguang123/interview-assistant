import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import { createAppRouter } from "../src/router";

const topics = [{ id: 1, name: "RAG", is_active: true }];
const tags = [{ id: 2, name: "Retrieval", is_active: true }];
const RouterLinkStub = defineComponent({
  props: ["to"],
  setup(_props, { slots }) {
    return () => h("a", slots.default?.());
  },
});

function makeQuestion(id: number, text: string, archivedAt: string | null = null) {
  return {
    id,
    text,
    normalized_text: text.toLowerCase(),
    search_text: text.toLowerCase(),
    normalized_hash: `hash-${id}`,
    answer_type: null,
    difficulty: null,
    status: "active",
    archived_at: archivedAt,
    topics,
    tags,
    state: { is_favorite: false, is_wrong: false, user_note: null },
  };
}

describe("manual question bank", () => {
  it("searches a query and renders matching questions", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionBankPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionBankPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule, "missing feature: QuestionBankPage.vue").toBeDefined();
    const Page = pageModule!.default;
    const match = makeQuestion(11, "MCP 通信协议如何工作？");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions?q=MCP") {
        return { ok: true, status: 200, json: async () => [match] } as Response;
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(Page!, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("input[aria-label='搜索题目']").setValue("MCP");
    await wrapper.get("form[aria-label='题库搜索']").trigger("submit.prevent");
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/questions?q=MCP", expect.anything());
    expect(wrapper.text()).toContain("MCP 通信协议如何工作？");
  });

  it("creates and archives a question with taxonomy links", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionBankPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionBankPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule, "missing feature: QuestionBankPage.vue").toBeDefined();
    const Page = pageModule!.default;
    let created = makeQuestion(7, "What is RAG?");
    let archived = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      if (path === "/api/v1/topics") return { ok: true, status: 200, json: async () => topics } as Response;
      if (path === "/api/v1/tags") return { ok: true, status: 200, json: async () => tags } as Response;
      if (path === "/api/v1/questions" && method === "GET") {
        return { ok: true, status: 200, json: async () => (archived ? [] : [created]) } as Response;
      }
      if (path === "/api/v1/questions" && method === "POST") {
        const body = JSON.parse(String(init?.body));
        created = { ...created, text: body.text, topics: [topics[0]], tags: [tags[0]] };
        return { ok: true, status: 201, json: async () => created } as Response;
      }
      if (path === "/api/v1/questions/7/archive" && method === "POST") {
        archived = true;
        created = { ...created, archived_at: "2026-10-08T00:00:00Z" };
        return { ok: true, status: 200, json: async () => created } as Response;
      }
      throw new Error(`Unexpected request: ${method} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(Page!, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("button[aria-label='切换新增题目表单']").trigger("click");
    await wrapper.get("textarea[aria-label='题目正文']").setValue("What is RAG?");
    await wrapper.get("input[type='checkbox'][value='1']").setValue(true);
    await wrapper.get("input[type='checkbox'][value='2']").setValue(true);
    await wrapper.get("form[aria-label='题目表单']").trigger("submit.prevent");
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/questions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          text: "What is RAG?",
          answer_type: null,
          difficulty: null,
          topic_ids: [1],
          tag_ids: [2],
        }),
      }),
    );
    expect(wrapper.text()).toContain("What is RAG?");

    await wrapper.get("button[aria-label='归档题目 7']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("当前没有题目");
  });

  it("marks linked inactive taxonomy and allows it to be removed", async () => {
    const formModules = import.meta.glob("../src/components/QuestionForm.vue", { eager: true });
    const formModule = formModules["../src/components/QuestionForm.vue"] as
      | { default?: object }
      | undefined;
    expect(formModule, "missing feature: QuestionForm.vue").toBeDefined();
    const Form = formModule!.default;
    const inactiveTopic = { id: 8, name: "Legacy Topic", is_active: false };
    const inactiveTag = { id: 9, name: "Legacy Tag", is_active: false };

    const wrapper = mount(Form!, {
      props: {
        initialText: "Existing question",
        topics: [inactiveTopic],
        tags: [inactiveTag],
        initialTopicIds: [8],
        initialTagIds: [9],
      },
    });

    expect(wrapper.text()).toContain("Legacy Topic（停用，先移除或替换）");
    expect(wrapper.text()).toContain("Legacy Tag（停用，先移除或替换）");
    expect(wrapper.get("input[type='checkbox'][value='8']").element.disabled).toBe(false);
    expect(wrapper.get("input[type='checkbox'][value='9']").element.disabled).toBe(false);
  });

  it("renders question validation errors from the shared envelope", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionBankPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionBankPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule, "missing feature: QuestionBankPage.vue").toBeDefined();
    const Page = pageModule!.default;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions" && (init?.method ?? "GET") === "GET") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      return {
        ok: false,
        status: 400,
        json: async () => ({
          error: {
            code: "VALIDATION_ERROR",
            message: "Invalid question",
            fields: { text: "Question text is required" },
          },
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(Page!, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("button[aria-label='切换新增题目表单']").trigger("click");
    await wrapper.get("form[aria-label='题目表单']").trigger("submit.prevent");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("Question text is required");
  });

  it("omits unchanged inactive taxonomy when editing question text", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule, "missing feature: QuestionDetailPage.vue").toBeDefined();
    const topic = { id: 8, parent_id: null, slug: "inactive", name: "Legacy Topic", is_active: false };
    const tag = { id: 9, name: "Legacy Tag", is_active: false };
    let question = { ...makeQuestion(1, "Original question"), topics: [topic], tags: [tag] };
    let patchBody: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        if (path === "/api/v1/questions/1" && (init?.method ?? "GET") === "GET") {
          return { ok: true, status: 200, json: async () => question } as Response;
        }
        if (path === "/api/v1/topics" || path === "/api/v1/tags") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1/practice-reviews") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1" && init?.method === "PATCH") {
          patchBody = JSON.parse(String(init.body));
          question = { ...question, text: String(patchBody.text) };
          return { ok: true, status: 200, json: async () => question } as Response;
        }
        throw new Error(`Unexpected request: ${String(init?.method ?? "GET")} ${path}`);
      }),
    );

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("textarea[aria-label='题目正文']").setValue("Updated question text");
    await wrapper.get("form[aria-label='题目表单']").trigger("submit.prevent");
    await flushPromises();

    expect(patchBody).toMatchObject({ text: "Updated question text" });
    expect(patchBody).not.toHaveProperty("topic_ids");
    expect(patchBody).not.toHaveProperty("tag_ids");
    expect(wrapper.text()).toContain("Legacy Topic");
  });

  it("keeps the question form available after a validation error", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule).toBeDefined();
    let question = makeQuestion(1, "Question that can be corrected");
    let patchCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/questions/1" && (init?.method ?? "GET") === "GET") {
        return { ok: true, status: 200, json: async () => question } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions/1/practice-reviews") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions/1" && init?.method === "PATCH") {
        patchCount += 1;
        const body = JSON.parse(String(init.body));
        if (patchCount === 1) {
          return {
            ok: false,
            status: 400,
            json: async () => ({
              error: { code: "VALIDATION_ERROR", message: "Invalid question", fields: { text: "Invalid" } },
            }),
          } as Response;
        }
        question = { ...question, text: body.text };
        return { ok: true, status: 200, json: async () => question } as Response;
      }
      throw new Error(`Unexpected request: ${String(init?.method ?? "GET")} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();
    const textarea = wrapper.get("textarea[aria-label='题目正文']");
    await textarea.setValue("   ");
    await wrapper.get("form[aria-label='题目表单']").trigger("submit.prevent");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("Invalid");
    expect(wrapper.get("form[aria-label='题目表单']").exists()).toBe(true);
    await wrapper.get("textarea[aria-label='题目正文']").setValue("Corrected question");
    await wrapper.get("form[aria-label='题目表单']").trigger("submit.prevent");
    await flushPromises();

    expect(patchCount).toBe(2);
    expect(wrapper.text()).toContain("练习掌握度历史");
  });

  it("offers a retry after the initial detail request fails", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule).toBeDefined();
    let detailAttempts = 0;
    const question = makeQuestion(1, "Retry this detail load");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/v1/questions/1") {
          detailAttempts += 1;
          if (detailAttempts === 1) {
            return {
              ok: false,
              status: 500,
              json: async () => ({ error: { code: "INTERNAL_ERROR", message: "Temporary failure" } }),
            } as Response;
          }
          return { ok: true, status: 200, json: async () => question } as Response;
        }
        if (path === "/api/v1/topics" || path === "/api/v1/tags") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1/practice-reviews") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        throw new Error(`Unexpected request: ${path}`);
      }),
    );

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("Temporary failure");
    await wrapper.get("button[aria-label='重试加载题目详情']").trigger("click");
    await flushPromises();

    expect(detailAttempts).toBe(2);
    expect((wrapper.get("textarea[aria-label='题目正文']").element as HTMLTextAreaElement).value).toBe(
      "Retry this detail load",
    );
  });

  it("shows the OCR source snapshot and original-image link for a question", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule).toBeDefined();
    const question = makeQuestion(1, "Question sourced from screenshot");
    const sourceRows = [
      {
        question_source_id: 91,
        question_id: 1,
        source_asset_id: 8,
        source_title: "Interview screenshot",
        original_filename: "capture.png",
        source_text_snapshot: "What is MCP?",
        raw_ocr_text_snapshot: "1. What is MCP?\nMCP protocol details",
        locator_json: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
        locator_correction_json: null,
        ocr_block_ids: ["block-uuid-1"],
        original_image_url: "/api/v1/sources/8/original",
        display_image_url: "/api/v1/sources/8/display",
      },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/questions/1") {
        return { ok: true, status: 200, json: async () => question } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions/1/practice-reviews") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/questions/1/sources") {
        return { ok: true, status: 200, json: async () => sourceRows } as Response;
      }
      throw new Error("Unexpected request: " + path);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[aria-label='题目来源证据']").text()).toContain("What is MCP?");
    expect(wrapper.text()).toContain("1. What is MCP?");
    expect(wrapper.get("a[href='/api/v1/sources/8/original']").exists()).toBe(true);
    expect(wrapper.get("img[alt='题目来源截图区域预览']").attributes("src")).toBe(
      "/api/v1/sources/8/display",
    );
  });
});

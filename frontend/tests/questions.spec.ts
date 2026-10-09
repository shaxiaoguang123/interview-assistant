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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
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
    expect((wrapper.get("input[type='checkbox'][value='8']").element as HTMLInputElement).disabled).toBe(false);
    expect((wrapper.get("input[type='checkbox'][value='9']").element as HTMLInputElement).disabled).toBe(false);
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
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          patchBody = body;
          question = { ...question, text: String(body.text) };
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
    expect(wrapper.find("[aria-label='截图来源定位']").exists()).toBe(false);
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
    expect(wrapper.find("form[aria-label='题目表单']").exists()).toBe(true);
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

  it("reuses the source viewer to highlight and switch OCR question sources", async () => {
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
        display_width: 1080,
        display_height: 1800,
        source_text_snapshot: "What is MCP?",
        raw_ocr_text_snapshot: "1. What is MCP?\nMCP protocol details",
        locator_json: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
        locator_correction_json: { x: 0.2, y: 0.25, width: 0.45, height: 0.12 },
        ocr_block_ids: ["block-uuid-1"],
        ocr_blocks: [
          {
            id: "block-uuid-1",
            text: "What is MCP?",
            bbox: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
            reading_order: 0,
            confidence: 0.95,
          },
        ],
        original_image_url: "/api/v1/sources/8/original",
        display_image_url: "/api/v1/sources/8/display",
      },
      {
        question_source_id: 92,
        question_id: 1,
        source_asset_id: 9,
        source_title: "Second screenshot",
        original_filename: "second.png",
        display_width: 800,
        display_height: 1200,
        source_text_snapshot: "How does MCP connect tools?",
        raw_ocr_text_snapshot: "How does MCP connect tools?\nOther text",
        locator_json: { x: 0.4, y: 0.5, width: 0.4, height: 0.12 },
        locator_correction_json: null,
        ocr_block_ids: ["block-uuid-2"],
        ocr_blocks: [
          {
            id: "block-uuid-2",
            text: "How does MCP connect tools?",
            bbox: { x: 0.4, y: 0.5, width: 0.4, height: 0.12 },
            reading_order: 0,
            confidence: 0.9,
          },
        ],
        original_image_url: "/api/v1/sources/9/original",
        display_image_url: "/api/v1/sources/9/display",
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
    expect(wrapper.find("a[href='/api/v1/sources/8/original']").exists()).toBe(true);
    expect(wrapper.find("[aria-label='截图来源定位']").exists()).toBe(true);
    expect(wrapper.get("[data-source-region-id='91']").attributes("x")).toBe("216");
    expect(wrapper.get("img[alt='EXIF 方向校正后的截图预览']").attributes("src")).toBe(
      "/api/v1/sources/8/display",
    );
    await wrapper.get("button[aria-label='来源区域 92']").trigger("click");
    await flushPromises();
    expect(wrapper.get("img[alt='EXIF 方向校正后的截图预览']").attributes("src")).toBe(
      "/api/v1/sources/9/display",
    );
    expect(wrapper.get("[data-source-region-id='92']").attributes("data-selected")).toBe("true");
    expect(wrapper.get("[aria-label='题目来源证据']").text()).toContain("Other text");
    expect(wrapper.find("a[href='/api/v1/sources/9/original']").exists()).toBe(true);
  });

  it("distinguishes source API failure from no sources and retries successfully", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule).toBeDefined();
    const sourceRow = {
      question_source_id: 201,
      question_id: 1,
      source_asset_id: 20,
      source_title: "Recovered screenshot",
      original_filename: "recovered.png",
      display_width: 800,
      display_height: 1200,
      source_text_snapshot: "Source loaded after retry",
      raw_ocr_text_snapshot: "Source loaded after retry",
      locator_json: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
      locator_correction_json: null,
      ocr_block_ids: [],
      ocr_blocks: [],
      original_image_url: "/api/v1/sources/20/original",
      display_image_url: "/api/v1/sources/20/display",
    };
    let sourceAttempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/v1/questions/1") {
          return { ok: true, status: 200, json: async () => makeQuestion(1, "Question with source") } as Response;
        }
        if (path === "/api/v1/topics" || path === "/api/v1/tags") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1/practice-reviews") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1/sources") {
          sourceAttempts += 1;
          if (sourceAttempts === 1) {
            return {
              ok: false,
              status: 503,
              json: async () => ({ error: { code: "UNAVAILABLE", message: "Source service unavailable" } }),
            } as Response;
          }
          return { ok: true, status: 200, json: async () => [sourceRow] } as Response;
        }
        throw new Error("Unexpected request: " + path);
      }),
    );

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[aria-label='题目来源加载失败']").text()).toContain("Source service unavailable");
    expect(wrapper.find("[aria-label='暂无截图来源']").exists()).toBe(false);
    await wrapper.get("button[aria-label='重试加载题目来源']").trigger("click");
    await flushPromises();

    expect(sourceAttempts).toBe(2);
    expect(wrapper.find("[data-source-asset-id='20']").exists()).toBe(true);
    expect(wrapper.get("[aria-label='题目来源证据']").text()).toContain("Source loaded after retry");
    expect(wrapper.find("[aria-label='题目来源加载失败']").exists()).toBe(false);
  });

  it("shows a real empty-source state for a manual question", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule).toBeDefined();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/v1/questions/1") {
          return { ok: true, status: 200, json: async () => makeQuestion(1, "Manual question") } as Response;
        }
        if (path === "/api/v1/topics" || path === "/api/v1/tags") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1/practice-reviews") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (path === "/api/v1/questions/1/sources") {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        throw new Error("Unexpected request: " + path);
      }),
    );
    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[aria-label='暂无截图来源']").text()).toBe("暂无截图来源");
    expect(wrapper.find("[aria-label='截图来源定位']").exists()).toBe(false);
    expect(wrapper.find("[aria-label='题目来源加载失败']").exists()).toBe(false);
  });

  it("ignores a delayed source response after navigation to another question", async () => {
    const pageModules = import.meta.glob("../src/pages/QuestionDetailPage.vue", { eager: true });
    const pageModule = pageModules["../src/pages/QuestionDetailPage.vue"] as
      | { default?: object }
      | undefined;
    expect(pageModule).toBeDefined();
    const sourceA = deferred<Response>();
    const sourceForQuestion = (questionId: number, sourceId: number, text: string) => [{
      question_source_id: sourceId,
      question_id: questionId,
      source_asset_id: sourceId,
      source_title: text,
      original_filename: `${sourceId}.png`,
      display_width: 800,
      display_height: 1200,
      source_text_snapshot: text,
      raw_ocr_text_snapshot: text,
      locator_json: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
      locator_correction_json: null,
      ocr_block_ids: [],
      ocr_blocks: [],
      original_image_url: `/api/v1/sources/${sourceId}/original`,
      display_image_url: `/api/v1/sources/${sourceId}/display`,
    }];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const questionMatch = path.match(/^\/api\/v1\/questions\/(\d+)(?:\/([^/]+))?$/);
      if (questionMatch && !questionMatch[2]) {
        const id = Number(questionMatch[1]);
        return { ok: true, status: 200, json: async () => makeQuestion(id, `Question ${id}`) } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      const reviews = path.match(/^\/api\/v1\/questions\/(\d+)\/practice-reviews$/);
      if (reviews) return { ok: true, status: 200, json: async () => [] } as Response;
      const sources = path.match(/^\/api\/v1\/questions\/(\d+)\/sources$/);
      if (sources && sources[1] === "1") return sourceA.promise;
      if (sources && sources[1] === "2") {
        return { ok: true, status: 200, json: async () => sourceForQuestion(2, 202, "Question B source") } as Response;
      }
      throw new Error("Unexpected request: " + path);
    });
    vi.stubGlobal("fetch", fetchMock);

    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(pageModule!.default!, { global: { plugins: [router] } });
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/questions/1/sources", expect.anything());

    await router.push("/questions/2");
    await flushPromises();
    expect(wrapper.find("[data-source-asset-id='202']").exists()).toBe(true);
    sourceA.resolve({
      ok: true,
      status: 200,
      json: async () => sourceForQuestion(1, 101, "Delayed Question A source"),
    } as Response);
    await flushPromises();

    expect(wrapper.find("[data-source-asset-id='202']").exists()).toBe(true);
    expect(wrapper.get("[aria-label='题目来源证据']").text()).toContain("Question B source");
    expect(wrapper.get("[aria-label='题目来源证据']").text()).not.toContain("Delayed Question A source");
    expect(wrapper.find("[aria-label='题目来源加载失败']").exists()).toBe(false);
  });
});

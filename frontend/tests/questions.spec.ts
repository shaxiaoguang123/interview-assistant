import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";

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
});

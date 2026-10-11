import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import { createAppRouter } from "../src/router";
import MockInterviewAnswerExport from "../src/components/mock-interview/MockInterviewAnswerExport.vue";
import MockInterviewSummary from "../src/components/mock-interview/MockInterviewSummary.vue";
import MockInterviewReviewPanel from "../src/components/mock-interview/MockInterviewReviewPanel.vue";
import MockInterviewSavedPage from "../src/pages/MockInterviewSavedPage.vue";
import type { MockInterviewTurn } from "../src/api/mock-interviews";

const turn: MockInterviewTurn & { id: number } = {
  id: 402,
  ordinal: 2,
  question_id: 31,
  question_text: "LangGraph Checkpointer 如何工作？",
  kind: "answer",
  text: "原始回答：保存线程状态并支持恢复。",
  sources: [],
  created_at: "2026-10-11T00:00:00Z",
};

const existingAnswer = {
  id: 90,
  question_id: 31,
  source_session_item_id: null,
  is_pinned: false,
  archived_at: null,
  created_at: "2026-10-10T00:00:00Z",
  updated_at: "2026-10-10T00:00:00Z",
  version_count: 1,
  current_version: {
    id: 900,
    saved_answer_id: 90,
    version_no: 1,
    content: "此前整理的回答",
    self_rating: 5,
    self_rating_updated_at: null,
    origin_kind: "ai_generated",
    source_session_item_id: null,
    source_practice_review_id: null,
    based_on_version_id: null,
    assistant_output_id: 10,
    created_at: "2026-10-10T00:00:00Z",
  },
};

function response(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response;
}

async function mountExport(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  const router = createAppRouter(createMemoryHistory());
  await router.push(`/mock-interview/saved/14`);
  await router.isReady();
  const wrapper = mount(MockInterviewAnswerExport, {
    props: { recordId: 14, turn },
    global: { plugins: [router] },
  });
  await wrapper.get("button").trigger("click");
  await flushPromises();
  return wrapper;
}

describe("mock interview answer export", () => {
  it("previews and edits a user answer before explicitly creating a SavedAnswer", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/api/v1/questions/31/saved-answers")) return response([]);
      if (path.endsWith("/api/v1/mock-interviews/saved/14/answers/402/export")) {
        expect(JSON.parse(String(init?.body))).toEqual({
          save_mode: "new_answer",
          content: "我补充了 thread_id 的隔离边界。",
          self_rating: 4,
        });
        return response({
          saved_answer: { id: 91, question_id: 31, is_pinned: false, archived_at: null },
          version: { id: 901, saved_answer_id: 91, version_no: 1, content: "我补充了 thread_id 的隔离边界。", self_rating: 4, origin_kind: "user_written" },
          source: { mock_interview_id: 14, mock_interview_title: "Agent 面试", turn_id: 402, question_id: 31, question_text: turn.question_text },
          already_exported: false,
        }, 201);
      }
      throw new Error(`Unexpected request ${String(init?.method ?? "GET")} ${path}`);
    });
    const wrapper = await mountExport(fetchMock);
    const content = wrapper.get("textarea[aria-label='最终保存内容']");
    expect((content.element as HTMLTextAreaElement).value).toBe(turn.text);
    await content.setValue("我补充了 thread_id 的隔离边界。");
    await wrapper.get("select[aria-label='答案质量评分']").setValue("4");
    await wrapper.get("button[aria-label='确认保存回答']").trigger("click");
    await flushPromises();

    expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/export"))).toHaveLength(1);
    expect(wrapper.text()).toContain("回答 #91 · v1");
    expect(wrapper.text()).toContain("来源：模拟面试 #14");
    expect(wrapper.emitted("saved")?.[0]?.[0]).toMatchObject({
      saved_answer: { id: 91 },
      version: { id: 901, origin_kind: "user_written" },
    });
  });

  it("appends a new user-written version and preserves the draft after a failed request", async () => {
    let failExport = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/api/v1/questions/31/saved-answers")) return response([existingAnswer]);
      if (path.endsWith("/api/v1/mock-interviews/saved/14/answers/402/export")) {
        const payload = JSON.parse(String(init?.body));
        expect(payload).toMatchObject({ save_mode: "append_version", saved_answer_id: 90 });
        if (failExport) {
          failExport = false;
          return response({ error: { code: "CONFLICT", message: "回答已导出，请重新加载。" } }, 409);
        }
        return response({
          saved_answer: { id: 90, question_id: 31, is_pinned: false, archived_at: null },
          version: { id: 902, saved_answer_id: 90, version_no: 2, content: "编辑后的版本", self_rating: null, origin_kind: "user_written" },
          source: { mock_interview_id: 14, mock_interview_title: "Agent 面试", turn_id: 402, question_id: 31, question_text: turn.question_text },
          already_exported: false,
        }, 201);
      }
      throw new Error(`Unexpected request ${String(init?.method ?? "GET")} ${path}`);
    });
    const wrapper = await mountExport(fetchMock);
    await wrapper.get("select[aria-label='保存方式']").setValue("append_version");
    await wrapper.get("textarea[aria-label='最终保存内容']").setValue("编辑后的版本");
    await wrapper.get("button[aria-label='确认保存回答']").trigger("click");
    await flushPromises();

    expect(wrapper.get("textarea[aria-label='最终保存内容']").element).toHaveProperty("value", "编辑后的版本");
    expect(wrapper.text()).toContain("回答已导出，请重新加载。");
    await wrapper.get("button[aria-label='确认保存回答']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("回答 #90 · v2");
    expect(wrapper.emitted("saved")?.length).toBe(1);
  });

  it("cancels without writing and shows an existing export instead of offering another copy", async () => {
    const alreadyExportedTurn = {
      ...turn,
      answer_export: { saved_answer_id: 91, saved_answer_version_id: 901, version_no: 1, question_id: 31, self_rating: null, created_at: "2026-10-11T00:00:00Z" },
    };
    const fetchMock = vi.fn(async () => response([]));
    vi.stubGlobal("fetch", fetchMock);
    const router = createAppRouter(createMemoryHistory());
    await router.push("/mock-interview/saved/14");
    await router.isReady();
    const wrapper = mount(MockInterviewAnswerExport, {
      props: { recordId: 14, turn: alreadyExportedTurn },
      global: { plugins: [router] },
    });
    expect(wrapper.text()).toContain("回答 #91 · v1");
    expect(wrapper.text()).toContain("来源：模拟面试 #14");
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("mock interview review actions", () => {
  it("loads wrong state and marks the actual canonical question only after user action", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/api/v1/mock-interviews/saved/14")) {
        return response({
          id: 14,
          title: "合成模拟面试",
          topic_id: null,
          topic_name: "Agent 技术",
          question_count: 1,
          started_at: turn.created_at,
          ended_at: turn.created_at,
          created_at: turn.created_at,
          context_selection: { project_ids: [], material_ids: [], exclude_material_ids: [] },
          summary: {
            overview: "复习 thread_id 隔离。",
            items: [{ question_id: 31, question_text: turn.question_text, answer_summary: "回答摘要", missing_points: ["隔离边界"], technical_concerns: [], next_directions: [] }],
            recommendations: [{ question_id: 31, question_text: turn.question_text, reason: "补足隔离设计。" }],
          },
          summary_sources: [],
          provider: "fake",
          model: "test-model",
          turns: [
            { ...turn, id: 401, ordinal: 1, kind: "question", text: turn.question_text },
            turn,
          ],
        });
      }
      if (path.endsWith("/api/v1/questions/31") && (!init || !init.method)) {
        return response({ id: 31, status: "active", archived_at: null, canonical_question_id: 31, state: { is_wrong: false } });
      }
      if (path.endsWith("/api/v1/questions/31/state") && init?.method === "PATCH") {
        expect(JSON.parse(String(init.body))).toEqual({ is_wrong: true });
        return response({ question_id: 31, is_wrong: true });
      }
      throw new Error(`Unexpected request ${String(init?.method ?? "GET")} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = createAppRouter(createMemoryHistory());
    await router.push("/mock-interview/saved/14");
    await router.isReady();
    const wrapper = mount(MockInterviewSavedPage, { global: { plugins: [router] } });
    await flushPromises();

    const markButton = wrapper.findAll("button").find((button) => button.text() === "标记为错题");
    expect(markButton, wrapper.text()).toBeTruthy();
    await markButton!.trigger("click");
    await flushPromises();

    expect(fetchMock.mock.calls.some(([path, init]) => String(path).endsWith("/state") && init?.method === "PATCH")).toBe(true);
    expect(wrapper.text()).toContain("已标记为错题");
    expect(wrapper.find("a[href='/practice?mode=wrong']").exists()).toBe(true);
  });

  it("groups the saved transcript by original question and keeps the full timeline available", async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push("/mock-interview/saved/14");
    await router.isReady();
    const turns: Array<MockInterviewTurn & { id: number }> = [
      { ...turn, id: 401, ordinal: 1, kind: "question", text: turn.question_text },
      turn,
      { ...turn, id: 403, ordinal: 3, kind: "follow_up", text: "thread_id 如何隔离状态？" },
      { ...turn, id: 404, ordinal: 4, text: "每个用户和会话应使用隔离的 thread_id。" },
    ];
    const wrapper = mount(MockInterviewReviewPanel, {
      props: { recordId: 14, turns },
      global: { plugins: [router] },
    });

    expect(wrapper.text()).toContain("LangGraph Checkpointer 如何工作？");
    expect(wrapper.text()).toContain("thread_id 如何隔离状态？");
    expect(wrapper.findAll("button").filter((button) => button.text().includes("保存为题库回答"))).toHaveLength(2);
    expect(wrapper.find("details summary").text()).toContain("完整对话时间线");
    expect(wrapper.findAll("a[href='/questions/31']").length).toBeGreaterThan(0);
  });

  it("shows real-question links and emits a deliberate wrong-question action", async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push("/mock-interview/saved/14");
    await router.isReady();
    const wrapper = mount(MockInterviewSummary, {
      props: {
        summary: {
          overview: "需要补充状态隔离的说明。",
          items: [{
            question_id: 31,
            question_text: turn.question_text,
            answer_summary: "说明状态持久化。",
            missing_points: ["thread_id 隔离"],
            technical_concerns: [],
            next_directions: ["讨论多请求并发"],
          }],
          recommendations: [{ question_id: 31, question_text: turn.question_text, reason: "复习状态隔离。" }],
        },
        questionStates: { 31: { is_wrong: false, writable: true } },
        markingQuestionIds: [],
      },
      global: { plugins: [router] },
    });

    expect(wrapper.find("a[href='/questions/31']").exists()).toBe(true);
    const markButton = wrapper.get("button");
    await markButton.trigger("click");
    expect(wrapper.emitted("markWrong")?.[0]).toEqual([31]);
    expect(wrapper.text()).toContain("开始错题练习");
  });
});

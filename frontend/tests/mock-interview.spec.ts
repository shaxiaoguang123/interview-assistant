import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import { createAppRouter } from "../src/router";
import MockInterviewSetupForm from "../src/components/mock-interview/MockInterviewSetupForm.vue";
import MockInterviewRoomPage from "../src/pages/MockInterviewRoomPage.vue";
import type { MockInterviewOptions, MockInterviewState } from "../src/api/mock-interviews";

const options: MockInterviewOptions = {
  topics: [{ id: 1, name: "Agent 技术" }],
  topic_question_counts: { 1: 3 },
  projects: [{ id: 7, name: "Interview Copilot" }],
  materials: [
    { id: 11, title: "Project Profile", kind: "project_profile", project_id: 7, version_no: 2, is_system_managed: true },
    { id: 12, title: "Unselected Resume", kind: "resume", project_id: null, version_no: 1, is_system_managed: false },
  ],
  available_question_count: 3,
  llm_configured: false,
};

function temporarySession(overrides: Partial<MockInterviewState> = {}): MockInterviewState {
  return {
    id: "1d158195-4687-4992-9677-68d8a2e87555",
    revision: 0,
    status: "active",
    topic_id: 1,
    topic_name: "Agent 技术",
    question_count: 2,
    current_index: 0,
    questions: [
      { id: 31, text: "LangGraph checkpointer 的作用是什么？", ordinal: 1 },
      { id: 32, text: "MCP 如何发现和调用工具？", ordinal: 2 },
    ],
    current_question: { id: 31, text: "LangGraph checkpointer 的作用是什么？", ordinal: 1 },
    turns: [{ ordinal: 1, question_id: 31, question_text: "LangGraph checkpointer 的作用是什么？", kind: "question", text: "LangGraph checkpointer 的作用是什么？", sources: [], created_at: "2026-10-11T00:00:00Z" }],
    context_selection: { project_ids: [], material_ids: [], exclude_material_ids: [] },
    context_sources: [],
    llm_configured: true,
    started_at: "2026-10-11T00:00:00Z",
    ended_at: null,
    summary: null,
    summary_sources: [],
    saved_record_id: null,
    ...overrides,
  };
}

describe("text mock interview", () => {
  it("keeps the interview optional and emits only the chosen project context", async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push("/mock-interview");
    await router.isReady();
    const wrapper = mount(MockInterviewSetupForm, { props: { options }, global: { plugins: [router] } });
    expect(wrapper.text()).toContain("未配置 AI Provider");
    expect((wrapper.get("button[type='submit']").element as HTMLButtonElement).disabled).toBe(false);

    const projectCheckbox = wrapper.findAll("input[type='checkbox']")[0];
    await projectCheckbox.setValue(true);
    const sourceCheckboxes = wrapper.findAll("input[type='checkbox']");
    expect(sourceCheckboxes).toHaveLength(3);
    expect((sourceCheckboxes[1].element as HTMLInputElement).checked).toBe(true);
    expect((sourceCheckboxes[2].element as HTMLInputElement).checked).toBe(false);
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("start")?.[0]?.[0]).toMatchObject({
      topic_id: null,
      question_count: 3,
      context: { project_ids: [7], material_ids: [], exclude_material_ids: [] },
    });
  });

  it("preserves the typed answer when the provider fails", async () => {
    const initial = temporarySession();
    const afterFailure = temporarySession({
      revision: 1,
      turns: [
        ...initial.turns,
        { ordinal: 2, question_id: 31, question_text: initial.questions[0].text, kind: "answer", text: "保存状态并支持恢复。", sources: [], created_at: "2026-10-11T00:01:00Z" },
      ],
    });
    let reads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith(`/api/v1/mock-interviews/${initial.id}`)) {
        reads += 1;
        return { ok: true, status: 200, json: async () => reads === 1 ? initial : afterFailure } as Response;
      }
      if (path.endsWith(`/api/v1/mock-interviews/${initial.id}/follow-up`) && init?.method === "POST") {
        return { ok: false, status: 504, json: async () => ({ error: { code: "LLM_TIMEOUT", message: "模型请求超时，输入已保留，可重试。" } }) } as Response;
      }
      throw new Error(`Unexpected request ${String(init?.method ?? "GET")} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = createAppRouter(createMemoryHistory());
    await router.push({ name: "mock-interview-room", params: { sessionId: initial.id } });
    await router.isReady();
    const wrapper = mount(MockInterviewRoomPage, { global: { plugins: [router] } });
    await flushPromises();
    const answer = "保存状态并支持恢复。";
    await wrapper.get("textarea[aria-label='模拟面试回答']").setValue(answer);
    await wrapper.get("button").trigger("click");
    await flushPromises();

    expect((wrapper.get("textarea[aria-label='模拟面试回答']").element as HTMLTextAreaElement).value).toBe(answer);
    expect(wrapper.text()).toContain("模型请求超时");
    const followUpCall = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/follow-up"));
    expect(JSON.parse(String(followUpCall?.[1]?.body))).toEqual({ answer, expected_revision: 0 });
  });

  it("does not offer automatic persistence while an interview is active", async () => {
    const state = temporarySession();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith(`/api/v1/mock-interviews/${state.id}`)) {
        return { ok: true, status: 200, json: async () => state } as Response;
      }
      throw new Error(`Unexpected request ${String(input)}`);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push({ name: "mock-interview-room", params: { sessionId: state.id } });
    await router.isReady();
    const wrapper = mount(MockInterviewRoomPage, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("让 AI 继续追问");
    expect(wrapper.text()).not.toContain("保存本次模拟面试");
  });
});

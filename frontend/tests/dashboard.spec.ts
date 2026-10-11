import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import DashboardPage from "../src/pages/DashboardPage.vue";
import QuestionBankPage from "../src/pages/QuestionBankPage.vue";
import { createAppRouter } from "../src/router";

const dashboard = {
  as_of: "2026-10-11T01:00:00Z",
  due_question_count: 2,
  pending_candidate_count: 1,
  active_question_count: 3,
  practice_session_count: 4,
  unfinished_session: { id: 4, mode: "due", started_at: "2026-10-10T09:00:00Z", completed_at: null, item_count: 3, completed_count: 1 },
  active_project_count: 1,
  recent_answers: [{ id: 5, question_id: 3, question_text: "Explain durable state", updated_at: "2026-10-10T08:00:00Z", is_pinned: true, version_id: 8, preview: "Use a transactional checkpoint.", self_rating: 4 }],
  recent_sessions: [{ id: 4, mode: "due", started_at: "2026-10-10T09:00:00Z", completed_at: null, item_count: 3, completed_count: 1 }],
  recent_materials: [{ id: 6, version_id: 9, title: "Resume", kind: "resume", updated_at: "2026-10-09T08:00:00Z", version_no: 2, is_system_managed: false }],
  recent_ai_outputs: [],
};

const emptyDashboard = {
  as_of: "2026-10-11T01:00:00Z",
  due_question_count: 0,
  pending_candidate_count: 0,
  active_question_count: 0,
  practice_session_count: 0,
  unfinished_session: null,
  active_project_count: 0,
  recent_answers: [],
  recent_sessions: [],
  recent_materials: [],
  recent_ai_outputs: [],
};

const systemStatus = {
  application: "agent-interview-assistant",
  backend: { ready: true, state: "ready" },
  python: { version: "3.12.10", supported: true },
  database: { ready: true, state: "ready", current_revision: "0007", latest_revision: "0007", migration_required: false },
  ocr: { ready: false, state: "missing", message: "OCR 模型尚未准备；题库、练习和项目功能仍可使用。" },
  llm: { configured: false },
  storage: { configured: true, location: "default" },
};

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;

describe("Dashboard workspace", () => {
  it("shows live review and Inbox counts with useful destinations", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      return path === "/api/v1/dashboard" ? json(dashboard) : path === "/api/v1/system/status" ? json(systemStatus) : json([]);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/dashboard");
    await router.isReady();
    const wrapper = mount(DashboardPage, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.text()).toContain("2");
    expect(wrapper.text()).toContain("截图待审核");
    expect(wrapper.get('a[href="/practice?mode=due"]').text()).toContain("开始复习");
    expect(wrapper.get('a[href="/practice/sessions/4"]').text()).toContain("继续练习");
    expect(wrapper.find('a[href="/inbox"]').exists()).toBe(true);
    expect(wrapper.get('a[href="/questions/3"]').text()).toContain("Explain durable state");
    expect(wrapper.text()).not.toContain("面试准备度");
  });

  it("redirects the root to Dashboard and keeps the mobile navigation operable", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/health")) return json({ status: "ok" });
      return path === "/api/v1/dashboard" ? json(dashboard) : path === "/api/v1/system/status" ? json(systemStatus) : json([]);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/dashboard");
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get('a[href="/dashboard"]').attributes("aria-current")).toBe("page");
    const menu = wrapper.get(".mobile-menu-toggle");
    expect(menu.attributes("aria-expanded")).toBe("false");
    await menu.trigger("click");
    expect(menu.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('a[href="/questions"]').exists()).toBe(true);
    await wrapper.get('a[href="/questions"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/questions");
    expect(menu.attributes("aria-expanded")).toBe("false");
  });

  it("opens the question form from the Dashboard shortcut", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([])));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions?new=1");
    await router.isReady();
    const wrapper = mount(QuestionBankPage, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.find('section[aria-label="新增题目"]').exists()).toBe(true);
  });

  it("guides a new user to existing question, Inbox, project and material flows", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      return path === "/api/v1/dashboard" ? json(emptyDashboard) : path === "/api/v1/system/status" ? json(systemStatus) : json([]);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/dashboard");
    await router.isReady();
    const wrapper = mount(DashboardPage, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.text()).toContain("欢迎开始");
    expect(wrapper.get('.welcome-action[href="/questions?new=1"]').text()).toContain("添加第一道题");
    expect(wrapper.get('.welcome-action[href="/inbox"]').text()).toContain("导入截图");
    expect(wrapper.get('.welcome-action[href="/projects?new=1"]').text()).toContain("创建个人项目");
    expect(wrapper.get('.welcome-action[href="/materials?upload=1"]').text()).toContain("上传简历或资料");
    expect(wrapper.text()).toContain("OCR 模型尚未准备");
    await wrapper.get('.welcome-action[href="/questions?new=1"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/questions?new=1");
    wrapper.unmount();
  });
});

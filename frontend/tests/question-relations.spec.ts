import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import InboxPage from "../src/pages/InboxPage.vue";
import QuestionRelationReview from "../src/components/QuestionRelationReview.vue";
import QuestionDetailPage from "../src/pages/QuestionDetailPage.vue";
import { createAppRouter } from "../src/router";

function json(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function relation(id = 1, otherId = 9, kind = "exact", decision = "suggested", type = "same_question") {
  return {
    id, question_id: 1, related_question_id: otherId, relation_type: type,
    decision_status: decision, suggested_by: decision === "suggested" ? "rule" : "user",
    confidence: kind === "exact" ? 1 : 0.46, match_kind: kind, review_token: String(id).padStart(64, "a"),
    other_question: { id: otherId, text: "相似题 " + otherId, status: "active", canonical_question_id: otherId, candidate_state: null },
  };
}

function result(questionId = 1, rows = [relation()]) {
  const unresolved = rows.filter((row) => row.relation_type === "same_question" && row.decision_status !== "rejected").length;
  return {
    question_id: questionId, canonical_question_id: null, candidate_state: "pending_review",
    total_count: rows.length, unresolved_count: unresolved, confirmation_blocked: unresolved > 0,
    scan_required: false, candidates: rows,
  };
}

function mountReview() {
  return mount(QuestionRelationReview, {
    props: { questionId: 1, text: "What is MCP?", contextKey: "first" },
    global: { stubs: { RouterLink: true } },
  });
}

describe("relation review panel", () => {
  it("labels exact and approximate matches as suggestions and offers no same-question final acceptance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(result(1, [relation(), relation(2, 10, "trigram")]))));
    const wrapper = mountReview();
    await flushPromises();
    expect(wrapper.text()).toContain("完全重复");
    expect(wrapper.text()).toContain("近似建议");
    expect(wrapper.text()).toContain("规则建议，尚未确认");
    expect(wrapper.text()).toContain("后续规范题归并功能");
    expect(wrapper.findAll("button").some((button) => /确认同题|已归并|执行归并/.test(button.text()))).toBe(false);
    await wrapper.get("button[aria-label='暂不处理关系 1']").trigger("click");
    expect(wrapper.text()).toContain("保留建议");
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ canConfirm: false });
  });

  it.each([
    ["排除误报", "same_question", "rejected", "已排除"],
    ["标记为相关题", "related_question", "accepted", "相关题"],
    ["标记为不同题", "different_question", "accepted", "不同题"],
  ])("supports %s and opens the confirmation gate after rereading current relations", async (label, type, decision, visible) => {
    let rows = [relation()];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const payload = JSON.parse(String(init.body)) as Record<string, unknown>;
        expect(payload).toMatchObject({ question_id: 1, relation_type: type, decision_status: decision, expected_review_token: rows[0].review_token });
        rows = [relation(1, 9, "exact", decision, type)];
        return json(rows[0]);
      }
      return json(result(1, rows));
    }));
    const wrapper = mountReview();
    await flushPromises();
    await wrapper.get(`button[aria-label='${label}关系 1']`).trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain(visible);
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ questionId: 1, contextKey: "first", canConfirm: true });
  });

  it("shows a load error and retry without claiming there are no similar questions", async () => {
    let fail = true;
    vi.stubGlobal("fetch", vi.fn(async () => fail ? json({ error: { code: "INTERNAL_ERROR", message: "similarity offline" } }, 500) : json(result())));
    const wrapper = mountReview();
    await flushPromises();
    expect(wrapper.get("[role='alert']").text()).toContain("similarity offline");
    expect(wrapper.text()).not.toContain("暂无相似题");
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ canConfirm: false });
    fail = false;
    await wrapper.get("button[aria-label='重新加载相似题']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("相似题 9");
    expect(wrapper.find("[role='alert']").exists()).toBe(false);
  });

  it("keeps a 409 decision error visible until rescan and never treats the failed write as reviewed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") return json({ error: { code: "REVIEW_CONFLICT", message: "review changed" } }, 409);
      return json(result());
    }));
    const wrapper = mountReview();
    await flushPromises();
    await wrapper.get("button[aria-label='排除误报关系 1']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[role='alert']").text()).toContain("review changed");
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ canConfirm: false });
    await wrapper.get("button[aria-label='重新扫描相似题']").trigger("click");
    await flushPromises();
    expect(wrapper.find("[role='alert']").exists()).toBe(false);
    expect(wrapper.text()).toContain("规则建议，尚未确认");
  });

  it("does not apply a delayed old question load after A → B → A", async () => {
    const old = deferred<Response>();
    let first = true;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/questions/1/") && first) { first = false; return old.promise; }
      return json(result(String(input).includes("/questions/2/") ? 2 : 1, []));
    }));
    const wrapper = mountReview();
    await wrapper.setProps({ questionId: 2, text: "Question B", contextKey: "second" });
    await flushPromises();
    await wrapper.setProps({ questionId: 1, text: "Second A", contextKey: "third" });
    await flushPromises();
    old.resolve(json(result()));
    await flushPromises();
    expect(wrapper.text()).not.toContain("相似题 9");
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ questionId: 1, contextKey: "third", canConfirm: true });
  });

  it("ignores a delayed old decision failure after switching questions", async () => {
    const old = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") return old.promise;
      return json(result(String(input).includes("/questions/2/") ? 2 : 1, String(input).includes("/questions/2/") ? [] : [relation()]));
    }));
    const wrapper = mountReview();
    await flushPromises();
    await wrapper.get("button[aria-label='排除误报关系 1']").trigger("click");
    await wrapper.setProps({ questionId: 2, text: "Question B", contextKey: "second" });
    await flushPromises();
    old.resolve(json({ error: { code: "REVIEW_CONFLICT", message: "old A conflict" } }, 409));
    await flushPromises();
    expect(wrapper.text()).not.toContain("old A conflict");
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ questionId: 2, canConfirm: true });
  });

  it("reloads when candidate text changes and exposes unresolved totals beyond the display limit", async () => {
    let page = result(1, []);
    vi.stubGlobal("fetch", vi.fn(async () => json(page)));
    const wrapper = mountReview();
    await flushPromises();
    page = { ...result(1, Array.from({ length: 20 }, (_, i) => relation(i + 1, i + 10))), total_count: 21, unresolved_count: 21 };
    await wrapper.setProps({ text: "New OCR text", contextKey: "revision-1" });
    await flushPromises();
    expect(wrapper.text()).toContain("待处理 21");
    expect(wrapper.findAll("[data-relation-id]")).toHaveLength(20);
    expect(wrapper.text()).toContain("优先展示");
    expect(wrapper.emitted("state")?.at(-1)?.[0]).toMatchObject({ canConfirm: false });
  });
});

function candidate(id = 101, jobId = 11, text = "What is MCP?", revision = 0) {
  return {
    id, text, status: "pending_review", archived_at: null, candidate_state: "pending_review",
    candidate_revision: revision, origin_ingestion_job_id: jobId, split_from_candidate_id: null,
    split_child_ids: [], superseded_by_candidate_id: null, topics: [], tags: [], sources: [],
  };
}

function source(id: number, jobId: number) {
  return {
    id, source_type: "image", title: "Synthetic " + id, original_filename: "synthetic.png", mime_type: "image/png",
    byte_size: 1, original_width: 12, original_height: 8, display_width: 12, display_height: 8, sha256: "a".repeat(64), archived_at: null,
    ingestion_jobs: [{ id: jobId, source_asset_id: id, status: "succeeded", stage: "completed", failure_stage: null, engine: "fake", engine_version: "1", error_code: null, error_message: null, candidate_count: 1 }],
  };
}

function inboxFetch(custom: (path: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const override = custom(path, init);
    if (override) return override;
    if (path === "/api/v1/sources") return json([source(1, 11), source(2, 22)]);
    if (path === "/api/v1/topics" || path === "/api/v1/tags") return json([]);
    if (path === "/api/v1/ingestions/11/candidates") return json([candidate()]);
    if (path === "/api/v1/ingestions/22/candidates") return json([candidate(202, 22, "Question B")]);
    if (path.endsWith("/ocr-blocks")) return json([]);
    if (path.includes("/similar-candidates")) return json(result(path.includes("/202/") ? 202 : 101, []));
    throw new Error("Unexpected request " + path);
  });
}

describe("Inbox relation review integration", () => {
  it("blocks duplicate confirmation, permits explicit exclusion, and retains candidate expected_revision", async () => {
    let reviewed = false;
    let confirmed = false;
    vi.stubGlobal("fetch", inboxFetch((path, init) => {
      if (path === "/api/v1/questions/101/similar-candidates") return json(result(101, reviewed ? [relation(1, 9, "exact", "rejected")] : [relation()]));
      if (path === "/api/v1/question-relations/1") { reviewed = true; return json(relation(1, 9, "exact", "rejected")); }
      if (path === "/api/v1/ingestion-candidates/101/confirm") {
        expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 0 });
        confirmed = true;
        return json(candidate());
      }
      return undefined;
    }));
    const wrapper = mount(InboxPage, {global:{stubs:{RouterLink:true}}});
    await flushPromises();
    await wrapper.get("button[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("相似题 9");
    await wrapper.get("button[aria-label='排除误报关系 1']").trigger("click");
    await flushPromises();
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeUndefined();
    await wrapper.get("button[aria-label='确认进入题库']").trigger("click");
    await flushPromises();
    expect(confirmed).toBe(true);
  });

  it("keeps confirmation disabled during relation load failure and recovers after retry", async () => {
    let failed = true;
    vi.stubGlobal("fetch", inboxFetch((path) => path.includes("/similar-candidates") ?
      failed ? json({ error: { code: "INTERNAL_ERROR", message: "review unavailable" } }, 500) : json(result(101, [])) : undefined));
    const wrapper = mount(InboxPage, {global:{stubs:{RouterLink:true}}});
    await flushPromises();
    await wrapper.get("button[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("review unavailable");
    failed = false;
    await wrapper.get("button[aria-label='重新加载相似题']").trigger("click");
    await flushPromises();
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeUndefined();
  });

  it("does not let an old Job decision error block or pollute the new Job", async () => {
    const old = deferred<Response>();
    vi.stubGlobal("fetch", inboxFetch((path, init) => {
      if (init?.method === "PATCH") return old.promise;
      if (path === "/api/v1/questions/101/similar-candidates") return json(result(101));
      return undefined;
    }));
    const wrapper = mount(InboxPage, {global:{stubs:{RouterLink:true}}});
    await flushPromises();
    await wrapper.get("button[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='排除误报关系 1']").trigger("click");
    await wrapper.get("button[aria-label='打开导入任务 22']").trigger("click");
    await flushPromises();
    old.resolve(json({ error: { code: "REVIEW_CONFLICT", message: "old Job conflict" } }, 409));
    await flushPromises();
    expect(wrapper.text()).toContain("Question B");
    expect(wrapper.text()).not.toContain("old Job conflict");
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeUndefined();
  });

  it("reloads suggestions after a candidate text edit without keeping the old exclusion", async () => {
    let edited = false;
    vi.stubGlobal("fetch", inboxFetch((path, init) => {
      if (path === "/api/v1/ingestion-candidates/101" && init?.method === "PATCH") { edited = true; return json(candidate(101, 11, "Changed text", 1)); }
      if (path === "/api/v1/ingestions/11/candidates") return json([candidate(101, 11, edited ? "Changed text" : "What is MCP?", edited ? 1 : 0)]);
      if (path === "/api/v1/questions/101/similar-candidates") return json(result(101, edited ? [relation()] : [relation(1, 9, "exact", "rejected")]));
      return undefined;
    }));
    const wrapper = mount(InboxPage, {global:{stubs:{RouterLink:true}}});
    await flushPromises();
    await wrapper.get("button[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeUndefined();
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("Changed text");
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.text()).toContain("规则建议，尚未确认");
    expect(wrapper.get("button[aria-label='确认进入题库']").attributes("disabled")).toBeDefined();
  });
});

describe("Question detail relation integration", () => {
  it("keeps normal detail loaded while similarity fails and ignores old Question review errors", async () => {
    const old = deferred<Response>();
    let fail = true;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/topics" || path === "/api/v1/tags" || /\/(sources|practice-reviews)$/.test(path)) return json([]);
      const history = path.match(/^\/api\/v1\/questions\/(\d+)\/history$/);
      if (history) return json({canonical_question_id:Number(history[1]), member_question_ids:[Number(history[1])], sources:[], practice_reviews:[], session_items:[]});
      const detail = path.match(/^\/api\/v1\/questions\/(\d+)$/);
      if (detail) return json({ id: Number(detail[1]), text: "Question " + detail[1], status: "active", archived_at: null, answer_type: null, difficulty: null, topics: [], tags: [], state: { is_favorite: false, is_wrong: false, user_note: null } });
      if (init?.method === "PATCH") return old.promise;
      if (path.includes("/similar-candidates")) return fail ? json({ error: { code: "INTERNAL_ERROR", message: "detail similarity unavailable" } }, 500) : json(result(path.includes("/2/") ? 2 : 1, path.includes("/2/") ? [] : [relation()]));
      throw new Error("Unexpected request " + path);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/questions/1");
    await router.isReady();
    const wrapper = mount(QuestionDetailPage, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("textarea[aria-label='题目正文']").element).toHaveProperty("value", "Question 1");
    expect(wrapper.text()).toContain("detail similarity unavailable");
    expect(wrapper.text()).toContain("暂无截图来源");
    fail = false;
    await wrapper.get("button[aria-label='重新加载相似题']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='排除误报关系 1']").trigger("click");
    await router.push("/questions/2");
    await flushPromises();
    old.resolve(json({ error: { code: "REVIEW_CONFLICT", message: "old Question conflict" } }, 409));
    await flushPromises();
    expect(wrapper.get("textarea[aria-label='题目正文']").element).toHaveProperty("value", "Question 2");
    expect(wrapper.text()).not.toContain("old Question conflict");
  });
});

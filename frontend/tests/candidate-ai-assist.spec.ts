import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import CandidateAiAssist from "../src/components/ingestion/CandidateAiAssist.vue";
import IngestionCandidateEditor from "../src/components/IngestionCandidateEditor.vue";

const candidate = {
  id: 31,
  text: "LangGraph checkpointer 有什么作用？怎么做断点恢复？",
  difficulty: null,
  candidate_revision: 2,
  topics: [],
  tags: [],
  sources: [
    {
      question_source_id: 41,
      source_text_snapshot: "LangGraph checkpointer 有什么作用？怎么做断点恢复？",
      raw_ocr_text_snapshot: "LangGraph checkpointer 有什么作用？怎么做断点恢复？",
      ocr_blocks: [
        {
          id: "00000000-0000-4000-8000-000000000031",
          text: "LangGraph checkpointer 有什么作用？怎么做断点恢复？",
          reading_order: 0,
          bbox: { x: 0.1, y: 0.2, width: 0.7, height: 0.1 },
        },
      ],
    },
  ],
};

const suggestion = {
  candidate_id: 31,
  candidate_revision: 2,
  original_text: candidate.text,
  suggested_text: "LangGraph 的 Checkpointer 有什么作用？如何实现断点恢复？",
  topic_ids: [7],
  tag_ids: [9],
  difficulty: "medium",
  reason: "保留原文中关于状态保存和恢复的内容。",
  warnings: [],
  split_parts: [
    {
      text: "LangGraph checkpointer 有什么作用？",
      ocr_block_ids: ["00000000-0000-4000-8000-000000000031"],
      source_text_snapshot: "LangGraph checkpointer 有什么作用？",
    },
    {
      text: "怎么做断点恢复？",
      ocr_block_ids: ["00000000-0000-4000-8000-000000000031"],
      source_text_snapshot: "怎么做断点恢复？",
    },
  ],
};

const editorCandidate = {
  ...candidate,
  status: "pending_review",
  candidate_state: "pending_review",
  archived_at: null,
  sources: [
    {
      ...candidate.sources[0],
      source_asset_id: 1,
      locator_type: "image_region",
      locator_json: { x: 0.1, y: 0.2, width: 0.7, height: 0.1 },
      locator_correction_json: null,
      confidence: 0.9,
    },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("CandidateAiAssist", () => {
  it("previews exactly the saved candidate and OCR evidence before making an explicit request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(CandidateAiAssist, {
      props: {
        candidate,
        topics: [{ id: 7, name: "LangGraph", is_active: true }],
        tags: [{ id: 9, name: "Persistence", is_active: true }],
        draftDirty: false,
      },
    });

    expect(wrapper.text()).toContain(candidate.text);
    expect(wrapper.text()).toContain("怎么做断点恢复？");
    expect(fetchMock).not.toHaveBeenCalled();
    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/ingestion-candidates/31/ai-suggestions");
    await flushPromises();
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("applies only explicitly selected suggestions to the editor draft", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(suggestion)));
    const wrapper = mount(CandidateAiAssist, {
      props: { candidate, topics: [], tags: [], draftDirty: false },
    });

    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("LangGraph 的 Checkpointer");
    await wrapper.get("input[aria-label='应用建议题干']").setValue(true);
    await wrapper.get("button[aria-label='应用选中的 AI 建议到草稿']").trigger("click");

    expect(wrapper.emitted("apply")).toEqual([[{ text: suggestion.suggested_text }]]);
    expect(wrapper.emitted("apply-split")).toBeUndefined();
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("requires explicit overwrite acknowledgement when an unsaved editor draft exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(suggestion)));
    const wrapper = mount(CandidateAiAssist, {
      props: { candidate, topics: [], tags: [], draftDirty: true },
    });

    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    await flushPromises();
    await wrapper.get("input[aria-label='应用建议题干']").setValue(true);
    const apply = wrapper.get("button[aria-label='应用选中的 AI 建议到草稿']");
    expect((apply.element as HTMLButtonElement).disabled).toBe(true);
    await wrapper.get("input[aria-label='确认将选中的建议用于未保存草稿']").setValue(true);
    expect((apply.element as HTMLButtonElement).disabled).toBe(false);
    await apply.trigger("click");

    expect(wrapper.emitted("apply")).toEqual([[{ text: suggestion.suggested_text }]]);
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("discards a late response after the user switches to another candidate", async () => {
    let resolveResponse: (value: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { resolveResponse = resolve; })));
    const wrapper = mount(CandidateAiAssist, {
      props: { candidate, topics: [], tags: [], draftDirty: false },
    });

    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    await wrapper.setProps({ candidate: { ...candidate, id: 32, text: "新候选文本" } });
    resolveResponse(jsonResponse({ ...suggestion, candidate_id: 31 }));
    await flushPromises();

    expect(wrapper.text()).toContain("新候选文本");
    expect(wrapper.text()).not.toContain(suggestion.suggested_text);
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("reports stale candidate conflicts so the inbox can reload current data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      error: { code: "CONFLICT", message: "候选已变化，请重新读取。" },
    }, 409)));
    const wrapper = mount(CandidateAiAssist, {
      props: { candidate, topics: [], tags: [], draftDirty: false },
    });

    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("候选已变化");
    expect(wrapper.emitted("conflict")).toHaveLength(1);
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("preserves an unsaved candidate draft until the user explicitly applies selected AI fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(suggestion)));
    const wrapper = mount(IngestionCandidateEditor, {
      props: {
        candidate: editorCandidate,
        topics: [{ id: 7, name: "LangGraph", is_active: true }],
        tags: [{ id: 9, name: "Persistence", is_active: true }],
      },
    });

    const draft = wrapper.get("textarea[aria-label='候选题正文']");
    await draft.setValue("我的未保存草稿");
    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    await flushPromises();
    await wrapper.get("input[aria-label='应用建议题干']").setValue(true);
    const apply = wrapper.get("button[aria-label='应用选中的 AI 建议到草稿']");
    expect((apply.element as HTMLButtonElement).disabled).toBe(true);
    expect((draft.element as HTMLTextAreaElement).value).toBe("我的未保存草稿");

    await wrapper.get("input[aria-label='确认将选中的建议用于未保存草稿']").setValue(true);
    await apply.trigger("click");

    expect((draft.element as HTMLTextAreaElement).value).toBe(suggestion.suggested_text);
    expect(wrapper.emitted("save")).toBeUndefined();
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("loads split suggestions into editable parts and waits for the existing split confirmation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(suggestion)));
    const wrapper = mount(IngestionCandidateEditor, {
      props: { candidate: editorCandidate, topics: [], tags: [] },
    });

    await wrapper.get("button[aria-label='使用 AI 分析当前候选']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='应用拆分建议到可编辑草稿']").trigger("click");

    expect((wrapper.get("textarea[aria-label='拆分第一部分正文']").element as HTMLTextAreaElement).value)
      .toBe(suggestion.split_parts[0].text);
    expect((wrapper.get("textarea[aria-label='拆分第二部分正文']").element as HTMLTextAreaElement).value)
      .toBe(suggestion.split_parts[1].text);
    expect(wrapper.emitted("split")).toBeUndefined();

    await wrapper.get("form[aria-label='拆分候选题']").trigger("submit");
    expect(wrapper.emitted("split")?.[0]?.[0]).toMatchObject({
      expected_revision: 2,
      parts: suggestion.split_parts,
    });
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it("preserves an unsaved split draft when a newer candidate revision is reloaded", async () => {
    const wrapper = mount(IngestionCandidateEditor, {
      props: { candidate: editorCandidate, topics: [], tags: [] },
    });

    await wrapper.get("button[aria-label='切换候选拆分']").trigger("click");
    const splitDraft = wrapper.get("textarea[aria-label='拆分第一部分正文']");
    await splitDraft.setValue("我的未保存拆分草稿");
    await wrapper.setProps({
      candidate: {
        ...editorCandidate,
        text: "Updated candidate from another tab",
        candidate_revision: editorCandidate.candidate_revision + 1,
      },
    });

    expect((wrapper.get("textarea[aria-label='拆分第一部分正文']").element as HTMLTextAreaElement).value)
      .toBe("我的未保存拆分草稿");
    expect((wrapper.get("textarea[aria-label='候选题正文']").element as HTMLTextAreaElement).value)
      .toBe("Updated candidate from another tab");
    expect(wrapper.text()).toContain("当前未保存草稿已保留");
    wrapper.unmount();
  });
});

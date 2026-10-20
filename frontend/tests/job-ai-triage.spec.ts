import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";

vi.mock("../src/api/ingestion-ai", () => ({
  reviewIngestionJob: vi.fn(),
}));

import { reviewIngestionJob } from "../src/api/ingestion-ai";
import JobAiTriage from "../src/components/ingestion/JobAiTriage.vue";

const block = {
  id: "00000000-0000-4000-8000-000000000001",
  text: "What is MCP?",
  bbox: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
  reading_order: 0,
  confidence: 0.93,
};
const orphan = {
  id: "00000000-0000-4000-8000-000000000002",
  text: "How does Redis evict cached keys?",
  bbox: { x: 0.1, y: 0.4, width: 0.5, height: 0.1 },
  reading_order: 1,
  confidence: 0.88,
};
const candidate = {
  id: 12,
  text: "What is MCP?",
  difficulty: null,
  status: "pending_review",
  archived_at: null,
  candidate_state: "pending_review",
  candidate_revision: 4,
  canonical_question_id: null,
  split_from_candidate_id: null,
  split_child_ids: [],
  superseded_by_candidate_id: null,
  topics: [],
  tags: [],
  sources: [{
    question_source_id: 5,
    source_asset_id: 3,
    locator_json: { x: 0.1, y: 0.2, width: 0.5, height: 0.1 },
    locator_correction_json: null,
    source_text_snapshot: "What is MCP?",
    raw_ocr_text_snapshot: "What is MCP?",
    confidence: 0.93,
    ocr_blocks: [block],
  }],
};
const batch = {
  job_id: 1,
  candidate_reviews: [{
    candidate_id: 12,
    candidate_revision: 4,
    classification: "question" as const,
    source_text_snapshot: "What is MCP?",
    suggested_text: "What is the Model Context Protocol?",
    topic_ids: [7],
    tag_ids: [8],
    difficulty: "medium" as const,
    reason: "This is a direct interview question.",
    warnings: [],
    split_parts: [],
  }],
  orphan_reviews: [{
    classification: "question" as const,
    ocr_block_ids: [orphan.id],
    source_text_snapshot: orphan.text,
    suggested_text: "How does Redis evict cached keys?",
    reason: "The unassigned OCR block is also a question.",
    warnings: [],
  }],
};

function mountTriage(overrides: Record<string, unknown> = {}) {
  return mount(JobAiTriage, {
    props: {
      jobId: 1,
      candidates: [candidate],
      ocrBlocks: [block, orphan],
      topics: [{ id: 7, name: "Agent", is_active: true }],
      tags: [{ id: 8, name: "Protocol", is_active: true }],
      ready: true,
      busy: false,
      draftDirty: false,
      ...overrides,
    },
  });
}

describe("job-level AI OCR triage", () => {
  it("waits for an explicit click and displays question, non-question, and uncertain routes", async () => {
    vi.mocked(reviewIngestionJob).mockResolvedValueOnce({
      ...batch,
      orphan_reviews: [
        { ...batch.orphan_reviews[0], classification: "not_question", suggested_text: null },
        { ...batch.orphan_reviews[0], ocr_block_ids: ["extra"], classification: "uncertain", suggested_text: null },
      ],
    });
    const wrapper = mountTriage();
    expect(reviewIngestionJob).not.toHaveBeenCalled();

    await wrapper.get(".ai-analyze-button").trigger("click");
    await flushPromises();

    expect(reviewIngestionJob).toHaveBeenCalledWith(1);
    expect(wrapper.text()).toContain("建议作为题目");
    expect(wrapper.text()).toContain("建议排除");
    expect(wrapper.text()).toContain("需要人工判断");
    expect(wrapper.text()).toContain("How does Redis evict cached keys?");
  });

  it("emits an editable pending-candidate patch only after the user applies it", async () => {
    vi.mocked(reviewIngestionJob).mockResolvedValueOnce(batch);
    const wrapper = mountTriage();
    await wrapper.get(".ai-analyze-button").trigger("click");
    await flushPromises();
    const candidateRow = wrapper.findAll(".job-ai-review-row")[0];
    await candidateRow.get("textarea").setValue("Edited by user before applying");
    await candidateRow.get("button").trigger("click");

    expect(wrapper.emitted("apply-candidate")?.[0]?.[0]).toEqual({
      candidate_id: 12,
      expected_revision: 4,
      text: "Edited by user before applying",
      topic_ids: [7],
      tag_ids: [8],
      difficulty: "medium",
    });
    expect(wrapper.emitted("archive-candidate")).toBeUndefined();
  });

  it("keeps unassigned question creation user-triggered and preserves its OCR block ID", async () => {
    vi.mocked(reviewIngestionJob).mockResolvedValueOnce(batch);
    const wrapper = mountTriage();
    await wrapper.get(".ai-analyze-button").trigger("click");
    await flushPromises();
    const orphanRow = wrapper.findAll(".job-ai-review-row")[1];
    await orphanRow.get("button").trigger("click");

    expect(wrapper.emitted("create-candidate")?.[0]?.[0]).toEqual({
      ocr_block_ids: [orphan.id],
      text: "How does Redis evict cached keys?",
    });
  });

  it("disables an old suggestion after a candidate revision changes", async () => {
    vi.mocked(reviewIngestionJob).mockResolvedValueOnce(batch);
    const wrapper = mountTriage();
    await wrapper.get(".ai-analyze-button").trigger("click");
    await flushPromises();
    await wrapper.setProps({
      candidates: [{ ...candidate, candidate_revision: 5, text: "Changed elsewhere" }],
    });

    expect(wrapper.text()).toContain("候选版本已变化");
    expect((wrapper.find("button").element as HTMLButtonElement).disabled).toBe(false);
    expect((wrapper.find(".job-ai-review-row button").element as HTMLButtonElement).disabled).toBe(true);
  });

  it("ignores a late response after switching to a different OCR job", async () => {
    let resolveRequest!: (value: typeof batch) => void;
    const pending = new Promise<typeof batch>((resolve) => { resolveRequest = resolve; });
    vi.mocked(reviewIngestionJob).mockReturnValueOnce(pending);
    const wrapper = mountTriage();
    await wrapper.get(".ai-analyze-button").trigger("click");
    await wrapper.setProps({ jobId: 2 });
    resolveRequest(batch);
    await flushPromises();

    expect(wrapper.find(".job-ai-results").exists()).toBe(false);
    expect(wrapper.find("[role='alert']").exists()).toBe(false);
  });

  it("keeps the batch review entry point usable without a configured model", async () => {
    vi.mocked(reviewIngestionJob).mockRejectedValueOnce(
      new ApiError("LLM_NOT_CONFIGURED", "请先配置模型", 503),
    );
    const wrapper = mountTriage();
    await wrapper.get(".ai-analyze-button").trigger("click");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("尚未配置 LLM");
    expect(wrapper.find(".ai-analyze-button").attributes("disabled")).toBeUndefined();
  });

  it("shows a safe validation reason when an AI result is rejected", async () => {
    vi.mocked(reviewIngestionJob).mockRejectedValueOnce(
      new ApiError(
        "INGESTION_AI_RESPONSE_INVALID",
        "AI 返回的题目或来源建议无法安全校验；原候选与 OCR 证据未更改。",
        502,
        { response: "建议引用的原文片段不属于所列 OCR 来源块" },
      ),
    );
    const wrapper = mountTriage();

    await wrapper.get(".ai-analyze-button").trigger("click");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("原文片段不属于所列 OCR 来源块");
  });
});

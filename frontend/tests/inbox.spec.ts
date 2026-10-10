import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import SourceImageViewer from "../src/components/SourceImageViewer.vue";
import { createAppRouter } from "../src/router";
import { emptySimilarityResponse } from "./fixtures/similarity";

const RouterLinkStub = defineComponent({
  props: ["to"],
  setup(_props, { slots }) {
    return () => h("a", slots.default?.());
  },
});

function loadComponent(globPath: string, error: string) {
  const modules = import.meta.glob("../src/**/*.vue", { eager: true });
  const module = modules[globPath] as { default?: object } | undefined;
  expect(module, error).toBeDefined();
  return module!.default!;
}

const candidateA = {
  id: 101,
  text: "MCP 和 Function Calling 有什么区别？",
  status: "pending_review",
  archived_at: null,
  candidate_state: "pending_review",
  candidate_revision: 0,
  topics: [],
  tags: [],
  origin_ingestion_job_id: 11,
  source_asset_id: 1,
  split_from_candidate_id: null,
  split_child_ids: [],
  superseded_by_candidate_id: null,
  sources: [
    {
      question_source_id: 501,
      source_asset_id: 1,
      locator_type: "image_region",
      locator_json: { x: 0.1, y: 0.2, width: 0.4, height: 0.1 },
      locator_correction_json: null,
      source_text_snapshot: "MCP 和 Function Calling 有什么区别？",
      raw_ocr_text_snapshot: "MCP 和 Function Calling 有什么区别？",
      confidence: 0.95,
      ocr_blocks: [
        {
          id: "00000000-0000-4000-8000-000000000001",
          text: "MCP 和 Function Calling 有什么区别？",
          bbox: { x: 0.1, y: 0.2, width: 0.4, height: 0.1 },
          reading_order: 0,
        },
      ],
    },
  ],
};

const candidateB = {
  ...candidateA,
  id: 102,
  text: "LangGraph 如何持久化状态？",
  sources: [
    {
      ...candidateA.sources[0],
      question_source_id: 502,
      source_asset_id: 2,
      source_text_snapshot: "LangGraph 如何持久化状态？",
      raw_ocr_text_snapshot: "LangGraph 如何持久化状态？",
      ocr_blocks: [
        {
          ...candidateA.sources[0].ocr_blocks[0],
          id: "00000000-0000-4000-8000-000000000002",
          text: "LangGraph 如何持久化状态？",
          bbox: { x: 0.2, y: 0.3, width: 0.5, height: 0.08 },
        },
      ],
    },
  ],
};

function source(id: number, jobs: object[] = []) {
  return {
    id,
    source_type: "image",
    title: "截图 " + id,
    original_filename: "source-" + id + ".png",
    mime_type: "image/png",
    byte_size: 128,
    original_width: 1080,
    original_height: 1800,
    display_width: 1080,
    display_height: 1800,
    sha256: "a".repeat(64),
    archived_at: null,
    ingestion_jobs: jobs,
  };
}

function job(id: number, status = "queued", sourceAssetId = id) {
  return {
    id,
    source_asset_id: sourceAssetId,
    status,
    stage: status,
    failure_stage: null,
    engine: null,
    engine_version: null,
    error_code: null,
    error_message: null,
    candidate_count: 0,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function submitFiles(wrapper: ReturnType<typeof mount>, count: number) {
  const input = wrapper.get("input[type=file]").element as HTMLInputElement;
  const files = Array.from({ length: count }, (_, index) =>
    new File(["screenshot"], "screenshot-" + index + ".png", { type: "image/png" }),
  );
  Object.defineProperty(input, "files", { configurable: true, value: files });
  await wrapper.get("input[type=file]").trigger("change");
  await wrapper.get("form[aria-label='截图上传']").trigger("submit.prevent");
}

const inboxGlob = "../src/pages/InboxPage.vue";
const viewerGlob = "../src/components/SourceImageViewer.vue";
const uploadGlob = "../src/components/SourceUpload.vue";

describe("screenshot inbox and OCR viewer", () => {
  it("registers the inbox route", () => {
    const router = createAppRouter(createMemoryHistory());
    expect(router.resolve("/inbox").name).toBe("inbox");
  });

  it("renders single and multi-file upload", async () => {
    const Upload = loadComponent(uploadGlob, "missing SourceUpload.vue");
    const wrapper = mount(Upload);
    expect(wrapper.get("input[type=file]").attributes("multiple")).toBeDefined();
    expect(wrapper.get("form[aria-label='截图上传']")).toBeTruthy();
  });

  it("continues the sequential OCR queue after one job fails", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const runIds: number[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources" && !init?.method) {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/sources" && init?.method === "POST") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            results: [
              { status: "stored", source: source(1), job: job(11, "queued", 1) },
              { status: "rejected", error: { code: "VALIDATION_ERROR", message: "Invalid", fields: {} } },
              { status: "stored", source: source(2), job: job(22, "queued", 2) },
            ],
          }),
        } as Response;
      }
      if (path === "/api/v1/ingestions/11/run") {
        runIds.push(11);
        return {
          ok: true,
          status: 200,
          json: async () => ({ job: { ...job(11, "failed", 1), error_code: "OCR_FAILED" } }),
        } as Response;
      }
      if (path === "/api/v1/ingestions/22/run") {
        runIds.push(22);
        return { ok: true, status: 200, json: async () => ({ job: job(22, "succeeded", 2) }) } as Response;
      }
      return { ok: true, status: 200, json: async () => [] } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await submitFiles(wrapper, 3);
    await flushPromises();

    expect(runIds).toEqual([11, 22]);
    expect(wrapper.text()).toContain("OCR_FAILED");
    expect(wrapper.text()).toContain("识别成功");
    expect(wrapper.text()).toContain("screenshot-1.png");
    expect(wrapper.get("[aria-label='本次上传结果']").text()).toContain("识别成功");
  });

  it("queries a timed-out job without posting run a second time", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    let statusReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources" && !init?.method) {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/sources" && init?.method === "POST") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ results: [{ status: "stored", source: source(1), job: job(11, "queued", 1) }] }),
        } as Response;
      }
      if (path === "/api/v1/ingestions/11/run") {
        throw new TypeError("request timed out");
      }
      if (path === "/api/v1/ingestions/11") {
        statusReads += 1;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            job: job(11, statusReads < 2 ? "running" : "succeeded", 1),
          }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => [] } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await submitFiles(wrapper, 1);
    await new Promise((resolve) => window.setTimeout(resolve, 550));
    await flushPromises();

    expect(fetchMock.mock.calls.filter(([path]) => path === "/api/v1/ingestions/11/run")).toHaveLength(1);
    expect(statusReads).toBeGreaterThanOrEqual(2);
  });

  it("can resume a persisted queued job after reloading the inbox", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "queued", 1)])];
    const requests: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      requests.push(path);
      if (path === "/api/v1/sources" || path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => path === "/api/v1/sources" ? records : [] } as Response;
      }
      if (path === "/api/v1/ingestions/11" && !init?.method) {
        return { ok: true, status: 200, json: async () => ({ job: job(11, "queued", 1) }) } as Response;
      }
      if (path === "/api/v1/ingestions/11/run") {
        return { ok: true, status: 200, json: async () => ({ job: job(11, "succeeded", 1) }) } as Response;
      }
      return { ok: true, status: 200, json: async () => [] } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();

    expect(wrapper.find("[aria-label='继续识别任务 11']").exists()).toBe(true);
    await wrapper.get("[aria-label='继续识别任务 11']").trigger("click");
    await flushPromises();

    expect(requests.indexOf("/api/v1/ingestions/11")).toBeLessThan(
      requests.indexOf("/api/v1/ingestions/11/run"),
    );
    expect(wrapper.text()).toContain("任务 11 · 识别成功");
  });

  it("ignores a late historical job response after another job is selected", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1), job(12, "succeeded", 1)])];
    const candidateAResponse = deferred<Response>();
    const blocksAResponse = deferred<Response>();
    const candidateBResponse = deferred<Response>();
    const blocksBResponse = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") {
        return { ok: true, status: 200, json: async () => records } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates") return candidateAResponse.promise;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return blocksAResponse.promise;
      if (path === "/api/v1/ingestions/12/candidates") return candidateBResponse.promise;
      if (path === "/api/v1/ingestions/12/ocr-blocks") return blocksBResponse.promise;
      return { ok: true, status: 200, json: async () => ({ job: job(11, "succeeded", 1) }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();

    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await wrapper.get("[aria-label='打开导入任务 12']").trigger("click");
    candidateBResponse.resolve({ ok: true, status: 200, json: async () => [candidateB] } as Response);
    blocksBResponse.resolve({ ok: true, status: 200, json: async () => candidateB.sources[0].ocr_blocks } as Response);
    await flushPromises();
    candidateAResponse.resolve({ ok: true, status: 200, json: async () => [candidateA] } as Response);
    blocksAResponse.resolve({ ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response);
    await flushPromises();

    expect(wrapper.get("[aria-label='导入任务详情']").text()).toContain("任务 12");
    expect(wrapper.get("[aria-label='候选题历史']").text()).toContain(candidateB.text);
    expect(wrapper.get("[aria-label='候选题历史']").text()).not.toContain(candidateA.text);
  });

  it("does not let a delayed candidate mutation refresh a different selected job", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1), job(12, "succeeded", 1)])];
    const delayedPatch = deferred<Response>();
    const candidateC = { ...candidateA, id: 201, text: "Job 12 candidate C" };
    const candidateD = { ...candidateB, id: 202, text: "Job 12 candidate D" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => [candidateA] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestions/12/candidates") return { ok: true, status: 200, json: async () => [candidateC, candidateD] } as Response;
      if (path === "/api/v1/ingestions/12/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestion-candidates/101" && init?.method === "PATCH") return delayedPatch.promise;
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("Delayed edit from job 11");
    const saveRequest = wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 12']").trigger("click");
    await flushPromises();
    await wrapper.get("[aria-label='查看候选题 202']").trigger("click");
    delayedPatch.resolve({ ok: true, status: 200, json: async () => ({ ...candidateA, text: "Delayed edit from job 11" }) } as Response);
    await saveRequest;
    await flushPromises();

    expect(wrapper.get("[aria-label='导入任务详情']").text()).toContain("任务 12");
    expect(wrapper.get("[aria-label='候选题历史']").text()).toContain(candidateD.text);
    expect(wrapper.get("[aria-label='查看候选题 202']").attributes("aria-pressed")).toBe("true");
  });

  it("does not show a delayed Job A conflict while Job B is selected", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1), job(12, "succeeded", 1)])];
    const delayedPatch = deferred<Response>();
    const candidateC = { ...candidateA, id: 201, text: "Job 12 candidate C" };
    const candidateD = { ...candidateB, id: 202, text: "Job 12 candidate D" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => [candidateA] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestions/12/candidates") return { ok: true, status: 200, json: async () => [candidateC, candidateD] } as Response;
      if (path === "/api/v1/ingestions/12/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestion-candidates/101" && init?.method === "PATCH") return delayedPatch.promise;
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("Delayed edit from job 11");
    const saveRequest = wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 12']").trigger("click");
    await flushPromises();
    await wrapper.get("[aria-label='查看候选题 202']").trigger("click");
    delayedPatch.resolve({
      ok: false,
      status: 409,
      json: async () => ({ error: { code: "CONFLICT", message: "Conflict", fields: {} } }),
    } as Response);
    await saveRequest;
    await flushPromises();

    expect(wrapper.get("[aria-label='导入任务详情']").text()).toContain("任务 12");
    expect(wrapper.get("[aria-label='查看候选题 202']").attributes("aria-pressed")).toBe("true");
    expect(wrapper.find("[role='alert']").exists()).toBe(false);
  });

  it("shows all candidates when opening a historical OCR job", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1)])];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") {
        return { ok: true, status: 200, json: async () => records } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates") {
        return {
          ok: true,
          status: 200,
          json: async () => [
            candidateA,
            { ...candidateA, id: 103, candidate_state: "confirmed" },
            { ...candidateA, id: 104, candidate_state: "rejected", archived_at: "now" },
            { ...candidateA, id: 105, candidate_state: "superseded", archived_at: "now" },
          ],
        } as Response;
      }
      if (path === "/api/v1/ingestions/11/ocr-blocks") {
        return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ job: job(11, "succeeded", 1) }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("待审核");
    expect(wrapper.text()).toContain("已确认");
    expect(wrapper.text()).toContain("已拒绝");
    expect(wrapper.text()).toContain("已替换");
    expect(wrapper.find("[aria-label='OCR 原文']").exists()).toBe(true);
  });

  it("separates automatic candidate count from the full reviewed history", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [{ ...job(11, "succeeded", 1), stage: "completed", candidate_count: 4 }])];
    const candidates = [
      { ...candidateA, id: 101 },
      { ...candidateA, id: 102 },
      { ...candidateA, id: 103 },
      { ...candidateA, id: 104 },
      { ...candidateA, id: 105, candidate_state: "confirmed", status: "active" },
      { ...candidateA, id: 106, candidate_state: "superseded", archived_at: "now" },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => candidates } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[aria-label='打开导入任务 11']").text()).toContain("自动候选 4");
    expect(wrapper.get("[aria-label='候选数量统计']").text()).toContain("历史候选 6");
    expect(wrapper.get("[aria-label='候选数量统计']").text()).toContain("待确认 4");
  });

  it("selects a QuestionSource by id and switches the displayed SourceAsset", async () => {
    const wrapper = mount(SourceImageViewer, {
      props: {
        sources: [candidateA.sources[0], candidateB.sources[0]],
        selectedSourceId: 501,
      },
    });
    await wrapper.get("[aria-label='来源区域 502']").trigger("click");
    expect(wrapper.emitted("select-source")?.[0]).toEqual([502]);
    await wrapper.setProps({ selectedSourceId: 502 });
    expect(wrapper.attributes("data-source-asset-id")).toBe("2");
    expect(wrapper.get("img").attributes("src")).toBe("/api/v1/sources/2/display");
  });

  it("highlights the selected QuestionSource region", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const wrapper = mount(Viewer, {
      props: { sources: [candidateA.sources[0]], selectedSourceId: 501, imageWidth: 100, imageHeight: 100 },
    });
    const selected = wrapper.get("[data-source-region-id='501']");
    expect(selected.attributes("data-selected")).toBe("true");
    expect(selected.attributes("x")).toBe("10");
  });

  it("unions effective locators belonging to the displayed asset", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const sameAssetSecond = {
      ...candidateA.sources[0],
      question_source_id: 503,
      locator_json: { x: 0.6, y: 0.2, width: 0.2, height: 0.1 },
    };
    const wrapper = mount(Viewer, {
      props: {
        sources: [candidateA.sources[0], sameAssetSecond, candidateB.sources[0]],
        selectedSourceId: 501,
        imageWidth: 100,
        imageHeight: 100,
      },
    });
    expect(wrapper.findAll("[data-source-region-id]")).toHaveLength(2);
    expect(wrapper.findAll("[data-source-asset-id='1'] [data-source-region-id]")).toHaveLength(2);
  });

  it("does not union source coordinates across different assets", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const wrapper = mount(Viewer, {
      props: {
        sources: [candidateA.sources[0], candidateB.sources[0]],
        selectedSourceId: 501,
        imageWidth: 100,
        imageHeight: 100,
      },
    });
    expect(wrapper.findAll("[data-source-region-id]")).toHaveLength(1);
    expect(wrapper.find("[data-source-region-id='502']").exists()).toBe(false);
  });

  it("keys OCR block overlays by stable UUID", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const wrapper = mount(Viewer, {
      props: { sources: [candidateA.sources[0]], selectedSourceId: 501, imageWidth: 100, imageHeight: 100 },
    });
    expect(wrapper.find("[data-block-id='00000000-0000-4000-8000-000000000001']").exists()).toBe(true);
  });

  it("previews manually selected OCR blocks without a persisted QuestionSource", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const block = candidateA.sources[0].ocr_blocks[0];
    const wrapper = mount(Viewer, {
      props: {
        sources: [],
        selectedSourceId: null,
        imageWidth: 1080,
        imageHeight: 1800,
        preview: {
          source_asset_id: 1,
          text: block.text,
          ocr_blocks: [block],
        },
      },
    });

    expect(wrapper.attributes("data-source-asset-id")).toBe("1");
    expect(wrapper.find("[data-source-region-id]").exists()).toBe(false);
    expect(wrapper.find("[data-block-id='00000000-0000-4000-8000-000000000001']").exists()).toBe(true);
    expect(wrapper.text()).toContain(block.text);
  });

  it("maps normalized boxes to the visible content rect with contain letterboxing", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const wrapper = mount(Viewer, {
      props: {
        sources: [candidateA.sources[0]],
        selectedSourceId: 501,
        imageWidth: 100,
        imageHeight: 200,
        containerWidth: 400,
        containerHeight: 200,
      },
    });
    const overlay = wrapper.get("[data-overlay]");
    expect(overlay.attributes("style")).toContain("left: 150px");
    expect(overlay.attributes("style")).toContain("width: 100px");
    expect(wrapper.get("[data-source-region-id='501']").attributes("x")).toBe("10");
  });

  it("uses the EXIF-normalized display preview for rotated screenshots", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const wrapper = mount(Viewer, {
      props: {
        sources: [candidateA.sources[0]],
        selectedSourceId: 501,
        imageWidth: 4,
        imageHeight: 8,
      },
    });
    expect(wrapper.get("img").attributes("src")).toBe("/api/v1/sources/1/display");
    expect(wrapper.get("img").attributes("data-orientation-normalized")).toBe("true");
  });

  it("maps portrait long screenshots into wide and tall containers", async () => {
    const Viewer = loadComponent(viewerGlob, "missing SourceImageViewer.vue");
    const wide = mount(Viewer, {
      props: {
        sources: [candidateA.sources[0]],
        selectedSourceId: 501,
        imageWidth: 1080,
        imageHeight: 1800,
        containerWidth: 600,
        containerHeight: 300,
      },
    });
    const tall = mount(Viewer, {
      props: {
        sources: [candidateA.sources[0]],
        selectedSourceId: 501,
        imageWidth: 1080,
        imageHeight: 1800,
        containerWidth: 300,
        containerHeight: 600,
      },
    });
    expect(wide.get("[data-overlay]").attributes("style")).toContain("width: 180px");
    expect(wide.get("[data-overlay]").attributes("style")).toContain("left: 210px");
    expect(tall.get("[data-overlay]").attributes("style")).toContain("width: 300px");
    expect(tall.get("[data-overlay]").attributes("style")).toContain("left: 0px");
  });

  it("edits a candidate without changing its immutable OCR snapshot", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const wrapper = mount(Editor, {
      props: {
        candidate: candidateA,
        topics: [{ id: 7, name: "MCP", is_active: true }],
        tags: [{ id: 8, name: "Protocol", is_active: true }],
      },
    });
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("Edited candidate text");
    await wrapper.get("input[aria-label='来源定位 x']").setValue("0.25");
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");

    const emitted = wrapper.emitted("save")?.[0]?.[0] as Record<string, unknown>;
    expect(emitted.expected_revision).toBe(0);
    expect(emitted.text).toBe("Edited candidate text");
    expect(emitted.source_locator_corrections).toEqual([
      {
        question_source_id: 501,
        locator_correction_json: { x: 0.25, y: 0.2, width: 0.4, height: 0.1 },
      },
    ]);
    expect(wrapper.text()).toContain("MCP 和 Function Calling 有什么区别？");
  });

  it("targets locator correction to the selected QuestionSource", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const secondSource = {
      ...candidateA.sources[0],
      question_source_id: 503,
      locator_json: { x: 0.3, y: 0.2, width: 0.2, height: 0.1 },
    };
    const wrapper = mount(Editor, {
      props: {
        candidate: { ...candidateA, sources: [candidateA.sources[0], secondSource] },
        selectedSourceId: 503,
      },
    });
    await wrapper.get("input[aria-label='来源定位 x']").setValue("0.35");
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    const emitted = wrapper.emitted("save")?.[0]?.[0] as {
      source_locator_corrections: Array<{ question_source_id: number }>;
    };
    expect(emitted.source_locator_corrections).toEqual([
      expect.objectContaining({
        question_source_id: 503,
        locator_correction_json: expect.objectContaining({ x: 0.35 }),
      }),
    ]);
  });

  it("omits unchanged inactive taxonomy and source locator in a minimal candidate patch", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const inactiveTopic = { id: 70, name: "Legacy Topic", is_active: false };
    const inactiveTag = { id: 80, name: "Legacy Tag", is_active: false };
    const wrapper = mount(Editor, {
      props: {
        candidate: { ...candidateA, topics: [inactiveTopic], tags: [inactiveTag] },
        topics: [inactiveTopic],
        tags: [inactiveTag],
      },
    });
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("Edited only the body");
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");

    const payload = wrapper.emitted("save")?.[0]?.[0] as Record<string, unknown>;
    expect(payload).toEqual({ expected_revision: 0, text: "Edited only the body" });
  });

  it("does not emit a candidate patch when all fields are unchanged", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const wrapper = mount(Editor, { props: { candidate: candidateA } });
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    expect(wrapper.emitted("save")).toBeUndefined();
  });

  it("submits split parts with exact OCR text and block UUIDs", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const wrapper = mount(Editor, { props: { candidate: candidateA } });
    await wrapper.get("button[aria-label='切换候选拆分']").trigger("click");
    await wrapper.get("textarea[aria-label='拆分第一部分正文']").setValue("MCP");
    await wrapper.get("textarea[aria-label='拆分第二部分正文']").setValue("Function Calling");
    await wrapper.get("select[aria-label='拆分第一部分 OCR 块']").setValue([
      "00000000-0000-4000-8000-000000000001",
    ]);
    await wrapper.get("select[aria-label='拆分第二部分 OCR 块']").setValue([
      "00000000-0000-4000-8000-000000000001",
    ]);
    await wrapper.get("textarea[aria-label='拆分第一部分 OCR 来源片段']").setValue("MCP");
    await wrapper.get("textarea[aria-label='拆分第二部分 OCR 来源片段']").setValue("Function Calling");
    await wrapper.get("form[aria-label='拆分候选题']").trigger("submit.prevent");

    const emitted = wrapper.emitted("split")?.[0]?.[0] as {
      expected_revision: number;
      parts: Array<{ text: string; source_text_snapshot: string; ocr_block_ids: string[] }>;
    };
    expect(emitted.expected_revision).toBe(0);
    expect(emitted.parts).toHaveLength(2);
    expect(emitted.parts.map((part) => part.text)).toEqual(["MCP", "Function Calling"]);
    expect(emitted.parts.map((part) => part.source_text_snapshot)).toEqual([
      "MCP",
      "Function Calling",
    ]);
    expect(emitted.parts[0].ocr_block_ids).toEqual(emitted.parts[1].ocr_block_ids);
  });

  it("keeps corrected split text separate from excerpts across multiple OCR blocks", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const secondBlock = {
      ...candidateA.sources[0].ocr_blocks[0],
      id: "00000000-0000-4000-8000-000000000003",
      text: "question",
      reading_order: 1,
      bbox: { x: 0.1, y: 0.35, width: 0.2, height: 0.04 },
    };
    const rawText = "LangGrapn state question";
    const candidate = {
      ...candidateA,
      text: rawText,
      sources: [
        {
          ...candidateA.sources[0],
          source_text_snapshot: rawText,
          raw_ocr_text_snapshot: rawText,
          ocr_blocks: [
            { ...candidateA.sources[0].ocr_blocks[0], text: "LangGrapn state", reading_order: 0 },
            secondBlock,
          ],
        },
      ],
    };
    const wrapper = mount(Editor, { props: { candidate } });
    await wrapper.get("button[aria-label='切换候选拆分']").trigger("click");
    await wrapper.get("textarea[aria-label='拆分第一部分正文']").setValue("LangGraph state");
    await wrapper.get("textarea[aria-label='拆分第二部分正文']").setValue("What does the question ask?");
    await wrapper.get("select[aria-label='拆分第一部分 OCR 块']").setValue([
      "00000000-0000-4000-8000-000000000001",
      "00000000-0000-4000-8000-000000000003",
    ]);
    await wrapper.get("textarea[aria-label='拆分第一部分 OCR 来源片段']").setValue(rawText);
    await wrapper.get("select[aria-label='拆分第二部分 OCR 块']").setValue([
      "00000000-0000-4000-8000-000000000003",
    ]);
    await wrapper.get("textarea[aria-label='拆分第二部分 OCR 来源片段']").setValue("question");
    await wrapper.get("form[aria-label='拆分候选题']").trigger("submit.prevent");

    const emitted = wrapper.emitted("split")?.[0]?.[0] as {
      parts: Array<{ text: string; source_text_snapshot: string; ocr_block_ids: string[] }>;
    };
    expect(emitted.parts.map((part) => part.text)).toEqual([
      "LangGraph state",
      "What does the question ask?",
    ]);
    expect(emitted.parts.map((part) => part.source_text_snapshot)).toEqual([
      "LangGrapn state question",
      "question",
    ]);
    expect(emitted.parts[0].ocr_block_ids).toHaveLength(2);
    expect(emitted.parts[1].ocr_block_ids).toEqual(["00000000-0000-4000-8000-000000000003"]);
  });

  it("merges only selected candidates from the same OCR job", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [{ ...job(11, "succeeded", 1), stage: "completed" }])];
    let mergeBody: Record<string, unknown> | null = null;
    let candidateReads = 0;
    let mergedCandidates = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") {
        return { ok: true, status: 200, json: async () => records } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates") {
        candidateReads += 1;
        return {
          ok: true,
          status: 200,
          json: async () => mergedCandidates
            ? [
                { ...candidateA, candidate_state: "superseded", archived_at: "now", superseded_by_candidate_id: 102 },
                { ...candidateB, id: 102, text: "Combined", split_from_candidate_id: null },
              ]
            : [candidateA, { ...candidateB, id: 102, text: "Second question" }],
        } as Response;
      }
      if (path === "/api/v1/ingestions/11/ocr-blocks") {
        return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates/merge" && init?.method === "POST") {
        mergeBody = JSON.parse(String(init.body));
        mergedCandidates = true;
        return {
          ok: true,
          status: 200,
          json: async () => ({ survivor: { ...candidateB, id: 102, text: "Combined" }, superseded: [candidateA] }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ job: job(11, "succeeded", 1) }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("[aria-label='查看候选题 102']").trigger("click");
    await wrapper.get("[aria-label='选择 OCR 候选区域 101']").setValue(true);
    await wrapper.get("textarea[aria-label='合并后题目正文']").setValue("Combined");
    await wrapper.get("form[aria-label='候选题同任务合并']").trigger("submit.prevent");
    await flushPromises();

    expect(mergeBody).toMatchObject({
      survivor_id: 102,
      final_text: "Combined",
      candidates: [
        { id: 101, expected_revision: 0 },
        { id: 102, expected_revision: 0 },
      ],
    });
    expect(candidateReads).toBeGreaterThanOrEqual(2);
    expect(wrapper.get("[aria-label='查看候选题 102']").attributes("aria-pressed")).toBe("true");
  });

  it("keeps the edited candidate and source selected after refresh", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1)])];
    let updated = false;
    const secondSource = {
      ...candidateA.sources[0],
      question_source_id: 503,
      locator_json: { x: 0.3, y: 0.2, width: 0.2, height: 0.1 },
    };
    const edited = { ...candidateB, id: 102, text: "Edited text", candidate_revision: 1 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") {
        return {
          ok: true,
          status: 200,
          json: async () => [
            { ...candidateA, sources: [candidateA.sources[0], secondSource] },
            updated ? edited : { ...candidateB, id: 102 },
          ],
        } as Response;
      }
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestion-candidates/102" && init?.method === "PATCH") {
        updated = true;
        return { ok: true, status: 200, json: async () => edited } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("[aria-label='查看候选题 102']").trigger("click");
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("Edited text");
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    await flushPromises();

    expect(wrapper.get("[aria-label='查看候选题 102']").attributes("aria-pressed")).toBe("true");
    expect(wrapper.get("[aria-label='来源区域 502']").attributes("aria-pressed")).toBe("true");
    expect((wrapper.get("textarea[aria-label='候选题正文']").element as HTMLTextAreaElement).value).toBe("Edited text");
  });

  it("keeps the 409 conflict message visible after refreshing the job", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1)])];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => [candidateA] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestion-candidates/101" && init?.method === "PATCH") {
        return {
          ok: false,
          status: 409,
          json: async () => ({ error: { code: "CONFLICT", message: "Conflict", fields: {} } }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("textarea[aria-label='候选题正文']").setValue("A conflicting edit");
    await wrapper.get("form[aria-label='候选题正文与分类']").trigger("submit.prevent");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("候选内容已被其他操作更新");
  });

  it("keeps a confirmed candidate selected as a read-only history row", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1)])];
    let confirmed = false;
    const confirmedCandidate = { ...candidateA, status: "active", candidate_state: "confirmed", candidate_revision: 1 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => [confirmed ? confirmedCandidate : candidateA] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestion-candidates/101/confirm" && init?.method === "POST") {
        confirmed = true;
        return { ok: true, status: 200, json: async () => confirmedCandidate } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='确认进入题库']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[aria-label='查看候选题 101']").attributes("aria-pressed")).toBe("true");
    expect(wrapper.get("[aria-label='导入任务详情']").text()).toContain("只能查看历史来源证据");
    expect(wrapper.find("button[aria-label='确认进入题库']").exists()).toBe(false);
  });

  it("selects a pending split child after refreshing candidate history", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1)])];
    const firstChild = {
      ...candidateA,
      id: 102,
      text: "First split part",
      split_from_candidate_id: 101,
      sources: [{ ...candidateA.sources[0], question_source_id: 601, source_text_snapshot: "First split part" }],
    };
    const secondChild = {
      ...candidateA,
      id: 103,
      text: "Second split part",
      split_from_candidate_id: 101,
      sources: [{ ...candidateA.sources[0], question_source_id: 602, source_text_snapshot: "Second split part" }],
    };
    const parent = { ...candidateA, candidate_state: "superseded", archived_at: "now", split_child_ids: [102, 103] };
    let splitDone = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => records } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => splitDone ? [parent, firstChild, secondChild] : [candidateA] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestions/11/candidates/101/split" && init?.method === "POST") {
        splitDone = true;
        return { ok: true, status: 200, json: async () => ({ parent, children: [firstChild, secondChild] }) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='切换候选拆分']").trigger("click");
    await wrapper.get("textarea[aria-label='拆分第一部分正文']").setValue("First split part");
    await wrapper.get("textarea[aria-label='拆分第二部分正文']").setValue("Second split part");
    await wrapper.get("form[aria-label='拆分候选题']").trigger("submit.prevent");
    await flushPromises();

    expect(wrapper.get("[aria-label='查看候选题 102']").attributes("aria-pressed")).toBe("true");
    expect((wrapper.get("textarea[aria-label='候选题正文']").element as HTMLTextAreaElement).value).toBe("First split part");
  });

  it("explains that inactive taxonomy must be replaced before candidate confirmation", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const inactiveCandidate = {
      ...candidateA,
      topics: [{ id: 7, name: "Legacy Topic", is_active: false }],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => [source(1, [job(11, "succeeded", 1)])] } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => [inactiveCandidate] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      if (path === "/api/v1/ingestion-candidates/101/confirm" && init?.method === "POST") {
        return {
          ok: false,
          status: 400,
          json: async () => ({
            error: { code: "VALIDATION_ERROR", message: "Invalid OCR candidate", fields: { topic_ids: "Inactive Topic ID(s): 7" } },
          }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='确认进入题库']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toContain("分类已停用");
    expect(wrapper.get("[role='alert']").text()).toContain("重新选择");
  });

  it("shows split and merge lineage labels in candidate history", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const parent = { ...candidateA, split_child_ids: [102, 103] };
    const child = { ...candidateB, id: 102, split_from_candidate_id: 101 };
    const mergedLoser = {
      ...candidateA,
      id: 103,
      candidate_state: "superseded",
      archived_at: "now",
      superseded_by_candidate_id: 102,
      split_child_ids: [],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") return { ok: true, status: 200, json: async () => [source(1, [job(11, "succeeded", 1)])] } as Response;
      if (path === "/api/v1/topics" || path === "/api/v1/tags") return { ok: true, status: 200, json: async () => [] } as Response;
      if (path === "/api/v1/ingestions/11/candidates") return { ok: true, status: 200, json: async () => [parent, child, mergedLoser] } as Response;
      if (path === "/api/v1/ingestions/11/ocr-blocks") return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();

    const history = wrapper.get("[aria-label='候选题历史']").text();
    expect(history).toContain("已拆分为候选 #102、#103");
    expect(history).toContain("拆分自候选 #101");
    expect(history).toContain("已合并至候选 #102");
  });

  it("provides explicit confirmation and split lineage labels", async () => {
    const Editor = loadComponent(
      "../src/components/IngestionCandidateEditor.vue",
      "missing IngestionCandidateEditor.vue",
    );
    const candidate = {
      ...candidateA,
      candidate_revision: 3,
      split_from_candidate_id: 44,
      candidate_state: "pending_review",
    };
    const wrapper = mount(Editor, { props: { candidate } });
    expect(wrapper.text()).toContain("候选题正文");
    await wrapper.get("button[aria-label='确认进入题库']").trigger("click");
    expect(wrapper.emitted("confirm")?.[0]?.[0]).toEqual({ expected_revision: 3 });
    await wrapper.get("button[aria-label='拒绝候选题']").trigger("click");
    expect(wrapper.emitted("archive")?.[0]?.[0]).toEqual({ expected_revision: 3 });
  });

  it("shows historical confirmed candidates without mutation controls", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [job(11, "succeeded", 1)])];
    const confirmed = {
      ...candidateA,
      status: "active",
      candidate_state: "confirmed",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") {
        return { ok: true, status: 200, json: async () => records } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates") {
        return { ok: true, status: 200, json: async () => [confirmed] } as Response;
      }
      if (path === "/api/v1/ingestions/11/ocr-blocks") {
        return { ok: true, status: 200, json: async () => candidateA.sources[0].ocr_blocks } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ job: job(11, "succeeded", 1) }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("只能查看历史来源证据");
    expect(wrapper.find("form[aria-label='候选题正文与分类']").exists()).toBe(false);
    expect(wrapper.find("button[aria-label='确认进入题库']").exists()).toBe(false);
  });

  it("creates a review candidate from selected OCR blocks inside the inbox", async () => {
    loadComponent(uploadGlob, "missing SourceUpload.vue");
    const Page = loadComponent(inboxGlob, "missing InboxPage.vue");
    const records = [source(1, [{ ...job(11, "succeeded", 1), stage: "completed" }])];
    let createdCandidate: typeof candidateA | null = null;
    let submitted: Record<string, unknown> | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const similar = emptySimilarityResponse(path);
      if (similar) return similar;
      if (path === "/api/v1/sources") {
        return { ok: true, status: 200, json: async () => records } as Response;
      }
      if (path === "/api/v1/topics" || path === "/api/v1/tags") {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates" && init?.method === "POST") {
        submitted = JSON.parse(String(init.body));
        createdCandidate = { ...candidateA, id: 106, text: "Corrected unnumbered question" };
        return { ok: true, status: 201, json: async () => createdCandidate } as Response;
      }
      if (path === "/api/v1/ingestions/11/candidates") {
        return {
          ok: true,
          status: 200,
          json: async () => createdCandidate ? [candidateA, createdCandidate] : [candidateA],
        } as Response;
      }
      if (path === "/api/v1/ingestions/11/ocr-blocks") {
        return {
          ok: true,
          status: 200,
          json: async () => candidateA.sources[0].ocr_blocks,
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ job: job(11, "succeeded", 1) }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mount(Page, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();
    await wrapper.get("[aria-label='打开导入任务 11']").trigger("click");
    await flushPromises();
    await wrapper.get("button[aria-label='补建候选题']").trigger("click");
    await wrapper.get("[aria-label='选择用于补建的 OCR 块 00000000-0000-4000-8000-000000000001']").setValue(true);
    expect(wrapper.find("[data-block-id='00000000-0000-4000-8000-000000000001']").exists()).toBe(true);
    await wrapper.get("textarea[aria-label='补建候选题正文']").setValue("Corrected unnumbered question");
    await wrapper.get("form[aria-label='从 OCR 块补建候选题']").trigger("submit.prevent");
    await flushPromises();

    expect(submitted).toEqual({
      ocr_block_ids: ["00000000-0000-4000-8000-000000000001"],
      text: "Corrected unnumbered question",
    });
    expect(wrapper.get("[aria-label='候选题历史']").text()).toContain("Corrected unnumbered question");
    expect(wrapper.get("[aria-label='候选题正文']").element).toHaveProperty(
      "value",
      "Corrected unnumbered question",
    );
  });
});

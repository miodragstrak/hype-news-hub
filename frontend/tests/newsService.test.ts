import { beforeEach, describe, expect, it, vi } from "vitest";

async function service(demo = "false", url = "https://backend.invalid") {
  vi.stubEnv("VITE_DEMO_MODE", demo);
  vi.stubEnv("VITE_API_URL", url);
  vi.stubEnv("VITE_API_BASE_URL", "");
  return import("../src/services/newsService");
}

beforeEach(() => vi.resetModules());

describe("explicit demo mode and live failures", () => {
  it("requires explicit opt-in even when the API URL is missing", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const news = await service("false", "");
    expect(news.isDemoDataModeEnabled()).toBe(false);
    await expect(news.collectLatestNews()).rejects.toThrow("not configured");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("serves sample data only when explicitly enabled, without network requests", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const news = await service("true");
    expect(news.isDemoDataModeEnabled()).toBe(true);
    const result = await news.collectLatestNews();
    expect(result.articles_total).toBe(22);
    expect(result.stories_total).toBe(8);
    expect(result.story_candidates_total).toBe(14);
    expect((await news.getDiscoverySources()).length).toBe(6);
    expect((await news.getStories()).stories_total).toBe(8);
    expect((await news.getEditorialQueue()).stories_total).toBe(8);
    const workspace = await news.getEditorialStoryWorkspace(result.stories[0].id);
    expect(workspace.serbian_draft.status).toBe("not_generated");
    expect((await news.generateDemoEditorialStoryDraft(workspace.id)).serbian_draft.status).toBe("demo_generated");
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["", "false", "1", "TRUE"])("does not infer demo mode from %j", async (flag) => {
    const news = await service(flag);
    expect(news.isDemoDataModeEnabled()).toBe(false);
  });

  it.each(["getDiscoverySources", "collectLatestNews", "getStories", "getEditorialQueue"] as const)("propagates network errors from %s", async (method) => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));
    const news = await service();
    await expect(news[method]()).rejects.toThrow("backend is unavailable");
  });

  it.each([401, 403, 404, 429, 500, 502])("does not turn HTTP %i into sample success", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("failure", { status })));
    const news = await service();
    await expect(news.collectLatestNews()).rejects.toThrow(`status ${status}`);
  });

  it("rejects malformed JSON instead of loading demo stories", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json")));
    const news = await service();
    await expect(news.getStories()).rejects.toThrow("invalid JSON");
  });

  it("preserves live endpoint paths and returned data", async () => {
    const payload = { sources_processed: 2, sources_failed: 1, articles_total: 0, articles: [], story_candidates_total: 0, stories_total: 0, stories: [] };
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
    vi.stubGlobal("fetch", fetch);
    const news = await service("false", " https://backend.invalid/// ");
    expect(await news.collectLatestNews()).toEqual(payload);
    expect(fetch).toHaveBeenCalledWith("https://backend.invalid/api/collect", undefined);
  });

  it("supports the legacy backend URL alias when the primary URL is blank", async () => {
    const news = await service("false", "");
    // Reload config after setting the backward-compatible alias.
    vi.resetModules();
    vi.stubEnv("VITE_API_BASE_URL", "https://legacy.invalid/");
    const fetch = vi.fn().mockResolvedValue(new Response('{"stories_total":0,"stories":[]}'));
    vi.stubGlobal("fetch", fetch);
    expect(news.isDemoDataModeEnabled()).toBe(false);
    await (await import("../src/services/newsService")).getStories();
    expect(fetch).toHaveBeenCalledWith("https://legacy.invalid/api/stories", undefined);
  });

  it("keeps detail and demo-generation errors visible in live mode", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("missing", { status: 404 }));
    vi.stubGlobal("fetch", fetch);
    const news = await service();
    await expect(news.getEditorialStoryWorkspace("story/a")).rejects.toThrow("status 404");
    await expect(news.generateDemoEditorialStoryDraft("story/a")).rejects.toThrow("status 404");
    expect(fetch).toHaveBeenLastCalledWith("https://backend.invalid/api/editorial-stories/story%2Fa/generate-demo-draft", { method: "POST" });
  });
});

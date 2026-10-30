import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App";
import { DemoDataProvider, useDemoData } from "../src/context/DemoDataContext";
import { ProcessingOverviewPage } from "../src/pages/ProcessingOverviewPage";
import * as news from "../src/services/newsService";
import type { CollectArticlesResponse, EditorialQueueResponse, StoriesResponse } from "../src/types/news";
import { allFailed, collection, deferred, editorial, sources, story } from "./fixtures";

vi.mock("../src/services/newsService", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/services/newsService")>(),
  isDemoDataModeEnabled: vi.fn(), collectLatestNews: vi.fn(), getDiscoverySources: vi.fn(),
  getStories: vi.fn(), getEditorialQueue: vi.fn(), getEditorialStoryWorkspace: vi.fn(),
}));

function Probe() {
  const data = useDemoData();
  return <>
    <output data-testid="state">{JSON.stringify({ result: data.collectionResult?.articles_total ?? null, stories: data.stories.map((s) => s.id), queue: data.editorialStories.map((s) => s.id), lastCollectedAt: data.lastCollectedAt })}</output>
    <button onClick={() => { void data.collectNow(); void data.collectNow(); }}>Request collection twice</button>
  </>;
}

function mount(route = "/", processing = false) {
  return render(<DemoDataProvider><MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <App />{processing ? <ProcessingOverviewPage /> : null}<Probe />
  </MemoryRouter></DemoDataProvider>);
}

function start() {
  fireEvent.click(screen.getAllByRole("button", { name: "Start Collection" })[0]);
}

function state() { return JSON.parse(screen.getByTestId("state").textContent ?? "{}"); }

beforeEach(() => {
  vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(false);
  vi.mocked(news.getDiscoverySources).mockReset().mockResolvedValue(sources);
  vi.mocked(news.getStories).mockReset().mockResolvedValue({ stories_total: 0, stories: [] });
  vi.mocked(news.getEditorialQueue).mockReset().mockResolvedValue({ stories_total: 0, stories: [] });
  vi.mocked(news.collectLatestNews).mockReset().mockResolvedValue(collection);
  vi.mocked(news.getEditorialStoryWorkspace).mockReset().mockResolvedValue({
    ...news.getDemoEditorialStoryWorkspace("story-finale-week"),
    id: story.id, story_id: story.id, headline: story.headline,
  });
});

describe("collection state and rendered outcomes", () => {
  it("starts live mode without seeded collection, counts or sync time", async () => {
    mount();
    await screen.findByText("Hype Serbia");
    expect(state()).toEqual({ result: null, stories: [], queue: [], lastCollectedAt: null });
    expect(screen.getByText("Collection has not started yet.")).toBeTruthy();
    expect(screen.queryByText("Collection completed successfully.")).toBeNull();
    expect(screen.getAllByText("0 articles")).toHaveLength(2);
    expect(screen.queryByText(/Finale week/)).toBeNull();
  });

  it("discloses explicitly enabled demo data without inventing a sync timestamp", async () => {
    vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(true);
    mount();
    expect(screen.getByText(/Demo mode — sample stories/)).toBeTruthy();
    expect(state().result).toBe(22);
    expect(state().lastCollectedAt).toBeNull();
  });

  it("shows initial discovery, story and queue failures", async () => {
    vi.mocked(news.getDiscoverySources).mockRejectedValue(new Error("Discovery unavailable"));
    vi.mocked(news.getStories).mockRejectedValue(new Error("Stories unavailable"));
    vi.mocked(news.getEditorialQueue).mockRejectedValue(new Error("Queue unavailable"));
    mount();
    await screen.findByText("Stories unavailable");
    expect(screen.getAllByText(/Discovery unavailable/).length).toBeGreaterThan(0);
    expect(screen.getByText("Queue unavailable")).toBeTruthy();
    expect(state().result).toBeNull();
    expect(state().stories).toEqual([]);
  });

  it("displays request failures without a success message or demo substitution", async () => {
    vi.mocked(news.collectLatestNews).mockRejectedValue(new Error("Collection failed (status 502)."));
    mount();
    start();
    await screen.findByText("Collection failed (status 502).");
    expect(screen.queryByText("Collection completed successfully.")).toBeNull();
    expect(state().result).toBeNull();
  });

  it("uses source URLs for accurate counts despite different discovery names", async () => {
    mount();
    start();
    await screen.findByText("Collection completed successfully.");
    const card = screen.getByText("Hype BiH").parentElement?.parentElement;
    expect(within(card as HTMLElement).getByText("1 articles")).toBeTruthy();
    expect(state().stories).toEqual([story.id]);
    expect(state().lastCollectedAt).not.toBeNull();
  });

  it("shows partial success and the actual failed source", async () => {
    vi.mocked(news.collectLatestNews).mockResolvedValue({
      ...collection, sources_failed: 1, articles_total: 1, articles: collection.articles.slice(1),
      story_candidates_total: 0,
      source_results: [allFailed.source_results![0], collection.source_results![1]],
    });
    mount();
    start();
    await screen.findByText("Collection completed with source failures.");
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Sources failed: 1")).toBeTruthy();
    expect(screen.queryByText("Collection completed successfully.")).toBeNull();
  });

  it("preserves previous stories and timestamp on an all-source failure", async () => {
    mount();
    start();
    await screen.findByText("Collection completed successfully.");
    const timestamp = state().lastCollectedAt;
    vi.mocked(news.collectLatestNews).mockResolvedValue(allFailed);
    start();
    await screen.findByText(/^Collection failed for all sources\./);
    expect(state().stories).toEqual([story.id]);
    expect(state().lastCollectedAt).toBe(timestamp);
    expect(screen.getByText("Sources failed: 2")).toBeTruthy();
    expect(screen.queryByText("Collection completed successfully.")).toBeNull();
  });

  it("does not display the previous successful collection as a completed rerun", async () => {
    mount();
    start();
    await screen.findByText("Collection completed successfully.");
    const pending = deferred<CollectArticlesResponse>();
    vi.mocked(news.collectLatestNews).mockReturnValue(pending.promise);
    start();
    expect(screen.getByText("Collection in progress.")).toBeTruthy();
    expect(screen.queryByText("Collection completed successfully.")).toBeNull();
    expect(screen.getByRole("button", { name: "Collecting articles..." }).hasAttribute("disabled")).toBe(true);
    await act(async () => pending.resolve(collection));
    await screen.findByText("Collection completed successfully.");
  });

  it("prevents overlapping collections even within the same render", async () => {
    const pending = deferred<CollectArticlesResponse>();
    vi.mocked(news.collectLatestNews).mockReturnValue(pending.promise);
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Request collection twice" }));
    expect(news.collectLatestNews).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(collection));
  });

  it("retains the last result on a failed rerun and labels it as previous", async () => {
    mount("/", true);
    start();
    await screen.findByText("Collection completed successfully.");
    const timestamp = state().lastCollectedAt;
    vi.mocked(news.collectLatestNews).mockRejectedValue(new Error("Backend unavailable"));
    start();
    await screen.findByText("Latest collection failed.");
    expect(state().result).toBe(2);
    expect(state().lastCollectedAt).toBe(timestamp);
    expect(screen.getByText("Collection counts below describe the last received response.")).toBeTruthy();
  });

  it("reports real grouping and queue counts, and shows queue refresh errors", async () => {
    vi.mocked(news.getEditorialQueue).mockResolvedValueOnce({ stories_total: 0, stories: [] }).mockResolvedValueOnce({ stories_total: 1, stories: [editorial] });
    mount("/", true);
    await waitFor(() => expect(news.getEditorialQueue).toHaveBeenCalledTimes(1));
    start();
    await screen.findByText("Editorial queue loaded: 1 stories.");
    const metric = screen.getByText("Articles Grouped into Existing Stories").parentElement!;
    expect(within(metric).getByText("1")).toBeTruthy();
    const storyMetric = screen.getByText("Stories Created").parentElement!;
    expect(within(storyMetric).getByText("1")).toBeTruthy();
    vi.mocked(news.getEditorialQueue).mockRejectedValue(new Error("Queue refresh failed"));
    start();
    await screen.findByText("Editorial queue unavailable: Queue refresh failed");
    expect(state().queue).toEqual([]);
    expect(screen.getByText("Unavailable")).toBeTruthy();
  });

  it("does not invent grouped articles or stories for an empty successful result", async () => {
    vi.mocked(news.collectLatestNews).mockResolvedValue({ ...collection, articles: [], articles_total: 0, stories: [], stories_total: 0, story_candidates_total: 0, source_results: collection.source_results?.map((s) => ({ ...s, articles_total: 0 })) });
    mount("/", true);
    start();
    await screen.findByText("Collection completed successfully.");
    expect(within(screen.getByText("Articles Grouped into Existing Stories").parentElement!).getByText("0")).toBeTruthy();
    expect(state().stories).toEqual([]);
  });

  it("does not let slow initial requests overwrite a new collection", async () => {
    const initialStories = deferred<StoriesResponse>();
    const initialQueue = deferred<EditorialQueueResponse>();
    vi.mocked(news.getStories).mockReturnValue(initialStories.promise);
    vi.mocked(news.getEditorialQueue).mockReturnValueOnce(initialQueue.promise).mockResolvedValueOnce({ stories_total: 1, stories: [editorial] });
    mount();
    start();
    await screen.findByText("Collection completed successfully.");
    await act(async () => {
      initialStories.resolve({ stories_total: 0, stories: [] });
      initialQueue.resolve({ stories_total: 0, stories: [] });
    });
    expect(state().stories).toEqual([story.id]);
    expect(state().queue).toEqual([story.id]);
  });

  it("does not mark collection complete just by navigating to publishing", async () => {
    mount("/publish");
    expect(state().result).toBeNull();
    expect(screen.getByRole("link", { name: /01 Collect/ })).toBeTruthy();
  });

  it("handles older backend responses without per-source outcomes honestly", async () => {
    vi.mocked(news.collectLatestNews).mockResolvedValue({ ...collection, source_results: undefined });
    mount();
    start();
    await screen.findByText("Collection completed successfully.");
    expect(screen.getAllByText("Per-source outcome unavailable")).toHaveLength(2);
  });

  it("reports zero processed sources as an unsuccessful attempt", async () => {
    vi.mocked(news.collectLatestNews).mockResolvedValue({ ...allFailed, sources_processed: 0, sources_failed: 0, source_results: [] });
    mount();
    start();
    await screen.findByText("No sources were processed. Previous stories are unchanged.");
    expect(state().lastCollectedAt).toBeNull();
    expect(screen.queryByText("Collection completed successfully.")).toBeNull();
  });

  it("shows the workspace's actual draft status and keeps draft creation disabled", async () => {
    mount(`/review/${story.id}`);
    await screen.findByText("Status: needs generation");
    expect(screen.getByText("Draft not generated")).toBeTruthy();
    expect(screen.queryByText(/Ready for Human Editing/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continue to Publishing Preview" }));
    await screen.findByRole("heading", { name: "Publishing Preview" });
    fireEvent.click(screen.getByRole("button", { name: "Preview WordPress Draft" }));
    const modal = screen.getByRole("dialog");
    expect(within(modal).getByRole("button", { name: /Create WordPress Draft/ }).hasAttribute("disabled")).toBe(true);
  });

  it("does not claim the editorial workflow is complete when viewing the portal preview", async () => {
    vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(true);
    mount(`/portal-preview/${story.id}`);
    await screen.findByText("Portal Preview Ready");
    expect(screen.queryByText("Editorial Workflow Complete")).toBeNull();
    expect(screen.getByText(/Demo mode — sample stories/)).toBeTruthy();
    expect(screen.getByText(/Opening this preview does not create a WordPress draft/)).toBeTruthy();
  });

  it("does not present an unmatched singleton as a zero-percent match", async () => {
    vi.mocked(news.getEditorialQueue).mockResolvedValue({ stories_total: 1, stories: [{ ...editorial, article_count: 1, similarity_score: 0 }] });
    mount("/review");
    await screen.findByText("No match yet");
    expect(screen.queryByText("0%")).toBeNull();
  });
});

import type {
  CollectArticlesResponse,
  DiscoveryResult,
  EditorialQueueResponse,
  EditorialStory,
  EditorialStoryWorkspace,
  NormalizedArticle,
  StoriesResponse,
  StorySummary,
} from "../types/news";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "");
const DEMO_MODE = API_BASE_URL.length === 0;

const DEMO_SOURCES: DiscoveryResult[] = [
  {
    name: "Hype Serbia",
    url: "https://hypetv.rs",
    wordpress: true,
    rss: false,
    preferred: "wordpress",
    posts_endpoint: "https://hypetv.rs/wp-json/wp/v2/posts",
    rss_endpoint: null,
    sample_article: {
      title: "Finale week dominates Balkan entertainment agenda",
      date: "2026-07-08T20:35:00Z",
      image: "https://images.unsplash.com/photo-1470229722913-7c0e2dbbafd3",
      url: "https://hypetv.rs/entertainment/finale-week-balkan",
      categories: ["Entertainment", "TV"]
    }
  },
  {
    name: "Hype Croatia",
    url: "https://hypetv.hr",
    wordpress: true,
    rss: false,
    preferred: "wordpress",
    posts_endpoint: "https://hypetv.hr/wp-json/wp/v2/posts",
    rss_endpoint: null,
    sample_article: {
      title: "Prime time guests boost cross-border viewership",
      date: "2026-07-08T19:10:00Z",
      image: "https://images.unsplash.com/photo-1516280440614-37939bbacd81",
      url: "https://hypetv.hr/entertainment/prime-time-guests",
      categories: ["TV", "Celebrities"]
    }
  },
  {
    name: "Hype Bosnia",
    url: "https://hypebih.ba",
    wordpress: true,
    rss: true,
    preferred: "wordpress",
    posts_endpoint: "https://hypebih.ba/wp-json/wp/v2/posts",
    rss_endpoint: "https://hypebih.ba/feed",
    sample_article: {
      title: "Regional talent format locks autumn production slots",
      date: "2026-07-08T18:40:00Z",
      image: "https://images.unsplash.com/photo-1506157786151-b8491531f063",
      url: "https://hypebih.ba/showbiz/talent-format-autumn",
      categories: ["Production", "Formats"]
    }
  },
  {
    name: "Hype Slovenia",
    url: "https://hypetv.si",
    wordpress: true,
    rss: false,
    preferred: "wordpress",
    posts_endpoint: "https://hypetv.si/wp-json/wp/v2/posts",
    rss_endpoint: null,
    sample_article: {
      title: "Music special sends weekend engagement to seasonal high",
      date: "2026-07-08T17:55:00Z",
      image: "https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f",
      url: "https://hypetv.si/music/weekend-engagement-high",
      categories: ["Music", "Digital"]
    }
  },
  {
    name: "Hype Macedonia",
    url: "https://hypetv.mk",
    wordpress: true,
    rss: false,
    preferred: "wordpress",
    posts_endpoint: "https://hypetv.mk/wp-json/wp/v2/posts",
    rss_endpoint: null,
    sample_article: {
      title: "Live event coverage drives sponsored segment demand",
      date: "2026-07-08T17:20:00Z",
      image: "https://images.unsplash.com/photo-1460723237483-7a6dc9d0b212",
      url: "https://hypetv.mk/events/live-coverage-demand",
      categories: ["Events", "Business"]
    }
  },
  {
    name: "Hype Production",
    url: "https://www.hypeproduction.rs",
    wordpress: true,
    rss: false,
    preferred: "wordpress",
    posts_endpoint: "https://www.hypeproduction.rs/wp-json/wp/v2/posts",
    rss_endpoint: null,
    sample_article: {
      title: "Editorial AI pilot reduces duplicate stories by 34%",
      date: "2026-07-08T16:45:00Z",
      image: "https://images.unsplash.com/photo-1504384308090-c894fdcc538d",
      url: "https://www.hypeproduction.rs/newsroom/ai-pilot-results",
      categories: ["Newsroom", "AI"]
    }
  }
];

const STORY_SEEDS: Array<{
  id: string;
  headline: string;
  sources: string[];
  publishedAt: string;
  similarity: number;
  status: StorySummary["status"];
}> = [
  {
    id: "story-finale-week",
    headline: "Finale week sparks synchronized ratings surge across regional channels",
    sources: ["Hype Serbia", "Hype Croatia", "Hype Bosnia"],
    publishedAt: "2026-07-08T20:35:00Z",
    similarity: 92,
    status: "review"
  },
  {
    id: "story-prime-guests",
    headline: "Prime time guest lineup pushes advertiser demand above forecast",
    sources: ["Hype Croatia", "Hype Slovenia"],
    publishedAt: "2026-07-08T19:12:00Z",
    similarity: 88,
    status: "review"
  },
  {
    id: "story-talent-format",
    headline: "Regional talent format confirms autumn production calendar",
    sources: ["Hype Bosnia", "Hype Serbia", "Hype Production"],
    publishedAt: "2026-07-08T18:40:00Z",
    similarity: 90,
    status: "review"
  },
  {
    id: "story-music-special",
    headline: "Weekend music special delivers strongest digital engagement this quarter",
    sources: ["Hype Slovenia", "Hype Macedonia"],
    publishedAt: "2026-07-08T17:56:00Z",
    similarity: 86,
    status: "review"
  },
  {
    id: "story-live-events",
    headline: "Live event coverage expands sponsorship inventory for Q3",
    sources: ["Hype Macedonia", "Hype Serbia", "Hype Croatia", "Hype Production"],
    publishedAt: "2026-07-08T17:18:00Z",
    similarity: 89,
    status: "review"
  },
  {
    id: "story-ai-pilot",
    headline: "AI editorial pilot cuts duplicate intake and accelerates review readiness",
    sources: ["Hype Production", "Hype Serbia", "Hype Bosnia"],
    publishedAt: "2026-07-08T16:45:00Z",
    similarity: 95,
    status: "review"
  },
  {
    id: "story-weekend-grid",
    headline: "Weekend grid refresh improves late-night retention across two markets",
    sources: ["Hype Croatia", "Hype Macedonia"],
    publishedAt: "2026-07-08T15:32:00Z",
    similarity: 84,
    status: "draft"
  },
  {
    id: "story-studio-upgrade",
    headline: "Studio upgrade package approved for next production block",
    sources: ["Hype Production", "Hype Slovenia", "Hype Serbia"],
    publishedAt: "2026-07-08T14:58:00Z",
    similarity: 82,
    status: "published"
  }
];

const SOURCE_URLS = new Map(DEMO_SOURCES.map((source) => [source.name, source.url]));
const SOURCE_LANGUAGES = new Map<string, string>([
  ["Hype Serbia", "sr"],
  ["Hype Croatia", "hr"],
  ["Hype Bosnia", "bs"],
  ["Hype Slovenia", "sl"],
  ["Hype Macedonia", "mk"],
  ["Hype Production", "sr"],
]);
const SOURCE_COUNTRIES = new Map<string, string>([
  ["Hype Serbia", "RS"],
  ["Hype Croatia", "HR"],
  ["Hype Bosnia", "BA"],
  ["Hype Slovenia", "SI"],
  ["Hype Macedonia", "MK"],
  ["Hype Production", "RS"],
]);

const DEMO_ARTICLES: NormalizedArticle[] = STORY_SEEDS.flatMap((story) =>
  story.sources.map((source, index) => {
    const sourceUrl = SOURCE_URLS.get(source) ?? "https://hypetv.rs";
    const suffix = index === 0 ? "" : ` - ${source.replace("Hype ", "")}`;

    return {
      external_id: `${story.id}-article-${index + 1}`,
      connector: "wordpress",
      source,
      source_url: sourceUrl,
      language: SOURCE_LANGUAGES.get(source) ?? "sr",
      title: `${story.headline}${suffix}`,
      url: `${sourceUrl}/demo/${story.id}/${index + 1}`,
      published_at: story.publishedAt,
      excerpt: `${story.headline} This source version captures local editorial framing and audience reaction trends.`,
      content: `${story.headline}. Editorial teams report measurable momentum and clear commercial relevance for the next rundown cycle.`,
      featured_image: null,
      categories: ["Entertainment", "Regional"],
      raw: { demo: true, story_id: story.id }
    };
  })
);

const DEMO_STORIES: StorySummary[] = STORY_SEEDS.map((story) => ({
  id: story.id,
  headline: story.headline,
  sources: story.sources,
  article_count: story.sources.length,
  similarity_score: story.similarity,
  status: story.status,
  published_at: story.publishedAt
}));

const DEMO_EDITORIAL_QUEUE: EditorialStory[] = STORY_SEEDS.map((story, index) => ({
  id: story.id,
  headline: story.headline,
  status: story.status,
  sources: story.sources,
  source_count: story.sources.length,
  article_count: story.sources.length,
  similarity_score: story.similarity,
  published_at: story.publishedAt,
  categories: ["Entertainment", "Regional"],
  language: "sr",
  importance_score: Math.max(70, 96 - index * 3),
  confidence_score: Math.max(68, 94 - index * 2),
  coverage: story.sources.length >= 4 ? "International" : story.sources.length >= 3 ? "Regional" : "Local",
  trend: index < 3 ? "Rising" : index < 6 ? "Stable" : "Declining",
  freshness: Math.max(60, 96 - index * 5),
  risk_level: index < 5 ? "Low" : "Medium",
  recommended_action: index < 3 ? "Publish Immediately" : index < 6 ? "Review Soon" : "Manual Review",
  reason:
    index < 3
      ? "High regional convergence and strong commercial relevance across multiple sources."
      : "Meaningful signal detected, but requires editorial alignment before broadcast packaging."
}));

const DEMO_COLLECTION_RESULT: CollectArticlesResponse = {
  sources_processed: DEMO_SOURCES.length,
  sources_failed: 0,
  articles_total: DEMO_ARTICLES.length,
  articles: DEMO_ARTICLES,
  story_candidates_total: DEMO_ARTICLES.length,
  stories_total: DEMO_STORIES.length,
  stories: DEMO_STORIES
};

const DEMO_EDITORIAL_STORY_OVERRIDES = new Map<string, Pick<EditorialStoryWorkspace, "status" | "serbian_draft">>();

function buildDemoEditorialStoryWorkspace(storyId: string): EditorialStoryWorkspace {
  const story = DEMO_STORIES.find((entry) => entry.id === storyId);
  const queueStory = DEMO_EDITORIAL_QUEUE.find((entry) => entry.id === storyId);

  if (!story || !queueStory) {
    throw new Error(`Story '${storyId}' not found`);
  }

  const sourceArticles = DEMO_ARTICLES.filter((article) => article.external_id.includes(storyId)).map((article) => ({
    external_id: article.external_id,
    source: article.source,
    source_url: article.source_url,
    country: SOURCE_COUNTRIES.get(article.source) ?? "RS",
    language: article.language,
    title: article.title,
    excerpt: article.excerpt,
    content: article.content,
    featured_image: article.featured_image,
    published_at: article.published_at,
    url: article.url,
    categories: article.categories,
  }));

  const override = DEMO_EDITORIAL_STORY_OVERRIDES.get(storyId);
  const serbianDraft =
    override?.serbian_draft ?? {
      headline: null,
      excerpt: null,
      content: null,
      status: "not_generated" as const,
    };
  const workspaceStatus = override?.status ?? "needs_generation";
  const currentStep = serbianDraft.status === "not_generated" ? "serbian_draft" : workspaceStatus === "approved" ? "publishing" : "human_review";
  const processingHistory = [
    ["collected", "Collected"],
    ["normalized", "Normalized"],
    ["sources_merged", "Sources Merged"],
    ["editorially_scored", "Editorially Scored"],
    ["serbian_draft", "Serbian Draft"],
    ["human_review", "Human Review"],
    ["publishing", "Publishing"],
  ].map(([key, label], index, steps) => {
    const currentIndex = steps.findIndex(([stepKey]) => stepKey === currentStep);
    return {
      key,
      label,
      state: index < currentIndex ? "completed" : index === currentIndex ? "current" : "future",
    } as const;
  });

  return {
    id: story.id,
    story_id: story.id,
    headline: story.headline,
    target_language: "sr",
    target_language_label: "Serbian",
    status: workspaceStatus,
    source_articles: sourceArticles,
    source_count: sourceArticles.length,
    source_languages: [...new Set(sourceArticles.map((article) => article.language).filter(Boolean))] as string[],
    source_countries: [...new Set(sourceArticles.map((article) => article.country))],
    editorial_intelligence: {
      importance_score: queueStory.importance_score,
      confidence_score: queueStory.confidence_score,
      coverage: queueStory.coverage,
      risk_level: queueStory.risk_level,
      recommended_action: queueStory.recommended_action,
      reason: queueStory.reason,
    },
    serbian_draft: serbianDraft,
    processing_history: processingHistory,
  };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function logDemoFallback(reason: string, error?: unknown): void {
  if (error) {
    console.warn(`[newsService] ${reason}. Using demo data fallback.`, error);
    return;
  }

  console.info(`[newsService] ${reason}. Using demo data fallback.`);
}

async function fetchWithFallback<T>(path: string, fallback: T, errorMessage: string): Promise<T> {
  if (DEMO_MODE) {
    logDemoFallback("VITE_API_URL/VITE_API_BASE_URL not configured");
    return clone(fallback);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`);

    if (!response.ok) {
      throw new Error(`${errorMessage} (status ${response.status})`);
    }

    return (await response.json()) as T;
  } catch (error) {
    logDemoFallback(errorMessage, error);
    return clone(fallback);
  }
}

export function isDemoDataModeEnabled(): boolean {
  return DEMO_MODE;
}

export function getDemoDiscoverySources(): DiscoveryResult[] {
  return clone(DEMO_SOURCES);
}

export function getDemoStoriesResponse(): StoriesResponse {
  return {
    stories_total: DEMO_STORIES.length,
    stories: clone(DEMO_STORIES)
  };
}

export function getDemoEditorialQueueResponse(): EditorialQueueResponse {
  return {
    stories_total: DEMO_EDITORIAL_QUEUE.length,
    stories: clone(DEMO_EDITORIAL_QUEUE)
  };
}

export function getDemoCollectArticlesResponse(): CollectArticlesResponse {
  return clone(DEMO_COLLECTION_RESULT);
}

export function getDemoEditorialStoryWorkspace(storyId: string): EditorialStoryWorkspace {
  return clone(buildDemoEditorialStoryWorkspace(storyId));
}

export async function getDiscoverySources(): Promise<DiscoveryResult[]> {
  return fetchWithFallback("/api/discovery", DEMO_SOURCES, "Unable to fetch source discovery");
}

export async function collectLatestNews(): Promise<CollectArticlesResponse> {
  return fetchWithFallback("/api/collect", DEMO_COLLECTION_RESULT, "Collection failed. Please try again.");
}

export async function getStories(): Promise<StoriesResponse> {
  return fetchWithFallback(
    "/api/stories",
    {
      stories_total: DEMO_STORIES.length,
      stories: DEMO_STORIES
    },
    "Unable to fetch stories"
  );
}

export async function getEditorialQueue(): Promise<EditorialQueueResponse> {
  return fetchWithFallback(
    "/api/editorial-queue",
    {
      stories_total: DEMO_EDITORIAL_QUEUE.length,
      stories: DEMO_EDITORIAL_QUEUE
    },
    "Unable to fetch editorial queue"
  );
}

export async function getEditorialStoryWorkspace(storyId: string): Promise<EditorialStoryWorkspace> {
  if (DEMO_MODE) {
    logDemoFallback("VITE_API_URL/VITE_API_BASE_URL not configured");
    return getDemoEditorialStoryWorkspace(storyId);
  }

  const response = await fetch(`${API_BASE_URL}/api/editorial-stories/${encodeURIComponent(storyId)}`);
  if (!response.ok) {
    throw new Error(response.status === 404 ? "Editorial story not found" : `Unable to fetch editorial story (status ${response.status})`);
  }

  return (await response.json()) as EditorialStoryWorkspace;
}

export async function generateDemoEditorialStoryDraft(storyId: string): Promise<EditorialStoryWorkspace> {
  if (DEMO_MODE) {
    const workspace = buildDemoEditorialStoryWorkspace(storyId);
    const primaryArticle = workspace.source_articles[0];
    DEMO_EDITORIAL_STORY_OVERRIDES.set(storyId, {
      status: "draft_ready",
      serbian_draft: {
        headline: workspace.headline,
        excerpt: primaryArticle?.excerpt ?? workspace.headline,
        content:
          "Demo Draft\n\nThis deterministic placeholder shows where the future unified Serbian editorial story will appear. It is not real AI output and it is not a real translation. The final Serbian version will later be prepared from all verified regional source articles listed in this workspace.",
        status: "demo_generated",
      },
    });
    return getDemoEditorialStoryWorkspace(storyId);
  }

  const response = await fetch(`${API_BASE_URL}/api/editorial-stories/${encodeURIComponent(storyId)}/generate-demo-draft`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(response.status === 404 ? "Editorial story not found" : `Unable to generate demo draft (status ${response.status})`);
  }

  return (await response.json()) as EditorialStoryWorkspace;
}

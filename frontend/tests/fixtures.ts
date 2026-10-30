import type { CollectArticlesResponse, DiscoveryResult, EditorialStory, NormalizedArticle, StorySummary } from "../src/types/news";

export const sources: DiscoveryResult[] = [
  { name: "Hype Serbia", url: "https://hypetv.rs", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
  { name: "Hype BiH", url: "https://hypebih.ba", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
];

const article: NormalizedArticle = {
  external_id: "1", connector: "wordpress", source: "Hype Serbia", source_url: "https://hypetv.rs",
  language: "sr", title: "Actual source coverage", url: "https://hypetv.rs/article", published_at: "2026-10-30T10:00:00Z",
  excerpt: "Original excerpt", content: null, featured_image: null, categories: ["Entertainment"], raw: null,
};

export const story: StorySummary = {
  id: "story-actual", headline: "Actual source coverage", sources: ["Hype Serbia", "Hype Bosnia"], article_count: 2,
  similarity_score: 77, status: "review", published_at: article.published_at,
};

export const editorial: EditorialStory = {
  ...story, status: "merged", source_count: 2, categories: ["Entertainment"], language: "sr",
  importance_score: 70, confidence_score: 57, coverage: "Regional", trend: "Stable", freshness: 70,
  risk_level: "Medium", recommended_action: "Review Soon", reason: "Rules-based score",
};

export const collection: CollectArticlesResponse = {
  sources_processed: 2, sources_failed: 0, articles_total: 2,
  articles: [article, { ...article, external_id: "2", source: "Hype Bosnia", source_url: "https://hypebih.ba", url: "https://hypebih.ba/article" }],
  story_candidates_total: 1, stories_total: 1, stories: [story],
  source_results: [
    { name: "Hype Serbia", url: "https://hypetv.rs", status: "success", articles_total: 1, error: null },
    { name: "Hype Bosnia", url: "https://hypebih.ba", status: "success", articles_total: 1, error: null },
  ],
};

export const allFailed: CollectArticlesResponse = {
  ...collection, sources_failed: 2, articles_total: 0, articles: [], story_candidates_total: 0, stories_total: 0, stories: [],
  source_results: collection.source_results?.map((source) => ({ ...source, status: "failed", articles_total: 0, error: "Unable to collect this source." })),
};

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

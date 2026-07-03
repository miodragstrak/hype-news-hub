export type DiscoveredArticle = {
  title: string | null;
  date: string | null;
  image: string | null;
  url: string | null;
  categories: string[];
};

export type DiscoveryResult = {
  name: string;
  url: string;
  wordpress: boolean;
  rss: boolean;
  preferred: "wordpress" | "rss" | "html_scraping";
  posts_endpoint: string | null;
  rss_endpoint: string | null;
  sample_article: DiscoveredArticle | null;
};

export type NormalizedArticle = {
  external_id: string;
  connector: string;
  source: string;
  source_url: string;
  language: string | null;
  title: string;
  url: string;
  published_at: string | null;
  excerpt: string;
  content: string | null;
  featured_image: string | null;
  categories: string[];
  raw: Record<string, unknown> | null;
};

export type CollectArticlesResponse = {
  sources_processed: number;
  sources_failed: number;
  articles_total: number;
  articles: NormalizedArticle[];
  story_candidates_total: number;
  stories_total: number;
  stories: StorySummary[];
};

export type StoryStatus = "collected" | "merged" | "translated" | "draft" | "review" | "published";

export type StorySummary = {
  id: string;
  headline: string;
  sources: string[];
  article_count: number;
  similarity_score: number;
  status: StoryStatus;
  published_at: string | null;
};

export type StoriesResponse = {
  stories_total: number;
  stories: StorySummary[];
};

export type EditorialCoverage = "Local" | "Regional" | "International";
export type EditorialTrend = "Rising" | "Stable" | "Declining";
export type EditorialRisk = "Low" | "Medium" | "High";
export type EditorialRecommendedAction = "Publish Immediately" | "Review Soon" | "Manual Review" | "Ignore";

export type EditorialStory = {
  id: string;
  headline: string;
  status: StoryStatus;
  sources: string[];
  source_count: number;
  article_count: number;
  similarity_score: number;
  published_at: string | null;
  categories: string[];
  language: string | null;
  importance_score: number;
  confidence_score: number;
  coverage: EditorialCoverage;
  trend: EditorialTrend;
  freshness: number;
  risk_level: EditorialRisk;
  recommended_action: EditorialRecommendedAction;
  reason: string;
};

export type EditorialQueueResponse = {
  stories_total: number;
  stories: EditorialStory[];
};

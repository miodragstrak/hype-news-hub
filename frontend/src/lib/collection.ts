import type { CollectArticlesResponse, DiscoveryResult } from "../types/news";

export function collectionOutcome(result: CollectArticlesResponse | null, running: boolean, error: string | null) {
  if (running) return "running";
  if (error) return "failed";
  if (!result || result.sources_processed === 0) return "idle";
  if (result.sources_failed === result.sources_processed) return "failed";
  return result.sources_failed > 0 ? "partial" : "complete";
}

// Source URLs, rather than discovery's display names, identify collection results.
export function collectionSources(sources: DiscoveryResult[], result: CollectArticlesResponse | null): DiscoveryResult[] {
  const byUrl = new Map(sources.map((source) => [source.url, source]));
  for (const source of result?.source_results ?? []) {
    const discovered = byUrl.get(source.url);
    byUrl.set(source.url, {
      name: source.name, url: source.url, wordpress: false, rss: false,
      preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null,
      ...discovered,
    });
  }
  return [...byUrl.values()];
}

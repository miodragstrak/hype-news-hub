import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { collectLatestNews, getDemoCollectArticlesResponse, getDemoEditorialQueueResponse, getDemoStoriesResponse, getDiscoverySources, getEditorialQueue, getStories } from "../services/newsService";
import type { CollectArticlesResponse, DiscoveryResult, EditorialStory, NormalizedArticle, StorySummary } from "../types/news";

export type EditorialDraftSource = {
  id: string;
  countryFlag: string;
  sourceName: string;
  originalLanguage: string;
  originalHeadline: string;
  url: string;
};

export type EditorialDraftPackage = {
  storyId: string;
  headline: string;
  slug: string;
  category: string;
  featuredImage: string | null;
  excerpt: string;
  mainContent: string;
  categories: string[];
  tags: string[];
  seoTitle: string;
  seoDescription: string;
  sourcesUsed: EditorialDraftSource[];
};

type DemoDataContextValue = {
  sources: DiscoveryResult[];
  sourceError: string | null;
  isLoadingSources: boolean;
  collectionResult: CollectArticlesResponse | null;
  isCollecting: boolean;
  collectError: string | null;
  lastCollectedAt: string | null;
  articles: NormalizedArticle[];
  stories: StorySummary[];
  editorialStories: EditorialStory[];
  sourceArticleCounts: Record<string, number>;
  selectedDraftPackage: EditorialDraftPackage | null;
  setSelectedDraftPackage: (draftPackage: EditorialDraftPackage | null) => void;
  collectNow: () => Promise<void>;
};

const FALLBACK_SOURCES: DiscoveryResult[] = [
  { name: "Hype Serbia", url: "https://hypetv.rs", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
  { name: "Hype Croatia", url: "https://hypetv.hr", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
  { name: "Hype Bosnia", url: "https://hypebih.ba", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
  { name: "Hype Slovenia", url: "https://hypetv.si", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
  { name: "Hype Macedonia", url: "https://hypetv.mk", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null },
  { name: "Hype Production", url: "https://www.hypeproduction.rs", wordpress: true, rss: false, preferred: "wordpress", posts_endpoint: null, rss_endpoint: null, sample_article: null }
];

const DemoDataContext = createContext<DemoDataContextValue | null>(null);

export function DemoDataProvider({ children }: { children: ReactNode }): JSX.Element {
  const [sources, setSources] = useState<DiscoveryResult[]>(FALLBACK_SOURCES);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [isLoadingSources, setIsLoadingSources] = useState(true);

  const [collectionResult, setCollectionResult] = useState<CollectArticlesResponse | null>(() => getDemoCollectArticlesResponse());
  const [isCollecting, setIsCollecting] = useState(false);
  const [collectError, setCollectError] = useState<string | null>(null);
  const [lastCollectedAt, setLastCollectedAt] = useState<string | null>(() => new Date().toISOString());
  const [stories, setStories] = useState<StorySummary[]>(() => getDemoStoriesResponse().stories);
  const [editorialStories, setEditorialStories] = useState<EditorialStory[]>(() => getDemoEditorialQueueResponse().stories);
  const [selectedDraftPackage, setSelectedDraftPackage] = useState<EditorialDraftPackage | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadSources(): Promise<void> {
      try {
        const discovered = await getDiscoverySources();
        if (isMounted && discovered.length > 0) {
          setSources(discovered.slice(0, 6));
        }
      } catch (error) {
        if (isMounted) {
          setSourceError(error instanceof Error ? error.message : "Unknown discovery error");
        }
      } finally {
        if (isMounted) {
          setIsLoadingSources(false);
        }
      }
    }

    void loadSources();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function loadEditorialQueue(): Promise<void> {
      try {
        const response = await getEditorialQueue();
        if (isMounted) {
          setEditorialStories(response.stories);
        }
      } catch {
        if (isMounted) {
          setEditorialStories([]);
        }
      }
    }

    void loadEditorialQueue();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function loadStories(): Promise<void> {
      try {
        const response = await getStories();
        if (isMounted) {
          setStories(response.stories);
        }
      } catch {
        if (isMounted) {
          setStories([]);
        }
      }
    }

    void loadStories();

    return () => {
      isMounted = false;
    };
  }, []);

  const sourceArticleCounts = useMemo(() => {
    return (collectionResult?.articles ?? []).reduce<Record<string, number>>((acc, article) => {
      acc[article.source] = (acc[article.source] ?? 0) + 1;
      return acc;
    }, {});
  }, [collectionResult]);

  const value = useMemo<DemoDataContextValue>(
    () => ({
      sources,
      sourceError,
      isLoadingSources,
      collectionResult,
      isCollecting,
      collectError,
      lastCollectedAt,
      articles: collectionResult?.articles ?? [],
      stories,
      editorialStories,
      sourceArticleCounts,
      selectedDraftPackage,
      setSelectedDraftPackage,
      collectNow: async () => {
        setCollectError(null);
        setIsCollecting(true);
        try {
          const data = await collectLatestNews();
          setCollectionResult(data);
          setStories(data.stories);

          try {
            const storyResponse = await getStories();
            setStories(storyResponse.stories);
          } catch {
            // Keep story data from /collect if /stories fetch fails.
          }

          try {
            const editorialResponse = await getEditorialQueue();
            setEditorialStories(editorialResponse.stories);
          } catch {
            setEditorialStories([]);
          }

          setLastCollectedAt(new Date().toISOString());
        } catch (error) {
          setCollectError(error instanceof Error ? error.message : "Unknown collection error");
        } finally {
          setIsCollecting(false);
        }
      }
    }),
    [collectionResult, collectError, editorialStories, isCollecting, isLoadingSources, lastCollectedAt, selectedDraftPackage, sourceArticleCounts, sourceError, sources, stories]
  );

  return <DemoDataContext.Provider value={value}>{children}</DemoDataContext.Provider>;
}

export function useDemoData(): DemoDataContextValue {
  const context = useContext(DemoDataContext);

  if (!context) {
    throw new Error("useDemoData must be used inside DemoDataProvider");
  }

  return context;
}

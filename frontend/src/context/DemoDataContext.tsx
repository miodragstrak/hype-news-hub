import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { collectLatestNews, getDemoCollectArticlesResponse, getDemoDiscoverySources, getDemoEditorialQueueResponse, getDemoStoriesResponse, getDiscoverySources, getEditorialQueue, getStories, isDemoDataModeEnabled } from "../services/newsService";
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
  isDemoMode: boolean;
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
  storiesError: string | null;
  editorialError: string | null;
  isLoadingEditorial: boolean;
  sourceArticleCounts: Record<string, number>;
  selectedDraftPackage: EditorialDraftPackage | null;
  setSelectedDraftPackage: (draftPackage: EditorialDraftPackage | null) => void;
  collectNow: () => Promise<void>;
};

const DemoDataContext = createContext<DemoDataContextValue | null>(null);

export function DemoDataProvider({ children }: { children: ReactNode }): JSX.Element {
  const isDemoMode = isDemoDataModeEnabled();
  const [sources, setSources] = useState<DiscoveryResult[]>(() => isDemoMode ? getDemoDiscoverySources() : []);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [isLoadingSources, setIsLoadingSources] = useState(true);

  const [collectionResult, setCollectionResult] = useState<CollectArticlesResponse | null>(() => isDemoMode ? getDemoCollectArticlesResponse() : null);
  const [isCollecting, setIsCollecting] = useState(false);
  const [collectError, setCollectError] = useState<string | null>(null);
  const [lastCollectedAt, setLastCollectedAt] = useState<string | null>(null);
  const [stories, setStories] = useState<StorySummary[]>(() => isDemoMode ? getDemoStoriesResponse().stories : []);
  const [editorialStories, setEditorialStories] = useState<EditorialStory[]>(() => isDemoMode ? getDemoEditorialQueueResponse().stories : []);
  const [storiesError, setStoriesError] = useState<string | null>(null);
  const [editorialError, setEditorialError] = useState<string | null>(null);
  const [isLoadingEditorial, setIsLoadingEditorial] = useState(true);
  const [selectedDraftPackage, setSelectedDraftPackage] = useState<EditorialDraftPackage | null>(null);
  const collectionVersion = useRef(0);
  const collectionInFlight = useRef(false);

  useEffect(() => {
    let isMounted = true;

    async function loadSources(): Promise<void> {
      try {
        const discovered = await getDiscoverySources();
        if (isMounted) {
          setSources(discovered);
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
    const version = collectionVersion.current;

    async function loadEditorialQueue(): Promise<void> {
      try {
        const response = await getEditorialQueue();
        if (isMounted && version === collectionVersion.current) {
          setEditorialStories(response.stories);
        }
      } catch (error) {
        if (isMounted && version === collectionVersion.current) {
          setEditorialError(error instanceof Error ? error.message : "Unable to load editorial queue.");
        }
      } finally {
        if (isMounted && version === collectionVersion.current) {
          setIsLoadingEditorial(false);
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
    const version = collectionVersion.current;

    async function loadStories(): Promise<void> {
      try {
        const response = await getStories();
        if (isMounted && version === collectionVersion.current) {
          setStories(response.stories);
        }
      } catch (error) {
        if (isMounted && version === collectionVersion.current) {
          setStoriesError(error instanceof Error ? error.message : "Unable to load stories.");
        }
      }
    }

    void loadStories();

    return () => {
      isMounted = false;
    };
  }, []);

  const collectNow = useCallback(async (): Promise<void> => {
    if (collectionInFlight.current) return;
    collectionInFlight.current = true;
    setCollectError(null);
    setIsCollecting(true);
    try {
      const data = await collectLatestNews();
      setCollectionResult(data);
      if (data.sources_processed === 0) {
        setCollectError("No sources were processed. Previous stories are unchanged.");
        return;
      }
      if (data.sources_processed > 0 && data.sources_failed === data.sources_processed) {
        setCollectError("Collection failed for all sources. No new articles were collected; previous stories are unchanged.");
        return;
      }

      // /collect supplies the complete visible snapshot: retained stories in
      // PostgreSQL mode, or the latest collection in memory/demo mode.
      collectionVersion.current += 1;
      setStories(data.stories);
      setStoriesError(null);
      setSelectedDraftPackage(null);
      setLastCollectedAt(new Date().toISOString());
      setEditorialStories([]);
      setEditorialError(null);
      setIsLoadingEditorial(true);
      try {
        const queue = await getEditorialQueue();
        setEditorialStories(queue.stories);
      } catch (error) {
        setEditorialError(error instanceof Error ? error.message : "Unable to load editorial queue.");
      }
    } catch (error) {
      setCollectError(error instanceof Error ? error.message : "Unable to collect articles.");
    } finally {
      setIsLoadingEditorial(false);
      setIsCollecting(false);
      collectionInFlight.current = false;
    }
  }, []);

  const sourceArticleCounts = useMemo(() => {
    return (collectionResult?.articles ?? []).reduce<Record<string, number>>((acc, article) => {
      acc[article.source] = (acc[article.source] ?? 0) + 1;
      return acc;
    }, {});
  }, [collectionResult]);

  const value = useMemo<DemoDataContextValue>(
    () => ({
      isDemoMode,
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
      storiesError,
      editorialError,
      isLoadingEditorial,
      sourceArticleCounts,
      selectedDraftPackage,
      setSelectedDraftPackage,
      collectNow,
    }),
    [collectNow, collectionResult, collectError, editorialError, editorialStories, isCollecting, isDemoMode, isLoadingEditorial, isLoadingSources, lastCollectedAt, selectedDraftPackage, sourceArticleCounts, sourceError, sources, stories, storiesError]
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

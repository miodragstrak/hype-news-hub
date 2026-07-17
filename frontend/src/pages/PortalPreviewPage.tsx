import { ArrowLeft, CheckCircle2, Home, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "../components/ui/button";
import { useDemoData, type EditorialDraftPackage } from "../context/DemoDataContext";
import { buildDraftPackage, PREPARED_DURING_PROCESSING } from "../lib/editorialDraft";
import { getEditorialStoryWorkspace } from "../services/newsService";
import type { StorySummary } from "../types/news";

const navItems = ["Naslovna", "Vesti", "Hype zvezde", "Showbiz", "Jet set", "Sport", "Hronika"];

function formatDate(value: string | null | undefined): string {
  const date = value ? new Date(value) : new Date();

  if (Number.isNaN(date.getTime())) {
    return new Intl.DateTimeFormat("sr-RS", { day: "2-digit", month: "long", year: "numeric" }).format(new Date());
  }

  return new Intl.DateTimeFormat("sr-RS", { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function findStoryDate(stories: StorySummary[], storyId: string | null, fallbackDate: string | null | undefined): string {
  const storyDate = stories.find((story) => story.id === storyId)?.published_at;
  return formatDate(storyDate ?? fallbackDate ?? null);
}

function splitContent(content: string): string[] {
  if (!content || content === PREPARED_DURING_PROCESSING) {
    return [PREPARED_DURING_PROCESSING];
  }

  return content
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

export function PortalPreviewPage(): JSX.Element {
  const { storyId: routeStoryId } = useParams();
  const storyId = routeStoryId ? decodeURIComponent(routeStoryId) : null;
  const { articles, editorialStories, selectedDraftPackage, setSelectedDraftPackage, stories } = useDemoData();
  const [loadedPackage, setLoadedPackage] = useState<EditorialDraftPackage | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const activePackage = selectedDraftPackage?.storyId === storyId ? selectedDraftPackage : loadedPackage?.storyId === storyId ? loadedPackage : null;

  useEffect(() => {
    if (!storyId || selectedDraftPackage?.storyId === storyId) {
      return;
    }

    let active = true;
    setIsLoading(true);
    setLoadError(null);

    void getEditorialStoryWorkspace(storyId)
      .then((workspace) => {
        if (!active) {
          return;
        }

        const packageData = buildDraftPackage(workspace);
        setLoadedPackage(packageData);
        setSelectedDraftPackage(packageData);
      })
      .catch((error) => {
        if (!active) {
          return;
        }

        setLoadedPackage(null);
        setLoadError(error instanceof Error ? error.message : "Unable to load the portal preview.");
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [selectedDraftPackage, setSelectedDraftPackage, storyId]);

  const latestStories = useMemo(() => {
    return [...editorialStories, ...stories]
      .filter((story, index, list) => story.id !== storyId && list.findIndex((entry) => entry.id === story.id) === index)
      .slice(0, 4);
  }, [editorialStories, stories, storyId]);

  const relatedStories = useMemo(() => latestStories.slice(0, 3), [latestStories]);

  const sourceArticle = articles.find((article) => article.raw?.story_id === storyId || article.external_id.includes(storyId ?? ""));
  const articleDate = findStoryDate(stories, storyId, sourceArticle?.published_at);
  const imageSrc = activePackage?.featuredImage ?? sourceArticle?.featured_image ?? null;
  const contentParagraphs = splitContent(activePackage?.mainContent ?? "");

  if (!storyId) {
    return <PortalEmptyState title="No story selected" message="Return to the newsroom and choose an editorial story before opening the portal preview." />;
  }

  if (isLoading) {
    return <PortalEmptyState title="Loading portal preview" message="Preparing the selected story preview..." />;
  }

  if (!activePackage) {
    return (
      <PortalEmptyState
        title="Portal preview unavailable"
        message={loadError || "The selected story could not be loaded. Return to the newsroom and select the story again."}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#f3f6fb] text-[#07173d]">
      <PortalHeader />

      <main className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:px-8">
        <article className="min-w-0 overflow-hidden bg-white shadow-[0_20px_55px_-42px_rgba(7,23,61,0.75)]">
          <div className="border-b border-[#dbe5f3] px-5 py-5 sm:px-8">
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex rounded-sm bg-[#f5c518] px-3 py-1 text-xs font-extrabold uppercase text-[#07173d]">Editorial Preview</span>
              <p className="text-sm font-semibold text-[#42618e]">This article has not been published. This page shows how it may appear on the Hype portal after editorial approval.</p>
            </div>
          </div>

          <div className="px-5 py-7 sm:px-8 lg:px-11 lg:py-10">
            <p className="text-sm font-bold uppercase text-[#456693]">{articleDate}</p>
            <h1 className="mt-3 break-words text-4xl font-extrabold leading-tight text-[#07173d] sm:text-5xl lg:text-[56px]">
              {activePackage.headline}
            </h1>
            <p className="mt-4 text-lg font-semibold leading-8 text-[#24466f]">{activePackage.excerpt}</p>
            <p className="mt-4 text-sm font-bold text-[#42618e]">Autor: Hype redakcija</p>
          </div>

          <div className="relative">
            <ArticleImage src={imageSrc} headline={activePackage.headline} />
            <span className="absolute left-5 top-5 rounded-sm bg-[#f5c518] px-3 py-2 text-xs font-extrabold uppercase text-[#07173d] sm:left-8">
              {activePackage.category}
            </span>
          </div>

          <div className="px-5 py-8 sm:px-8 lg:px-11">
            <div className="space-y-6 text-lg leading-9 text-[#112e58]">
              {contentParagraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>

            <div className="mt-9 border-t border-[#dbe5f3] pt-6">
              <p className="text-sm font-extrabold uppercase text-[#07173d]">Izvori</p>
              <div className="mt-3 grid gap-2">
                {activePackage.sourcesUsed.length > 0 ? (
                  activePackage.sourcesUsed.map((source) => (
                    <a key={source.id} href={source.url} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-[#1b4f93] hover:text-[#07173d]">
                      {source.sourceName}: {source.originalHeadline}
                    </a>
                  ))
                ) : (
                  <p className="text-sm text-[#42618e]">Source attribution will be prepared during editorial processing.</p>
                )}
              </div>
            </div>

            <div className="mt-7 flex flex-wrap gap-2">
              {activePackage.tags.map((tag) => (
                <span key={tag} className="rounded-sm border border-[#c7d4e6] px-3 py-2 text-xs font-bold uppercase text-[#24466f]">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </article>

        <aside className="space-y-6 lg:sticky lg:top-6 lg:self-start">
          <SidebarStories title="Najnovije" stories={latestStories} />
        </aside>
      </main>

      <section className="mx-auto w-full max-w-7xl px-4 pb-10 sm:px-6 lg:px-8">
        <RelatedStories stories={relatedStories} />
        <WorkflowCompletePanel storyId={storyId} />
      </section>
    </div>
  );
}

function PortalHeader(): JSX.Element {
  return (
    <header className="bg-[#07173d] text-white">
      <div className="mx-auto flex max-w-7xl flex-col items-center gap-4 px-4 py-5 sm:px-6 lg:px-8">
        <div className="flex w-full flex-col items-center gap-3 sm:flex-row sm:justify-between">
          <p className="text-sm font-semibold text-[#d6e3ff]">{formatDate(new Date().toISOString())}</p>
          <img src="/hype-logo.png" alt="Hype logo" className="h-20 w-auto object-contain sm:h-24" />
          <div className="inline-flex items-center gap-2 text-sm font-bold uppercase text-white">
            <Search className="h-4 w-4 text-[#f5c518]" />
            Search
          </div>
        </div>

        <nav className="w-full overflow-x-auto border-t border-white/15 pt-4">
          <div className="mx-auto flex min-w-max justify-center gap-5 text-sm font-extrabold uppercase text-white sm:gap-7">
            {navItems.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </nav>
      </div>
    </header>
  );
}

function ArticleImage({ src, headline }: { src: string | null; headline: string }): JSX.Element {
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    setHasFailed(false);
  }, [src]);

  if (!src || hasFailed) {
    return (
      <div className="flex aspect-[16/9] min-h-64 w-full items-center justify-center bg-[#07173d] px-6 text-center">
        <div>
          <img src="/hype-logo.png" alt="" className="mx-auto h-16 w-auto object-contain" />
          <p className="mt-4 text-sm font-extrabold uppercase text-[#f5c518]">Hype portal preview</p>
        </div>
      </div>
    );
  }

  return <img src={src} alt={headline} className="aspect-[16/9] w-full object-cover" onError={() => setHasFailed(true)} />;
}

function SidebarStories({ title, stories }: { title: string; stories: StorySummary[] }): JSX.Element {
  return (
    <section className="bg-white p-5 shadow-[0_16px_45px_-40px_rgba(7,23,61,0.75)]">
      <h2 className="border-b-4 border-[#f5c518] pb-3 text-2xl font-extrabold text-[#07173d]">{title}</h2>
      <div className="mt-5 space-y-4">
        {stories.length > 0 ? (
          stories.map((story) => <StoryTeaser key={story.id} story={story} compact />)
        ) : (
          <p className="text-sm font-semibold text-[#42618e]">No additional stories are available in the current preview state.</p>
        )}
      </div>
    </section>
  );
}

function RelatedStories({ stories }: { stories: StorySummary[] }): JSX.Element {
  return (
    <section className="bg-white p-5 sm:p-7">
      <h2 className="border-b-4 border-[#f5c518] pb-3 text-3xl font-extrabold text-[#07173d]">Povezane vesti</h2>
      <div className="mt-6 grid gap-5 md:grid-cols-3">
        {stories.length > 0 ? (
          stories.map((story) => <StoryTeaser key={story.id} story={story} />)
        ) : (
          <p className="text-sm font-semibold text-[#42618e]">Related stories will appear when more stories are available.</p>
        )}
      </div>
    </section>
  );
}

function StoryTeaser({ story, compact = false }: { story: StorySummary; compact?: boolean }): JSX.Element {
  return (
    <div className={compact ? "grid grid-cols-[76px_1fr] gap-3" : "space-y-3"}>
      <div className={`${compact ? "h-16" : "h-36"} flex items-center justify-center bg-[#07173d]`}>
        <span className="text-xs font-extrabold uppercase text-[#f5c518]">Hype</span>
      </div>
      <div className="min-w-0">
        <p className="text-xs font-bold uppercase text-[#42618e]">{formatDate(story.published_at)}</p>
        <h3 className={`${compact ? "text-sm leading-5" : "text-lg leading-6"} mt-1 break-words font-extrabold text-[#07173d]`}>
          {story.headline}
        </h3>
      </div>
    </div>
  );
}

function WorkflowCompletePanel({ storyId }: { storyId: string }): JSX.Element {
  const steps = ["Sources collected", "Related stories merged", "Editorial draft prepared", "Publishing package ready", "Portal preview generated"];

  return (
    <section className="mt-8 bg-[#07173d] p-5 text-white sm:p-7">
      <h2 className="text-3xl font-extrabold">Editorial Workflow Complete</h2>
      <div className="mt-5 grid gap-3 md:grid-cols-5">
        {steps.map((step) => (
          <div key={step} className="flex items-center gap-2 border border-white/15 bg-[#0b2a67] p-3 text-sm font-bold">
            <CheckCircle2 className="h-5 w-5 shrink-0 text-[#f5c518]" />
            <span>{step}</span>
          </div>
        ))}
      </div>
      <p className="mt-6 text-sm font-bold uppercase text-[#f5c518]">Next milestone:</p>
      <p className="mt-1 text-xl font-extrabold">WordPress Draft Integration</p>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <Button asChild size="lg">
          <Link to="/publish">
            <ArrowLeft className="mr-2 h-5 w-5" />
            Back to Publishing Package
          </Link>
        </Button>
        <Button asChild size="lg" variant="secondary">
          <Link to="/review">
            <Home className="mr-2 h-5 w-5" />
            Return to Newsroom
          </Link>
        </Button>
      </div>
      <p className="mt-4 text-xs font-semibold text-[#c2d3f5]">Preview route: /portal-preview/{storyId}</p>
    </section>
  );
}

function PortalEmptyState({ title, message }: { title: string; message: string }): JSX.Element {
  return (
    <div className="min-h-screen bg-[#f3f6fb] text-[#07173d]">
      <PortalHeader />
      <main className="mx-auto flex min-h-[55vh] w-full max-w-3xl items-center px-4 py-10 sm:px-6">
        <section className="w-full bg-white p-7 text-center shadow-[0_20px_55px_-42px_rgba(7,23,61,0.75)]">
          <p className="mx-auto inline-flex rounded-sm bg-[#f5c518] px-3 py-1 text-xs font-extrabold uppercase text-[#07173d]">Editorial Preview</p>
          <h1 className="mt-5 text-3xl font-extrabold text-[#07173d]">{title}</h1>
          <p className="mt-3 text-base font-semibold leading-7 text-[#42618e]">{message}</p>
          <div className="mt-6 flex justify-center">
            <Button asChild size="lg">
              <Link to="/review">Return to Newsroom</Link>
            </Button>
          </div>
        </section>
      </main>
    </div>
  );
}

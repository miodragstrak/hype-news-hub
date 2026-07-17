import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, Circle, CircleDot, ExternalLink, ImageIcon, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { NextStepPanel } from "../components/NextStepPanel";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { buildDraftPackage, flagLabel, languageLabel, PREPARED_DURING_PROCESSING } from "../lib/editorialDraft";
import { getEditorialStoryWorkspace } from "../services/newsService";
import type { EditorialStoryWorkspace, SourceArticle } from "../types/news";

const timeline = [
  { label: "Articles Collected", state: "complete" },
  { label: "Content Normalized", state: "complete" },
  { label: "Related Sources Merged", state: "complete" },
  { label: "Editorially Scored", state: "complete" },
  { label: "Editorial Draft Prepared", state: "current" },
  { label: "Human Approval", state: "future" },
  { label: "WordPress Draft", state: "future" }
] as const;

export function ReviewPage(): JSX.Element {
  const { storyId: routeStoryId } = useParams();
  const navigate = useNavigate();
  const { setSelectedDraftPackage } = useDemoData();
  const storyId = routeStoryId ? decodeURIComponent(routeStoryId) : null;

  const [workspace, setWorkspace] = useState<EditorialStoryWorkspace | null>(null);
  const [selectedArticleId, setSelectedArticleId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!storyId) {
      return;
    }

    let active = true;
    setIsLoading(true);
    setError(null);

    void getEditorialStoryWorkspace(storyId)
      .then((response) => {
        if (!active) {
          return;
        }

        setWorkspace(response);
        setSelectedArticleId(response.source_articles[0]?.external_id ?? null);
      })
      .catch((fetchError) => {
        if (!active) {
          return;
        }

        setError(fetchError instanceof Error ? fetchError.message : "Unable to load editorial story workspace.");
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [storyId]);

  const draftPackage = useMemo(() => (workspace ? buildDraftPackage(workspace) : null), [workspace]);
  const selectedArticle = workspace?.source_articles.find((article) => article.external_id === selectedArticleId) ?? workspace?.source_articles[0] ?? null;

  if (!storyId) {
    return <Navigate to="/review" replace />;
  }

  const continueToPublishing = (): void => {
    if (!draftPackage) {
      return;
    }

    setSelectedDraftPackage(draftPackage);
    navigate("/publish");
  };

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-4xl font-bold tracking-tight text-white">Editorial Story Workspace</h2>
          <p className="mt-2 text-sm text-[#c2d3f5]">Review source material, inspect the editorial draft package, then continue to publishing preview.</p>
        </div>
        <Link to="/review" className="text-sm font-semibold text-[#d6e3ff] hover:text-white">
          Back to Queue
        </Link>
      </div>

      {isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 p-8 text-[#dbe6ff]">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading editorial story workspace...
          </CardContent>
        </Card>
      ) : null}

      {error ? (
        <Card className="border-rose-400/40 bg-rose-500/10">
          <CardContent className="flex items-center gap-3 p-6 text-rose-100">
            <AlertCircle className="h-5 w-5" />
            {error}
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !error && workspace && draftPackage ? (
        <>
          <Card className="border-[#f5c518]/45 bg-[#0a285f]">
            <CardContent className="grid gap-5 p-6 xl:grid-cols-[minmax(0,1fr)_420px]">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Badge variant="warning">Editorial Draft</Badge>
                  <Badge variant="muted">Status: Ready for Human Editing</Badge>
                  <Badge variant="muted">Target Language: Serbian</Badge>
                </div>
                <h3 className="break-words text-3xl font-bold leading-tight text-white">{draftPackage.headline}</h3>
                <div className="rounded-2xl border border-[#f5c518]/35 bg-[#f5c518]/10 p-4">
                  <p className="text-lg font-bold text-white">Nothing is published automatically.</p>
                  <p className="mt-1 text-sm font-semibold text-[#f9edb8]">Human editorial approval is always required.</p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                {[
                  { label: "Sources", value: workspace.source_count },
                  { label: "Editorial importance", value: workspace.editorial_intelligence.importance_score },
                  { label: "Confidence", value: `${workspace.editorial_intelligence.confidence_score}%` }
                ].map((metric) => (
                  <div key={metric.label} className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">{metric.label}</p>
                    <p className="mt-2 text-2xl font-bold text-white">{metric.value}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-2xl text-white">Editorial Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
                {timeline.map((step) => (
                  <div
                    key={step.label}
                    className={`rounded-2xl border p-4 ${
                      step.state === "complete"
                        ? "border-emerald-400/35 bg-emerald-500/12 text-emerald-50"
                        : step.state === "current"
                        ? "border-[#f5c518] bg-[#f5c518] text-[#07173d]"
                        : "border-white/20 bg-[#08245a] text-[#dbe6ff]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {step.state === "complete" ? <CheckCircle2 className="h-5 w-5" /> : step.state === "current" ? <CircleDot className="h-5 w-5" /> : <Circle className="h-5 w-5" />}
                      <p className="text-sm font-semibold">{step.label}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
            <Card>
              <CardHeader>
                <CardTitle className="text-2xl text-white">Editorial Draft</CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <article className="overflow-hidden rounded-2xl border border-white/20 bg-[#08245a]">
                  <div className="p-5 sm:p-7">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="warning">Ready for Human Editing</Badge>
                      <Badge variant="muted">Central Hype WordPress Portal</Badge>
                    </div>
                    <h1 className="mt-4 break-words text-4xl font-extrabold leading-tight text-white">{draftPackage.headline}</h1>
                    <p className="mt-4 text-lg leading-8 text-[#dbe6ff]">{draftPackage.excerpt}</p>
                  </div>

                  <FeaturedImagePreview src={draftPackage.featuredImage} />

                  <div className="space-y-5 p-5 sm:p-7">
                    <DraftField label="Headline" value={draftPackage.headline} />
                    <DraftField label="Excerpt" value={draftPackage.excerpt} />
                    <DraftField label="Main article content" value={draftPackage.mainContent} prominent />
                    <DraftField label="Categories" value={draftPackage.categories.join(", ")} />
                    <DraftField label="Tags" value={draftPackage.tags.join(", ")} />
                    <DraftField label="Slug" value={draftPackage.slug} />
                    <DraftField label="SEO title" value={draftPackage.seoTitle} />
                    <DraftField label="SEO description" value={draftPackage.seoDescription} />

                    <div className="rounded-2xl border border-white/20 bg-[#0a285f] p-5">
                      <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">
                        <ShieldCheck className="h-4 w-4" />
                        Source attribution
                      </p>
                      <p className="mt-3 text-sm leading-7 text-[#eef4ff]">
                        Prepared from {workspace.source_count} original source article{workspace.source_count === 1 ? "" : "s"}. Original language material remains available below for human verification.
                      </p>
                    </div>
                  </div>
                </article>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="text-2xl text-white">Sources Used</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {draftPackage.sourcesUsed.length > 0 ? (
                    draftPackage.sourcesUsed.map((source) => (
                      <div key={source.id} className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-lg font-semibold text-white">{source.countryFlag} {source.sourceName}</p>
                            <p className="mt-1 text-sm text-[#c2d3f5]">Original Language: {source.originalLanguage}</p>
                          </div>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-[#eef4ff]">{source.originalHeadline}</p>
                        <a href={source.url} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex items-center gap-2 rounded-full border border-[#f5c518] px-4 py-2 text-sm font-semibold text-[#f5c518] transition-colors hover:bg-[#f5c518] hover:text-[#07173d]">
                          Open Original Article
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-5 text-sm text-amber-50">
                      Source attribution will be prepared during editorial processing.
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-2xl text-white">Original Source Detail</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3">
                    {workspace.source_articles.map((article) => {
                      const isSelected = article.external_id === selectedArticle?.external_id;
                      return (
                        <button
                          key={article.external_id}
                          type="button"
                          onClick={() => setSelectedArticleId(article.external_id)}
                          className={`rounded-2xl border p-4 text-left transition ${
                            isSelected ? "border-[#f5c518] bg-[#12357a]" : "border-white/20 bg-[#08245a] hover:border-white/35"
                          }`}
                        >
                          <p className="text-lg font-semibold text-white">{flagLabel(article.country)} {article.source}</p>
                          <p className="mt-1 text-sm text-[#c2d3f5]">{languageLabel(article.language)}</p>
                          <p className="mt-3 line-clamp-2 text-sm leading-6 text-[#dbe6ff]">{article.title}</p>
                        </button>
                      );
                    })}
                  </div>

                  {selectedArticle ? <SourceArticleDetail article={selectedArticle} /> : null}
                </CardContent>
              </Card>
            </div>
          </div>

          <NextStepPanel
            message="Review the editorial draft package and continue to preview the exact WordPress draft payload."
            ctaLabel="Continue to Publishing Preview"
            onAction={continueToPublishing}
          />
        </>
      ) : null}
    </section>
  );
}

function DraftField({ label, value, prominent = false }: { label: string; value: string; prominent?: boolean }): JSX.Element {
  return (
    <div className="rounded-2xl border border-white/20 bg-[#0a285f] p-5">
      <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">{label}</p>
      <p className={`mt-3 whitespace-pre-line break-words leading-7 text-[#eef4ff] ${prominent ? "text-base" : "text-sm"}`}>{value || PREPARED_DURING_PROCESSING}</p>
    </div>
  );
}

function SourceArticleDetail({ article }: { article: SourceArticle }): JSX.Element {
  return (
    <div className="space-y-4 rounded-2xl border border-white/20 bg-[#08245a] p-5">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant="muted">{flagLabel(article.country)} {article.source}</Badge>
        <Badge variant="muted">Original Language: {languageLabel(article.language)}</Badge>
      </div>

      <SourceImage src={article.featured_image} title={article.title} />

      <div>
        <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Original Headline</p>
        <h4 className="mt-2 text-xl font-semibold text-white">{article.title || PREPARED_DURING_PROCESSING}</h4>
      </div>

      <div>
        <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Original Excerpt</p>
        <p className="mt-2 text-sm leading-7 text-[#dbe6ff]">{article.excerpt || "Original excerpt is unavailable."}</p>
      </div>

      <a href={article.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-full border border-[#f5c518] px-4 py-2 text-sm font-semibold text-[#f5c518] transition-colors hover:bg-[#f5c518] hover:text-[#07173d]">
        Open Original Article
        <ExternalLink className="h-4 w-4" />
      </a>
    </div>
  );
}

function FeaturedImagePreview({ src }: { src: string | null }): JSX.Element {
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    setHasFailed(false);
  }, [src]);

  if (!src || hasFailed) {
    return (
      <div className="flex min-h-64 items-center justify-center border-y border-white/20 bg-[#0a285f] px-5 py-10 text-center">
        <div>
          <ImageIcon className="mx-auto h-8 w-8 text-[#f5c518]" />
          <p className="mt-3 font-semibold text-white">Featured image</p>
          <p className="mt-2 text-sm text-[#c2d3f5]">{PREPARED_DURING_PROCESSING}</p>
        </div>
      </div>
    );
  }

  return <img src={src} alt="" className="max-h-[420px] w-full object-cover" onError={() => setHasFailed(true)} />;
}

function SourceImage({ src, title }: { src: string | null; title: string }): JSX.Element {
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    setHasFailed(false);
  }, [src]);

  if (!src || hasFailed) {
    return (
      <div className="flex min-h-32 items-center justify-center rounded-2xl border border-white/20 bg-[#0a285f] px-5 py-8 text-center">
        <p className="text-sm text-[#dbe6ff]">Original source image unavailable.</p>
      </div>
    );
  }

  return <img src={src} alt={title} className="h-48 w-full rounded-2xl object-cover" onError={() => setHasFailed(true)} />;
}

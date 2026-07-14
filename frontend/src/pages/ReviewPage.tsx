import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, ExternalLink, Languages, Loader2, Pencil, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { NextStepPanel } from "../components/NextStepPanel";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { generateDemoEditorialStoryDraft, getEditorialStoryWorkspace } from "../services/newsService";
import type { EditorialStoryWorkspace, SourceArticle } from "../types/news";

const languageLabels: Record<string, string> = {
  sr: "Serbian",
  hr: "Croatian",
  bs: "Bosnian",
  sl: "Slovenian",
  mk: "Macedonian",
};

const countryFlags: Record<string, string> = {
  RS: "🇷🇸",
  HR: "🇭🇷",
  BA: "🇧🇦",
  SI: "🇸🇮",
  MK: "🇲🇰",
};

const statusLabels: Record<EditorialStoryWorkspace["status"], string> = {
  needs_generation: "Needs Generation",
  draft_ready: "Draft Ready",
  in_review: "In Review",
  approved: "Approved",
  rejected: "Rejected",
  ready_for_publishing: "Ready for Publishing",
  published: "Published",
};

function formatDate(value: string | null): string {
  if (!value) {
    return "Date unavailable";
  }

  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function languageLabel(language: string | null): string {
  if (!language) {
    return "Unknown";
  }

  return languageLabels[language] ?? language.toUpperCase();
}

function flagLabel(country: string): string {
  return countryFlags[country] ?? "🌍";
}

export function ReviewPage(): JSX.Element {
  const { storyId: routeStoryId } = useParams();
  const storyId = routeStoryId ? decodeURIComponent(routeStoryId) : null;

  const [workspace, setWorkspace] = useState<EditorialStoryWorkspace | null>(null);
  const [selectedArticleId, setSelectedArticleId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workspaceStatus, setWorkspaceStatus] = useState<EditorialStoryWorkspace["status"] | null>(null);
  const [draftHeadline, setDraftHeadline] = useState("");
  const [draftExcerpt, setDraftExcerpt] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);

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
        setWorkspaceStatus(response.status);
        setSelectedArticleId(response.source_articles[0]?.external_id ?? null);
        setDraftHeadline(response.serbian_draft.headline ?? "");
        setDraftExcerpt(response.serbian_draft.excerpt ?? "");
        setDraftContent(response.serbian_draft.content ?? "");
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

  if (!storyId) {
    return <Navigate to="/review" replace />;
  }

  const selectedArticle = workspace?.source_articles.find((article) => article.external_id === selectedArticleId) ?? workspace?.source_articles[0] ?? null;
  const effectiveStatus = workspaceStatus ?? workspace?.status ?? "needs_generation";
  const hasDraft = workspace?.serbian_draft.status !== "not_generated";

  const applyWorkspace = (response: EditorialStoryWorkspace): void => {
    setWorkspace(response);
    setWorkspaceStatus(response.status);
    setSelectedArticleId((current) => current ?? response.source_articles[0]?.external_id ?? null);
    setDraftHeadline(response.serbian_draft.headline ?? "");
    setDraftExcerpt(response.serbian_draft.excerpt ?? "");
    setDraftContent(response.serbian_draft.content ?? "");
  };

  const handleGenerateDraft = async (): Promise<void> => {
    if (!storyId) {
      return;
    }

    setIsGenerating(true);
    setError(null);
    try {
      const response = await generateDemoEditorialStoryDraft(storyId);
      applyWorkspace(response);
      setIsEditing(false);
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : "Unable to generate demo draft.");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = (): void => {
    setWorkspaceStatus("approved");
    setIsEditing(false);
  };

  const handleReject = (): void => {
    if (!window.confirm("Reject this draft from the editorial workflow?")) {
      return;
    }

    setWorkspaceStatus("rejected");
    setIsEditing(false);
  };

  const handleSaveEdits = (): void => {
    setIsEditing(false);
    setWorkspaceStatus("in_review");
  };

  const nextAction = !hasDraft
    ? { label: "Generate Demo Serbian Draft", to: undefined, onAction: () => void handleGenerateDraft(), disabled: isGenerating }
    : effectiveStatus === "approved"
    ? { label: "Continue to Publishing", to: "/publish", onAction: undefined, disabled: false }
    : { label: "Review and Approve Draft", to: undefined, onAction: () => handleApprove(), disabled: false };

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-4xl font-bold tracking-tight text-white">Editorial Story Workspace</h2>
          <p className="mt-2 text-sm text-[#c2d3f5]">Multiple regional sources → one unified Serbian editorial story → human review → publishing.</p>
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

      {!isLoading && !error && workspace ? (
        <>
          <Card className="border-[#f5c518]/35 bg-[#0a285f]">
            <CardContent className="space-y-5 p-6">
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.9fr)]">
                <div className="min-w-0 space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant={effectiveStatus === "approved" ? "success" : "warning"}>{statusLabels[effectiveStatus]}</Badge>
                    <Badge variant="muted">Target Language: Serbian</Badge>
                    {hasDraft ? <Badge variant="warning">Demo Draft</Badge> : null}
                  </div>
                  <h3 className="break-words text-3xl font-bold leading-tight text-white">{workspace.headline}</h3>
                  <p className="text-sm text-[#d6e3ff]">Nothing is published without human editorial approval.</p>
                </div>

                <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
                  {[
                    { label: "Coverage", value: workspace.editorial_intelligence.coverage },
                    { label: "Importance", value: `${workspace.editorial_intelligence.importance_score}` },
                    { label: "Confidence", value: `${workspace.editorial_intelligence.confidence_score}%` },
                    { label: "Recommended", value: workspace.editorial_intelligence.recommended_action },
                    { label: "Sources", value: `${workspace.source_count}` },
                  ].map((metric) => (
                    <div key={metric.label} className="min-w-0 rounded-2xl border border-white/20 bg-[#08245a] px-4 py-3">
                      <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">{metric.label}</p>
                      <p className="mt-1 break-words text-lg font-semibold text-white">{metric.value}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
                {workspace.processing_history.map((step, index) => (
                  <motion.div
                    key={step.key}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, delay: index * 0.03 }}
                    className={`rounded-2xl border px-4 py-3 ${
                      step.state === "completed"
                        ? "border-emerald-400/35 bg-emerald-500/12"
                        : step.state === "current"
                        ? "border-[#f5c518] bg-[#f5c518] text-[#07173d]"
                        : "border-white/20 bg-[#08245a]"
                    }`}
                  >
                    <p className={`text-xs uppercase tracking-[0.15em] ${step.state === "future" ? "text-[#b7c9ee]" : ""}`}>{step.label}</p>
                  </motion.div>
                ))}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
            <Card>
              <CardHeader>
                <CardTitle className="text-2xl text-white">Original Sources</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
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
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-lg font-semibold text-white">{flagLabel(article.country)} {article.source}</p>
                            <p className="text-sm text-[#c2d3f5]">{languageLabel(article.language)} · {formatDate(article.published_at)}</p>
                          </div>
                          <Badge variant="muted" className="shrink-0">Source</Badge>
                        </div>
                        <p className="mt-3 line-clamp-2 text-sm leading-6 text-[#dbe6ff]">{article.title}</p>
                      </button>
                    );
                  })}
                </div>

                {selectedArticle ? (
                  <SourceArticleDetail article={selectedArticle} multipleSources={workspace.source_count > 1} />
                ) : null}
              </CardContent>
            </Card>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="text-2xl text-white">Unified Serbian Story</CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  {!hasDraft ? (
                    <div className="space-y-4 rounded-2xl border border-white/20 bg-[#08245a] p-5">
                      <div className="flex flex-wrap items-center gap-3">
                        <Badge variant="muted">Status: Not Generated</Badge>
                        <Badge variant="muted">Target Language: Serbian</Badge>
                      </div>
                      <p className="text-sm leading-7 text-[#dbe6ff]">
                        A single Serbian editorial version will be prepared from all verified regional sources.
                      </p>
                      <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-50">
                        Demo behavior only. This does not use AI and it does not perform real translation.
                      </div>
                      <Button size="lg" onClick={() => void handleGenerateDraft()} disabled={isGenerating}>
                        {isGenerating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Languages className="mr-2 h-4 w-4" />}
                        Generate Demo Serbian Draft
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-center gap-3">
                        <Badge variant="warning">Demo Draft</Badge>
                        <Badge variant={effectiveStatus === "approved" ? "success" : "muted"}>{statusLabels[effectiveStatus]}</Badge>
                      </div>

                      <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
                        <p className="text-xs uppercase tracking-[0.18em] text-[#b7c9ee]">Draft Headline</p>
                        {isEditing ? (
                          <textarea value={draftHeadline} onChange={(event) => setDraftHeadline(event.target.value)} className="mt-2 min-h-20 w-full rounded-xl border border-white/20 bg-[#061a44] px-4 py-3 text-white" />
                        ) : (
                          <p className="mt-2 text-2xl font-semibold text-white">{draftHeadline}</p>
                        )}
                      </div>

                      <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
                        <p className="text-xs uppercase tracking-[0.18em] text-[#b7c9ee]">Draft Excerpt</p>
                        {isEditing ? (
                          <textarea value={draftExcerpt} onChange={(event) => setDraftExcerpt(event.target.value)} className="mt-2 min-h-24 w-full rounded-xl border border-white/20 bg-[#061a44] px-4 py-3 text-white" />
                        ) : (
                          <p className="mt-2 text-sm leading-7 text-[#dbe6ff]">{draftExcerpt}</p>
                        )}
                      </div>

                      <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
                        <p className="text-xs uppercase tracking-[0.18em] text-[#b7c9ee]">Draft Content</p>
                        {isEditing ? (
                          <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} className="mt-2 min-h-48 w-full rounded-xl border border-white/20 bg-[#061a44] px-4 py-3 text-white" />
                        ) : (
                          <p className="mt-2 whitespace-pre-line text-sm leading-7 text-[#dbe6ff]">{draftContent}</p>
                        )}
                      </div>

                      <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-50">
                        Demo Draft: clearly marked placeholder content showing where a future unified Serbian article will appear. It is not a real AI translation.
                      </div>

                      <div className="flex flex-wrap gap-3">
                        {isEditing ? (
                          <Button onClick={handleSaveEdits}>Save Draft Changes</Button>
                        ) : (
                          <Button variant="secondary" onClick={() => setIsEditing(true)}>
                            <Pencil className="mr-2 h-4 w-4" />
                            Edit
                          </Button>
                        )}
                        <Button onClick={handleApprove}>
                          <CheckCircle2 className="mr-2 h-4 w-4" />
                          Approve
                        </Button>
                        <Button variant="accent" onClick={handleReject}>
                          <XCircle className="mr-2 h-4 w-4" />
                          Reject
                        </Button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-2xl text-white">Why This Story Matters</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Recommended Action</p>
                    <p className="mt-2 font-semibold text-white">{workspace.editorial_intelligence.recommended_action}</p>
                  </div>
                  <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Risk Level</p>
                    <p className="mt-2 font-semibold text-white">{workspace.editorial_intelligence.risk_level}</p>
                  </div>
                  <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Regional Coverage</p>
                    <p className="mt-2 font-semibold text-white">{workspace.editorial_intelligence.coverage}</p>
                  </div>
                  <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Confidence</p>
                    <p className="mt-2 font-semibold text-white">{workspace.editorial_intelligence.confidence_score}%</p>
                  </div>
                  <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4 sm:col-span-2">
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Editorial Reason</p>
                    <p className="mt-2 text-sm leading-7 text-[#dbe6ff]">{workspace.editorial_intelligence.reason}</p>
                    <div className="mt-4 flex flex-wrap gap-3 text-sm text-[#d6e3ff]">
                      <span className="inline-flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-300" />{workspace.source_count} sources</span>
                      <span className="inline-flex items-center gap-2"><Sparkles className="h-4 w-4 text-[#f5c518]" />{workspace.source_languages.join(", ") || "Unknown languages"}</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>

          <NextStepPanel
            message={
              !hasDraft
                ? "Generate a clearly marked demo Serbian draft to preview the future unified editorial story from these verified sources."
                : effectiveStatus === "approved"
                ? "Draft is approved. Continue to publishing to preview the package before any live integration is used."
                : "Review the demo draft, refine it if needed, and approve it when the editorial version is ready for publishing review."
            }
            ctaLabel={nextAction.label}
            ctaTo={nextAction.to}
            onAction={nextAction.onAction}
            disabled={nextAction.disabled}
          />
        </>
      ) : null}
    </section>
  );
}

type SourceArticleDetailProps = {
  article: SourceArticle;
  multipleSources: boolean;
};

function SourceArticleDetail({ article, multipleSources }: SourceArticleDetailProps): JSX.Element {
  return (
    <div className="space-y-4 rounded-2xl border border-white/20 bg-[#08245a] p-5">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant="muted">{flagLabel(article.country)} {article.source}</Badge>
        <Badge variant="muted">{languageLabel(article.language)}</Badge>
        {multipleSources ? <Badge variant="warning">Merged Story Coverage</Badge> : null}
      </div>

      <SourceArticleImage src={article.featured_image} title={article.title} />

      <div>
        <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Original Headline</p>
        <h4 className="mt-2 text-2xl font-semibold text-white">{article.title}</h4>
      </div>

      <div>
        <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Excerpt</p>
        <p className="mt-2 text-sm leading-7 text-[#dbe6ff]">{article.excerpt || "No excerpt available."}</p>
      </div>

      <div>
        <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Original Content</p>
        <p className="mt-2 text-sm leading-7 text-[#dbe6ff]">{article.content ?? "Content unavailable."}</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {article.categories.map((category) => (
          <Badge key={category} variant="default">
            {category}
          </Badge>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[#c2d3f5]">Published {formatDate(article.published_at)}</p>
        <a href={article.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-full border border-[#f5c518] px-4 py-2 text-sm font-semibold text-[#f5c518] transition-colors hover:bg-[#f5c518] hover:text-[#07173d]">
          Open Original Article
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>
    </div>
  );
}

type SourceArticleImageProps = {
  src: string | null;
  title: string;
};

function SourceArticleImage({ src, title }: SourceArticleImageProps): JSX.Element {
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    setHasFailed(false);
  }, [src]);

  if (!src || hasFailed) {
    return (
      <div className="flex min-h-36 items-center justify-center rounded-2xl border border-white/20 bg-[#0a285f] px-5 py-8 text-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#f5c518]">Hype World News</p>
          <p className="mt-2 text-sm text-[#dbe6ff]">Original source image unavailable.</p>
        </div>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={title}
      className="h-56 w-full rounded-2xl object-cover"
      onError={() => setHasFailed(true)}
    />
  );
}

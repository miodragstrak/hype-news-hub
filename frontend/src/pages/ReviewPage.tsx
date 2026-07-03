import { Link, Navigate, useParams } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

function formatDate(value: string | null): string {
  if (!value) {
    return "Date unavailable";
  }

  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

export function ReviewPage(): JSX.Element {
  const { articleId } = useParams();
  const { articles, stories } = useDemoData();

  if (articles.length === 0 && stories.length === 0) {
    return <Navigate to="/review" replace />;
  }

  const targetId = articleId ? decodeURIComponent(articleId) : (stories[0]?.id ?? articles[0].external_id);
  const article = articles.find((entry) => entry.external_id === targetId) ?? null;
  const story = stories.find((entry) => entry.id === targetId) ?? null;

  const fallbackArticle = article ?? articles[0] ?? null;
  const fallbackStory = story ?? stories[0] ?? null;

  const headline = fallbackArticle?.title ?? fallbackStory?.headline;
  const sourceLabel = fallbackArticle?.source ?? (fallbackStory?.sources[0] ?? "Story");
  const publishedAt = fallbackArticle?.published_at ?? fallbackStory?.published_at ?? null;
  const sourceText = fallbackArticle?.excerpt || fallbackArticle?.content || "Story-level editorial context is available. Review details and proceed to approve, edit, or reject.";
  const sourceUrl = fallbackArticle?.url;

  if (!headline) {
    return <Navigate to="/review" replace />;
  }

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-4xl font-bold tracking-tight">Editorial Review</h2>
        <Link to="/review" className="text-sm font-semibold text-[#0b1f4d] hover:text-[#34518f]">
          Back to Queue
        </Link>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="rounded-[26px]">
          <CardHeader>
            <CardTitle className="text-3xl">Original Article</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Badge variant="muted">{sourceLabel}</Badge>
              <h3 className="text-3xl font-semibold leading-tight">{headline}</h3>
              <p className="text-sm text-[#5a72a3]">{formatDate(publishedAt)}</p>
            </div>
            <p className="leading-8 text-[#233c6f]">{sourceText}</p>
            {sourceUrl ? (
              <a href={sourceUrl} target="_blank" rel="noreferrer" className="inline-flex text-sm font-semibold text-[#0b1f4d] hover:text-[#34518f]">
                Open source article
              </a>
            ) : null}
          </CardContent>
        </Card>

        <Card className="rounded-[26px] border-[#f5c518]/55 bg-gradient-to-b from-white to-[#f5f8fd]">
          <CardHeader>
            <CardTitle className="text-3xl">AI Rewritten Version</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="rounded-2xl border border-dashed border-[#bfd0e9] bg-white p-5 leading-7 text-[#233c6f]">
              Placeholder: AI-enhanced, executive-ready rewrite with tightened narrative, localized context, and TV-ready hooks.
            </p>

            <div className="rounded-2xl border border-[#d8e1ef] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#5a72a3]">AI Actions</p>
              <div className="mt-3 grid gap-2 text-sm">
                {[
                  "Translation",
                  "Rewrite",
                  "SEO Title",
                  "Categories"
                ].map((action) => (
                  <p key={action} className="inline-flex items-center gap-2 font-medium text-emerald-700">
                    <CheckCircle2 className="h-4 w-4" />
                    {action}
                  </p>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap gap-3 pt-2">
              <Button variant="default">Approve</Button>
              <Button variant="secondary">Edit</Button>
              <Button variant="accent">Reject</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

import { motion } from "framer-motion";
import { ArrowRight, Gauge, Globe2, Hash, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

function getCountryFlag(source: string): string {
  if (source.includes("Serbia")) return "🇷🇸";
  if (source.includes("Croatia")) return "🇭🇷";
  if (source.includes("Bosnia") || source.includes("BiH")) return "🇧🇦";
  if (source.includes("Slovenia")) return "🇸🇮";
  if (source.includes("Macedonia")) return "🇲🇰";
  return "🇷🇸";
}

function getFlagCluster(sources: string[]): string {
  return [...new Set(sources.map((source) => getCountryFlag(source)))].join(" ");
}

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

export function EditorialQueuePage(): JSX.Element {
  const { editorialStories } = useDemoData();

  const stories = [...editorialStories].sort((left, right) => right.importance_score - left.importance_score);

  if (stories.length === 0) {
    return (
      <Card>
        <CardContent className="p-8 text-center">
          <p className="text-lg font-semibold">No editorial stories yet.</p>
          <p className="mt-2 text-slate-600">Run Collect Latest News to evaluate stories with the Editorial Intelligence layer.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-[#0b1f4d]">Editorial Queue</h2>
        <p className="text-[#4d6391]">Editorial stories prioritized by deterministic newsroom intelligence.</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {stories.map((story, index) => (
          <motion.div
            key={story.id}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03, duration: 0.35 }}
          >
            <Card className="overflow-hidden rounded-[26px]">
              <div className="flex min-h-52 items-end bg-gradient-to-r from-[#edf3fc] via-[#f8fbff] to-[#fff7d6] px-7 pb-7 pt-8">
                <div className="space-y-4">
                  <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-[#5a72a3]">
                    <Globe2 className="h-4 w-4" />
                    Editorial Signal
                  </p>
                  <h3 className="max-w-2xl text-3xl font-semibold leading-tight tracking-tight text-[#0b1f4d]">{story.headline}</h3>
                  <div className="flex flex-wrap items-center gap-2 text-2xl">{getFlagCluster(story.sources)}</div>
                </div>
              </div>
              <CardContent className="space-y-5 p-7">
                <p className="text-sm text-[#4d6391]">Published {formatDate(story.published_at)}</p>

                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {[
                    { label: "Sources", value: story.source_count, icon: Hash },
                    { label: "Coverage", value: story.coverage, icon: ShieldCheck },
                    { label: "Similarity", value: `${story.similarity_score}%`, icon: Sparkles },
                    { label: "Importance", value: story.importance_score, icon: Gauge }
                  ].map((metric) => (
                    <div key={metric.label} className="rounded-2xl border border-[#d9e4f5] bg-[#f7faff] p-4">
                      <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-[#5a72a3]">
                        <metric.icon className="h-4 w-4" />
                        {metric.label}
                      </p>
                      <p className="mt-2 text-lg font-semibold text-[#0b1f4d]">{metric.value}</p>
                    </div>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-3 rounded-2xl border border-[#d9e4f5] bg-white p-4 sm:grid-cols-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#5a72a3]">Trend</p>
                    <p className="mt-1 font-semibold text-[#0b1f4d]">{story.trend}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#5a72a3]">Risk</p>
                    <p className="mt-1 font-semibold text-[#0b1f4d]">{story.risk_level}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#5a72a3]">Status</p>
                    <p className="mt-1 font-semibold capitalize text-[#0b1f4d]">{story.status}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#5a72a3]">Flags</p>
                    <p className="mt-1 text-2xl">{getFlagCluster(story.sources)}</p>
                  </div>
                </div>

                <div className="rounded-xl border border-[#d9e4f5] bg-[#f9fbff] p-4">
                  <p className="text-xs uppercase tracking-[0.15em] text-[#5a72a3]">Recommended Action</p>
                  <p className="mt-1 font-semibold text-[#0b1f4d]">{story.recommended_action}</p>
                  <p className="mt-2 text-sm text-[#4d6391]">{story.reason}</p>
                </div>

                <div className="flex items-center justify-between">
                  <Badge variant="success">{story.status === "review" ? "Ready" : story.status}</Badge>
                  <Link to={`/review/${encodeURIComponent(story.id)}`}>
                    <Button>
                      Review <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

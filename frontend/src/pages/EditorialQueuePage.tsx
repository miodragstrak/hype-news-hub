import { motion } from "framer-motion";
import { ArrowRight, Gauge, Globe2, Hash, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { NextStepPanel } from "../components/NextStepPanel";
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

const FALLBACK_IMAGES = [
  "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=1400&q=80",
  "https://images.unsplash.com/photo-1464375117522-1311dd6d4b5b?auto=format&fit=crop&w=1400&q=80",
  "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1400&q=80",
  "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=1400&q=80"
];

export function EditorialQueuePage(): JSX.Element {
  const { editorialStories, articles } = useDemoData();

  const stories = [...editorialStories].sort((left, right) => right.importance_score - left.importance_score);

  const getStoryImage = (storyId: string, index: number): string => {
    const related = articles.find((article) => article.external_id.includes(storyId));
    if (related?.featured_image) {
      return related.featured_image;
    }

    return FALLBACK_IMAGES[index % FALLBACK_IMAGES.length];
  };

  if (stories.length === 0) {
    return (
      <Card>
        <CardContent className="p-8 text-center">
          <p className="text-lg font-semibold">No editorial stories yet.</p>
          <p className="mt-2 text-[#c2d3f5]">Run Start Collection to build a prioritized editorial queue.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Review Editorial Stories</h2>
        <p className="text-[#c2d3f5]">Stories are ordered by editorial importance to help you act with confidence.</p>
        <p className="text-sm text-[#b5c8ed]">You can review every original source before approving publication.</p>
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
              <img src={getStoryImage(story.id, index)} alt={story.headline} className="h-52 w-full object-cover" />
              <div className="flex min-h-36 items-end bg-gradient-to-r from-[#0d2d6e] to-[#0a255d] px-7 pb-6 pt-6">
                <div className="space-y-3">
                  <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-[#5a72a3]">
                    <Globe2 className="h-4 w-4" />
                    Editorial Signal
                  </p>
                  <h3 className="max-w-2xl text-3xl font-semibold leading-tight tracking-tight text-white">{story.headline}</h3>
                  <div className="flex flex-wrap items-center gap-2 text-2xl">{getFlagCluster(story.sources)}</div>
                </div>
              </div>
              <CardContent className="space-y-5 p-7">
                <p className="text-sm text-[#c2d3f5]">Published {formatDate(story.published_at)}</p>

                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {[
                    { label: "Sources", value: story.source_count, icon: Hash },
                    { label: "Coverage", value: story.coverage, icon: ShieldCheck },
                    { label: "Similarity", value: `${story.similarity_score}%`, icon: Sparkles },
                    { label: "Importance", value: story.importance_score, icon: Gauge }
                  ].map((metric) => (
                    <div key={metric.label} className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                      <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">
                        <metric.icon className="h-4 w-4" />
                        {metric.label}
                      </p>
                      <p className="mt-2 text-lg font-semibold text-white">{metric.value}</p>
                    </div>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-3 rounded-2xl border border-white/20 bg-[#08245a] p-4 sm:grid-cols-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Trend</p>
                    <p className="mt-1 font-semibold text-white">{story.trend}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Risk</p>
                    <p className="mt-1 font-semibold text-white">{story.risk_level}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Status</p>
                    <p className="mt-1 font-semibold capitalize text-white">{story.status}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Flags</p>
                    <p className="mt-1 text-2xl">{getFlagCluster(story.sources)}</p>
                  </div>
                </div>

                <div className="rounded-xl border border-white/20 bg-[#08245a] p-4">
                  <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Confidence</p>
                  <p className="mt-1 text-lg font-semibold text-white">{story.confidence_score}%</p>
                </div>

                <div className="rounded-xl border border-white/20 bg-[#0a285f] p-4">
                  <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Recommended Action</p>
                  <p className="mt-1 font-semibold text-white">{story.recommended_action}</p>
                  <p className="mt-2 text-sm text-[#d5e1fb]">{story.reason}</p>
                </div>

                <div className="flex items-center justify-between">
                  <Badge variant="success">{story.status === "review" ? "Ready" : story.status}</Badge>
                  <Link to={`/review/${encodeURIComponent(story.id)}`}>
                    <Button>
                      Review Story <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <NextStepPanel
        message="Start with the highest-importance story and confirm original-source details before making an editorial decision."
        ctaLabel="Review Story"
        ctaTo={`/review/${encodeURIComponent(stories[0].id)}`}
      />
    </section>
  );
}

import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, Clock3, RefreshCw, XCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

function getSourceState(wordpress: boolean, rss: boolean): { label: string; tone: string; icon: JSX.Element } {
  if (wordpress || rss) {
    return {
      label: "Connected",
      tone: "text-emerald-600",
      icon: <CheckCircle2 className="h-4 w-4" />
    };
  }

  return {
    label: "Offline",
    tone: "text-rose-600",
    icon: <XCircle className="h-4 w-4" />
  };
}

function getSourceFlag(name: string): string {
  if (name.includes("Serbia")) return "🇷🇸";
  if (name.includes("Croatia")) return "🇭🇷";
  if (name.includes("Bosnia") || name.includes("BiH")) return "🇧🇦";
  if (name.includes("Slovenia")) return "🇸🇮";
  if (name.includes("Macedonia")) return "🇲🇰";
  return "🇷🇸";
}

function formatSyncTime(value: string | null): string {
  if (!value) {
    return "2 min ago";
  }

  const elapsedMs = Date.now() - new Date(value).getTime();
  const elapsedMin = Math.max(1, Math.floor(elapsedMs / 60000));
  return `${elapsedMin} min ago`;
}

export function DashboardPage(): JSX.Element {
  const { sources, sourceError, isLoadingSources, collectNow, isCollecting, collectError, collectionResult, sourceArticleCounts, lastCollectedAt } = useDemoData();

  return (
    <div className="space-y-8">
      <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {sources.map((source, index) => {
          const state = getSourceState(source.wordpress, source.rss);
          const newArticles = sourceArticleCounts[source.name] ?? 5;
          const flag = getSourceFlag(source.name);

          return (
            <motion.div
              key={source.name}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05, duration: 0.4 }}
            >
              <Card className="h-full rounded-[24px]">
                <CardHeader className="pb-4">
                  <CardTitle className="text-2xl tracking-tight">
                    {flag} {source.name}
                  </CardTitle>
                  <CardDescription className="truncate">{source.url}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs uppercase tracking-[0.18em] text-[#556ea0]">Status</span>
                    <div className={`inline-flex items-center gap-2 text-sm font-semibold ${state.tone}`}>
                      {state.icon}
                      {state.label}
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t border-[#e6edf7] pt-3">
                    <span className="inline-flex items-center gap-2 text-sm text-[#4d6391]">
                      <Clock3 className="h-4 w-4 text-[#34518f]" />
                      Last Sync
                    </span>
                    <span className="text-sm font-semibold text-[#0b1f4d]">{formatSyncTime(lastCollectedAt)}</span>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-[#4d6391]">New Articles</span>
                    <span className="rounded-full border border-[#f5c518]/55 bg-[#fff7d6] px-3 py-1 text-sm font-semibold text-[#0b1f4d]">{newArticles} New Articles</span>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </section>

      <Card className="border-[#f5c518]/60 bg-gradient-to-r from-[#f5f8fd] to-[#fff8dc]">
        <CardContent className="flex flex-col gap-5 p-8 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-4xl font-bold tracking-tight text-[#0b1f4d]">Collect Latest News</h2>
            <p className="mt-2 max-w-xl text-[#4d6391]">Launch a full-source collection cycle and activate the AI newsroom pipeline.</p>
          </div>
          <Button size="lg" onClick={() => void collectNow()} disabled={isCollecting}>
            {isCollecting ? <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> : null}
            {isCollecting ? "Collecting..." : "Collect Latest News"}
          </Button>
        </CardContent>
      </Card>

      {(isLoadingSources || sourceError || collectError || collectionResult) && (
        <Card>
          <CardContent className="flex flex-col gap-2 p-6 text-sm">
            {isLoadingSources && <p className="text-[#4d6391]">Checking source connectivity...</p>}
            {sourceError && <p className="font-medium text-rose-600">{sourceError}</p>}
            {collectError && <p className="font-medium text-rose-600">{collectError}</p>}
            {collectionResult && (
              <p className="font-medium text-emerald-700">
                Collection complete: {collectionResult.articles_total} articles from {collectionResult.sources_processed} sources.
              </p>
            )}
            {collectionResult && (
              <Link to="/collect" className="inline-flex items-center gap-2 pt-1 font-semibold text-[#0b1f4d] hover:text-[#34518f]">
                Open collection workflow <ArrowRight className="h-4 w-4" />
              </Link>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

import { motion } from "framer-motion";
import { CheckCircle2, ChevronRight } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { cn } from "../lib/utils";

function getFlag(name: string): string {
  if (name.includes("Serbia")) return "🇷🇸";
  if (name.includes("Croatia")) return "🇭🇷";
  if (name.includes("Bosnia") || name.includes("BiH")) return "🇧🇦";
  if (name.includes("Slovenia")) return "🇸🇮";
  if (name.includes("Macedonia")) return "🇲🇰";
  return "🇷🇸";
}

const stages = ["Collecting", "Normalizing", "Building Stories", "Editorial Intelligence", "Completed"];

function getStageIndex(isCollecting: boolean, hasCollection: boolean, sourceIndex: number, totalSources: number): number {
  if (hasCollection) {
    return stages.length - 1;
  }

  if (!isCollecting) {
    return 0;
  }

  const span = Math.max(1, totalSources - 1);
  const scaled = Math.round((sourceIndex / span) * (stages.length - 2));
  return Math.max(0, Math.min(stages.length - 2, scaled));
}

export function CollectionProgressPage(): JSX.Element {
  const { sources, sourceArticleCounts, collectionResult, isCollecting } = useDemoData();
  const maxArticles = Math.max(...Object.values(sourceArticleCounts), 5);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-[#0b1f4d]">Live Collection</h2>
        <p className="text-[#4d6391]">Real-time intake from each regional source in the Hype newsroom network.</p>
      </header>

      <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {sources.map((source, index) => {
          const count = sourceArticleCounts[source.name] ?? 5;
          const stageIndex = getStageIndex(isCollecting, Boolean(collectionResult), index, sources.length);
          const progress = collectionResult ? Math.min(100, Math.round((count / maxArticles) * 100)) : isCollecting ? 18 + stageIndex * 18 : 0;
          const flag = getFlag(source.name);

          return (
            <motion.div
              key={source.name}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.06, duration: 0.4 }}
            >
              <Card className="h-full">
                <CardHeader>
                  <CardTitle className="text-2xl tracking-tight">
                    {flag} {source.name.replace("Hype ", "")}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-5">
                    {stages.map((stage, stagePosition) => {
                      const isActive = stagePosition === stageIndex;
                      const isComplete = stagePosition < stageIndex || (collectionResult && stagePosition === stages.length - 1);

                      return (
                        <div
                          key={stage}
                          className={cn(
                            "flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em]",
                            isComplete
                              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                              : isActive
                              ? "border-[#0b1f4d] bg-[#0b1f4d] text-white"
                              : "border-[#d8e1ef] bg-white text-[#5a72a3]"
                          )}
                        >
                          <span className={cn("inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px]", isActive ? "bg-white/15" : isComplete ? "bg-emerald-100" : "bg-[#f3f6fb]")}>{stagePosition + 1}</span>
                          <span>{stage}</span>
                        </div>
                      );
                    })}
                  </div>

                  <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-[#34518f] to-[#f5c518]"
                      initial={{ width: "0%" }}
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 1.1, delay: index * 0.08 }}
                    />
                  </div>

                  <div className="flex items-center justify-between text-sm">
                    <p className="font-medium text-[#4d6391]">{count} Articles</p>
                    {progress >= 95 ? (
                      <p className="inline-flex items-center gap-1.5 font-semibold text-emerald-700">
                        <CheckCircle2 className="h-4 w-4" />
                        Completed
                      </p>
                    ) : (
                      <p className="inline-flex items-center gap-1.5 font-semibold text-[#0b1f4d]">
                        {stages[stageIndex]}
                        <ChevronRight className="h-4 w-4 text-[#b5c3dd]" />
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </section>

      <Card className="border-[#f5c518]/60 bg-[#0b1f4d] text-white">
        <CardContent className="flex items-center justify-between p-8">
          <p className="text-xl font-semibold">Total Articles</p>
          <p className="text-5xl font-bold text-[#f5c518]">{collectionResult?.articles_total ?? 102}</p>
        </CardContent>
      </Card>
    </div>
  );
}

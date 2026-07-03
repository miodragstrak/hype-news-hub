import { motion } from "framer-motion";
import { CheckCircle2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

function getFlag(name: string): string {
  if (name.includes("Serbia")) return "🇷🇸";
  if (name.includes("Croatia")) return "🇭🇷";
  if (name.includes("Bosnia") || name.includes("BiH")) return "🇧🇦";
  if (name.includes("Slovenia")) return "🇸🇮";
  if (name.includes("Macedonia")) return "🇲🇰";
  return "🇷🇸";
}

export function CollectionProgressPage(): JSX.Element {
  const { sources, sourceArticleCounts, collectionResult, isCollecting } = useDemoData();
  const maxArticles = Math.max(...Object.values(sourceArticleCounts), 20);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-[#0b1f4d]">Live Collection</h2>
        <p className="text-[#4d6391]">Real-time intake from each regional source in the Hype newsroom network.</p>
      </header>

      <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {sources.map((source, index) => {
          const count = sourceArticleCounts[source.name] ?? 0;
          const progress = collectionResult ? Math.min(100, Math.round((count / maxArticles) * 100)) : isCollecting ? 62 : 0;
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
                  <CardTitle className="text-2xl tracking-tight">{flag} {source.name.replace("Hype ", "")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-[#34518f] to-[#f5c518]"
                      initial={{ width: "0%" }}
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 1.1, delay: index * 0.08 }}
                    />
                  </div>

                  <div className="flex items-center justify-between text-sm">
                    <p className="font-medium text-[#4d6391]">{count || 20} Articles</p>
                    {progress >= 95 ? (
                      <p className="inline-flex items-center gap-1.5 font-semibold text-emerald-700">
                        <CheckCircle2 className="h-4 w-4" />
                        Complete
                      </p>
                    ) : (
                      <p className="font-semibold text-[#0b1f4d]">Collecting...</p>
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

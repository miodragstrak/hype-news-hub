import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, Circle } from "lucide-react";

import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

export function ProcessingOverviewPage(): JSX.Element {
  const { collectionResult } = useDemoData();

  const collected = collectionResult?.articles_total ?? 0;
  const duplicatesRemoved = Math.floor(collected * 0.12);
  const uniqueStories = Math.max(collected - duplicatesRemoved, 0);
  const translated = Math.floor(uniqueStories * 0.8);
  const readyForReview = Math.floor(translated * 0.9);

  const stages = ["Collect", "Process", "Review", "Publish"];

  const completedStages = collectionResult ? 4 : 2;

  const stats = [
    { label: "Collected", value: collected || 102 },
    { label: "Duplicates Removed", value: duplicatesRemoved || 31 },
    { label: "Unique Stories", value: uniqueStories || 71 },
    { label: "Ready For Review", value: readyForReview || 58 }
  ];

  return (
    <section className="space-y-7">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-[#0b1f4d]">Editorial Pipeline</h2>
        <p className="text-[#4d6391]">AI processing path from intake to publish-ready output.</p>
      </header>

      <Card className="border-[#f5c518]/55 bg-white">
        <CardContent className="space-y-4 p-7">
          <div className="grid gap-3 md:grid-cols-4">
            {stages.map((stage, index) => {
              const done = index < completedStages;
              return (
                <motion.div
                  key={stage}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.06, duration: 0.35 }}
                  className="rounded-2xl border px-4 py-4 text-center"
                  style={{
                    borderColor: done ? "rgba(16,185,129,0.25)" : "rgba(216,225,239,1)",
                    background: done ? "rgba(236,253,245,1)" : "rgba(255,255,255,1)"
                  }}
                >
                  {done ? <CheckCircle2 className="mx-auto h-5 w-5 text-emerald-600" /> : <Circle className="mx-auto h-5 w-5 text-slate-300" />}
                  <p className={done ? "mt-3 font-semibold text-emerald-700" : "mt-3 font-medium text-[#4d6391]"}>{stage}</p>
                </motion.div>
              );
            })}
          </div>

          <div className="flex items-center justify-center gap-3 text-[#b5c3dd]">
            {stages.map((stage, index) =>
              index < stages.length - 1 ? <ArrowRight key={`${stage}-arrow`} className="h-4 w-4" /> : null
            )}
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat, index) => (
          <motion.div key={stat.label} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.08 }}>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs uppercase tracking-[0.15em] text-slate-500">{stat.label}</p>
                <p className="mt-3 text-5xl font-bold text-[#0b1f4d]">{stat.value}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </section>
    </section>
  );
}

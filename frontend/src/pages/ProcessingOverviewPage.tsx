import { motion } from "framer-motion";
import { ArrowDown, CheckCircle2, Circle } from "lucide-react";

import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

export function ProcessingOverviewPage(): JSX.Element {
  const { collectionResult } = useDemoData();

  const collected = collectionResult?.articles_total ?? 0;
  const duplicatesRemoved = Math.floor(collected * 0.12);
  const uniqueStories = Math.max(collected - duplicatesRemoved, 0);
  const translated = Math.floor(uniqueStories * 0.8);
  const readyForReview = Math.floor(translated * 0.9);

  const stages = [
    "Collect",
    "Normalize",
    "Duplicate Detection",
    "Translation",
    "AI Rewrite",
    "Editorial Review",
    "Ready to Publish"
  ];

  const completedStages = collectionResult ? 7 : 4;

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
        <CardContent className="space-y-2 p-7">
          {stages.map((stage, index) => {
            const done = index < completedStages;
            return (
              <div key={stage}>
                <motion.div
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.07, duration: 0.35 }}
                  className="flex items-center gap-3"
                >
                  {done ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <Circle className="h-5 w-5 text-slate-300" />}
                  <p className={done ? "font-semibold text-emerald-700" : "font-medium text-[#4d6391]"}>{stage}</p>
                </motion.div>
                {index < stages.length - 1 ? <ArrowDown className="my-1.5 ml-0.5 h-4 w-4 text-slate-300" /> : null}
              </div>
            );
          })}
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

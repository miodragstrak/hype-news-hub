import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, Circle } from "lucide-react";
import { Link } from "react-router-dom";

import { NextStepPanel } from "../components/NextStepPanel";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

export function ProcessingOverviewPage(): JSX.Element {
  const { collectionResult } = useDemoData();

  const collected = collectionResult?.articles_total ?? 25;
  const duplicatesMerged = Math.max(1, Math.floor(collected * 0.12));
  const uniqueStories = Math.max(collected - duplicatesMerged, 0);
  const readyForReview = Math.max(1, Math.floor(uniqueStories * 0.68));

  const processingStages = [
    "Collected Articles",
    "Normalized",
    "Stories Created",
    "Duplicates Merged",
    "Editorially Scored",
    "Ready for Review"
  ];

  const completedStages = collectionResult ? processingStages.length : 2;

  const stats = [
    { label: "Articles Collected", value: collected },
    { label: "Duplicates Merged", value: duplicatesMerged },
    { label: "Unique Stories", value: uniqueStories },
    { label: "Ready For Review", value: readyForReview }
  ];

  const isProcessingComplete = Boolean(collectionResult);

  return (
    <section className="space-y-7">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Process Editorial Signals</h2>
        <p className="text-[#c2d3f5]">Normalize articles, merge duplicates, and rank stories for editorial review.</p>
        <p className="text-sm text-[#b5c8ed]">Actions can be reviewed before publishing.</p>
      </header>

      <Card className="border-white/25 bg-[#0a285f]">
        <CardContent className="space-y-4 p-7">
          <div className="flex flex-wrap items-center gap-2">
            {processingStages.map((stage, index) => {
              const done = index < completedStages;
              return (
                <motion.div
                  key={stage}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.06, duration: 0.35 }}
                  className="inline-flex items-center gap-2 rounded-2xl border px-4 py-3"
                  style={done ? { borderColor: "rgba(52,211,153,0.35)", background: "rgba(16,185,129,0.12)" } : { borderColor: "rgba(255,255,255,0.2)", background: "rgba(8,36,90,1)" }}
                >
                  {done ? <CheckCircle2 className="h-5 w-5 text-emerald-200" /> : <Circle className="h-5 w-5 text-[#b0c3ea]" />}
                  <p className={done ? "font-semibold text-emerald-50" : "font-medium text-[#d4e2ff]"}>{stage}</p>
                </motion.div>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-[#f5c518]">
            {processingStages.map((stage, index) =>
              index < processingStages.length - 1 ? <ArrowRight key={`${stage}-arrow`} className="h-4 w-4" /> : null
            )}
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat, index) => (
          <motion.div key={stat.label} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.08 }}>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs uppercase tracking-[0.15em] text-[#b5c8ed]">{stat.label}</p>
                <p className="mt-3 text-5xl font-bold text-white">{stat.value}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </section>

      {isProcessingComplete ? (
        <Card className="border-emerald-400/35 bg-emerald-500/10">
          <CardContent className="space-y-3 p-6">
            <h3 className="text-2xl font-bold text-emerald-100">Processing Complete</h3>
            <ul className="space-y-1 text-sm text-emerald-50">
              <li>{collected} articles collected</li>
              <li>{duplicatesMerged} duplicates merged</li>
              <li>{uniqueStories} unique stories</li>
              <li>{readyForReview} ready for review</li>
            </ul>
            <Button size="lg" asChild>
              <Link to="/review">Review Editorial Stories</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-white/20 bg-[#0a285f]">
          <CardContent className="p-6 text-sm text-[#d4e2ff]">Run collection first to complete all processing stages.</CardContent>
        </Card>
      )}

      <NextStepPanel
        message={
          isProcessingComplete
            ? "Processing is complete. Review editorial stories to approve, edit, or reject each item."
            : "Collection is required before processing can complete. Go back and run Start Collection."
        }
        ctaLabel={isProcessingComplete ? "Review Editorial Stories" : "Return to Collect"}
        ctaTo={isProcessingComplete ? "/review" : "/"}
      />
    </section>
  );
}

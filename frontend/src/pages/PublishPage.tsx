import { motion } from "framer-motion";
import { Send, Sparkles } from "lucide-react";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

export function PublishPage(): JSX.Element {
  const { collectionResult } = useDemoData();

  const collected = collectionResult?.articles_total ?? 102;
  const duplicatesRemoved = Math.floor(collected * 0.3);
  const uniqueStories = Math.max(collected - duplicatesRemoved, 0);
  const readyForReview = Math.floor(uniqueStories * 0.82);
  const readyToPublish = Math.floor(readyForReview * 0.76);

  return (
    <section className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <Card className="h-full border-[#f5c518]/55">
          <CardHeader>
            <CardDescription>Publish Readiness</CardDescription>
            <CardTitle className="text-4xl">Ready to Broadcast</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                { label: "Collected", value: collected },
                { label: "Unique", value: uniqueStories },
                { label: "Ready", value: readyForReview },
                { label: "Publish", value: readyToPublish }
              ].map((metric) => (
                <div key={metric.label} className="rounded-2xl border border-[#d8e1ef] bg-white p-4 text-center shadow-sm">
                  <p className="text-xs uppercase tracking-[0.16em] text-[#5a72a3]">{metric.label}</p>
                  <p className="mt-2 text-3xl font-bold text-[#0b1f4d]">{metric.value}</p>
                </div>
              ))}
            </div>

            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-emerald-700">
                <Sparkles className="h-4 w-4" />
                Editorial package quality score is above launch threshold.
              </p>
            </div>

            <Button size="lg" className="w-full sm:w-auto">
              <Send className="mr-2 h-4 w-4" />
              Publish to Executive Rundown
            </Button>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.45, delay: 0.08 }}>
        <Card>
          <CardHeader>
            <CardDescription>Distribution Channels</CardDescription>
            <CardTitle className="text-2xl">Output Targets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              "Prime Time Rundown",
              "Digital Breaking News",
              "Morning Bulletin",
              "Social Clips"
            ].map((channel) => (
              <div key={channel} className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3">
                <p className="font-medium text-[#0b1f4d]">{channel}</p>
                <Badge variant="success">Ready</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </motion.div>
    </section>
  );
}

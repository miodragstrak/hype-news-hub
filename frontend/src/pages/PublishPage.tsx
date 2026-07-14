import { motion } from "framer-motion";
import { Sparkles, TimerReset } from "lucide-react";

import { NextStepPanel } from "../components/NextStepPanel";
import { Badge } from "../components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { isDemoDataModeEnabled } from "../services/newsService";

export function PublishPage(): JSX.Element {
  const { collectionResult, stories } = useDemoData();

  const collected = collectionResult?.articles_total ?? 25;
  const duplicatesRemoved = Math.floor(collected * 0.12);
  const uniqueStories = Math.max(collected - duplicatesRemoved, 0);
  const readyForReview = Math.floor(uniqueStories * 0.7);
  const readyToPublish = stories.filter((story) => story.status === "review" || story.status === "draft").length;
  const mainPortalStatus = isDemoDataModeEnabled() ? "Preview Only" : "Ready";

  const targets = [
    {
      name: "Main Hype WordPress Portal",
      status: mainPortalStatus,
      tone: mainPortalStatus === "Ready" ? "success" : "warning",
      note: "Central editorial draft target. Current implementation is preview-only until final publish wiring is completed."
    },
    { name: "Regional Portals", status: "Planned", tone: "warning", note: "Planned for phased rollout after central portal stabilization." },
    { name: "Social Media", status: "Planned", tone: "warning", note: "Planned export to social channels with editorial controls." },
    { name: "Newsletter", status: "Planned", tone: "warning", note: "Planned packaging for newsletter distribution." },
    { name: "Mobile Push", status: "Planned", tone: "warning", note: "Planned push workflow for mobile alerts." }
  ] as const;

  return (
    <section className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <Card className="h-full border-[#f5c518]/55 bg-[#0a285f]">
          <CardHeader>
            <CardDescription>Publish Stage</CardDescription>
            <CardTitle className="text-4xl text-white">Publish Overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                { label: "Collected", value: collected },
                { label: "Unique", value: uniqueStories },
                { label: "Ready", value: readyForReview },
                { label: "Publish", value: readyToPublish }
              ].map((metric) => (
                <div key={metric.label} className="rounded-2xl border border-white/20 bg-[#08245a] p-4 text-center shadow-sm">
                  <p className="text-xs uppercase tracking-[0.16em] text-[#b7c9ee]">{metric.label}</p>
                  <p className="mt-2 text-3xl font-bold text-white">{metric.value}</p>
                </div>
              ))}
            </div>

            <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-[#f5c518]">
                <Sparkles className="h-4 w-4" />
                Approved stories will eventually be sent to the central Hype WordPress portal as editorial drafts.
              </p>
              <p className="mt-2 text-sm text-[#d6e3ff]">Nothing is published automatically from this prototype. Actions can be reviewed before publishing.</p>
            </div>

            <div className="rounded-2xl border border-emerald-400/35 bg-emerald-500/10 p-4">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-emerald-100">
                <Badge variant="success">Ready</Badge>
                Editorial package preview is ready for manual verification.
              </p>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.45, delay: 0.08 }}>
        <Card>
          <CardHeader>
            <CardDescription>Distribution Channels</CardDescription>
            <CardTitle className="text-2xl text-white">Output Targets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4 text-sm text-[#d6e3ff]">
              <p className="inline-flex items-center gap-2 font-semibold text-white">
                <TimerReset className="h-4 w-4 text-[#f5c518]" />
                Planned integrations are clearly marked.
              </p>
              <p className="mt-2">Unfinished integrations do not appear operational. Status labels indicate the actual implementation state.</p>
            </div>

            {targets.map((target) => (
              <div key={target.name} className="rounded-2xl border border-white/20 bg-[#08245a] px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-white">{target.name}</p>
                    <p className="mt-1 text-sm text-[#c2d3f5]">{target.note}</p>
                  </div>
                  <Badge variant={target.status === "Ready" ? "success" : "warning"}>{target.status}</Badge>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </motion.div>

      <div className="lg:col-span-2">
        <NextStepPanel
          message="Preview the publishing package to confirm approved stories before any live distribution integration is enabled."
          ctaLabel="Preview Publishing Package"
          ctaTo="/publish"
        />
      </div>
    </section>
  );
}

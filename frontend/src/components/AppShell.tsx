import { motion } from "framer-motion";
import { Activity, Check, Clock3, Newspaper } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "../lib/utils";
import { useDemoData } from "../context/DemoDataContext";

const steps = [
  { to: "/", label: "Collect", order: "01" },
  { to: "/process", label: "Process", order: "02" },
  { to: "/review", label: "Review", order: "03" },
  { to: "/publish", label: "Publish", order: "04" }
];

function matchesStep(pathname: string, stepTo: string): boolean {
  if (stepTo === "/") {
    return pathname === "/";
  }

  if (stepTo === "/review") {
    return pathname.startsWith("/review");
  }

  return pathname === stepTo;
}

export function AppShell(): JSX.Element {
  const location = useLocation();
  const { sources, collectionResult, lastCollectedAt, stories } = useDemoData();

  const connectedSources = sources.filter((source) => source.wordpress || source.rss).length;
  const storiesToday = collectionResult?.stories_total ?? stories.length ?? 18;
  const readyForReview = stories.filter((story) => story.status === "review").length || 12;
  const publishedStories = stories.filter((story) => story.status === "published").length || 4;

  const lastSyncLabel = lastCollectedAt
    ? new Date(lastCollectedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : "09:42";

  const activeStepIndex = steps.findIndex((step) => matchesStep(location.pathname, step.to));

  return (
    <div className="relative min-h-screen overflow-hidden bg-white text-[#0b1f4d]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(11,31,77,0.08)_0%,transparent_34%),radial-gradient(circle_at_top_right,rgba(245,197,24,0.15)_0%,transparent_24%),radial-gradient(circle_at_bottom,rgba(11,31,77,0.05)_0%,transparent_40%)]" />
      <div className="relative z-10 mx-auto flex min-h-screen max-w-7xl flex-col px-4 pb-10 pt-6 sm:px-8 lg:px-10">
        <header className="rounded-[30px] border border-[#d8e1ef] bg-white/95 px-6 py-6 shadow-[0_32px_72px_-52px_rgba(11,31,77,0.55)] backdrop-blur sm:px-7 sm:py-7">
          <div className="grid gap-8 xl:grid-cols-[1.2fr_0.8fr] xl:items-start">
            <div className="space-y-6">
              <div className="flex flex-col items-start gap-4">
                <img src="/hype-logo.png" alt="Hype Logo" className="h-16 w-auto rounded-2xl object-contain shadow-[0_18px_28px_-22px_rgba(11,31,77,0.55)] sm:h-20" />
                <div className="max-w-2xl space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.32em] text-[#5a72a3]">Official Hype Product</p>
                  <h1 className="text-4xl font-extrabold tracking-tight text-[#0b1f4d] sm:text-5xl lg:text-6xl">HYPE WORLD NEWS</h1>
                  <p className="max-w-xl text-base leading-7 text-[#4d6391] sm:text-lg">AI-powered editorial system that monitors, merges and prioritizes entertainment news across the region in real time.</p>
                </div>
              </div>

              <nav className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {steps.map((step, index) => {
                  const isActive = matchesStep(location.pathname, step.to);
                  const isCompleted = activeStepIndex > -1 && index < activeStepIndex;

                  return (
                    <NavLink
                      key={step.to}
                      to={step.to}
                      end={step.to === "/"}
                      className={cn(
                        "group flex items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-all duration-300",
                        isActive
                          ? "border-[#0b1f4d] bg-[#0b1f4d] text-white shadow-[0_18px_25px_-18px_rgba(11,31,77,0.9)]"
                          : isCompleted
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                          : "border-[#d8e1ef] bg-white text-[#0b1f4d] hover:border-[#bfd0e9] hover:bg-[#f5f8fd]"
                      )}
                    >
                      <span className={cn("inline-flex h-9 w-9 items-center justify-center rounded-full text-xs font-bold tracking-[0.18em]", isActive ? "bg-white/15 text-white" : isCompleted ? "bg-emerald-100 text-emerald-700" : "bg-[#f2f6fc] text-[#34518f]")}>{isCompleted ? <Check className="h-4 w-4" /> : step.order}</span>
                      <span className="flex flex-col">
                        <span className="text-xs uppercase tracking-[0.2em] opacity-70">Step</span>
                        <span className="text-sm font-semibold">{step.label}</span>
                      </span>
                    </NavLink>
                  );
                })}
              </nav>

              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45 }}
                className="rounded-2xl border border-[#f5c518]/65 bg-[#f7faff] p-5"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#536b9a]">AI Newsroom Status</p>
                    <p className="mt-1 inline-flex items-center gap-2 text-sm font-semibold text-emerald-700">
                      <Activity className="h-4 w-4" />
                      Monitoring
                    </p>
                  </div>
                  <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3 sm:gap-6">
                    <p className="inline-flex items-center gap-2 font-medium text-[#0b1f4d]">
                      <Newspaper className="h-4 w-4 text-[#34518f]" />
                      {connectedSources} Sources Connected
                    </p>
                    <p className="font-medium text-[#0b1f4d]">{collectionResult?.articles_total ?? 25} Articles Today</p>
                    <p className="inline-flex items-center gap-2 font-medium text-[#0b1f4d]">
                      <Clock3 className="h-4 w-4 text-[#f5c518]" />
                      Last Sync {lastSyncLabel}
                    </p>
                  </div>
                </div>
              </motion.section>
            </div>

            <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-1">
              {[
                { label: "Stories Today", value: storiesToday },
                { label: "Ready for Review", value: readyForReview },
                { label: "Published", value: publishedStories }
              ].map((metric, index) => (
                <motion.div
                  key={metric.label}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: index * 0.05 }}
                  className="rounded-2xl border border-[#d8e1ef] bg-[#fbfdff] p-5 shadow-[0_18px_28px_-24px_rgba(11,31,77,0.45)]"
                >
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#5a72a3]">{metric.label}</p>
                  <p className="mt-3 text-4xl font-bold tracking-tight text-[#0b1f4d]">{metric.value}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </header>

        <main className="mt-10 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

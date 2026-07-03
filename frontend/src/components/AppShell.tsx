import { motion } from "framer-motion";
import { Activity, ArrowDown, Clock3, Newspaper } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { cn } from "../lib/utils";
import { useDemoData } from "../context/DemoDataContext";

const steps = [
  { to: "/", label: "Collect", order: "01" },
  { to: "/process", label: "Process", order: "02" },
  { to: "/review", label: "Review", order: "03" },
  { to: "/publish", label: "Publish", order: "04" }
];

export function AppShell(): JSX.Element {
  const { sources, collectionResult, lastCollectedAt } = useDemoData();

  const connectedSources = sources.filter((source) => source.wordpress || source.rss).length;
  const articlesToday = collectionResult?.articles_total ?? 102;

  const lastSyncLabel = lastCollectedAt
    ? new Date(lastCollectedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : "09:42";

  return (
    <div className="relative min-h-screen overflow-hidden bg-white text-[#0b1f4d]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(11,31,77,0.08)_0%,transparent_34%),radial-gradient(circle_at_top_right,rgba(245,197,24,0.15)_0%,transparent_24%),radial-gradient(circle_at_bottom,rgba(11,31,77,0.05)_0%,transparent_40%)]" />
      <div className="relative z-10 mx-auto flex min-h-screen max-w-7xl flex-col px-4 pb-10 pt-6 sm:px-8 lg:px-10">
        <header className="rounded-[30px] border border-[#d8e1ef] bg-white/95 px-7 py-7 shadow-[0_32px_72px_-52px_rgba(11,31,77,0.55)] backdrop-blur">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex items-start gap-4">
              <img src="/hype-logo.png" alt="Hype Logo" className="h-12 w-auto rounded-md object-contain" />
              <div>
                <h1 className="text-4xl font-extrabold tracking-tight text-[#0b1f4d] sm:text-5xl">HYPE WORLD NEWS</h1>
                <p className="mt-2 text-sm font-semibold uppercase tracking-[0.3em] text-[#34518f]">AI Editorial Control Center</p>
              </div>
            </div>
            <nav className="flex flex-col gap-1.5 lg:items-end">
              {steps.map((step, index) => (
                <div key={step.to} className="flex flex-col items-start lg:items-end">
                  <NavLink
                    to={step.to}
                    end={step.to === "/"}
                    className={({ isActive }) =>
                      cn(
                        "inline-flex items-center gap-3 rounded-2xl border px-4 py-2 text-sm font-semibold transition-all duration-300",
                        isActive
                          ? "border-[#0b1f4d] bg-[#0b1f4d] text-white shadow-[0_18px_25px_-18px_rgba(11,31,77,0.9)]"
                          : "border-[#d8e1ef] bg-white text-[#0b1f4d] hover:border-[#bfd0e9] hover:bg-[#f5f8fd]"
                      )
                    }
                  >
                    <span className="text-xs tracking-[0.2em] text-amber-400">{step.order}</span>
                    <span>{step.label}</span>
                  </NavLink>
                  {index < steps.length - 1 ? <ArrowDown className="mx-3 my-1.5 h-4 w-4 text-[#b5c3dd]" /> : null}
                </div>
              ))}
            </nav>
          </div>

          <motion.section
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45 }}
            className="mt-8 rounded-2xl border border-[#f5c518]/65 bg-[#f7faff] p-5"
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
                <p className="font-medium text-[#0b1f4d]">{articlesToday} Articles Today</p>
                <p className="inline-flex items-center gap-2 font-medium text-[#0b1f4d]">
                  <Clock3 className="h-4 w-4 text-[#f5c518]" />
                  Last Sync {lastSyncLabel}
                </p>
              </div>
            </div>
          </motion.section>
        </header>

        <main className="mt-10 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

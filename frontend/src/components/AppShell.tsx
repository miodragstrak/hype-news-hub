import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "../lib/utils";

const steps = [
  { to: "/", label: "Collect", order: "01" },
  { to: "/process", label: "Process", order: "02" },
  { to: "/review", label: "Review", order: "03" },
  { to: "/publish", label: "Publish", order: "04" }
];

function matchesStep(pathname: string, stepTo: string): boolean {
  if (stepTo === "/") {
    return pathname === "/" || pathname === "/collect";
  }

  if (stepTo === "/review") {
    return pathname.startsWith("/review");
  }

  return pathname === stepTo;
}

export function AppShell(): JSX.Element {
  const location = useLocation();

  const activeStepIndex = steps.findIndex((step) => matchesStep(location.pathname, step.to));

  return (
    <div className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_20%_-10%,rgba(32,68,137,0.5)_0%,transparent_45%),radial-gradient(circle_at_90%_0%,rgba(245,197,24,0.09)_0%,transparent_28%),#07173d] text-[#f4f8ff]">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_bottom,rgba(255,255,255,0.03)_0%,rgba(255,255,255,0)_32%),linear-gradient(to_right,rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:100%_100%,28px_28px,28px_28px]" />
      <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 pb-10 pt-5 sm:px-8 lg:px-10">
        <header className="rounded-[28px] border border-white/20 bg-[#0b2a67]/85 px-5 py-5 shadow-[0_24px_52px_-34px_rgba(0,0,0,0.75)] backdrop-blur md:px-7 md:py-6">
          <div className="space-y-5">
            <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <img src="/hype-logo.png" alt="Hype logo" className="h-14 w-auto object-contain sm:h-16" />
                <div className="space-y-1">
                  <h1 className="text-2xl font-extrabold tracking-[0.02em] text-white sm:text-3xl">HYPE WORLD NEWS</h1>
                  <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#d6e3ff]">AI Editorial Control Center</p>
                </div>
              </div>
              <p className="max-w-xl text-sm leading-6 text-[#c2d3f5]">AI-powered workflow for collecting, merging, prioritizing and publishing news.</p>
            </div>

            <motion.nav initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="overflow-x-auto pb-1">
              <div className="flex min-w-max items-center gap-2 md:gap-3">
                {steps.map((step, index) => {
                  const isActive = matchesStep(location.pathname, step.to);
                  const isCompleted = activeStepIndex > -1 && index < activeStepIndex;

                  return (
                    <div key={step.to} className="flex items-center gap-2 md:gap-3">
                      <NavLink
                        to={step.to}
                        end={step.to === "/"}
                        className={cn(
                          "group inline-flex min-w-[170px] items-center gap-3 rounded-2xl border px-4 py-3 transition-all duration-300",
                          isActive
                            ? "border-[#f5c518] bg-[#f5c518] text-[#07173d] shadow-[0_14px_26px_-18px_rgba(245,197,24,0.95)]"
                            : isCompleted
                            ? "border-emerald-400/35 bg-emerald-500/15 text-emerald-100"
                            : "border-white/25 bg-[#08245b] text-[#d2ddf5] hover:border-white/40 hover:text-white"
                        )}
                      >
                        <span
                          className={cn(
                            "inline-flex h-9 w-9 items-center justify-center rounded-full text-xs font-bold tracking-[0.14em]",
                            isActive ? "bg-[#07173d]/15" : isCompleted ? "bg-emerald-500/25 text-emerald-50" : "bg-[#12377f] text-[#dce7ff]"
                          )}
                        >
                          {isCompleted ? <Check className="h-4 w-4" /> : step.order}
                        </span>
                        <span className="text-lg font-semibold leading-none">{step.label}</span>
                      </NavLink>

                      {index < steps.length - 1 ? (
                        <span className={cn("text-lg font-black tracking-[0.05em]", index < activeStepIndex ? "text-emerald-300" : "text-white/45")}>→</span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </motion.nav>
          </div>
        </header>

        <main className="mt-6 flex-1">
          <motion.div key={location.pathname} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
            <Outlet />
          </motion.div>
        </main>
      </div>
    </div>
  );
}

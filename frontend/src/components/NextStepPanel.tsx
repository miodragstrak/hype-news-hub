import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "./ui/button";

type NextStepPanelProps = {
  message: string;
  ctaLabel: string;
  ctaTo?: string;
  onAction?: () => void;
  disabled?: boolean;
};

export function NextStepPanel({ message, ctaLabel, ctaTo, onAction, disabled = false }: NextStepPanelProps): JSX.Element {
  return (
    <section className="rounded-2xl border border-white/20 bg-[#0a285f]/80 p-5">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#b7c9ee]">Recommended Next Step</p>
      <p className="mt-2 text-sm leading-6 text-[#e1eaff]">{message}</p>
      <div className="mt-4">
        {disabled ? (
          <Button size="lg" disabled>
            {ctaLabel}
          </Button>
        ) : onAction ? (
          <Button size="lg" onClick={onAction}>
            {ctaLabel}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        ) : ctaTo ? (
          <Link to={ctaTo}>
            <Button size="lg">
              {ctaLabel}
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
        ) : (
          <Button size="lg" disabled>
            {ctaLabel}
          </Button>
        )}
      </div>
    </section>
  );
}

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "./ui/button";

export function ConfirmDiscardDialog({ title, message, confirmLabel, cancelLabel = "Keep editing", lang, onCancel, onConfirm }: { title: string; message: string; confirmLabel: string; cancelLabel?: string; lang?: string; onCancel: () => void; onConfirm: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const id = useId();
  const [viewport, setViewport] = useState<{ top: number; left: number; width: number; height: number }>();
  useEffect(() => {
    // Mobile keyboards and zoom can shrink/pan the visual viewport without
    // resizing the layout viewport or its CSS viewport units.
    const visible = window.visualViewport;
    if (!visible) return;
    const update = () => setViewport({ top: visible.offsetTop, left: visible.offsetLeft, width: visible.width, height: visible.height });
    update();
    visible.addEventListener("resize", update);
    visible.addEventListener("scroll", update);
    return () => { visible.removeEventListener("resize", update); visible.removeEventListener("scroll", update); };
  }, []);
  useEffect(() => {
    const previous = document.activeElement;
    cancel.current?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return createPortal(<div style={viewport} className="fixed inset-x-0 top-0 z-50 flex h-screen items-center justify-center overflow-hidden bg-black/75 p-4 pt-[max(1rem,env(safe-area-inset-top))] pr-[max(1rem,env(safe-area-inset-right))] pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] supports-[height:100dvh]:h-[100dvh]">
    <div ref={panel} lang={lang} role="alertdialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-message`} className="flex max-h-full min-h-0 w-full min-w-0 max-w-lg flex-col overflow-y-auto overscroll-contain rounded-2xl border border-[#f5c518] bg-[#0b2a67] p-4 shadow-xl sm:p-6" onKeyDown={event => {
      if (event.key === "Escape") { event.preventDefault(); onCancel(); }
      if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex="0"]');
        if (controls?.length) {
          if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1].focus(); }
          else if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0].focus(); }
        }
      }
    }}>
      <h2 id={`${id}-title`} className="shrink-0 text-xl font-bold text-white [overflow-wrap:anywhere]">{title}</h2>
      <div role="region" aria-labelledby={`${id}-title`} tabIndex={0} className="my-2 min-h-[2.5em] overflow-y-auto overscroll-contain whitespace-pre-wrap text-[#dbe6ff] [overflow-wrap:anywhere] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#f5c518]">
        <p id={`${id}-message`}>{message}</p>
      </div>
      <div className="grid shrink-0 grid-cols-2 gap-3"><Button ref={cancel} type="button" variant="secondary" className="h-auto min-h-10 min-w-0 whitespace-normal [overflow-wrap:anywhere]" onClick={onCancel}>{cancelLabel}</Button><Button type="button" className="h-auto min-h-10 min-w-0 whitespace-normal [overflow-wrap:anywhere]" onClick={onConfirm}>{confirmLabel}</Button></div>
    </div>
  </div>, document.body);
}

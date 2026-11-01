/** Browser-only layout fixture. No identity adapter, API calls or production entry. */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ConfirmDiscardDialog } from "../../src/components/ConfirmDiscardDialog";
import "../../src/index.css";

type Scenario = "decision" | "unbroken" | "url" | "discard";
const hash = "abcdef0123456789".repeat(4);
const reasons = {
  decision: "Z" + "Proverene činjenice i detaljno obrazloženje. ".repeat(60).slice(0, 1998) + "Z",
  unbroken: "Z".repeat(2000),
  url: ("https://example.test/" + "x".repeat(2000)).slice(0, 2000),
};
const probe = { confirmed: 0, cancelled: 0, expectedMessage: "", reason: "", hash };
declare global { interface Window { dialogFixture: typeof probe } }
window.dialogFixture = probe;

function Fixture() {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const discard = scenario === "discard";
  const title = discard ? "Leave unsaved editorial changes?" : "Potvrdite: Zatraži izmene";
  function open(next: Scenario) {
    probe.reason = next === "discard" ? "" : reasons[next];
    probe.expectedMessage = next === "discard"
      ? "Local edits and unconfirmed save commands are held only in this page. Leaving discards them; an in-flight server request may still complete."
      : `Verzija 27, očekivana revizija 83. SHA-256: ${hash} · Obrazloženje: ${probe.reason}. Odluku će proveriti server.`;
    setScenario(next);
  }
  // A transformed ancestor must not constrain a viewport-level dialog.
  return <div style={{ transform: "translateY(0)", minHeight: 1600, padding: 12 }}>
    {(["decision", "unbroken", "url", "discard"] as const).map(kind => <button key={kind} id={`open-${kind}`} onClick={() => open(kind)} style={{ display: "block", marginBottom: 8 }}>{kind}</button>)}
    {scenario ? <ConfirmDiscardDialog lang={discard ? undefined : "sr-Latn"} title={title} message={probe.expectedMessage} confirmLabel={discard ? "Discard and leave" : "Potvrdi odluku"} cancelLabel={discard ? undefined : "Odustani"} onCancel={() => { probe.cancelled += 1; setScenario(null); }} onConfirm={() => { probe.confirmed += 1; setScenario(null); }} /> : null}
  </div>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);

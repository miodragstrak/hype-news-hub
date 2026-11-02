import { Link } from "react-router-dom";
import { useEditorialAccess } from "../context/EditorialAccessContext";
import { useDemoData } from "../context/DemoDataContext";
import { editorialErrorMessage } from "../services/editorialApi";

export function EditorialAccessBanner({ storyId }: { storyId?: string }) {
  const access = useEditorialAccess();
  const { isDemoMode } = useDemoData();
  const readable = !isDemoMode && access.state === "ready" && access.capabilities?.permissions.includes("editorial:read");
  const editable = readable && access.capabilities?.commands_enabled && access.capabilities.permissions.includes("editorial:edit");
  const message = isDemoMode ? "Production editorial editing is unavailable for sample demo stories." :
    access.state === "unconfigured" ? "Production editorial editing is unavailable. Sign-in integration has not been configured." :
    access.state === "signed_out" ? "Production editorial editing is unavailable. Sign in through your newsroom identity provider." :
    access.state === "checking" ? "Checking authenticated editorial access…" :
    access.state === "error" ? `Production editorial editing is unavailable. ${editorialErrorMessage(access.error)}` :
    editable ? "Authenticated draft editing is available. Saves create private editorial versions." : "Read-only editorial access. Creating or saving a draft requires Editor permission.";
  return <aside className="rounded-2xl border border-white/25 bg-[#0b2a67] p-4 text-sm text-[#dbe6ff]" aria-label="Production editorial access">
    <p>{message}</p>
    <p className="mt-1 text-[#b7c9ee]">Public collection and source previews remain available.</p>
    {readable && storyId ? <Link className="mt-3 inline-block font-semibold text-[#f5c518] underline" to={`/review/${encodeURIComponent(storyId)}/edit`}>{editable ? "Open draft editor" : "Open saved editorial draft"}</Link> : null}
    {readable && storyId ? <Link className="ml-4 mt-3 inline-block font-semibold text-[#f5c518] underline" to={`/review/${encodeURIComponent(storyId)}/decisions`}>Pregled i odluke</Link> : null}
    {readable && storyId ? <Link className="ml-4 mt-3 inline-block font-semibold text-[#f5c518] underline" to={`/review/${encodeURIComponent(storyId)}/ai`}>AI predlozi</Link> : null}
    {access.state === "error" || access.state === "signed_out" ? <button type="button" className="mt-3 block font-semibold text-[#f5c518] underline" onClick={access.refresh}>Retry editorial access</button> : null}
  </aside>;
}

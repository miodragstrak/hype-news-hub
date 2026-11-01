import { useCallback, useState, type ReactNode } from "react";
import { useEditorialAccess } from "../context/EditorialAccessContext";
import { useDemoData } from "../context/DemoDataContext";
import { isUuid } from "../lib/editorialForm";
import type { EditorialApi } from "../services/editorialApi";
import type { EditorialCapabilities } from "../types/editorial";
import { EditorialAccessBanner } from "./EditorialAccessBanner";
import { EditorialNavigation } from "./EditorialNavigation";
import { Button } from "./ui/button";
export type PrivatePageAccess = { client: EditorialApi; capabilities: EditorialCapabilities; onDenied: (message: string) => void };
function Authorized({ client, capabilities, retry, children }: Omit<PrivatePageAccess, "onDenied"> & { retry: () => void; children: (access: PrivatePageAccess) => ReactNode }) {
  const [denied, setDenied] = useState<string | null>(null);
  const onDenied = useCallback((message: string) => setDenied(message), []);
  return denied ? <div className="space-y-4 rounded-xl border border-rose-300 p-5"><p role="alert">{denied}</p><Button type="button" onClick={retry}>Ponovo proveri pristup</Button></div> : children({ client, capabilities, onDenied });
}
export function EditorialPrivatePage({ storyId, title, children }: { storyId: string; title: string; children: (access: PrivatePageAccess) => ReactNode }) {
  const access = useEditorialAccess(); const { isDemoMode } = useDemoData();
  const readable = !isDemoMode && access.state === "ready" && access.capabilities?.permissions.includes("editorial:read");
  return <section lang="sr-Latn" className="space-y-6"><h2 className="text-3xl font-bold">{title}</h2><EditorialNavigation storyId={storyId} />
    {!readable ? <EditorialAccessBanner storyId={storyId} /> : !isUuid(storyId) ? <p role="alert">Potreban je trajno sačuvan identifikator priče.</p> : access.client && access.capabilities ? <Authorized key={`${access.sessionKey}:${storyId}`} client={access.client} capabilities={access.capabilities} retry={access.refresh}>{children}</Authorized> : null}
  </section>;
}

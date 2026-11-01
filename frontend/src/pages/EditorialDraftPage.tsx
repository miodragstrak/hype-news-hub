import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useBeforeUnload, useBlocker, useParams } from "react-router-dom";
import { EditorialAccessBanner } from "../components/EditorialAccessBanner";
import { ConfirmDiscardDialog } from "../components/ConfirmDiscardDialog";
import { EditorialFormFields } from "../components/EditorialFormFields";
import { EditorialSourceEvidence } from "../components/EditorialSourceEvidence";
import { EditorialNavigation } from "../components/EditorialNavigation";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { useEditorialAccess } from "../context/EditorialAccessContext";
import { canonicalJson, emptyForm, formFromPayload, isUuid, newCommandId, readPublishingPayload, validateForm, type EditorialForm, type FormErrors } from "../lib/editorialForm";
import { EditorialApi, EditorialApiError, editorialErrorMessage } from "../services/editorialApi";
import type { CreateDraftCommand, EditorialDraft, EditorialReceipt, PublishingPayload, SaveRevisionCommand, StorySource } from "../types/editorial";

type Intent = { kind: "create" | "save"; draftId: string | null; command: CreateDraftCommand | SaveRevisionCommand; receipt: EditorialReceipt | null };
type DraftOperation = { kind: "save" | "reload" | "compare"; signal: AbortSignal; inputRevision: number };

function checkedDraft(value: EditorialDraft, storyId: string): EditorialDraft {
  if (!isUuid(value?.id) || value.story_id !== storyId || value.target_locale !== "sr-Latn" || !Number.isSafeInteger(value.revision) || value.revision < 1 || !["editing", "in_review", "changes_requested", "approved", "rejected"].includes(value.status)) throw new EditorialApiError(502, "Invalid saved draft response.");
  const version = value.current_version;
  if (version !== null && (!version || typeof version !== "object" || !Array.isArray(version.sources))) throw new EditorialApiError(502, "Invalid saved version response.");
  if (version && (version.payload_schema_version !== 1 || !readPublishingPayload(version.payload))) throw new Error("This saved version uses an unsupported publishing payload. Editing is unavailable; contact a newsroom administrator.");
  if (version && (!isUuid(version.id) || !Number.isSafeInteger(version.version_number) || version.version_number < 1 || typeof version.content_hash !== "string" || !/^[0-9a-f]{64}$/.test(version.content_hash) || version.sources.some(row => !row || !isUuid(row.id) || !isUuid(row.article_id) || !isUuid(row.source_id) || typeof row.source_name !== "string" || typeof row.input_text !== "string" || typeof row.source_url !== "string" || typeof row.original_url !== "string" || typeof row.captured_at !== "string" || typeof row.snapshot_hash !== "string" || !/^[0-9a-f]{64}$/.test(row.snapshot_hash)))) throw new EditorialApiError(502, "Invalid frozen evidence response.");
  return value;
}

function checkedSources(value: StorySource[]): StorySource[] {
  if (!Array.isArray(value) || value.some(row => !row || !isUuid(row.article_id) || !isUuid(row.source_id) || typeof row.source_name !== "string" || typeof row.title !== "string" || typeof row.excerpt !== "string" || [row.source_url, row.original_url, row.canonical_url, row.published_at].some(field => field !== null && typeof field !== "string"))) throw new EditorialApiError(502, "Invalid source response.");
  return value;
}

export function EditorialDraftPage() {
  const { storyId = "" } = useParams();
  const access = useEditorialAccess();
  const { isDemoMode } = useDemoData();
  const readable = !isDemoMode && access.state === "ready" && access.capabilities?.permissions.includes("editorial:read");
  return <section className="space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-3xl font-bold text-white">Manual editorial draft</h2><p className="mt-2 text-[#c2d3f5]">Serbian Latin · private version history · Save when ready</p></div><Link className="font-semibold text-[#f5c518] underline" to={`/review/${encodeURIComponent(storyId)}`}>Public story preview</Link></header>
    <EditorialNavigation storyId={storyId} />
    {!readable ? <EditorialAccessBanner storyId={storyId} /> : !isUuid(storyId) ? <p role="alert">Production editing requires a persisted story. This preview story cannot create a production draft.</p> : access.client ? <DraftWorkspace key={`${access.sessionKey}:${storyId}`} client={access.client} storyId={storyId} canEdit={Boolean(access.capabilities?.commands_enabled && access.capabilities.permissions.includes("editorial:edit"))} retryAccess={access.refresh} /> : null}
  </section>;
}

function DraftWorkspace({ client, storyId, canEdit, retryAccess }: { client: EditorialApi; storyId: string; canEdit: boolean; retryAccess: () => void }) {
  const [draft, setDraft] = useState<EditorialDraft | null>(null);
  const [form, setForm] = useState<EditorialForm | null>(null);
  const [baseline, setBaseline] = useState("");
  const baselinePayload = useRef<PublishingPayload | null>(null);
  const [sources, setSources] = useState<StorySource[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [operationKind, setOperationKind] = useState<DraftOperation["kind"] | null>(null);
  const operation = useRef<DraftOperation | null>(null);
  const inputRevision = useRef(0);
  const active = useRef(false);
  const controller = useRef<AbortController>();
  const [intent, setIntent] = useState<Intent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<FormErrors>({});
  const [conflict, setConflict] = useState<{ latest: EditorialDraft | null } | null>(null);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const errorSummary = useRef<HTMLDivElement>(null);
  const dirty = Boolean(form && canonicalJson(form) !== baseline);
  const saving = operationKind === "save";
  const guarded = dirty || Boolean(intent) || operationKind !== null;
  const blocker = useBlocker(guarded);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => { if (guarded) { event.preventDefault(); event.returnValue = ""; } }, [guarded]));
  useEffect(() => { if (accessDenied && blocker.state === "blocked") blocker.reset(); }, [accessDenied, blocker]);

  const handleError = useCallback((reason: unknown) => {
    setError(reason instanceof EditorialApiError ? editorialErrorMessage(reason) : reason instanceof Error ? reason.message : "The editorial request failed.");
    if (reason instanceof EditorialApiError && [401, 403].includes(reason.status)) {
      // Private content must not survive loss of authorized access in the DOM.
      controller.current?.abort(); operation.current = null; setOperationKind(null);
      baselinePayload.current = null; setReplaceOpen(false);
      setAccessDenied(true); setForm(null); setDraft(null); setSources([]); setIntent(null); setBaseline(""); setConflict(null);
    }
  }, []);

  const apply = useCallback((head: EditorialDraft | null) => {
    const payload = head?.current_version ? readPublishingPayload(head.current_version.payload) : null;
    const next = payload ? formFromPayload(payload) : emptyForm();
    inputRevision.current += 1;
    setDraft(head); setForm(next); setBaseline(canonicalJson(next)); baselinePayload.current = payload;
    setIntent(null); setConflict(null); setErrors({}); setError(null);
  }, []);

  const find = useCallback(async (signal: AbortSignal): Promise<EditorialDraft | null> => {
    try { return checkedDraft(await client.find(storyId, signal), storyId); }
    catch (reason) { if (reason instanceof EditorialApiError && reason.status === 404) return null; throw reason; }
  }, [client, storyId]);

  useEffect(() => {
    const abort = new AbortController(); controller.current = abort; active.current = true;
    void Promise.all([find(abort.signal), client.sources(storyId, 0, abort.signal).then(checkedSources)]).then(([head, rows]) => {
      if (!abort.signal.aborted) { apply(head); setSources(rows); setOffset(rows.length); setHasMore(rows.length === 50); }
    }).catch(reason => { if (!abort.signal.aborted) handleError(reason); }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => { active.current = false; operation.current = null; abort.abort(); };
  }, [client, storyId, find, apply, handleError]);

  function begin(kind: DraftOperation["kind"]): DraftOperation | null {
    const signal = controller.current?.signal;
    if (!active.current || !signal || signal.aborted || operation.current) return null;
    // The ref closes the gap before React renders disabled controls.
    const next = { kind, signal, inputRevision: inputRevision.current };
    operation.current = next; setOperationKind(kind);
    return next;
  }
  function owns(pending: DraftOperation) {
    return active.current && !pending.signal.aborted && operation.current === pending;
  }
  function finish(pending: DraftOperation) {
    if (operation.current === pending) { operation.current = null; if (active.current) setOperationKind(null); }
  }

  async function replaceLatest() {
    const pending = begin("reload"); if (!pending) return;
    setReplaceOpen(false); setError(null); setMessage(null);
    try {
      const latest = await find(pending.signal);
      if (!owns(pending)) return;
      if (inputRevision.current !== pending.inputRevision) { setError("Local input changed while reloading. Your edits were kept; reload again when ready."); return; }
      apply(latest); setMessage("Loaded the latest saved draft. Local edits were replaced at your request.");
    } catch (reason) { if (owns(pending)) handleError(reason); }
    finally { finish(pending); }
  }

  async function compareLatest() {
    const pending = begin("compare"); if (!pending) return;
    setError(null);
    try { const latest = await find(pending.signal); if (owns(pending)) setConflict({ latest }); }
    catch (reason) { if (owns(pending)) handleError(reason); }
    finally { finish(pending); }
  }

  async function save() {
    if (!form || !canEdit || operation.current || conflict || draft?.status === "in_review" || draft?.status === "rejected") return;
    setError(null); setMessage(null);
    let pending = intent;
    if (!pending) {
      const result = validateForm(form); setErrors(result.errors);
      if (Object.keys(result.errors).length) { setTimeout(() => errorSummary.current?.focus(), 0); return; }
      if (baselinePayload.current && canonicalJson(result.payload) === canonicalJson(baselinePayload.current)) {
        const next = formFromPayload(result.payload); setForm(next); setBaseline(canonicalJson(next));
        setMessage("No content changed after trimming. No new version was created."); return;
      }
      try {
        pending = draft ? { kind: "save", draftId: draft.id, receipt: null, command: { command_id: newCommandId(), expected_revision: draft.revision, payload: result.payload } } :
          { kind: "create", draftId: null, receipt: null, command: { command_id: newCommandId(), expected_revision: 0, story_id: storyId, target_locale: "sr-Latn", payload: result.payload } };
      } catch (reason) { handleError(reason); return; }
    }
    const current = begin("save"); if (!current) return;
    setIntent(pending); setReplaceOpen(false);
    try {
      if (!pending.receipt) {
        const receipt = pending.kind === "create" ? await client.create(pending.command as CreateDraftCommand, current.signal) : await client.save(pending.draftId!, pending.command, current.signal);
        if (!owns(current)) return;
        if (!receipt || receipt.command_id !== pending.command.command_id || !isUuid(receipt.draft_id) || receipt.status !== "editing" || receipt.revision !== pending.command.expected_revision + 1 || !Number.isInteger(receipt.version_number) || receipt.version_number < 1 || !/^[0-9a-f]{64}$/.test(receipt.content_hash)) throw new EditorialApiError(502, "Unconfirmed receipt.");
        pending = { ...pending, receipt }; setIntent(pending);
      }
      const receipt = pending.receipt;
      if (!receipt) throw new EditorialApiError(502, "Missing save receipt.");
      const head = checkedDraft(await client.draft(receipt.draft_id, current.signal), storyId);
      if (!owns(current)) return;
      if (head.revision < receipt.revision) throw new EditorialApiError(502, "Saved version has not been confirmed.");
      if (head.current_version?.version_number !== receipt.version_number || head.current_version.content_hash !== receipt.content_hash) {
        setIntent(null); setConflict({ latest: head }); setError("The server acknowledged your save, then another version became current. Your local text is intact; compare the latest saved draft."); return;
      }
      const savedPayload = readPublishingPayload(head.current_version.payload);
      if (!savedPayload || canonicalJson(savedPayload) !== canonicalJson(pending.command.payload)) throw new EditorialApiError(502, "Saved content could not be confirmed.");
      apply(head); setMessage(`Saved version ${head.current_version.version_number}. Revision ${head.revision} confirmed by the server.`);
    } catch (reason) {
      if (!owns(current)) return;
      if (reason instanceof EditorialApiError && reason.status === 409) {
        setIntent(null); setConflict({ latest: null }); handleError(reason);
        // Comparison belongs to the same operation; it cannot race a reload.
        try { const latest = await find(current.signal); if (owns(current)) setConflict({ latest }); }
        catch (comparisonError) { if (owns(current)) handleError(comparisonError); }
      } else if (reason instanceof EditorialApiError && [400, 413, 415, 422].includes(reason.status)) { setIntent(null); handleError(reason); }
      else handleError(reason);
    } finally { finish(current); }
  }

  if (accessDenied) return <Card><CardContent className="space-y-4 p-6"><p role="alert">{error} Private editorial content has been cleared.</p><Button type="button" onClick={retryAccess}>Retry editorial access</Button></CardContent></Card>;
  if (loading) return <p role="status">Loading saved editorial workspace…</p>;
  if (!form) return <Card><CardContent className="space-y-4 p-6"><p role="alert">{error || "The editorial workspace could not be loaded."}</p><Button type="button" onClick={retryAccess}>Retry editorial access</Button></CardContent></Card>;

  const frozen = draft?.current_version?.sources ?? [];
  const choices = [...sources];
  for (const row of frozen) if (!choices.some(source => source.article_id === row.article_id)) choices.push({ ...row, title: `Saved source ${row.article_id}`, excerpt: "" });
  const locked = !canEdit || operationKind !== null || Boolean(intent) || draft?.status === "in_review" || draft?.status === "rejected";
  function changeForm(next: EditorialForm) {
    if (locked || operation.current) return;
    inputRevision.current += 1; setForm(next); setMessage(null);
  }
  return <div className="space-y-5">
    <Card><CardContent className="space-y-3 p-5">
      <p className="font-semibold">{draft ? `Saved draft · ${draft.status.replace(/_/g, " ")} · version ${draft.current_version?.version_number ?? "none"} · revision ${draft.revision}` : "New manual draft · not saved"}</p>
      <p className="text-sm text-[#c2d3f5]">{canEdit ? "Save persists a private version. Open Pregled i odluke for review actions. WordPress publishing is unavailable." : "Read-only access. Creating and saving require Editor permission."}</p>
      {draft?.status === "approved" ? <p className="text-amber-100">Saving changes creates a new editing version and invalidates its current approval.</p> : null}
      {draft?.status === "in_review" || draft?.status === "rejected" ? <p className="text-amber-100">This draft cannot be edited in its current state. Review or reopening must be handled through the authorized workflow.</p> : null}
      <p role="status" className="font-semibold text-[#f5c518]">{saving ? "Saving and confirming with the server…" : operationKind === "reload" ? "Reloading saved draft… Local input is locked." : operationKind === "compare" ? "Loading comparison… Local input is locked." : intent ? "Save confirmation is incomplete. Your exact command is retained for retry; editing is paused." : dirty ? "Unsaved changes" : "No unsaved changes"}</p>
      {message ? <p role="status" className="text-emerald-200">{message}</p> : null}
      {error ? <p role="alert" className="text-rose-200">{error}</p> : null}
      <Button type="button" variant="secondary" disabled={operationKind !== null} onClick={() => { if (!operation.current) setReplaceOpen(true); }}>Reload saved draft</Button>
    </CardContent></Card>
    {conflict ? <Card><CardContent className="space-y-3 p-5"><h3 className="text-xl font-bold text-amber-100">Concurrent edit conflict</h3><p>Your local text has been preserved. Saving is paused until you explicitly load the latest saved draft.</p>
      <Button type="button" variant="secondary" disabled={operationKind !== null} onClick={() => void compareLatest()}>Compare latest saved draft</Button>
      {conflict.latest ? <details><summary className="cursor-pointer text-[#f5c518]">Latest server version {conflict.latest.current_version?.version_number} · revision {conflict.latest.revision}</summary><pre className="mt-3 whitespace-pre-wrap break-words text-sm">{JSON.stringify(conflict.latest.current_version?.payload, null, 2)}</pre></details> : <p>The latest server version has not been loaded.</p>}
      <Button type="button" disabled={operationKind !== null} onClick={() => { if (!operation.current) setReplaceOpen(true); }}>Replace local edits with latest saved draft</Button>
    </CardContent></Card> : null}
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <Card><CardContent className="p-5 sm:p-6"><form noValidate onSubmit={event => { event.preventDefault(); void save(); }} className="space-y-6" aria-label="Serbian Latin editorial form">
        <p className="text-sm text-[#c2d3f5]">Fields marked * are required. Enter plain Serbian Latin text; HTML is not supported.</p>
        {Object.keys(errors).length ? <div ref={errorSummary} tabIndex={-1} role="alert" className="rounded-xl border border-rose-300 p-4 text-rose-100"><p className="font-bold">Check the editorial form</p><ul className="mt-2 list-disc pl-5">{Object.entries(errors).map(([key, value]) => <li key={key}>{key}: {value}</li>)}</ul></div> : null}
        <EditorialFormFields form={form} errors={errors} readOnly={locked} sources={choices} onChange={changeForm} />
        <fieldset className="space-y-3 rounded-xl border border-white/20 p-4" aria-describedby={errors.sources ? "source-error" : undefined}><legend className="px-2 font-bold">Source attribution *</legend>
          <p className="text-sm text-[#c2d3f5]">Select the original articles used for this version. Saved versions keep their source evidence.</p>
          {choices.length ? choices.map(source => <label key={source.article_id} className="flex items-start gap-3 rounded-lg border border-white/15 p-3 text-sm">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-[#f5c518]" disabled={locked} checked={form.sources.some(row => row.article_id === source.article_id)} onChange={event => {
              changeForm({ ...form, sources: event.target.checked ? [...form.sources, { article_id: source.article_id, source_id: source.source_id }] : form.sources.filter(row => row.article_id !== source.article_id) });
            }} /><span><span className="font-bold">Use {source.source_name} — {source.title || source.article_id}</span><span className="mt-1 block break-all text-xs text-[#b7c9ee]">{source.original_url ?? "Original URL unavailable"}{!sources.some(row => row.article_id === source.article_id) ? " · frozen source; current summary not loaded" : ""}</span></span>
          </label>) : <p>No persisted source articles are available for this story.</p>}
          {errors.sources ? <p id="source-error" className="text-rose-200">{errors.sources}</p> : null}
          {hasMore ? <Button type="button" variant="secondary" disabled={sourceLoading || saving} onClick={async () => {
            const signal = controller.current?.signal; if (!signal || signal.aborted) return;
            setSourceLoading(true);
            try { const next = checkedSources(await client.sources(storyId, offset, signal)); if (active.current && !signal.aborted) { setSources(previous => [...previous, ...next.filter(row => !previous.some(item => item.article_id === row.article_id))]); setOffset(offset + next.length); setHasMore(next.length === 50); } }
            catch (reason) { if (active.current && !signal.aborted) handleError(reason); } finally { if (active.current && !signal.aborted) setSourceLoading(false); }
          }}>{sourceLoading ? "Loading more sources…" : "Load more sources"}</Button> : null}
        </fieldset>
        <Button type="submit" size="lg" disabled={!canEdit || operationKind !== null || Boolean(conflict) || (!dirty && !intent) || draft?.status === "in_review" || draft?.status === "rejected" || choices.length === 0}>{saving ? "Saving…" : intent?.receipt ? "Confirm saved version" : intent ? "Retry save" : draft ? "Save revision" : "Create and save draft"}</Button>
      </form></CardContent></Card>
      <div className="min-w-0"><EditorialSourceEvidence storyId={storyId} sources={sources} frozen={frozen} /></div>
    </div>
    {blocker.state === "blocked" ? <ConfirmDiscardDialog title="Leave unsaved editorial changes?" message="Local edits and unconfirmed save commands are held only in this page. Leaving discards them; an in-flight server request may still complete." confirmLabel="Discard and leave" onCancel={() => blocker.reset()} onConfirm={() => blocker.proceed()} /> : null}
    {replaceOpen ? <ConfirmDiscardDialog title="Replace local editorial text?" message="Reloading replaces your local input with the latest saved draft. Copy any text you want to keep before continuing. An unconfirmed server request may still complete." confirmLabel="Reload and replace" onCancel={() => setReplaceOpen(false)} onConfirm={() => void replaceLatest()} /> : null}
  </div>;
}

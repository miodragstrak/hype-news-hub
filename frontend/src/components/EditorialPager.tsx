import { Button } from "./ui/button";
export function EditorialPager({ offset, limit, count, busy, onPage, label, hasMore }: { offset: number; limit: number; count: number; busy: boolean; onPage: (offset: number, limit: number) => void; label: string; hasMore?: boolean }) {
  return <div className="flex flex-wrap items-center gap-3 text-sm">
    <Button type="button" variant="secondary" disabled={busy || offset === 0} onClick={() => onPage(Math.max(0, offset - limit), limit)}>Prethodna stranica</Button>
    <span role="status">{count ? `${offset + 1}–${offset + count}` : "Nema stavki na ovoj stranici"}</span>
    <Button type="button" variant="secondary" disabled={busy || !(hasMore ?? count >= limit) || offset + limit > 1_000_000} onClick={() => onPage(offset + limit, limit)}>Sledeća stranica</Button>
    <label>{label}<select className="ml-2 rounded-lg bg-[#071d49] p-2" aria-label={label} disabled={busy} value={limit} onChange={event => onPage(0, Number(event.target.value))}>{[5, 10, 20, 50].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
  </div>;
}

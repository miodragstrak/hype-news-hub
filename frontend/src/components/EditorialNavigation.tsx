import { NavLink } from "react-router-dom";
export function EditorialNavigation({ storyId }: { storyId: string }) {
  const base = `/review/${encodeURIComponent(storyId)}`;
  const links = [["/review", "Urednički red"], [`${base}/edit`, "Uređivanje nacrta"], [`${base}/history`, "Istorija verzija"], [`${base}/decisions`, "Pregled i odluke"], [`${base}/approved`, "Odobreni pregled"]];
  return <nav aria-label="Urednički tok" lang="sr-Latn" className="flex flex-wrap gap-3 rounded-xl border border-white/20 p-4 text-sm">{links.map(([to, label]) => <NavLink key={to} end to={to} className={({ isActive }) => `rounded-lg px-3 py-2 font-semibold underline focus:outline-none focus:ring-2 focus:ring-[#f5c518] ${isActive ? "bg-[#f5c518] text-[#07173d]" : "text-[#f5c518]"}`}>{label}</NavLink>)}</nav>;
}

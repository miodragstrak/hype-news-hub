import type { Attribution, EditorialImage, PublishingPayload } from "../types/editorial";

export const isUuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export type EditorialForm = {
  headline: string; body: string; excerpt: string; slug: string; categories: string[]; tags: string[];
  seoTitle: string; seoDescription: string; images: EditorialImage[]; sources: Attribution[];
};
export type FormErrors = Record<string, string>;
export function canonicalJson(value: unknown): string {
  const sort = (item: unknown): unknown => Array.isArray(item) ? item.map(sort) : item && typeof item === "object" ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, sort(entry)])) : item;
  return JSON.stringify(sort(value));
}
export const emptyForm = (): EditorialForm => ({ headline: "", body: "", excerpt: "", slug: "", categories: [""], tags: [], seoTitle: "", seoDescription: "", images: [], sources: [] });
export const formFromPayload = (payload: PublishingPayload): EditorialForm => ({ headline: payload.headline, body: payload.body, excerpt: payload.excerpt, slug: payload.slug, categories: [...payload.categories], tags: [...payload.tags], seoTitle: payload.seo.title, seoDescription: payload.seo.description, images: payload.images.map(image => ({ ...image })), sources: payload.source_attribution.map(source => ({ ...source })) });

// Match PublishingPayload's Pydantic Text(strip_whitespace=True), before the
// command is frozen. Unlike JS trim, this removes NEL and preserves FEFF. Python's
// extra U+001C–U+001F whitespace is rejected by Text, not stripped by Pydantic.
export const normalizeEditorialText = (value: string): string => value.replace(/^[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, "");

export function safeLink(value: string | null): string | null {
  if (!value || /[\x00-\x20\x7f]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || (url.port && !["80", "443"].includes(url.port))) return null;
    if (url.hostname === "localhost" || url.hostname.endsWith(".localhost")) return null;
    return url.href;
  } catch { return null; }
}

export function validateForm(form: EditorialForm): { payload: PublishingPayload; errors: FormErrors } {
  const errors: FormErrors = {};
  function text(key: string, value: string, maximum: number, trim = true): string {
    const result = trim ? normalizeEditorialText(value) : value;
    if (!result) errors[key] = "This field is required.";
    else if ([...result].length > maximum) errors[key] = `Use at most ${maximum} characters.`;
    else if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]|<[!?/a-zA-Z]/u.test(result)) errors[key] = "Use plain text without HTML or control characters.";
    else if (/[\u0400-\u052f]/u.test(result)) errors[key] = "Use Serbian Latin script.";
    return result;
  }
  function labels(key: string, values: string[], max: number, required: boolean): string[] {
    if ((required && !values.length) || values.length > max) errors[key] = `Enter ${required ? "1" : "0"}–${max} labels, one per box.`;
    values.forEach((item, index) => {
      const field = `${key}-${index}`;
      text(field, item, 100, false);
      // Preserve labels exactly. A valid command can contain only labels that
      // Pydantic will also preserve; padding requires an explicit editor change.
      if (normalizeEditorialText(item) !== item) errors[field] = "Remove leading or trailing whitespace from this label.";
    });
    if (new Set(values.map(item => item.toLowerCase())).size !== values.length) errors[key] = "Remove duplicate labels.";
    return [...values];
  }
  const payload: PublishingPayload = {
    headline: text("headline", form.headline, 300), body: text("body", form.body, 100000), excerpt: text("excerpt", form.excerpt, 1000),
    slug: form.slug.trim(), categories: labels("categories", form.categories, 20, true), tags: labels("tags", form.tags, 50, false),
    seo: { title: text("seoTitle", form.seoTitle, 120), description: text("seoDescription", form.seoDescription, 320) },
    images: form.images.map((image, index) => {
      const url = image.url.trim();
      if (!safeLink(url) || url.length > 2048) errors[`image-${index}-url`] = "Enter an HTTP(S) image URL without credentials (maximum 2048 characters).";
      if (!form.sources.some(source => source.article_id === image.source_article_id)) errors[`image-${index}-source`] = "Choose a selected source article for this image.";
      return { url, alt: text(`image-${index}-alt`, image.alt, 300), credit: text(`image-${index}-credit`, image.credit, 300), source_article_id: image.source_article_id };
    }),
    source_attribution: form.sources.map(source => ({ ...source })),
  };
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(payload.slug) || payload.slug.length > 200) errors.slug = "Use lowercase ASCII letters, digits and single hyphens, up to 200 characters.";
  if (!form.sources.length || form.sources.length > 100 || form.sources.some(source => !isUuid(source.article_id) || !isUuid(source.source_id)) || new Set(form.sources.map(source => source.article_id)).size !== form.sources.length) errors.sources = "Choose 1–100 source articles using their stable article identities.";
  if (form.images.length > 10) errors.images = "At most 10 image references are supported.";
  return { payload, errors };
}

export function readPublishingPayload(input: unknown): PublishingPayload | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const value = input as Record<string, unknown>;
  // Refuse unsupported/legacy shapes rather than dropping unknown publishing fields.
  const keys = ["headline", "body", "excerpt", "slug", "categories", "tags", "seo", "images", "source_attribution"];
  if (Object.keys(value).length !== keys.length || keys.some(key => !(key in value))) return null;
  if (!["headline", "body", "excerpt", "slug"].every(key => typeof value[key] === "string")) return null;
  if (![value.categories, value.tags].every(list => Array.isArray(list) && list.every(item => typeof item === "string"))) return null;
  const seo = value.seo as Record<string, unknown> | null;
  if (!seo || Object.keys(seo).length !== 2 || typeof seo.title !== "string" || typeof seo.description !== "string") return null;
  if (!Array.isArray(value.images) || value.images.some(image => !image || Object.keys(image).length !== 4 || ![image.url, image.alt, image.credit, image.source_article_id].every(item => typeof item === "string"))) return null;
  if (!Array.isArray(value.source_attribution) || value.source_attribution.some(source => !source || Object.keys(source).length !== 2 || !isUuid(source.article_id) || !isUuid(source.source_id))) return null;
  return value as PublishingPayload;
}

export function newCommandId(): string {
  if (!globalThis.crypto?.randomUUID) throw new Error("A secure browser context is required to save editorial commands.");
  return crypto.randomUUID();
}

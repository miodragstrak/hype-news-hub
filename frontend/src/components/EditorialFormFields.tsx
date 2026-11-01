import type { EditorialForm, FormErrors } from "../lib/editorialForm";
import type { StorySource } from "../types/editorial";
import { Button } from "./ui/button";

const fieldClass = "mt-2 block w-full rounded-xl border border-white/30 bg-[#071d49] px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-[#f5c518] read-only:opacity-80";

export function EditorialFormFields({ form, errors, readOnly, sources, onChange }: { form: EditorialForm; errors: FormErrors; readOnly: boolean; sources: StorySource[]; onChange: (form: EditorialForm) => void }) {
  function field(key: keyof Pick<EditorialForm, "headline" | "body" | "excerpt" | "slug" | "seoTitle" | "seoDescription">, label: string, rows: number, maximum: number, required = true) {
    return <label className="block text-sm font-semibold text-[#dbe6ff]" key={key}>
      {label}{required ? " *" : ""}
      <textarea id={`editor-${key}`} name={key} value={form[key]} rows={rows} maxLength={maximum * 2} required={required} readOnly={readOnly} lang="sr-Latn" aria-invalid={Boolean(errors[key])} aria-describedby={errors[key] ? `error-${key}` : undefined} className={fieldClass} onChange={event => onChange({ ...form, [key]: event.target.value })} />
      {errors[key] ? <span id={`error-${key}`} className="mt-1 block text-rose-200">{errors[key]}</span> : null}
    </label>;
  }
  function labels(key: "categories" | "tags", singular: string, maximum: number) {
    return <fieldset className="space-y-3 rounded-xl border border-white/20 p-4" aria-describedby={`${key}-hint`}>
      <legend className="px-2 font-bold">{key === "categories" ? "Categories *" : "Tags"}</legend>
      <p id={`${key}-hint`} className="text-sm text-[#c2d3f5]">Each box is one label. Line breaks and commas remain part of that label.</p>
      {form[key].map((value, index) => <div key={index} className="space-y-2">
        <label className="block text-sm font-semibold text-[#dbe6ff]">{singular} {index + 1} *
          <textarea id={`editor-${key}-${index}`} rows={2} value={value} maxLength={200} required readOnly={readOnly} lang="sr-Latn" className={fieldClass} aria-invalid={Boolean(errors[`${key}-${index}`])} aria-describedby={errors[`${key}-${index}`] ? `error-${key}-${index}` : undefined} onChange={event => onChange({ ...form, [key]: form[key].map((item, position) => position === index ? event.target.value : item) })} />
        </label>
        {errors[`${key}-${index}`] ? <p id={`error-${key}-${index}`} className="text-sm text-rose-200">{errors[`${key}-${index}`]}</p> : null}
        <Button type="button" variant="secondary" disabled={readOnly} onClick={() => onChange({ ...form, [key]: form[key].filter((_, position) => position !== index) })}>Remove {singular.toLowerCase()} {index + 1}</Button>
      </div>)}
      {!form[key].length ? <p className="text-sm text-[#c2d3f5]">No {key} selected.</p> : null}
      <Button type="button" variant="secondary" disabled={readOnly || form[key].length >= maximum} onClick={() => onChange({ ...form, [key]: [...form[key], ""] })}>Add {singular.toLowerCase()}</Button>
      {errors[key] ? <p role="alert" className="text-rose-200">{errors[key]}</p> : null}
    </fieldset>;
  }
  const selected = sources.filter(source => form.sources.some(pair => pair.article_id === source.article_id));
  return <div className="space-y-5">
    {field("headline", "Headline", 2, 300)}
    {field("body", "Body", 14, 100000)}
    {field("excerpt", "Excerpt", 3, 1000)}
    {field("slug", "Slug", 1, 200)}
    <div className="grid gap-5 md:grid-cols-2">{labels("categories", "Category", 20)}{labels("tags", "Tag", 50)}</div>
    <fieldset className="space-y-4 rounded-xl border border-white/20 p-4"><legend className="px-2 font-bold">SEO metadata</legend>{field("seoTitle", "SEO title", 2, 120)}{field("seoDescription", "SEO description", 3, 320)}</fieldset>
    <fieldset className="space-y-4 rounded-xl border border-white/20 p-4"><legend className="px-2 font-bold">Image references</legend>
      <p className="text-sm text-[#c2d3f5]">The first reference is the featured image. Images are not downloaded here. Supply source attribution and credit for each reference.</p>
      {form.images.map((image, index) => <div key={index} className="space-y-3 rounded-xl border border-white/20 p-4">
        <h3 className="font-semibold">{index === 0 ? "Featured image" : `Image ${index + 1}`}</h3>
        {(["url", "alt", "credit"] as const).map(key => <label key={key} className="block text-sm">{index === 0 ? "Featured image" : `Image ${index + 1}`} {key === "url" ? "URL" : key === "alt" ? "alternative text" : "credit"} *
          <textarea rows={1} value={image[key]} readOnly={readOnly} className={fieldClass} aria-invalid={Boolean(errors[`image-${index}-${key}`])} aria-describedby={errors[`image-${index}-${key}`] ? `error-image-${index}-${key}` : undefined} onChange={event => onChange({ ...form, images: form.images.map((row, position) => position === index ? { ...row, [key]: event.target.value } : row) })} />
          {errors[`image-${index}-${key}`] ? <span id={`error-image-${index}-${key}`} className="block text-rose-200">{errors[`image-${index}-${key}`]}</span> : null}
        </label>)}
        <label className="block text-sm">Image {index + 1} source article *<select className={fieldClass} disabled={readOnly} value={image.source_article_id} aria-invalid={Boolean(errors[`image-${index}-source`])} aria-describedby={errors[`image-${index}-source`] ? `error-image-${index}-source` : undefined} onChange={event => onChange({ ...form, images: form.images.map((row, position) => position === index ? { ...row, source_article_id: event.target.value } : row) })}>
          <option value="">Choose a selected source</option>{selected.map(source => <option key={source.article_id} value={source.article_id}>{source.source_name} — {source.title || source.article_id}</option>)}
        </select>{errors[`image-${index}-source`] ? <span id={`error-image-${index}-source`} className="text-rose-200">{errors[`image-${index}-source`]}</span> : null}</label>
        <Button type="button" variant="secondary" disabled={readOnly} onClick={() => onChange({ ...form, images: form.images.filter((_, position) => position !== index) })}>Remove image {index + 1}</Button>
      </div>)}
      <Button type="button" variant="secondary" disabled={readOnly || form.images.length >= 10} onClick={() => onChange({ ...form, images: [...form.images, { url: "", alt: "", credit: "", source_article_id: "" }] })}>Add image reference</Button>
      {errors.images ? <p className="text-rose-200">{errors.images}</p> : null}
    </fieldset>
  </div>;
}

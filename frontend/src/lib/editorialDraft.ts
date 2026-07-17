import type { EditorialDraftPackage } from "../context/DemoDataContext";
import type { EditorialStoryWorkspace } from "../types/news";

export const PREPARED_DURING_PROCESSING = "To be prepared during editorial processing";
export const FUTURE_ARTICLE_BODY = "The final Serbian editorial article will appear here after language processing and editorial preparation.";

const languageLabels: Record<string, string> = {
  sr: "Serbian",
  hr: "Croatian",
  bs: "Bosnian",
  sl: "Slovenian",
  mk: "Macedonian"
};

const countryFlags: Record<string, string> = {
  RS: "RS",
  HR: "HR",
  BA: "BA",
  SI: "SI",
  MK: "MK"
};

export function languageLabel(language: string | null): string {
  if (!language) {
    return "Unknown";
  }

  return languageLabels[language] ?? language.toUpperCase();
}

export function flagLabel(country: string): string {
  return countryFlags[country] ?? "Global";
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 72);
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

export function buildDraftPackage(workspace: EditorialStoryWorkspace): EditorialDraftPackage {
  const primaryArticle = workspace.source_articles[0];
  const categories = uniqueValues(workspace.source_articles.flatMap((article) => article.categories));
  const headline = workspace.headline || primaryArticle?.title || PREPARED_DURING_PROCESSING;
  const excerpt = workspace.serbian_draft.excerpt || primaryArticle?.excerpt || PREPARED_DURING_PROCESSING;
  const category = categories[0] ?? PREPARED_DURING_PROCESSING;
  const tags = uniqueValues([category, workspace.editorial_intelligence.coverage, "Hype World News", "Editorial Draft"]).filter(
    (tag) => tag !== PREPARED_DURING_PROCESSING
  );

  return {
    storyId: workspace.story_id,
    headline: workspace.serbian_draft.headline || headline,
    slug: headline === PREPARED_DURING_PROCESSING ? PREPARED_DURING_PROCESSING : slugify(headline),
    category,
    featuredImage: primaryArticle?.featured_image ?? null,
    excerpt,
    mainContent: workspace.serbian_draft.content || FUTURE_ARTICLE_BODY,
    categories: categories.length > 0 ? categories : [PREPARED_DURING_PROCESSING],
    tags: tags.length > 0 ? tags : [PREPARED_DURING_PROCESSING],
    seoTitle: headline === PREPARED_DURING_PROCESSING ? PREPARED_DURING_PROCESSING : `${headline} | Hype World News`,
    seoDescription: excerpt === PREPARED_DURING_PROCESSING ? PREPARED_DURING_PROCESSING : excerpt.slice(0, 156),
    sourcesUsed: workspace.source_articles.map((article) => ({
      id: article.external_id,
      countryFlag: flagLabel(article.country),
      sourceName: article.source,
      originalLanguage: languageLabel(article.language),
      originalHeadline: article.title || PREPARED_DURING_PROCESSING,
      url: article.url
    }))
  };
}

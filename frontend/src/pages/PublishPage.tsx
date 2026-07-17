import { motion } from "framer-motion";
import { CheckCircle2, FileText, ImageIcon, Tag, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { NextStepPanel } from "../components/NextStepPanel";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData, type EditorialDraftPackage } from "../context/DemoDataContext";

const PREPARED_DURING_PROCESSING = "To be prepared during editorial processing";

export function PublishPage(): JSX.Element {
  const { collectionResult, sources, selectedDraftPackage } = useDemoData();
  const [isDraftPreviewOpen, setIsDraftPreviewOpen] = useState(false);

  const collected = collectionResult?.articles_total ?? 0;
  const sourcesProcessed = collectionResult?.sources_processed ?? sources.length;
  const storiesCreated = collectionResult?.stories_total ?? 0;

  const summary = [
    { label: "Sources processed", value: sourcesProcessed },
    { label: "Articles collected", value: collected },
    { label: "Stories created", value: storiesCreated },
    { label: "Publishing destination", value: "Central Hype WordPress Portal" },
    { label: "CMS", value: "WordPress" },
    { label: "Status", value: "Ready for Draft Creation Preview" }
  ];

  const packageRows = selectedDraftPackage
    ? [
        { label: "Headline", value: selectedDraftPackage.headline },
        { label: "Slug", value: selectedDraftPackage.slug },
        { label: "Category", value: selectedDraftPackage.category },
        { label: "Excerpt", value: selectedDraftPackage.excerpt },
        { label: "Main content", value: selectedDraftPackage.mainContent },
        { label: "Tags", value: selectedDraftPackage.tags.join(", ") },
        { label: "SEO title", value: selectedDraftPackage.seoTitle },
        { label: "SEO description", value: selectedDraftPackage.seoDescription }
      ]
    : [];

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Publishing Preview</h2>
        <p className="text-[#c2d3f5]">Preview the exact editorial package that will later be sent to WordPress as a draft.</p>
        <p className="text-sm text-[#b5c8ed]">No publishing request is made from this preview.</p>
      </header>

      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
        <Card className="border-[#f5c518]/45 bg-[#0a285f]">
          <CardHeader>
            <CardDescription>Publishing Package Summary</CardDescription>
            <CardTitle className="text-3xl text-white">Ready for Draft Creation Preview</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {summary.map((item) => (
                <div key={item.label} className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
                  <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">{item.label}</p>
                  <p className="mt-2 break-words text-lg font-semibold text-white">{item.value}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <Card className="border-[#f5c518]/45 bg-[#12357a]">
        <CardContent className="flex flex-col gap-4 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-2xl font-bold text-white">Preview on Hype Portal</h3>
            <p className="mt-2 text-sm leading-6 text-[#dbe6ff]">See how readers will experience this article on the Hype website.</p>
          </div>
          {selectedDraftPackage ? (
            <Button asChild size="lg">
              <Link to={`/portal-preview/${encodeURIComponent(selectedDraftPackage.storyId)}`}>Preview on Hype Portal</Link>
            </Button>
          ) : (
            <Button size="lg" type="button" disabled>
              Preview on Hype Portal
            </Button>
          )}
        </CardContent>
      </Card>

      {!selectedDraftPackage ? (
        <Card className="border-amber-400/35 bg-amber-400/10">
          <CardContent className="space-y-4 p-6">
            <h3 className="text-2xl font-bold text-amber-50">No editorial draft selected.</h3>
            <p className="text-sm leading-7 text-amber-50/90">Open an editorial story, review the draft package, then continue to Publishing Preview.</p>
            <Button asChild>
              <Link to="/review">Back to Editorial Review</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[0.82fr_1.18fr]">
          <Card className="h-fit">
            <CardHeader>
              <CardDescription>Publishing Destination</CardDescription>
              <CardTitle className="text-3xl text-white">Central Hype WordPress Portal</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                <InfoTile label="CMS" value="WordPress" />
                <InfoTile label="Status" value="Ready for Draft Creation Preview" />
                <InfoTile label="Destination" value="Central Hype WordPress Portal" />
              </div>

              <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
                <p className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                  <CheckCircle2 className="h-4 w-4 text-emerald-300" />
                  Human approval remains required.
                </p>
                <p className="mt-2 text-sm leading-6 text-[#c2d3f5]">This package is a draft creation preview only. It does not publish or create a WordPress post.</p>
              </div>

              <Button size="lg" type="button" onClick={() => setIsDraftPreviewOpen(true)}>
                Preview WordPress Draft
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Article</CardDescription>
              <CardTitle className="text-3xl text-white">Publishing Package</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
                <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">
                  <ImageIcon className="h-4 w-4" />
                  Featured image
                </p>
                <FeaturedImagePreview src={selectedDraftPackage.featuredImage} />
              </div>

              {packageRows.map((row) => (
                <PackageField key={row.label} label={row.label} value={row.value} />
              ))}

              <SourcesUsed packageData={selectedDraftPackage} />
            </CardContent>
          </Card>
        </div>
      )}

      <NextStepPanel
        message={selectedDraftPackage ? "Preview the WordPress draft package. Real draft creation remains disabled for this demo." : "Select an editorial draft before finishing the publishing preview."}
        ctaLabel={selectedDraftPackage ? "Finish Demo" : "Back to Editorial Review"}
        ctaTo={selectedDraftPackage ? undefined : "/review"}
        onAction={selectedDraftPackage ? () => undefined : undefined}
      />

      <PublishingPackageModal
        isOpen={isDraftPreviewOpen}
        packageData={selectedDraftPackage}
        onClose={() => setIsDraftPreviewOpen(false)}
      />
    </section>
  );
}

function InfoTile({ label, value }: { label: string; value: string | number }): JSX.Element {
  return (
    <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
      <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">{label}</p>
      <p className="mt-2 break-words text-lg font-semibold text-white">{value}</p>
    </div>
  );
}

function PackageField({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
      <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">
        {label === "Tags" ? <Tag className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
        {label}
      </p>
      <p className="mt-3 whitespace-pre-line break-words text-sm leading-7 text-[#eef4ff]">{value || PREPARED_DURING_PROCESSING}</p>
    </div>
  );
}

function SourcesUsed({ packageData }: { packageData: EditorialDraftPackage }): JSX.Element {
  return (
    <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
      <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Sources used</p>
      <div className="mt-4 grid gap-3">
        {packageData.sourcesUsed.length > 0 ? (
          packageData.sourcesUsed.map((source) => (
            <div key={source.id} className="rounded-2xl border border-white/15 bg-[#0a285f] p-4">
              <p className="font-semibold text-white">{source.countryFlag} {source.sourceName}</p>
              <p className="mt-1 text-sm text-[#c2d3f5]">Original Language: {source.originalLanguage}</p>
              <p className="mt-3 text-sm leading-6 text-[#eef4ff]">{source.originalHeadline}</p>
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-[#f5c518] hover:text-[#ffe27a]">
                Open Original Article
              </a>
            </div>
          ))
        ) : (
          <p className="text-sm text-[#dbe6ff]">Source attribution will be prepared during editorial processing.</p>
        )}
      </div>
    </div>
  );
}

type PublishingPackageModalProps = {
  isOpen: boolean;
  packageData: EditorialDraftPackage | null;
  onClose: () => void;
};

function PublishingPackageModal({ isOpen, packageData, onClose }: PublishingPackageModalProps): JSX.Element | null {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#020817]/80 px-4 py-6 backdrop-blur-sm" onMouseDown={onClose}>
      <motion.section
        role="dialog"
        aria-modal="true"
        aria-labelledby="publishing-package-title"
        aria-describedby="publishing-package-subtitle"
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.2 }}
        className="max-h-[90vh] w-full max-w-5xl overflow-y-auto rounded-[24px] border border-white/20 bg-[#0b2a67] shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-white/15 bg-[#0b2a67]/95 px-5 py-4 backdrop-blur sm:px-7">
          <div>
            <h3 id="publishing-package-title" className="text-2xl font-bold text-white">
              Publishing Package
            </h3>
            <p id="publishing-package-subtitle" className="mt-1 text-sm text-[#c2d3f5]">
              This package will later be sent to WordPress as a draft after editorial approval.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/20 bg-[#08245a] text-white transition hover:border-[#f5c518] hover:text-[#f5c518] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f5c518]"
            aria-label="Close Preview"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 p-5 sm:p-7">
          {!packageData ? (
            <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-6">
              <p className="text-xl font-semibold text-amber-50">No editorial draft selected.</p>
              <p className="mt-2 text-sm leading-6 text-amber-50/90">Return to editorial review and continue with a draft before previewing the publishing package.</p>
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <InfoTile label="Status" value="Ready for Draft Creation Preview" />
                <InfoTile label="Destination" value="Central Hype WordPress Portal" />
                <InfoTile label="CMS" value="WordPress" />
              </div>

              <div className="rounded-2xl border border-white/20 bg-[#08245a] p-5">
                <p className="text-xs uppercase tracking-[0.15em] text-[#b7c9ee]">Featured image</p>
                <FeaturedImagePreview src={packageData.featuredImage} />
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                {[
                  { label: "Headline", value: packageData.headline },
                  { label: "Slug", value: packageData.slug },
                  { label: "Category", value: packageData.category },
                  { label: "Excerpt", value: packageData.excerpt },
                  { label: "Main content", value: packageData.mainContent },
                  { label: "Tags", value: packageData.tags.join(", ") },
                  { label: "SEO title", value: packageData.seoTitle },
                  { label: "SEO description", value: packageData.seoDescription }
                ].map((row) => (
                  <div key={row.label} className={row.label === "Main content" ? "lg:col-span-2" : ""}>
                    <PackageField label={row.label} value={row.value} />
                  </div>
                ))}
              </div>

              <SourcesUsed packageData={packageData} />
            </>
          )}

          <div className="flex flex-col gap-3 border-t border-white/15 pt-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <Button type="button" variant="secondary" onClick={onClose}>
              Close Preview
            </Button>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button asChild type="button" variant="accent">
                <Link to="/review">Back to Editorial Review</Link>
              </Button>
              <Button type="button" disabled>
                Create WordPress Draft - Coming Soon
              </Button>
            </div>
          </div>
        </div>
      </motion.section>
    </div>
  );
}

function FeaturedImagePreview({ src }: { src: string | null }): JSX.Element {
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    setHasFailed(false);
  }, [src]);

  if (!src || hasFailed) {
    return (
      <div className="mt-4 flex min-h-44 items-center justify-center rounded-2xl border border-dashed border-white/25 bg-[#0a285f] px-5 py-8 text-center">
        <div>
          <ImageIcon className="mx-auto h-7 w-7 text-[#f5c518]" />
          <p className="mt-3 font-semibold text-white">Featured image</p>
          <p className="mt-2 text-sm text-[#c2d3f5]">{PREPARED_DURING_PROCESSING}</p>
        </div>
      </div>
    );
  }

  return <img src={src} alt="" className="mt-4 h-64 w-full rounded-2xl object-cover" onError={() => setHasFailed(true)} />;
}

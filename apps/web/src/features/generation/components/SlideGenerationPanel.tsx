import { useEffect } from "react";
import type { DeckPurpose } from "../../extraction/types";
import {
  automaticGenerationRequestKey,
  generationFailureGuidance,
} from "../state";
import { useSlideGeneration } from "../hooks/useSlideGeneration";
import { SlidePreview } from "./SlidePreview";
import {
  normalizePresentationDensity,
  type PresentationDensity,
} from "../density";

export function SlideGenerationPanel({
  extractionJobId,
  deckType,
  density,
}: {
  extractionJobId: string;
  deckType: DeckPurpose;
  density: PresentationDensity;
}) {
  const generation = useSlideGeneration();
  const job = generation.job.data;
  const automaticRequestKey = automaticGenerationRequestKey(
    extractionJobId,
    deckType,
    density,
  );
  const analysis = job?.analysis ?? generation.result.data?.job.analysis;

  useEffect(() => {
    if (!job && generation.start.status === "idle") {
      generation.start.mutate({
        extractionJobId,
        deckType,
        requestKey: automaticRequestKey,
        density,
      });
    }
  }, [automaticRequestKey, deckType, density, extractionJobId, generation.start.status, job]);

  function startAgain(requestKey: string) {
    generation.start.mutate({ extractionJobId, deckType, requestKey, density });
  }

  async function download() {
    const artifact = await generation.download.mutateAsync();
    const url = URL.createObjectURL(artifact);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "financial-slides.pptx";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="mt-6 border-t border-stone-200 pt-6 dark:border-white/10">
      {!job && generation.start.isPending && (
        <p className="text-sm font-semibold text-stone-700 dark:text-stone-200" role="status">
          Starting AI analysis…
        </p>
      )}
      {!job && generation.start.isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
          <p>{generation.start.error instanceof Error ? generation.start.error.message : "AI slide generation could not start."}</p>
          <button
            className="mt-3 font-bold underline"
            onClick={() => startAgain(automaticRequestKey)}
            type="button"
          >
            Retry AI generation
          </button>
        </div>
      )}
      {job && job.status !== "succeeded" && job.status !== "failed" && (
        <div role="status">
          <div className="mb-2 flex justify-between text-sm">
            <strong>{job.status === "analyzing" ? "Analyzing report" : job.status === "rendering" ? "Rendering PowerPoint" : "Queued"}</strong>
            <span>{job.progress}%</span>
          </div>
          <progress className="w-full" max="100" value={job.progress} />
        </div>
      )}
      {job?.failure && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
          <p>{generationFailureGuidance(job.failure)}</p>
          {job.failure.retryable && job.attempt_count < job.max_attempts && (
            <button className="mt-3 font-bold underline" onClick={() => generation.retry.mutate()} type="button">
              Retry generation
            </button>
          )}
        </div>
      )}
      {job?.status === "succeeded" && (
        <div className="mb-4 text-sm" role="status">
          <strong>Ready</strong>
          <p className="mt-1 text-stone-600 dark:text-stone-300">
            Presentation detail: {normalizePresentationDensity(job.density)}
          </p>
          {analysis && (
            <p className="mt-1 text-stone-600 dark:text-stone-300">
              {analysis.mode === "hosted"
                ? `AI analysis: ${analysis.provider} / ${analysis.model}`
                : "Deterministic analysis — hosted AI was not used."}
              {analysis.fallback_used ? " A deterministic fallback produced this deck." : ""}
            </p>
          )}
        </div>
      )}
      {generation.result.data && (
        <>
          <SlidePreview result={generation.result.data} />
          <button
            className="mt-5 w-full rounded-xl bg-orange-700 px-5 py-3 font-bold text-white disabled:opacity-45"
            disabled={generation.download.isPending}
            onClick={() => void download()}
            type="button"
          >
            {generation.download.isPending ? "Preparing download…" : "Download editable PowerPoint"}
          </button>
          <button
            className="mt-3 w-full rounded-xl border border-emerald-900 px-5 py-3 font-bold text-emerald-950 disabled:opacity-45 dark:border-emerald-200 dark:text-emerald-100"
            disabled={generation.start.isPending}
            onClick={() => startAgain(`manual:${globalThis.crypto?.randomUUID?.() ?? Date.now()}`)}
            type="button"
          >
            Generate again
          </button>
        </>
      )}
    </section>
  );
}

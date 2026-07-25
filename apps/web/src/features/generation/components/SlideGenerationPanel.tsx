import type { DeckPurpose } from "../../extraction/types";
import { generationFailureGuidance } from "../state";
import { useSlideGeneration } from "../hooks/useSlideGeneration";
import { SlidePreview } from "./SlidePreview";

export function SlideGenerationPanel({
  extractionJobId,
  deckType,
}: {
  extractionJobId: string;
  deckType: DeckPurpose;
}) {
  const generation = useSlideGeneration();
  const job = generation.job.data;

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
      {!job && (
        <button
          className="w-full rounded-xl bg-emerald-950 px-5 py-3 font-bold text-white disabled:opacity-45 dark:bg-emerald-200 dark:text-emerald-950"
          disabled={generation.start.isPending}
          onClick={() => generation.start.mutate({ extractionJobId, deckType })}
          type="button"
        >
          {generation.start.isPending ? "Starting…" : "Generate presentation"}
        </button>
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
        </>
      )}
    </section>
  );
}

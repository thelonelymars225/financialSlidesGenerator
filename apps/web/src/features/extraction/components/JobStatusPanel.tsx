import { failureGuidance } from "../state";
import type { ExtractionJob } from "../types";

const LABELS = {
  queued: "Queued",
  running: "Extracting",
  succeeded: "Ready",
  failed: "Needs attention",
  cancelled: "Cancelled",
} as const;

export function JobStatusPanel({
  job,
  cancelling,
  onCancel,
  onRetry,
}: {
  job: ExtractionJob;
  cancelling: boolean;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const canCancel = job.status === "queued" || job.status === "running";
  const canRetry = job.status === "failed" || job.status === "cancelled";

  return (
    <section className="mt-6 rounded-2xl border border-stone-200 bg-stone-50 p-5 dark:border-white/10 dark:bg-black/20" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-wider text-emerald-700 uppercase dark:text-emerald-300">Extraction job {job.id.slice(0, 8)}</p>
          <h2 className="mt-1 text-xl font-bold">{LABELS[job.status]}</h2>
        </div>
        {canCancel && (
          <button type="button" onClick={onCancel} disabled={cancelling} className="rounded-full border border-stone-300 px-4 py-2 text-sm font-semibold hover:border-red-600 hover:text-red-700 disabled:opacity-50 dark:border-white/20">
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        )}
        {canRetry && (
          <button type="button" onClick={onRetry} className="rounded-full bg-emerald-950 px-4 py-2 text-sm font-semibold text-white dark:bg-emerald-200 dark:text-emerald-950">
            Submit again
          </button>
        )}
      </div>
      {(job.status === "queued" || job.status === "running") && (
        <p className="mt-3 text-sm text-stone-600 dark:text-stone-400">
          {job.status === "queued" ? "Waiting for an available worker." : `Attempt ${job.attempt_count} of ${job.max_attempts}. This page will update automatically.`}
        </p>
      )}
      {job.failure && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-red-950 dark:border-red-400/20 dark:bg-red-950/30 dark:text-red-100" role="alert">
          <strong>{job.failure.code.replaceAll("_", " ")}</strong>
          <p className="mt-1 text-sm">{failureGuidance(job.failure)}</p>
        </div>
      )}
    </section>
  );
}

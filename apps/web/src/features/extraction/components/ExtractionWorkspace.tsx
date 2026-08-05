import { FormEvent, useMemo, useState } from "react";
import { SlideGenerationPanel } from "../../generation/components/SlideGenerationPanel";
import { ExtractionApiError } from "../api";
import { fileRequest } from "../file";
import { useExtractionJob } from "../hooks/useExtractionJob";
import type { CreateJobRequest, DeckPurpose, InputMode } from "../types";
import { ExtractionResultPreview } from "./ExtractionResultPreview";
import { JobStatusPanel } from "./JobStatusPanel";

function newRequestKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function ExtractionWorkspace() {
  const [inputMode, setInputMode] = useState<InputMode>("file");
  const [sourceText, setSourceText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [deckPurpose, setDeckPurpose] = useState<DeckPurpose>("management-review");
  const [slideCount, setSlideCount] = useState(10);
  const [jobId, setJobId] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(newRequestKey);
  const [lastRequest, setLastRequest] = useState<CreateJobRequest | null>(null);
  const extraction = useExtractionJob(jobId);

  const errorMessage = useMemo(() => {
    const error = extraction.create.error ?? extraction.job.error ?? extraction.result.error ?? extraction.cancel.error;
    if (!error) return null;
    if (error instanceof ExtractionApiError) return error.message;
    return error instanceof Error ? error.message : "The extraction request failed.";
  }, [extraction.cancel.error, extraction.create.error, extraction.job.error, extraction.result.error]);

  async function buildRequest(): Promise<CreateJobRequest> {
    if (inputMode === "file") {
      if (!file) throw new Error("Choose a PDF before submitting.");
      return fileRequest(file, deckPurpose, slideCount, requestKey);
    }
    if (!sourceText.trim()) throw new Error("Paste source text before submitting.");
    return {
      input_mode: "text",
      source_text: sourceText,
      deck_purpose: deckPurpose,
      slide_count: slideCount,
      request_key: requestKey,
    };
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    try {
      const request = await buildRequest();
      setLastRequest(request);
      const job = await extraction.create.mutateAsync(request);
      setJobId(job.id);
    } catch {
      // React Query exposes a safe error state below the form.
    }
  }

  async function retry() {
    if (!lastRequest) return;
    const nextRequest = { ...lastRequest, request_key: newRequestKey() };
    setRequestKey(nextRequest.request_key);
    setLastRequest(nextRequest);
    try {
      const job = await extraction.create.mutateAsync(nextRequest);
      setJobId(job.id);
    } catch {
      // React Query exposes a safe error state below the form.
    }
  }

  return (
    <section className="rounded-3xl border border-stone-200 bg-white p-5 shadow-[0_24px_70px_rgba(29,58,48,0.08)] transition-colors sm:p-8 dark:border-white/10 dark:bg-white/[0.045] dark:shadow-black/30">
      <form onSubmit={(event) => void submit(event)}>
        <fieldset>
          <legend className="sr-only">Input method</legend>
          <div className="mb-6 flex gap-2">
            {(["file", "text"] as const).map((mode) => (
              <button
                className={`rounded-full px-4 py-2 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 ${inputMode === mode ? "bg-emerald-950 text-white dark:bg-emerald-200 dark:text-emerald-950" : "bg-stone-100 text-stone-600 hover:bg-stone-200 dark:bg-white/10 dark:text-stone-300 dark:hover:bg-white/15"}`}
                type="button"
                key={mode}
                aria-pressed={inputMode === mode}
                onClick={() => {
                  setInputMode(mode);
                  setRequestKey(newRequestKey());
                }}
              >
                {mode === "file" ? "Upload report" : "Paste text"}
              </button>
            ))}
          </div>
        </fieldset>

        {inputMode === "file" ? (
          <label className="grid min-h-48 cursor-pointer place-content-center rounded-2xl border border-dashed border-emerald-800/40 bg-emerald-50/50 p-7 text-center transition hover:border-emerald-700 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-700 dark:border-emerald-200/25 dark:bg-emerald-950/20">
            <strong className="mb-2 text-lg">{file?.name ?? "Choose a born-digital PDF"}</strong>
            <span className="mb-4 block text-sm text-stone-500 dark:text-stone-400">PDF files up to the backend safety limit are supported.</span>
            <input
              className="mx-auto max-w-72 text-sm file:mr-3 file:rounded-full file:border-0 file:bg-emerald-950 file:px-4 file:py-2 file:font-semibold file:text-white dark:file:bg-emerald-200 dark:file:text-emerald-950"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setRequestKey(newRequestKey());
              }}
            />
          </label>
        ) : (
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-stone-600 dark:text-stone-300">Source text</span>
            <textarea
              className="w-full rounded-xl border border-stone-300 bg-stone-50 p-3 text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-emerald-700 focus:ring-3 focus:ring-emerald-700/10 dark:border-white/15 dark:bg-black/20 dark:text-stone-100 dark:focus:border-emerald-300"
              rows={9}
              value={sourceText}
              onChange={(event) => {
                setSourceText(event.target.value);
                setRequestKey(newRequestKey());
              }}
              placeholder="Paste report content here…"
              required
            />
          </label>
        )}

        <div className="mt-5 grid gap-5 sm:grid-cols-[1fr_9rem]">
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-stone-600 dark:text-stone-300">Deck purpose</span>
            <select className="w-full rounded-xl border border-stone-300 bg-stone-50 p-3 text-stone-900 outline-none focus:border-emerald-700 dark:border-white/15 dark:bg-[#121b18] dark:text-stone-100" value={deckPurpose} onChange={(event) => setDeckPurpose(event.target.value as DeckPurpose)}>
              <option value="management-review">Management review</option>
              <option value="board-update">Board update</option>
              <option value="investor-summary">Investor summary</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-stone-600 dark:text-stone-300">Slides</span>
            <input className="w-full rounded-xl border border-stone-300 bg-stone-50 p-3 text-stone-900 outline-none focus:border-emerald-700 dark:border-white/15 dark:bg-black/20 dark:text-stone-100" type="number" min="5" max="20" value={slideCount} onChange={(event) => setSlideCount(Number(event.target.value))} />
          </label>
        </div>

        <button className="mt-6 w-full rounded-xl bg-orange-700 px-5 py-3.5 font-bold text-white transition hover:bg-orange-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-700 disabled:cursor-not-allowed disabled:opacity-45 dark:bg-orange-600 dark:hover:bg-orange-500" disabled={extraction.create.isPending || (inputMode === "file" ? !file : !sourceText.trim())}>
          {extraction.create.isPending ? "Submitting…" : "Extract source"}
        </button>
      </form>

      {!jobId && !errorMessage && <p className="mt-4 text-center text-sm text-stone-500">Submit a report to see extraction progress and source-grounded results.</p>}
      {errorMessage && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900 dark:border-red-400/20 dark:bg-red-950/30 dark:text-red-100" role="alert">{errorMessage}</p>}
      {extraction.job.data && (
        <JobStatusPanel
          job={extraction.job.data}
          cancelling={extraction.cancel.isPending}
          onCancel={() => extraction.cancel.mutate()}
          onRetry={() => void retry()}
        />
      )}
      {extraction.result.isLoading && <p className="mt-5 text-sm text-stone-500" role="status">Loading the validated result…</p>}
      {extraction.result.data && (
        <>
          <ExtractionResultPreview result={extraction.result.data} />
          <SlideGenerationPanel
            key={extraction.result.data.job.id}
            extractionJobId={extraction.result.data.job.id}
            deckType={deckPurpose}
          />
        </>
      )}
    </section>
  );
}

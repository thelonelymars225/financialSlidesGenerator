import { FormEvent, useEffect, useState } from "react";
import { createJob } from "./api";
import { useGeneratorStore } from "./store";

export function App() {
  const state = useGeneratorStore();
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", state.theme === "dark");
    document.documentElement.style.colorScheme = state.theme;
    window.localStorage.setItem("financial-slides-theme", state.theme);
  }, [state.theme]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage("");
    try {
      const job = await createJob({
        input_mode: state.inputMode,
        source_text: state.inputMode === "text" ? state.sourceText : undefined,
        file_name: state.inputMode === "file" ? state.fileName ?? undefined : undefined,
        deck_purpose: state.deckPurpose,
        slide_count: state.slideCount,
      });
      setMessage(`Job ${job.id.slice(0, 8)} is queued.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-stone-100 px-4 py-10 text-emerald-950 transition-colors duration-300 sm:py-18 dark:bg-[#0b1210] dark:text-stone-100">
      <div className="mx-auto w-full max-w-5xl">
        <nav className="mb-14 flex items-center justify-between sm:mb-20" aria-label="Page controls">
          <span className="text-sm font-bold tracking-tight">financialSlidesGenerator</span>
          <button
            type="button"
            onClick={state.toggleTheme}
            className="inline-flex items-center gap-2 rounded-full border border-stone-300 bg-white px-3 py-2 text-sm font-semibold text-stone-700 shadow-sm transition hover:border-emerald-700 hover:text-emerald-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 dark:border-white/15 dark:bg-white/5 dark:text-stone-200 dark:hover:border-emerald-300 dark:hover:text-emerald-200"
            aria-label={`Switch to ${state.theme === "light" ? "dark" : "light"} mode`}
            aria-pressed={state.theme === "dark"}
          >
            <span aria-hidden="true" className="text-base">{state.theme === "light" ? "☾" : "☀"}</span>
            {state.theme === "light" ? "Dark" : "Light"}
          </button>
        </nav>

        <header className="mb-9 max-w-4xl sm:mb-12">
          <span className="text-xs font-extrabold tracking-[0.16em] text-emerald-700 uppercase dark:text-emerald-300">Source-grounded presentations</span>
          <h1 className="mt-3 max-w-4xl text-[clamp(2.75rem,8vw,5.75rem)] leading-[0.94] font-bold tracking-[-0.06em] text-balance">
            Turn a financial report into a useful first draft.
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-stone-600 dark:text-stone-400">Upload company information, choose the deck shape, and keep every important claim traceable.</p>
        </header>

        <form className="rounded-3xl border border-stone-200 bg-white p-5 shadow-[0_24px_70px_rgba(29,58,48,0.08)] transition-colors sm:p-8 dark:border-white/10 dark:bg-white/[0.045] dark:shadow-black/30" onSubmit={submit}>
        <div className="mb-6 flex gap-2" aria-label="Input method">
          {(["file", "text"] as const).map((mode) => (
            <button
              className={`rounded-full px-4 py-2 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 ${state.inputMode === mode ? "bg-emerald-950 text-white dark:bg-emerald-200 dark:text-emerald-950" : "bg-stone-100 text-stone-600 hover:bg-stone-200 dark:bg-white/10 dark:text-stone-300 dark:hover:bg-white/15"}`}
              type="button"
              key={mode}
              onClick={() => state.setInputMode(mode)}
            >
              {mode === "file" ? "Upload report" : "Paste text"}
            </button>
          ))}
        </div>

        {state.inputMode === "file" ? (
          <label className="grid min-h-48 cursor-pointer place-content-center rounded-2xl border border-dashed border-emerald-800/40 bg-emerald-50/50 p-7 text-center transition hover:border-emerald-700 dark:border-emerald-200/25 dark:bg-emerald-950/20 dark:hover:border-emerald-200/50">
            <strong className="mb-2 text-lg">{state.fileName ?? "Choose a report"}</strong>
            <span className="mb-4 block text-sm text-stone-500 dark:text-stone-400">PDF and Office formats will be enabled as extraction support is added.</span>
            <input className="mx-auto max-w-72 text-sm file:mr-3 file:rounded-full file:border-0 file:bg-emerald-950 file:px-4 file:py-2 file:font-semibold file:text-white dark:file:bg-emerald-200 dark:file:text-emerald-950" type="file" onChange={(event) => state.setFileName(event.target.files?.[0]?.name ?? null)} />
          </label>
        ) : (
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-stone-600 dark:text-stone-300">Source text</span>
            <textarea className="w-full rounded-xl border border-stone-300 bg-stone-50 p-3 text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-emerald-700 focus:ring-3 focus:ring-emerald-700/10 dark:border-white/15 dark:bg-black/20 dark:text-stone-100 dark:focus:border-emerald-300 dark:focus:ring-emerald-300/10" rows={9} value={state.sourceText} onChange={(event) => state.setSourceText(event.target.value)} placeholder="Paste report content here…" required />
          </label>
        )}

        <div className="mt-5 grid gap-5 sm:grid-cols-[1fr_9rem]">
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-stone-600 dark:text-stone-300">Deck purpose</span>
            <select className="w-full rounded-xl border border-stone-300 bg-stone-50 p-3 text-stone-900 outline-none transition focus:border-emerald-700 focus:ring-3 focus:ring-emerald-700/10 dark:border-white/15 dark:bg-[#121b18] dark:text-stone-100 dark:focus:border-emerald-300" value={state.deckPurpose} onChange={(event) => state.setDeckPurpose(event.target.value)}>
              <option value="management-review">Management review</option>
              <option value="board-update">Board update</option>
              <option value="investor-summary">Investor summary</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-stone-600 dark:text-stone-300">Slides</span>
            <input className="w-full rounded-xl border border-stone-300 bg-stone-50 p-3 text-stone-900 outline-none transition focus:border-emerald-700 focus:ring-3 focus:ring-emerald-700/10 dark:border-white/15 dark:bg-black/20 dark:text-stone-100 dark:focus:border-emerald-300" type="number" min="5" max="20" value={state.slideCount} onChange={(event) => state.setSlideCount(Number(event.target.value))} />
          </label>
        </div>

        <button className="mt-6 w-full rounded-xl bg-orange-700 px-5 py-3.5 font-bold text-white transition hover:bg-orange-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-700 disabled:cursor-not-allowed disabled:opacity-45 dark:bg-orange-600 dark:hover:bg-orange-500" disabled={submitting || (state.inputMode === "file" && !state.fileName)}>
          {submitting ? "Creating job…" : "Create presentation"}
        </button>
        {message && <p className="mt-4 text-center text-sm font-medium text-emerald-700 dark:text-emerald-300" role="status">{message}</p>}
        </form>
      </div>
    </main>
  );
}

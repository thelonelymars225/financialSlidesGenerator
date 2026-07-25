import { useEffect } from "react";
import { ExtractionWorkspace } from "./features/extraction/components/ExtractionWorkspace";
import { useGeneratorStore } from "./store";

export function App() {
  const state = useGeneratorStore();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", state.theme === "dark");
    document.documentElement.style.colorScheme = state.theme;
    window.localStorage.setItem("financial-slides-theme", state.theme);
  }, [state.theme]);

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
          <p className="mt-6 max-w-2xl text-lg leading-8 text-stone-600 dark:text-stone-400">Upload company information, inspect the extraction, and keep every important claim traceable.</p>
        </header>

        <ExtractionWorkspace />
      </div>
    </main>
  );
}

import { FormEvent, useState } from "react";
import { createJob } from "./api";
import { useGeneratorStore } from "./store";

export function App() {
  const state = useGeneratorStore();
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
    <main className="shell">
      <header className="hero">
        <span className="eyebrow">Source-grounded presentations</span>
        <h1>Turn a financial report into a useful first draft.</h1>
        <p>Upload company information, choose the deck shape, and keep every important claim traceable.</p>
      </header>

      <form className="card" onSubmit={submit}>
        <div className="tabs" aria-label="Input method">
          {(["file", "text"] as const).map((mode) => (
            <button className={state.inputMode === mode ? "active" : ""} type="button" key={mode} onClick={() => state.setInputMode(mode)}>
              {mode === "file" ? "Upload report" : "Paste text"}
            </button>
          ))}
        </div>

        {state.inputMode === "file" ? (
          <label className="dropzone">
            <strong>{state.fileName ?? "Choose a report"}</strong>
            <span>PDF and Office formats will be enabled as extraction support is added.</span>
            <input type="file" onChange={(event) => state.setFileName(event.target.files?.[0]?.name ?? null)} />
          </label>
        ) : (
          <label>
            <span>Source text</span>
            <textarea rows={9} value={state.sourceText} onChange={(event) => state.setSourceText(event.target.value)} placeholder="Paste report content here…" required />
          </label>
        )}

        <div className="options">
          <label>
            <span>Deck purpose</span>
            <select value={state.deckPurpose} onChange={(event) => state.setDeckPurpose(event.target.value)}>
              <option value="management-review">Management review</option>
              <option value="board-update">Board update</option>
              <option value="investor-summary">Investor summary</option>
            </select>
          </label>
          <label>
            <span>Slides</span>
            <input type="number" min="5" max="20" value={state.slideCount} onChange={(event) => state.setSlideCount(Number(event.target.value))} />
          </label>
        </div>

        <button className="primary" disabled={submitting || (state.inputMode === "file" && !state.fileName)}>
          {submitting ? "Creating job…" : "Create presentation"}
        </button>
        {message && <p className="message" role="status">{message}</p>}
      </form>
    </main>
  );
}

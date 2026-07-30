import { documentSummary, orderedBlocks, safeBlockText, sourceLabel } from "../state";
import type { ExtractedBlock, JobResult } from "../types";

function TablePreview({ block, pageNumber }: { block: ExtractedBlock; pageNumber?: number }) {
  const cells = block.cells ?? [];
  const rowIndexes = [...new Set(cells.map((cell) => cell.row ?? 0))].sort((a, b) => a - b);
  const columnIndexes = [...new Set(cells.map((cell) => cell.column ?? 0))].sort((a, b) => a - b);

  return (
    <div className="overflow-x-auto">
      {block.caption && <p className="mb-2 font-semibold">{block.caption}</p>}
      <table className="w-full min-w-96 border-collapse text-left text-sm">
        <tbody>
          {rowIndexes.map((row) => (
            <tr key={row}>
              {columnIndexes.map((column) => {
                const cell = cells.find((item) => (item.row ?? 0) === row && (item.column ?? 0) === column);
                return <td key={column} className="border border-stone-200 p-2 align-top dark:border-white/10">{cell?.text ?? ""}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-stone-500">{sourceLabel(block.source, pageNumber)}</p>
    </div>
  );
}

export function ExtractionResultPreview({ result }: { result: JobResult }) {
  const summary = documentSummary(result.document);
  const source = result.document.source;

  return (
    <section className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/50 p-5 dark:border-emerald-300/15 dark:bg-emerald-950/20" aria-labelledby="extraction-preview-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-wider text-emerald-700 uppercase dark:text-emerald-300">Validated extraction</p>
          <h2 id="extraction-preview-title" className="mt-1 text-2xl font-bold">{source?.fileName ?? "Pasted text"}</h2>
          <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{source?.mediaType ?? "Unknown media type"} · Contract {result.document.schemaVersion ?? "unknown"}</p>
        </div>
        <dl className="grid grid-cols-3 gap-4 text-center text-sm">
          <div><dt className="text-stone-500">Pages</dt><dd className="font-bold">{summary.pageCount}</dd></div>
          <div><dt className="text-stone-500">Blocks</dt><dd className="font-bold">{summary.blockCount}</dd></div>
          <div><dt className="text-stone-500">Warnings</dt><dd className="font-bold">{summary.warningCount}</dd></div>
        </dl>
      </div>

      {result.document.warnings?.length ? (
        <ul className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-300/20 dark:bg-amber-950/30 dark:text-amber-100">
          {result.document.warnings.map((warning, index) => (
            <li key={`${warning.code}:${warning.severity}:${index}`}>{warning.message}</li>
          ))}
        </ul>
      ) : null}

      <div className="mt-5 space-y-4">
        {(result.document.pages ?? []).map((page, pageIndex) => (
          <article key={page.pageNumber ?? pageIndex} className="rounded-xl bg-white p-4 shadow-sm dark:bg-white/5">
            <h3 className="mb-3 font-bold">Page {page.pageNumber ?? pageIndex + 1}</h3>
            <div className="space-y-4">
              {orderedBlocks(page.blocks).map((block, blockIndex) => (
                <div key={block.id ?? blockIndex}>
                  {block.type === "table" ? (
                    <TablePreview block={block} pageNumber={page.pageNumber} />
                  ) : (
                    <>
                      <p className="whitespace-pre-wrap text-sm leading-6">{safeBlockText(block) || "No previewable text."}</p>
                      <p className="mt-1 text-xs text-stone-500">{sourceLabel(block.source, page.pageNumber)}</p>
                    </>
                  )}
                </div>
              ))}
            </div>
          </article>
        ))}
        {!summary.pageCount && <p className="text-sm text-stone-600 dark:text-stone-400">The extractor returned no previewable pages.</p>}
      </div>
    </section>
  );
}

import type {
  ExtractedBlock,
  ExtractedDocument,
  JobFailure,
  JobStatus,
  SourceReference,
} from "./types";

const TERMINAL_STATUSES = new Set<JobStatus>(["succeeded", "failed", "cancelled"]);
const MAX_PREVIEW_TEXT = 4_000;

export function isTerminalStatus(status: JobStatus | undefined): boolean {
  return status !== undefined && TERMINAL_STATUSES.has(status);
}

export function nextPollInterval(status: JobStatus | undefined): number | false {
  if (isTerminalStatus(status)) return false;
  return status === "running" ? 1_000 : 1_500;
}

export function failureGuidance(failure: JobFailure | null | undefined): string {
  if (!failure) return "The extraction stopped before producing a result.";
  const guidance: Record<string, string> = {
    encrypted_file: "Remove the document password and submit the file again.",
    unsupported_file: "Submit a born-digital PDF or paste the report text.",
    file_too_large: "Split the report into smaller files and submit one at a time.",
    page_limit_exceeded: "Submit a shorter report or split it into sections.",
    extraction_timeout: "Try a smaller file. The job stopped at the safety timeout.",
    cancelled: "The job was cancelled. You can submit it again when ready.",
  };
  return guidance[failure.code] ?? failure.message;
}

export function sourceLabel(source: SourceReference | undefined, fallbackPage?: number): string {
  const page = source?.pageNumber ?? fallbackPage;
  const section = source?.sectionPath?.filter(Boolean).join(" › ");
  return [page ? `Page ${page}` : null, section || null].filter(Boolean).join(" · ") || "Source";
}

export function safeBlockText(block: ExtractedBlock): string {
  const value = block.text ?? block.caption ?? "";
  return value.length > MAX_PREVIEW_TEXT ? `${value.slice(0, MAX_PREVIEW_TEXT)}…` : value;
}

export function orderedBlocks(blocks: ExtractedBlock[] | undefined): ExtractedBlock[] {
  return [...(blocks ?? [])].sort((left, right) => (left.order ?? 0) - (right.order ?? 0));
}

export function documentSummary(document: ExtractedDocument) {
  const pages = document.pages ?? [];
  const blocks = pages.flatMap((page) => page.blocks ?? []);
  return {
    pageCount: pages.length,
    blockCount: blocks.length,
    warningCount: (document.warnings?.length ?? 0)
      + blocks.reduce((total, block) => total + (block.warnings?.length ?? 0), 0),
  };
}

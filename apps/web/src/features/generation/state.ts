import type { GenerationFailure, GenerationStatus } from "./types";

export function isTerminalGeneration(status: GenerationStatus | undefined): boolean {
  return status === "succeeded" || status === "failed";
}

export function generationPollInterval(status: GenerationStatus | undefined): number | false {
  return isTerminalGeneration(status) ? false : 1_000;
}

export function generationFailureGuidance(
  failure: GenerationFailure | null | undefined,
): string {
  if (!failure) return "Slide generation stopped before producing a presentation.";
  const guidance: Record<string, string> = {
    analysis_insufficient_data: "Add financial values or comparisons, then extract the source again.",
    compilation_failed: "The analysis could not be mapped to the approved slide format.",
    rendering_failed: "The PowerPoint renderer was unavailable. Retry this generation job.",
  };
  return guidance[failure.code] ?? failure.message;
}

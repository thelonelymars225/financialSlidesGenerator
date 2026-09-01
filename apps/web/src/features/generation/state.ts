import type { GenerationFailure, GenerationStatus } from "./types";
import {
  DEFAULT_PRESENTATION_DENSITY,
  type PresentationDensity,
} from "./density";

export function isTerminalGeneration(status: GenerationStatus | undefined): boolean {
  return status === "succeeded" || status === "failed";
}

export function generationPollInterval(status: GenerationStatus | undefined): number | false {
  return isTerminalGeneration(status) ? false : 1_000;
}

export function automaticGenerationRequestKey(
  extractionJobId: string,
  deckType: string,
  density: PresentationDensity = DEFAULT_PRESENTATION_DENSITY,
): string {
  return `auto:${extractionJobId}:${deckType}:${density}`;
}

export function generationFailureGuidance(
  failure: GenerationFailure | null | undefined,
): string {
  if (!failure) return "Slide generation stopped before producing a presentation.";
  const guidance: Record<string, string> = {
    analysis_insufficient_data: "Add financial values or comparisons, then extract the source again.",
    analysis_authentication_failed: "The analysis service credentials were rejected. Contact the service operator.",
    analysis_payment_required: "The analysis service has no available balance or quota. Contact the service operator.",
    analysis_rate_limited: "The analysis service is busy. Wait briefly, then retry generation.",
    analysis_invalid_request: "The analysis service rejected this request. Contact the service operator.",
    analysis_network_failure: "The analysis service could not be reached. Retry generation.",
    analysis_invalid_response: "The analysis service returned an unusable response. Retry generation.",
    analysis_invalid_output: "The analysis did not match the required slide format. Retry generation.",
    analysis_ungrounded_output: "The analysis could not be verified against the report. Retry generation.",
    analysis_input_too_large: "This report contains too much financial evidence for one analysis request.",
    analysis_timeout: "The analysis service took too long. Retry generation.",
    analysis_provider_failure: "The analysis service is temporarily unavailable. Retry generation.",
    compilation_failed: "The analysis could not be mapped to the approved slide format.",
    rendering_failed: "The PowerPoint renderer was unavailable. Retry this generation job.",
  };
  return guidance[failure.code] ?? failure.message;
}

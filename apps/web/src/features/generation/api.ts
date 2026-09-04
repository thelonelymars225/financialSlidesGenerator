import type { DeckPurpose } from "../extraction/types";
import type { GenerationJob, GenerationResult } from "./types";
import {
  DEFAULT_PRESENTATION_DENSITY,
  type PresentationDensity,
} from "./density";
import { apiUrl } from "../../api-url";
import {
  ARTIFACT_REQUEST_TIMEOUT_MS,
  createHttpClient,
} from "../../http";

export { ApiError as GenerationApiError } from "../../http";

type Fetcher = typeof fetch;

function ownerHeaders(ownerId: string): HeadersInit {
  return { "X-Owner-ID": ownerId };
}

export function createGenerationApi(fetcher: Fetcher = fetch, ownerId = "local-development") {
  const request = createHttpClient(fetcher, "GenerationApiError");
  return {
    async start(
      extractionJobId: string,
      deckType: DeckPurpose,
      requestKey: string,
      density: PresentationDensity = DEFAULT_PRESENTATION_DENSITY,
    ): Promise<GenerationJob> {
      return request<GenerationJob>(apiUrl(`/api/jobs/${encodeURIComponent(extractionJobId)}/slides`), {
        method: "POST",
        headers: { "content-type": "application/json", ...ownerHeaders(ownerId) },
        body: JSON.stringify({
          deck_type: deckType,
          density,
          request_key: requestKey,
        }),
        fallbackMessage: "Slide generation could not be completed.",
      });
    },

    async getJob(jobId: string): Promise<GenerationJob> {
      return request<GenerationJob>(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}`), {
        headers: ownerHeaders(ownerId),
        fallbackMessage: "Slide generation could not be completed.",
      });
    },

    async getResult(jobId: string): Promise<GenerationResult> {
      return request<GenerationResult>(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}/result`), {
        headers: ownerHeaders(ownerId),
        fallbackMessage: "Slide generation could not be completed.",
      });
    },

    async retry(jobId: string): Promise<GenerationJob> {
      return request<GenerationJob>(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}/retry`), {
        method: "POST",
        headers: ownerHeaders(ownerId),
        fallbackMessage: "Slide generation could not be completed.",
      });
    },

    async download(jobId: string): Promise<Blob> {
      return request<Blob>(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}/artifact`), {
        headers: ownerHeaders(ownerId),
        responseType: "blob",
        timeoutMs: ARTIFACT_REQUEST_TIMEOUT_MS,
        fallbackMessage: "The presentation download could not be completed.",
      });
    },
  };
}

export type GenerationApi = ReturnType<typeof createGenerationApi>;
export const generationApi = createGenerationApi();

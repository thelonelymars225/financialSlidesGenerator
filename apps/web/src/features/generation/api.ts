import type { DeckPurpose } from "../extraction/types";
import type { GenerationJob, GenerationResult } from "./types";
import {
  DEFAULT_PRESENTATION_DENSITY,
  type PresentationDensity,
} from "./density";
import { apiUrl } from "../../api-url";

export class GenerationApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "GenerationApiError";
  }
}

type Fetcher = typeof fetch;

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const problem = await response.json().catch(() => null) as { detail?: string } | null;
  throw new GenerationApiError(
    problem?.detail || "Slide generation could not be completed.",
    response.status,
  );
}

function ownerHeaders(ownerId: string): HeadersInit {
  return { "X-Owner-ID": ownerId };
}

export function createGenerationApi(fetcher: Fetcher = fetch, ownerId = "local-development") {
  return {
    async start(
      extractionJobId: string,
      deckType: DeckPurpose,
      requestKey: string,
      density: PresentationDensity = DEFAULT_PRESENTATION_DENSITY,
    ): Promise<GenerationJob> {
      const response = await fetcher(apiUrl(`/api/jobs/${encodeURIComponent(extractionJobId)}/slides`), {
        method: "POST",
        headers: { "content-type": "application/json", ...ownerHeaders(ownerId) },
        body: JSON.stringify({
          deck_type: deckType,
          density,
          request_key: requestKey,
        }),
      });
      return parseResponse<GenerationJob>(response);
    },

    async getJob(jobId: string): Promise<GenerationJob> {
      const response = await fetcher(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}`), {
        headers: ownerHeaders(ownerId),
      });
      return parseResponse<GenerationJob>(response);
    },

    async getResult(jobId: string): Promise<GenerationResult> {
      const response = await fetcher(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}/result`), {
        headers: ownerHeaders(ownerId),
      });
      return parseResponse<GenerationResult>(response);
    },

    async retry(jobId: string): Promise<GenerationJob> {
      const response = await fetcher(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}/retry`), {
        method: "POST",
        headers: ownerHeaders(ownerId),
      });
      return parseResponse<GenerationJob>(response);
    },

    async download(jobId: string): Promise<Blob> {
      const response = await fetcher(apiUrl(`/api/slide-jobs/${encodeURIComponent(jobId)}/artifact`), {
        headers: ownerHeaders(ownerId),
      });
      if (!response.ok) await parseResponse(response);
      return response.blob();
    },
  };
}

export type GenerationApi = ReturnType<typeof createGenerationApi>;
export const generationApi = createGenerationApi();

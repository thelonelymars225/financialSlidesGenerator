import type { CreateJobRequest, ExtractionJob, JobResult } from "./types";
import { apiUrl } from "../../api-url";
import { createHttpClient } from "../../http";

export { ApiError as ExtractionApiError } from "../../http";

type Fetcher = typeof fetch;

function ownerHeaders(ownerId: string): HeadersInit {
  return { "X-Owner-ID": ownerId };
}

export function createExtractionApi(fetcher: Fetcher = fetch, ownerId = "local-development") {
  const request = createHttpClient(fetcher, "ExtractionApiError");
  return {
    async createJob(payload: CreateJobRequest): Promise<ExtractionJob> {
      return request<ExtractionJob>(apiUrl("/api/jobs"), {
        method: "POST",
        headers: { "content-type": "application/json", ...ownerHeaders(ownerId) },
        body: JSON.stringify(payload),
        fallbackMessage: "The extraction request could not be completed.",
      });
    },

    async getJob(jobId: string): Promise<ExtractionJob> {
      return request<ExtractionJob>(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}`), {
        headers: ownerHeaders(ownerId),
        fallbackMessage: "The extraction request could not be completed.",
      });
    },

    async getResult(jobId: string): Promise<JobResult> {
      return request<JobResult>(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/result`), {
        headers: ownerHeaders(ownerId),
        fallbackMessage: "The extraction request could not be completed.",
      });
    },

    async cancelJob(jobId: string): Promise<ExtractionJob> {
      const result = await request<{ job: ExtractionJob }>(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/cancel`), {
        method: "POST",
        headers: ownerHeaders(ownerId),
        fallbackMessage: "The extraction request could not be completed.",
      });
      return result.job;
    },
  };
}

export type ExtractionApi = ReturnType<typeof createExtractionApi>;
export const extractionApi = createExtractionApi();

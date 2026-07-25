import type { CreateJobRequest, ExtractionJob, JobResult } from "./types";

export class ExtractionApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = "request_failed",
  ) {
    super(message);
    this.name = "ExtractionApiError";
  }
}

type Fetcher = typeof fetch;

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;

  const problem = await response.json().catch(() => null) as
    | { detail?: string | Array<{ msg?: string }>; code?: string }
    | null;
  const detail = Array.isArray(problem?.detail)
    ? problem.detail.map((item) => item.msg).filter(Boolean).join("; ")
    : problem?.detail;
  throw new ExtractionApiError(
    detail || "The extraction request could not be completed.",
    response.status,
    problem?.code,
  );
}

function ownerHeaders(ownerId: string): HeadersInit {
  return { "X-Owner-ID": ownerId };
}

export function createExtractionApi(fetcher: Fetcher = fetch, ownerId = "local-development") {
  return {
    async createJob(payload: CreateJobRequest): Promise<ExtractionJob> {
      const response = await fetcher("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json", ...ownerHeaders(ownerId) },
        body: JSON.stringify(payload),
      });
      return parseResponse<ExtractionJob>(response);
    },

    async getJob(jobId: string): Promise<ExtractionJob> {
      const response = await fetcher(`/api/jobs/${encodeURIComponent(jobId)}`, {
        headers: ownerHeaders(ownerId),
      });
      return parseResponse<ExtractionJob>(response);
    },

    async getResult(jobId: string): Promise<JobResult> {
      const response = await fetcher(`/api/jobs/${encodeURIComponent(jobId)}/result`, {
        headers: ownerHeaders(ownerId),
      });
      return parseResponse<JobResult>(response);
    },

    async cancelJob(jobId: string): Promise<ExtractionJob> {
      const response = await fetcher(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
        headers: ownerHeaders(ownerId),
      });
      const result = await parseResponse<{ job: ExtractionJob }>(response);
      return result.job;
    },
  };
}

export type ExtractionApi = ReturnType<typeof createExtractionApi>;
export const extractionApi = createExtractionApi();

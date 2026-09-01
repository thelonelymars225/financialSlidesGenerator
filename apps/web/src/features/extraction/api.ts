import type { ExtractionJob, JobResult, JobSubmission } from "./types";
import { apiUrl } from "../../api-url";
import { apiAuthHeaders } from "../../auth";

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

function isFileSubmission(payload: JobSubmission): payload is Extract<JobSubmission, { file: File }> {
  return "file" in payload;
}

export function createExtractionApi(fetcher: Fetcher = fetch, ownerId = "local-development") {
  return {
    async createJob(payload: JobSubmission): Promise<ExtractionJob> {
      const authorization = await apiAuthHeaders(ownerId);
      if (isFileSubmission(payload)) {
        const digest = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", await payload.file.arrayBuffer())),
        ).map((byte) => byte.toString(16).padStart(2, "0")).join("");
        const signed = await parseResponse<{
          id: string; signed_url: string;
        }>(await fetcher(apiUrl("/api/uploads"), {
          method: "POST",
          headers: { "content-type": "application/json", ...authorization },
          body: JSON.stringify({
            file_name: payload.file.name,
            media_type: "application/pdf",
            size_bytes: payload.file.size,
            sha256: `sha256:${digest}`,
          }),
        }));
        const upload = await fetcher(signed.signed_url, {
          method: "PUT",
          headers: { "content-type": "application/pdf" },
          body: payload.file,
        });
        if (!upload.ok) throw new ExtractionApiError("The file upload failed.", upload.status);
        return parseResponse<ExtractionJob>(await fetcher(
          apiUrl(`/api/uploads/${encodeURIComponent(signed.id)}/jobs`),
          {
            method: "POST",
            headers: { "content-type": "application/json", ...authorization },
            body: JSON.stringify({
              deck_purpose: payload.deck_purpose,
              slide_count: payload.slide_count,
              request_key: payload.request_key,
            }),
          },
        ));
      }
      const response = await fetcher(apiUrl("/api/jobs"), {
        method: "POST",
        headers: { "content-type": "application/json", ...authorization },
        body: JSON.stringify(payload),
      });
      return parseResponse<ExtractionJob>(response);
    },

    async getJob(jobId: string): Promise<ExtractionJob> {
      const response = await fetcher(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}`), {
        headers: await apiAuthHeaders(ownerId),
      });
      return parseResponse<ExtractionJob>(response);
    },

    async getResult(jobId: string): Promise<JobResult> {
      const response = await fetcher(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/result`), {
        headers: await apiAuthHeaders(ownerId),
      });
      return parseResponse<JobResult>(response);
    },

    async cancelJob(jobId: string): Promise<ExtractionJob> {
      const response = await fetcher(apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/cancel`), {
        method: "POST",
        headers: await apiAuthHeaders(ownerId),
      });
      const result = await parseResponse<{ job: ExtractionJob }>(response);
      return result.job;
    },
  };
}

export type ExtractionApi = ReturnType<typeof createExtractionApi>;
export const extractionApi = createExtractionApi();

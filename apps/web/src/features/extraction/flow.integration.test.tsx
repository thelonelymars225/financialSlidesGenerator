import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import backendResponses from "../../../../../fixtures/integration/extraction-api-v0.1.json";
import { createExtractionApi } from "./api";
import { ExtractionResultPreview } from "./components/ExtractionResultPreview";
import { JobStatusPanel } from "./components/JobStatusPanel";
import { submitPollAndLoad } from "./flow";
import type { CreateJobRequest, ExtractionJob, JobResult } from "./types";

const request: CreateJobRequest = {
  input_mode: "text",
  source_text: "Revenue increased to $12.4 million.",
  deck_purpose: "management-review",
  slide_count: 8,
  request_key: "integration-request",
};

const successfulResult = backendResponses.successful_result as JobResult;
const failedJob = backendResponses.failed_job as ExtractionJob;

function job(status: ExtractionJob["status"]): ExtractionJob {
  const terminal = ["succeeded", "failed", "cancelled"].includes(status);
  return {
    ...successfulResult.job,
    status,
    started_at: status === "queued" ? null : "2026-07-25T06:00:00Z",
    finished_at: terminal ? "2026-07-25T06:00:01Z" : null,
    attempt_count: status === "queued" ? 0 : 1,
    failure: null,
    telemetry: status === "succeeded" ? successfulResult.job.telemetry : null,
  };
}

describe("submit → poll → render integration", () => {
  it("renders a traceable preview after a queued job succeeds", async () => {
    const responses = [
      new Response(JSON.stringify(job("queued")), { status: 202 }),
      new Response(JSON.stringify(job("running"))),
      new Response(JSON.stringify(job("succeeded"))),
      new Response(JSON.stringify(successfulResult)),
    ];
    const fetcher = vi.fn(async () => responses.shift()!);
    const flow = await submitPollAndLoad(createExtractionApi(fetcher as typeof fetch), request, {
      wait: async () => undefined,
      maxPolls: 4,
    });

    expect(flow.job.status).toBe("succeeded");
    const markup = renderToStaticMarkup(<ExtractionResultPreview result={flow.result!} />);
    expect(markup).toContain("Revenue increased to $12.4 million.");
    expect(markup).toContain("Page 1 · Pasted input");
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("renders an actionable typed failure and never requests a result", async () => {
    const responses = [
      new Response(JSON.stringify(job("queued")), { status: 202 }),
      new Response(JSON.stringify(failedJob)),
    ];
    const fetcher = vi.fn(async () => responses.shift()!);
    const flow = await submitPollAndLoad(createExtractionApi(fetcher as typeof fetch), request, {
      wait: async () => undefined,
      maxPolls: 2,
    });

    const markup = renderToStaticMarkup(
      <JobStatusPanel job={flow.job} cancelling={false} onCancel={() => undefined} onRetry={() => undefined} />,
    );
    expect(markup).toContain("Remove the document password");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("renders structured PDF warnings with unique React keys", () => {
    const result: JobResult = {
      ...successfulResult,
      document: {
        ...successfulResult.document,
        warnings: [
          { code: "document.route.mixed", severity: "info", message: "Mixed extraction route." },
          { code: "ocr.low_confidence", severity: "warning", message: "Review OCR output." },
        ],
      },
    };
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    try {
      const markup = renderToStaticMarkup(<ExtractionResultPreview result={result} />);
      expect(markup).toContain("Mixed extraction route.");
      expect(markup).toContain("Review OCR output.");
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });
});

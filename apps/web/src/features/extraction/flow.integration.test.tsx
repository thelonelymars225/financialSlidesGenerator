import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createExtractionApi } from "./api";
import { ExtractionResultPreview } from "./components/ExtractionResultPreview";
import { JobStatusPanel } from "./components/JobStatusPanel";
import { submitPollAndLoad } from "./flow";
import type { CreateJobRequest, ExtractionJob } from "./types";

const request: CreateJobRequest = {
  input_mode: "text",
  source_text: "Revenue increased to $12.4 million.",
  deck_purpose: "management-review",
  slide_count: 8,
  request_key: "integration-request",
};

function job(status: ExtractionJob["status"], failure: ExtractionJob["failure"] = null): ExtractionJob {
  return {
    id: "4c4f87b3-5a21-487b-b2d0-080ace475214",
    input_mode: "text",
    file_name: null,
    deck_purpose: "management-review",
    slide_count: 8,
    status,
    created_at: "2026-07-25T06:00:00Z",
    updated_at: "2026-07-25T06:00:01Z",
    started_at: status === "queued" ? null : "2026-07-25T06:00:00Z",
    finished_at: ["succeeded", "failed", "cancelled"].includes(status) ? "2026-07-25T06:00:01Z" : null,
    attempt_count: status === "queued" ? 0 : 1,
    max_attempts: 3,
    failure,
    telemetry: status === "succeeded" ? { route: "pasted_text", duration_ms: 5, retries: 0, external_cost_usd: 0 } : null,
  };
}

describe("submit → poll → render integration", () => {
  it("renders a traceable preview after a queued job succeeds", async () => {
    const responses = [
      new Response(JSON.stringify(job("queued")), { status: 202 }),
      new Response(JSON.stringify(job("running"))),
      new Response(JSON.stringify(job("succeeded"))),
      new Response(JSON.stringify({
        job: job("succeeded"),
        document: {
          schemaVersion: "0.1",
          source: { inputType: "text", mediaType: "text/plain" },
          pages: [{
            pageNumber: 1,
            blocks: [{
              id: "text-1",
              type: "text",
              order: 0,
              text: "Revenue increased to $12.4 million.",
              source: { pageNumber: 1, sectionPath: ["Pasted input"] },
            }],
          }],
          warnings: [],
        },
      })),
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
    const failure = { code: "encrypted_file", message: "The PDF is encrypted." };
    const responses = [
      new Response(JSON.stringify(job("queued")), { status: 202 }),
      new Response(JSON.stringify(job("failed", failure))),
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
});

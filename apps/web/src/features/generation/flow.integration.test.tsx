import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createGenerationApi } from "./api";
import { SlidePreview } from "./components/SlidePreview";
import { generatePollAndLoad, waitForGeneration } from "./flow";
import { generationFailureGuidance } from "./state";
import type { GenerationJob, GenerationResult } from "./types";

const extractionJobId = "c23ac48d-f9be-4214-997f-a32af1332d71";

function job(status: GenerationJob["status"], attemptCount = 1): GenerationJob {
  return {
    id: "61b109d8-d46b-4e73-8b38-d60d1bcb3204",
    extraction_job_id: extractionJobId,
    deck_type: "management-review",
    slide_count: 8,
    status,
    progress: status === "succeeded" || status === "failed" ? 100 : 25,
    attempt_count: attemptCount,
    max_attempts: 2,
    created_at: "2026-07-25T12:00:00Z",
    updated_at: "2026-07-25T12:00:01Z",
    failure: null,
    analysis: null,
  };
}

const result: GenerationResult = {
  job: job("succeeded"),
  slide_spec: {
    title: "Management Review",
    slides: [
      {
        id: "slide-title",
        order: 1,
        title: "Management Review",
        components: [
          {
            id: "summary",
            type: "text",
            text: "Revenue reached $12.4 million.",
          },
        ],
      },
    ],
  },
  download_url: "/api/slide-jobs/61b109d8-d46b-4e73-8b38-d60d1bcb3204/artifact",
};

describe("extraction → analysis → preview → PowerPoint integration", () => {
  it("renders a safe preview and downloads the PowerPoint artifact", async () => {
    const responses = [
      new Response(JSON.stringify(job("queued")), { status: 202 }),
      new Response(JSON.stringify(job("analyzing"))),
      new Response(JSON.stringify(job("rendering"))),
      new Response(JSON.stringify(job("succeeded"))),
      new Response(JSON.stringify(result)),
      new Response(new Uint8Array([80, 75, 3, 4]), {
        headers: {
          "content-type":
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        },
      }),
    ];
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => responses.shift()!);
    const api = createGenerationApi(fetcher as typeof fetch);
    const flow = await generatePollAndLoad(
      api,
      extractionJobId,
      "management-review",
      { wait: async () => undefined, maxPolls: 4 },
    );
    const artifact = await api.download(flow.job.id);
    const markup = renderToStaticMarkup(<SlidePreview result={flow.result!} />);

    expect(markup).toContain("Revenue reached $12.4 million.");
    expect(markup).not.toContain("dangerouslySetInnerHTML");
    expect(artifact.type).toContain("presentationml.presentation");
    expect(fetcher).toHaveBeenCalledTimes(6);
    expect(fetcher.mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({
        deck_type: "management-review",
        request_key: `auto:${extractionJobId}:management-review`,
      }),
    );
  });

  it("keeps a typed renderer failure retryable and completes the same job", async () => {
    const failed = {
      ...job("failed"),
      failure: {
        code: "rendering_failed",
        message: "safe renderer message",
        retryable: true,
      },
    };
    const responses = [
      new Response(JSON.stringify(failed)),
      new Response(JSON.stringify(job("queued")), { status: 200 }),
      new Response(JSON.stringify(job("rendering", 2))),
      new Response(JSON.stringify(job("succeeded", 2))),
    ];
    const fetcher = vi.fn(async () => responses.shift()!);
    const api = createGenerationApi(fetcher as typeof fetch);

    const first = await api.getJob(failed.id);
    expect(generationFailureGuidance(first.failure)).toContain("Retry");
    await api.retry(failed.id);
    const retried = await waitForGeneration(api, failed.id, {
      wait: async () => undefined,
      maxPolls: 2,
    });

    expect(retried.status).toBe("succeeded");
    expect(retried.attempt_count).toBe(2);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});

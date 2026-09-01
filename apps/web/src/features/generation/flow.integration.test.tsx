import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createGenerationApi, GenerationApiError } from "./api";
import { currentGenerationResult } from "./components/SlideGenerationPanel";
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
    density: "balanced",
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
  it("never displays a cached result for a different or failed current job", () => {
    expect(currentGenerationResult(job("failed"), result)).toBeUndefined();
    expect(currentGenerationResult({ ...job("succeeded"), id: "new-job" }, result)).toBeUndefined();
    expect(currentGenerationResult(job("succeeded"), result)).toBe(result);
  });

  it("provides actionable analysis-provider failure guidance", () => {
    expect(generationFailureGuidance({
      code: "analysis_timeout",
      message: "safe timeout",
      retryable: true,
    })).toContain("took too long");
    expect(generationFailureGuidance({
      code: "analysis_authentication_failed",
      message: "safe auth failure",
      retryable: false,
    })).toContain("credentials");
  });

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
        density: "balanced",
        request_key: `auto:${extractionJobId}:management-review:balanced`,
      }),
    );
  });

  it("submits every canonical density without changing the extraction job", async () => {
    const fetcher = vi.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => new Response(JSON.stringify(job("queued")), { status: 202 }));
    const api = createGenerationApi(fetcher as typeof fetch);

    for (const density of ["concise", "balanced", "detailed"] as const) {
      await api.start(extractionJobId, "management-review", `density:${density}`, density);
    }

    expect(fetcher).toHaveBeenCalledTimes(3);
    for (const [index, density] of ["concise", "balanced", "detailed"].entries()) {
      expect(fetcher.mock.calls[index]?.[0].toString()).toContain(extractionJobId);
      expect(fetcher.mock.calls[index]?.[1]?.body).toBe(JSON.stringify({
        deck_type: "management-review",
        density,
        request_key: `density:${density}`,
      }));
    }
  });

  it("surfaces an invalid density response as a typed client error", async () => {
    const api = createGenerationApi(vi.fn(async () => new Response(
      JSON.stringify({ detail: "Input should be 'concise', 'balanced' or 'detailed'" }),
      { status: 422 },
    )) as typeof fetch);

    await expect(api.start(extractionJobId, "management-review", "invalid", "detailed"))
      .rejects.toEqual(expect.objectContaining<Partial<GenerationApiError>>({
        name: "GenerationApiError",
        status: 422,
      }));
  });

  it("preserves measurable profile differences and source citations through polling", async () => {
    const detail = {
      concise: "Revenue grew.",
      balanced: "Revenue grew 12% with enterprise renewals supporting the result.",
      detailed: "Revenue grew 12% with enterprise renewals supporting the result; management should monitor margin pressure and renewal concentration.",
    } as const;
    const observed: number[] = [];

    for (const density of Object.keys(detail) as Array<keyof typeof detail>) {
      const terminal = { ...job("succeeded"), density };
      const slides = Array.from({ length: terminal.slide_count }, (_, index) => ({
        id: `slide-${index + 1}`,
        order: index + 1,
        title: `Grounded slide ${index + 1}`,
        components: [{
          id: `source-${index + 1}`,
          type: "text",
          text: detail[density],
          sources: [{ documentId: "document-1", pageNumber: 1, blockId: "block-1" }],
        }],
      }));
      const profileResult: GenerationResult = {
        job: terminal,
        slide_spec: { title: "Management Review", densityProfile: density, slides },
        download_url: `/api/slide-jobs/${terminal.id}/artifact`,
      };
      const responses = [
        new Response(JSON.stringify({ ...job("queued"), density }), { status: 202 }),
        new Response(JSON.stringify(terminal)),
        new Response(JSON.stringify(profileResult)),
      ];
      const api = createGenerationApi(vi.fn(async () => responses.shift()!) as typeof fetch);
      const flow = await generatePollAndLoad(api, extractionJobId, "management-review", {
        density,
        maxPolls: 1,
        wait: async () => undefined,
      });

      observed.push(flow.result!.slide_spec.slides.length);
      expect(flow.result!.slide_spec.densityProfile).toBe(density);
      expect(flow.result!.slide_spec.slides[0]?.components[0]?.text).toBe(detail[density]);
      expect(flow.result!.slide_spec.slides.every((slide) =>
        slide.components[0]?.sources?.[0]?.blockId === "block-1"
      )).toBe(true);
    }

    expect(observed).toEqual([8, 8, 8]);
    expect(detail.concise.length).toBeLessThan(detail.balanced.length);
    expect(detail.balanced.length).toBeLessThan(detail.detailed.length);
  });

  it("keeps a typed renderer failure retryable and completes the same job", async () => {
    const failed = {
      ...job("failed"),
      density: "detailed" as const,
      failure: {
        code: "rendering_failed",
        message: "safe renderer message",
        retryable: true,
      },
    };
    const responses = [
      new Response(JSON.stringify(failed)),
      new Response(JSON.stringify({ ...job("queued"), density: "detailed" }), { status: 200 }),
      new Response(JSON.stringify({ ...job("rendering", 2), density: "detailed" })),
      new Response(JSON.stringify({ ...job("succeeded", 2), density: "detailed" })),
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
    expect(retried.density).toBe("detailed");
    expect(retried.attempt_count).toBe(2);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});

import { describe, expect, it, vi } from "vitest";
import { createExtractionApi } from "./api";
import type { CreateJobRequest } from "./types";

const request: CreateJobRequest = {
  input_mode: "text",
  source_text: "Revenue increased.",
  deck_purpose: "management-review",
  slide_count: 8,
  request_key: "request-1",
};

describe("extraction API client", () => {
  it("submits the canonical request with the owner boundary", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ id: "job-1", status: "queued" }), { status: 202 }));
    const api = createExtractionApi(fetcher as typeof fetch, "owner-1");

    await expect(api.createJob(request)).resolves.toMatchObject({ id: "job-1", status: "queued" });
    expect(fetcher).toHaveBeenCalledWith("/api/jobs", expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "X-Owner-ID": "owner-1" }),
    }));
  });

  it("surfaces a safe typed HTTP problem", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ detail: "File is encrypted.", code: "encrypted_pdf" }), { status: 422 }));
    const api = createExtractionApi(fetcher as typeof fetch);

    await expect(api.createJob(request)).rejects.toMatchObject({
      message: "File is encrypted.",
      status: 422,
      code: "encrypted_pdf",
    });
  });
});

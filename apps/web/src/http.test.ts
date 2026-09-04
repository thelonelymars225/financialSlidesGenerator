import { describe, expect, it, vi } from "vitest";
import { createHttpClient } from "./http";

describe("shared HTTP client", () => {
  it("parses JSON and Blob responses", async () => {
    const responses = [
      new Response(JSON.stringify({ status: "ok" })),
      new Response(new Uint8Array([80, 75, 3, 4]), { headers: { "content-type": "application/zip" } }),
    ];
    const request = createHttpClient(vi.fn(async () => responses.shift()!) as typeof fetch);

    await expect(request<{ status: string }>("/status")).resolves.toEqual({ status: "ok" });
    const artifact = await request<Blob>("/artifact", { responseType: "blob" });
    expect(artifact.type).toBe("application/zip");
  });

  it("retries safe network and server failures at most twice", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new TypeError("network failure"))
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" })));
    const request = createHttpClient(fetcher as typeof fetch);

    await expect(request<{ status: string }>("/status")).resolves.toEqual({ status: "ok" });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("never retries 4xx responses or mutations", async () => {
    const validationFetcher = vi.fn(async () => new Response(
      JSON.stringify({ detail: [{ msg: "Select a valid option." }], code: "invalid_input" }),
      { status: 422, headers: { "X-Request-ID": "api-request-1" } },
    ));
    const mutationFetcher = vi.fn(async () => new Response(null, { status: 503 }));

    await expect(createHttpClient(validationFetcher as typeof fetch)("/jobs"))
      .rejects.toMatchObject({
        kind: "validation",
        status: 422,
        code: "invalid_input",
        requestId: "api-request-1",
      });
    await expect(createHttpClient(mutationFetcher as typeof fetch)("/jobs", { method: "POST" }))
      .rejects.toMatchObject({ kind: "api", status: 503 });
    expect(validationFetcher).toHaveBeenCalledOnce();
    expect(mutationFetcher).toHaveBeenCalledOnce();
  });

  it("normalizes timeouts without retrying", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>(
      (_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new Error("aborted"))),
    ));

    try {
      const pending = createHttpClient(fetcher as typeof fetch)("/slow", { timeoutMs: 25 });
      const rejection = expect(pending).rejects.toMatchObject({
        kind: "timeout",
        code: "request_timeout",
      });
      await vi.advanceTimersByTimeAsync(25);
      await rejection;
      expect(fetcher).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});

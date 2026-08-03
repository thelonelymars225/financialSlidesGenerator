import { describe, expect, it } from "vitest";
import { apiUrl } from "./api-url";

describe("API URL", () => {
  it("keeps same-origin paths for local development", () => {
    expect(apiUrl("/api/jobs", "")).toBe("/api/jobs");
  });

  it("joins a hosted API origin without duplicate slashes", () => {
    expect(apiUrl("/api/jobs", " https://api.example.com/ ")).toBe(
      "https://api.example.com/api/jobs",
    );
  });

  it("rejects ambiguous relative paths", () => {
    expect(() => apiUrl("api/jobs", "https://api.example.com")).toThrow(
      "API paths must start with /",
    );
  });
});

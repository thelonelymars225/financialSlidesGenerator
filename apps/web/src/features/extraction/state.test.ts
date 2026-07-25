import { describe, expect, it } from "vitest";
import {
  documentSummary,
  failureGuidance,
  isTerminalStatus,
  nextPollInterval,
  orderedBlocks,
  sourceLabel,
} from "./state";
import type { JobStatus } from "./types";

describe("extraction state mapping", () => {
  it("stops polling for every terminal state", () => {
    const terminal: JobStatus[] = ["succeeded", "failed", "cancelled"];
    expect(terminal.every(isTerminalStatus)).toBe(true);
    expect(nextPollInterval("succeeded")).toBe(false);
    expect(nextPollInterval("running")).toBe(1_000);
    expect(nextPollInterval("queued")).toBe(1_500);
  });

  it("maps typed failures to actionable guidance", () => {
    expect(failureGuidance({ code: "encrypted_file", message: "encrypted" })).toContain("password");
    expect(failureGuidance({ code: "custom", message: "Specific safe message" })).toBe("Specific safe message");
  });

  it("sorts blocks and summarizes safe document metadata", () => {
    expect(orderedBlocks([{ id: "b", order: 2 }, { id: "a", order: 1 }]).map((block) => block.id)).toEqual(["a", "b"]);
    expect(sourceLabel({ pageNumber: 7, sectionPath: ["Results", "Revenue"] })).toBe("Page 7 · Results › Revenue");
    expect(documentSummary({
      pages: [{ blocks: [{ warnings: ["low confidence"] }, {}] }],
      warnings: ["review"],
    })).toEqual({ pageCount: 1, blockCount: 2, warningCount: 2 });
  });
});

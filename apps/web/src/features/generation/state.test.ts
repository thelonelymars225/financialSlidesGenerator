import { describe, expect, it } from "vitest";
import { automaticGenerationRequestKey } from "./state";

describe("automatic generation idempotency", () => {
  it("uses a stable key for rerenders and polling races", () => {
    expect(automaticGenerationRequestKey("extraction-1", "management-review")).toBe(
      "auto:extraction-1:management-review",
    );
    expect(automaticGenerationRequestKey("extraction-1", "management-review")).toBe(
      automaticGenerationRequestKey("extraction-1", "management-review"),
    );
  });
});

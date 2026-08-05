import { describe, expect, it } from "vitest";
import { automaticGenerationRequestKey } from "./state";
import {
  DEFAULT_PRESENTATION_DENSITY,
  normalizePresentationDensity,
} from "./density";

describe("automatic generation idempotency", () => {
  it("uses a stable key for rerenders and polling races", () => {
    expect(automaticGenerationRequestKey("extraction-1", "management-review")).toBe(
      "auto:extraction-1:management-review:balanced",
    );
    expect(automaticGenerationRequestKey("extraction-1", "management-review")).toBe(
      automaticGenerationRequestKey("extraction-1", "management-review"),
    );
  });

  it("includes density in the stable request key", () => {
    expect(automaticGenerationRequestKey("extraction-1", "management-review", "concise"))
      .toBe("auto:extraction-1:management-review:concise");
    expect(automaticGenerationRequestKey("extraction-1", "management-review", "detailed"))
      .toBe("auto:extraction-1:management-review:detailed");
  });

  it("defaults omitted and stale values to balanced", () => {
    expect(DEFAULT_PRESENTATION_DENSITY).toBe("balanced");
    expect(normalizePresentationDensity(undefined)).toBe("balanced");
    expect(normalizePresentationDensity("maximum")).toBe("balanced");
    expect(normalizePresentationDensity("concise")).toBe("concise");
  });
});

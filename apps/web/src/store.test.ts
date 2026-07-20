import { beforeEach, describe, expect, it } from "vitest";
import { useGeneratorStore } from "./store";

describe("generator store", () => {
  beforeEach(() => useGeneratorStore.setState({ inputMode: "file", sourceText: "", fileName: null }));

  it("switches input mode and retains source text", () => {
    useGeneratorStore.getState().setInputMode("text");
    useGeneratorStore.getState().setSourceText("Revenue increased.");
    expect(useGeneratorStore.getState()).toMatchObject({ inputMode: "text", sourceText: "Revenue increased." });
  });
});

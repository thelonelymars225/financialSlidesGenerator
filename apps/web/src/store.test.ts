import { beforeEach, describe, expect, it } from "vitest";
import { useGeneratorStore } from "./store";

describe("generator store", () => {
  beforeEach(() => useGeneratorStore.setState({ theme: "light" }));

  it("toggles the color theme", () => {
    useGeneratorStore.getState().toggleTheme();
    expect(useGeneratorStore.getState().theme).toBe("dark");
  });
});

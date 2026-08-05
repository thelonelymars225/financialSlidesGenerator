import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PresentationDensitySelector } from "./components/PresentationDensitySelector";
import { PRESENTATION_DENSITY_OPTIONS } from "./density";

describe("presentation density selector", () => {
  it("renders one keyboard-native radio for every canonical profile", () => {
    const markup = renderToStaticMarkup(
      <PresentationDensitySelector
        onChange={() => undefined}
        value="balanced"
      />,
    );

    expect(PRESENTATION_DENSITY_OPTIONS.map(({ value }) => value)).toEqual([
      "concise",
      "balanced",
      "detailed",
    ]);
    expect(markup.match(/type="radio"/g)).toHaveLength(3);
    expect(markup).toContain("Presentation detail");
    expect(markup).toContain("aria-describedby=\"density-help\"");
    expect(markup).toContain("checked=\"\" value=\"balanced\"");
    expect(markup).toContain("not greater accuracy");
  });
});

import { type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApplicationErrorBoundary, RecoveryScreen } from "./error-boundary";

describe("ApplicationErrorBoundary", () => {
  it("shows a safe fallback and resets its children", () => {
    const boundary = new ApplicationErrorBoundary({
      children: <p>Application recovered</p>,
    });
    boundary.state = ApplicationErrorBoundary.getDerivedStateFromError(
      new Error("technical rendering detail"),
    );
    boundary.setState = vi.fn(() => {
      boundary.state = { error: null };
    }) as typeof boundary.setState;

    const fallback = boundary.render() as ReactElement<{
      onReset: () => void;
      onReload: () => void;
    }>;
    const markup = renderToStaticMarkup(fallback);

    expect(fallback.type).toBe(RecoveryScreen);
    expect(markup).toContain("Something went wrong");
    expect(markup).toContain("Try again");
    expect(markup).toContain("Reload application");
    expect(markup).not.toContain("technical rendering detail");

    fallback.props.onReset();

    expect(renderToStaticMarkup(boundary.render())).toContain("Application recovered");
  });
});

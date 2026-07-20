/**
 * Deterministic analysis-to-DeckSpec compilation belongs here.
 * Model-generated arbitrary HTML is intentionally outside this boundary.
 */
export function createPreflightReport(slideCount) {
  if (!Number.isInteger(slideCount) || slideCount < 0) {
    throw new TypeError("slideCount must be a non-negative integer");
  }
  return { status: "pending", slideCount, failures: [] };
}

export type PresentationDensity = "concise" | "balanced" | "detailed";

export const DEFAULT_PRESENTATION_DENSITY: PresentationDensity = "balanced";

export const PRESENTATION_DENSITY_OPTIONS = Object.freeze([
  {
    value: "concise",
    label: "Concise",
    summary: "Fast executive scan",
    detail: "About 4–6 slides with essential insights and minimal notes.",
  },
  {
    value: "balanced",
    label: "Balanced",
    summary: "Recommended",
    detail: "About 6–10 slides with moderate depth, cost, and supporting evidence.",
  },
  {
    value: "detailed",
    label: "Detailed",
    summary: "Greater depth",
    detail: "Up to 16 slides with richer notes and supported tables—not greater accuracy.",
  },
] satisfies ReadonlyArray<{
  value: PresentationDensity;
  label: string;
  summary: string;
  detail: string;
}>);

export function normalizePresentationDensity(value: unknown): PresentationDensity {
  return PRESENTATION_DENSITY_OPTIONS.some((option) => option.value === value)
    ? value as PresentationDensity
    : DEFAULT_PRESENTATION_DENSITY;
}

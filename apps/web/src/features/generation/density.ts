export type PresentationDensity = "concise" | "balanced" | "detailed";

export const DEFAULT_PRESENTATION_DENSITY: PresentationDensity = "balanced";

export const PRESENTATION_DENSITY_OPTIONS = Object.freeze([
  {
    value: "concise",
    label: "Concise",
    summary: "Fast executive scan",
    detail: "Essential insights with shorter content and minimal notes on each slide.",
  },
  {
    value: "balanced",
    label: "Balanced",
    summary: "Recommended",
    detail: "Moderate detail and supporting evidence on each slide.",
  },
  {
    value: "detailed",
    label: "Detailed",
    summary: "Greater depth",
    detail: "Richer detail, notes, and supported tables on each slide—not greater accuracy.",
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

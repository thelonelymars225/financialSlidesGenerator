const PROFILE = Object.freeze({
  concise: Object.freeze({ insights: 1, bullets: 3, rows: 5, minFont: 18, spacing: 6, fit: 1, repair: 1 }),
  balanced: Object.freeze({ insights: 2, bullets: 5, rows: 8, minFont: 16, spacing: 4, fit: 2, repair: 2 }),
  detailed: Object.freeze({ insights: 3, bullets: 7, rows: 12, minFont: 14, spacing: 4, fit: 2, repair: 2 }),
});

const documentId = "document-consolidated-financial-performance-report-fy2026-management-reviewed";

function source(pageNumber = 1) {
  return { documentId, pageNumber, blockId: `page-${pageNumber}-block-1` };
}

function value(amount, label = "FY 2026") {
  return {
    displayedValue: `${amount < 0 ? "-" : ""}$${Math.abs(amount).toFixed(1)}m`,
    value: amount,
    normalizedValue: amount * 1_000_000,
    unit: { kind: "currency", code: "USD", scaleFactor: 1_000_000 },
    period: { type: "year", label, startDate: "2026-01-01", endDate: "2026-12-31" },
  };
}

function text(id, region, content, variant = "body") {
  return { id, type: "text", region, sources: [], text: content, variant };
}

function insight(id, region, statement, emphasis = "neutral", page = 1) {
  return { id, type: "insight", region, sources: [source(page)], findingId: `finding-${id}`, statement, emphasis };
}

function metric(id, region, label, amount, page = 1) {
  return { id, type: "metric", region, sources: [source(page)], metricId: `metric-${id}`, label, value: value(amount) };
}

function rows(count) {
  return Array.from({ length: count }, (_, index) => [
    { kind: "text", text: `Business unit ${index + 1}` },
    { kind: "financial", value: value(18.4 - index * 2.1) },
    { kind: "financial", value: value(index === count - 1 ? -1.2 : 3.8 - index * 0.3) },
  ]);
}

export function visualFixture(density = "balanced") {
  const profile = PROFILE[density];
  if (!profile) throw new Error(`Unknown visual fixture density: ${density}`);
  const sourceList = Array.from({ length: 10 }, (_, index) => source(index + 1));
  return {
    schemaVersion: "0.1",
    densityContractVersion: "0.2",
    densityProfile: density,
    densityConstraints: {
      maxInsightsPerSlide: profile.insights,
      maxBulletsPerSlide: profile.bullets,
      maxTableRows: profile.rows,
      chartPreference: density === "concise" ? "essential-only" : density === "detailed" ? "when-supported" : "when-useful",
      speakerNotesDepth: density === "concise" ? "minimal" : density === "detailed" ? "rich" : "standard",
      appendixPolicy: density === "concise" ? "only-when-needed" : density === "detailed" ? "include-when-supported" : "evidence-dependent",
      preflight: { minFontSize: profile.minFont, minSpacing: profile.spacing, maxAutoFitPasses: profile.fit, maxRepairAttempts: profile.repair },
    },
    requestedSlideCount: 8,
    deckId: `deck-layout-regression-${density}`,
    sourceAnalysisId: "analysis-layout-regression",
    sourceDocumentIds: [documentId],
    title: "FY 2026 performance review",
    subtitle: "Management discussion",
    audience: "Executive leadership",
    themeId: "theme-corporate-default",
    slides: [
      {
        id: "slide-title", order: 1, layoutId: "title", title: "FY 2026 performance review",
        components: [text("title-subtitle", "body", "Management discussion | 5 August 2026", "heading")],
      },
      {
        id: "slide-summary", order: 2, layoutId: "executive-summary", title: "Growth held while margins tightened",
        components: [
          insight("summary-finding", "left", "Revenue grew 12%, led by enterprise renewals and higher expansion revenue.", "positive", 2),
          text("summary-context", "right", "Gross margin declined 1.2 points as cloud and implementation costs rose. The next-quarter focus is disciplined delivery and pricing.", "body"),
        ],
      },
      {
        id: "slide-scorecard", order: 3, layoutId: "kpi-grid", title: "KPI scorecard",
        components: [
          metric("revenue", "top-left", "Revenue", 48.2, 2),
          metric("gross-profit", "top-right", "Gross profit", 31.4, 3),
          metric("operating-income", "bottom-left", "Operating income", 7.6, 3),
          metric("free-cash-flow", "bottom-right", "Free cash flow", -1.2, 4),
        ],
      },
      {
        id: "slide-trend", order: 4, layoutId: "chart", title: "Quarterly revenue trend",
        components: [
          {
            id: "revenue-trend", type: "chart", region: "primary", sources: [source(5)], chartType: "line",
            categories: ["Q1", "Q2", "Q3", "Q4"],
            series: [{ id: "revenue-series", name: "Revenue", values: [10.2, 11.4, 12.1, 14.5].map((amount, index) => value(amount, `Q${index + 1} 2026`)) }],
          },
          insight("trend-callout", "secondary", "Q4 acceleration followed two enterprise launches; concentration remains a watch item.", "warning", 5),
        ],
      },
      {
        id: "slide-table", order: 5, layoutId: "financial-table", title: "Business-unit performance",
        components: [{ id: "unit-table", type: "table", region: "body", sources: [source(6)], columns: ["Business unit", "Revenue", "Operating income"], rows: rows(profile.rows) }],
      },
      {
        id: "slide-drivers", order: 6, layoutId: "key-drivers", title: "Key value drivers",
        components: [
          insight("driver-renewals", "left", "Enterprise renewals remained the largest growth contributor.", "positive", 7),
          insight("driver-pricing", "right", "Pricing actions partially offset higher delivery costs.", "neutral", 7),
        ].slice(0, profile.insights === 1 ? 1 : 2),
      },
      {
        id: "slide-actions", order: 7, layoutId: "risks-actions", title: "Risks and management actions",
        components: [
          insight("risk-concentration", "left", "Customer concentration increased after the Q4 launches.", "warning", 8),
          text("action-concentration", "right", "Action: strengthen mid-market pipeline coverage and add renewal checkpoints to the operating cadence.", "callout"),
        ],
      },
      {
        id: "slide-sources", order: 8, layoutId: "sources-appendix", title: "Sources and appendix",
        components: [{ id: "sources-table", type: "table", region: "body", sources: sourceList, columns: ["Section", "Reference"], rows: [[{ kind: "text", text: "Financial statements" }, { kind: "text", text: "Pages 2–6" }], [{ kind: "text", text: "Management commentary" }, { kind: "text", text: "Pages 7–10" }]] }],
      },
    ],
  };
}

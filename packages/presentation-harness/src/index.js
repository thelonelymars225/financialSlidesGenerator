import {
  DEFAULT_PREFLIGHT_POLICY,
  analyzeMeasurements,
  createRepairPlan,
  deriveFitOverrides,
  measureBrowserPage,
  preflightBrowserDeck,
} from "./preflight.js";
import {
  defaultPresentationTheme,
  resolvePresentationTheme,
} from "./theme.js";

const CANVAS = Object.freeze({ width: 1280, height: 720 });
const THEME = defaultPresentationTheme;
const TYPOGRAPHY = Object.freeze({
  fontFamily: `${THEME.fonts.body}, ${THEME.fonts.fallback}`,
  titleSize: THEME.typography.title.web,
  headingSize: THEME.typography.heading.web,
  bodySize: THEME.typography.body.web,
  captionSize: THEME.typography.caption.web,
});

const REGIONS = Object.freeze({
  title: Object.freeze({ x: 72, y: 124, width: 1136, height: 64 }),
  body: Object.freeze({ x: 72, y: 212, width: 1136, height: 428 }),
  left: Object.freeze({ x: 72, y: 144, width: 548, height: 504 }),
  right: Object.freeze({ x: 660, y: 144, width: 548, height: 504 }),
  primary: Object.freeze({ x: 72, y: 144, width: 744, height: 504 }),
  secondary: Object.freeze({ x: 856, y: 144, width: 352, height: 504 }),
  footer: Object.freeze({ x: 72, y: 664, width: 1136, height: 32 }),
  background: Object.freeze({ x: 0, y: 0, width: 1280, height: 720 }),
});

function layout(allowedComponents, regionNames) {
  return Object.freeze({
    canvas: CANVAS,
    typography: TYPOGRAPHY,
    allowedComponents: Object.freeze(allowedComponents),
    regions: Object.freeze(
      Object.fromEntries(regionNames.map((name) => [name, REGIONS[name]])),
    ),
  });
}

export const layoutRegistry = Object.freeze({
  title: layout(["text", "image"], ["title", "body", "background", "footer"]),
  "executive-summary": layout(
    ["text", "metric", "insight"],
    ["title", "body", "left", "right", "footer"],
  ),
  "kpi-grid": layout(
    ["text", "metric"],
    ["title", "body", "primary", "secondary", "footer"],
  ),
  "financial-table": layout(["text", "table"], ["title", "body", "footer"]),
  chart: layout(
    ["text", "chart", "insight"],
    ["title", "primary", "secondary", "footer"],
  ),
  insight: layout(
    ["text", "metric", "insight"],
    ["title", "body", "primary", "secondary", "footer"],
  ),
});

const UNSAFE_CONTENT = /<\/?[a-z][^>]*>|javascript:|data:text\/html/i;
function cssColor(value) {
  return `#${value.toLowerCase()}`;
}

const CSS = `
*{box-sizing:border-box}html,body{margin:0;background:${cssColor(THEME.colors.border)}}
body{font-family:${THEME.fonts.body},${THEME.fonts.fallback};color:${cssColor(THEME.colors.ink)}}
.deck{display:grid;gap:24px;padding:24px}
.slide{position:relative;width:1280px;height:720px;overflow:hidden;background:${cssColor(THEME.colors.canvas)}}
.slide-title{position:absolute;left:72px;top:40px;width:1136px;height:72px;margin:0;
font-family:${THEME.fonts.heading},${THEME.fonts.fallback};font-size:${THEME.typography.title.web}px;line-height:1.1;border-bottom:2px solid ${cssColor(THEME.colors.accent)}}
.component{position:absolute;overflow:hidden;font-size:${THEME.typography.body.web}px;line-height:1.3}
.text-heading,.text-callout{font-weight:700}.text-heading{font-size:${THEME.typography.heading.web}px}
.text-caption{font-size:${THEME.typography.caption.web}px;color:${cssColor(THEME.colors.muted)}}.metric{text-align:center}
.metric-value{display:block;color:${cssColor(THEME.colors.accent)};font-size:${THEME.typography.metric.web}px;font-weight:700}
.insight{padding:28px;background:${cssColor(THEME.colors.surface)};border:1px solid ${cssColor(THEME.colors.border)};font-weight:700}
.insight-positive{color:${cssColor(THEME.colors.positive)}}.insight-negative{color:${cssColor(THEME.colors.negative)}}
.insight-warning{color:${cssColor(THEME.colors.warning)}}.insight-neutral{color:${cssColor(THEME.colors.muted)}}
table{width:100%;border-collapse:collapse}th,td{padding:12px;border:1px solid ${cssColor(THEME.table.border)};text-align:left}
th{background:${cssColor(THEME.table.headerFill)};color:${cssColor(THEME.table.headerText)}}tbody tr:nth-child(even){background:${cssColor(THEME.table.stripeFill)}}
.chart-data caption{text-align:left;font-weight:700;margin-bottom:12px}.slide-source-note{position:absolute;left:72px;top:684px;width:1136px;height:20px;overflow:hidden;color:${cssColor(THEME.sourceNote.color)};font-size:${THEME.sourceNote.webFontSize}px}
.image{object-fit:contain} @media print{.deck{display:block;padding:0}.slide{break-after:page}}
`.trim();

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function assertSafe(value, label) {
  if (typeof value === "string" && UNSAFE_CONTENT.test(value)) {
    throw new Error(`${label} contains unsafe content`);
  }
  if (value && typeof value === "object") {
    for (const nested of Object.values(value)) assertSafe(nested, label);
  }
}

export function densityPreflightPolicy(deckSpec) {
  if (
    deckSpec?.densityContractVersion !== "0.1" ||
    !["concise", "balanced", "detailed"].includes(deckSpec.densityProfile)
  ) {
    throw new Error("Presentation density contract v0.1 is required");
  }
  const constraints = deckSpec.densityConstraints;
  const preflight = constraints?.preflight;
  if (
    !constraints ||
    !Array.isArray(constraints.targetSlideRange) ||
    constraints.targetSlideRange.length !== 2 ||
    !preflight
  ) {
    throw new Error("Resolved presentation density constraints are required");
  }
  return Object.freeze({ ...preflight });
}

function assertDensityLimits(deckSpec) {
  const { maxInsightsPerSlide, maxTableRows } = deckSpec.densityConstraints;
  for (const slide of deckSpec.slides) {
    const insights = slide.components.filter(({ type }) => type === "insight").length;
    if (insights > maxInsightsPerSlide) {
      throw new Error(`Slide ${slide.id} exceeds the density insight limit`);
    }
    for (const table of slide.components.filter(({ type }) => type === "table")) {
      if (table.rows.length > maxTableRows) {
        throw new Error(`Slide ${slide.id} exceeds the density table-row limit`);
      }
    }
  }
}

function regionStyle(region) {
  return `left:${region.x}px;top:${region.y}px;width:${region.width}px;height:${region.height}px`;
}

function sourceAttribute(component) {
  const sources = (component.sources ?? [])
    .map(({ documentId, pageNumber, blockId }) => `${documentId}:${pageNumber}:${blockId}`)
    .join(",");
  return sources ? ` data-sources="${escapeHtml(sources)}"` : "";
}

function sourceNote(slide) {
  const references = new Map();
  for (const component of slide.components) {
    for (const source of component.sources ?? []) {
      const label = `${source.documentId} p.${source.pageNumber}`;
      references.set(label, label);
    }
  }
  const text = [...references.values()].join("; ");
  return text ? `<div class="slide-source-note">Sources: ${escapeHtml(text)}</div>` : "";
}

function assetUrl(assetRef, assets) {
  const url = assets[assetRef];
  if (!url) throw new Error(`Missing image asset: ${assetRef}`);
  if (!/^\/[a-zA-Z0-9/_-]+\.[a-zA-Z0-9]+$/.test(url) && !/^data:image\/(png|jpeg|webp);base64,/i.test(url)) {
    throw new Error(`Unsafe image asset URL: ${assetRef}`);
  }
  return url;
}

function renderTable(component) {
  const headings = component.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const rows = component.rows
    .map(
      (row) =>
        `<tr>${row
          .map((cell) => {
            const value = cell.kind === "financial" ? cell.value.displayedValue : cell.text;
            return `<td>${escapeHtml(value)}</td>`;
          })
          .join("")}</tr>`,
    )
    .join("");
  return `<table><thead><tr>${headings}</tr></thead><tbody>${rows}</tbody></table>`;
}

function renderChart(component) {
  const headings = component.categories.map((category) => `<th>${escapeHtml(category)}</th>`).join("");
  const rows = component.series
    .map(
      (series) =>
        `<tr><th>${escapeHtml(series.name)}</th>${series.values
          .map((value) => `<td>${escapeHtml(value.displayedValue)}</td>`)
          .join("")}</tr>`,
    )
    .join("");
  return `<table class="chart-data" data-chart-type="${component.chartType}"><caption>Editable chart data</caption><thead><tr><th>Series</th>${headings}</tr></thead><tbody>${rows}</tbody></table>`;
}

function fitStyle(fit = {}) {
  const declarations = [];
  for (const [property, unit] of [
    ["fontSize", "px"],
    ["lineHeight", ""],
    ["padding", "px"],
  ]) {
    if (fit[property] === undefined) continue;
    if (!Number.isFinite(fit[property]) || fit[property] < 0) {
      throw new Error(`Invalid ${property} fit override`);
    }
    declarations.push(`${property.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}:${fit[property]}${unit}`);
  }
  return declarations.length ? `;${declarations.join(";")}` : "";
}

function renderComponent(component, region, assets, fitOverrides) {
  const attributes = `class="component ${component.type}" data-component-id="${escapeHtml(component.id)}" data-region="${escapeHtml(component.region)}"${sourceAttribute(component)} style="${regionStyle(region)}${fitStyle(fitOverrides[component.id])}"`;
  if (component.type === "text") {
    return `<div ${attributes.replace(`component ${component.type}`, `component text text-${component.variant}`)}>${escapeHtml(component.text)}</div>`;
  }
  if (component.type === "metric") {
    return `<div ${attributes}><span class="metric-value">${escapeHtml(component.value.displayedValue)}</span><span>${escapeHtml(component.label)}</span></div>`;
  }
  if (component.type === "table") return `<div ${attributes}>${renderTable(component)}</div>`;
  if (component.type === "chart") return `<div ${attributes}>${renderChart(component)}</div>`;
  if (component.type === "insight") {
    return `<div ${attributes.replace("component insight", `component insight insight-${component.emphasis}`)}>${escapeHtml(component.statement)}</div>`;
  }
  if (component.type === "image") {
    return `<img ${attributes} src="${escapeHtml(assetUrl(component.assetRef, assets))}" alt="${escapeHtml(component.altText)}">`;
  }
  throw new Error(`Unsupported component type: ${component.type}`);
}

function renderSlide(slide, assets, fitOverrides) {
  const approved = layoutRegistry[slide.layoutId];
  if (!approved) throw new Error(`Unknown layout: ${slide.layoutId}`);
  const components = slide.components.map((component) => {
    if (!approved.allowedComponents.includes(component.type)) {
      throw new Error(`Layout ${slide.layoutId} does not allow ${component.type}`);
    }
    const region = approved.regions[component.region];
    if (!region) throw new Error(`Layout ${slide.layoutId} does not define region ${component.region}`);
    return renderComponent(component, region, assets, fitOverrides);
  });
  return `<section class="slide layout-${slide.layoutId}" data-slide-id="${escapeHtml(slide.id)}"><h1 class="slide-title">${escapeHtml(slide.title)}</h1>${components.join("")}${sourceNote(slide)}</section>`;
}

export function compileDeckHtml(deckSpec, { assets = {}, fitOverrides = {} } = {}) {
  if (deckSpec?.schemaVersion !== "0.1" || !Array.isArray(deckSpec.slides)) {
    throw new Error("Slide specification v0.1 is required");
  }
  densityPreflightPolicy(deckSpec);
  assertDensityLimits(deckSpec);
  resolvePresentationTheme(deckSpec.themeId);
  assertSafe(deckSpec, "Slide specification");
  const slides = [...deckSpec.slides]
    .sort((left, right) => left.order - right.order)
    .map((slide) => renderSlide(slide, assets, fitOverrides))
    .join("");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${escapeHtml(deckSpec.title)}</title><style>${CSS}</style></head><body><main class="deck" data-deck-id="${escapeHtml(deckSpec.deckId)}" data-density-profile="${escapeHtml(deckSpec.densityProfile)}">${slides}</main></body></html>`;
}

export async function runBrowserPreflight(
  deckSpec,
  { page, assets = {}, policy = {}, repairAttempt = 0 } = {},
) {
  const densityPolicy = densityPreflightPolicy(deckSpec);
  return preflightBrowserDeck({
    page,
    deckSpec,
    policy: { ...densityPolicy, ...policy },
    repairAttempt,
    layoutRegistry,
    compile: (fitOverrides) => compileDeckHtml(deckSpec, { assets, fitOverrides }),
  });
}

export {
  DEFAULT_PREFLIGHT_POLICY,
  analyzeMeasurements,
  createRepairPlan,
  deriveFitOverrides,
  measureBrowserPage,
  defaultPresentationTheme,
  resolvePresentationTheme,
};

export function createPreflightReport(slideCount) {
  if (!Number.isInteger(slideCount) || slideCount < 0) {
    throw new TypeError("slideCount must be a non-negative integer");
  }
  return { status: "pending", slideCount, failures: [] };
}

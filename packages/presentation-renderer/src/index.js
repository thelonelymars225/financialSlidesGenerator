import { writeFile } from "node:fs/promises";

import PptxGenJS from "pptxgenjs";

import {
  formatSourceReferences,
  layoutRegistry,
  resolvePresentationTheme,
} from "@financial-slides/presentation-harness";

const PX_PER_INCH = 96;

function componentBox(component, layoutId) {
  const region = layoutRegistry[layoutId]?.regions[component.region];
  if (!region) throw new Error(`Layout ${layoutId} does not define region ${component.region}`);
  return {
    x: region.x / PX_PER_INCH,
    y: region.y / PX_PER_INCH,
    w: region.width / PX_PER_INCH,
    h: region.height / PX_PER_INCH,
  };
}

function displayTitle(title, maxLength = 76) {
  if (title.length <= maxLength) return title;
  const candidate = title.slice(0, maxLength - 1);
  const boundary = candidate.lastIndexOf(" ");
  return `${candidate.slice(0, boundary > maxLength * 0.6 ? boundary : undefined).trimEnd()}…`;
}

function chartType(pptx, requestedType, warnings) {
  if (requestedType === "line") return pptx.ChartType.line;
  if (requestedType === "waterfall") {
    warnings.push("Waterfall charts use an editable bar-chart fallback.");
  }
  return pptx.ChartType.bar;
}

function tableValue(cell) {
  return cell.kind === "financial" ? cell.value.displayedValue : cell.text;
}

function tableRows(component, theme) {
  const header = component.columns.map((text) => ({
    text,
    options: {
      bold: true,
      color: theme.table.headerText,
      fill: theme.table.headerFill,
    },
  }));
  const rows = component.rows.map((row, index) =>
    row.map((cell) => ({
      text: tableValue(cell),
      options: {
        fill: index % 2 ? theme.table.stripeFill : theme.table.bodyFill,
      },
    })),
  );
  return [header, ...rows];
}

function speakerNotes(spec, renderedTitle) {
  const notes = [];
  if (spec.speakerNotes) notes.push(spec.speakerNotes);
  if (renderedTitle !== spec.title) notes.push(`[Full title]\n${spec.title}`);
  const sources = formatSourceReferences(spec, Number.POSITIVE_INFINITY);
  if (sources) notes.push(`[Sources]\n${sources}`);
  return notes.join("\n\n");
}

function imageSource(assetRef, assets) {
  const asset = assets[assetRef];
  if (!asset) throw new Error(`Missing image asset: ${assetRef}`);
  if (typeof asset === "string") {
    if (/^https?:\/\//i.test(asset)) {
      throw new Error(`Remote image URLs are not allowed: ${assetRef}`);
    }
    return asset.startsWith("data:") ? { data: asset } : { path: asset };
  }
  if (asset.data || asset.path) return asset;
  throw new Error(`Invalid image asset: ${assetRef}`);
}

function addComponent(pptx, slide, component, box, assets, warnings, theme) {
  const baseText = {
    color: theme.colors.ink,
    fontFace: theme.fonts.body,
    margin: 0.08,
    valign: "mid",
  };

  if (component.type === "text") {
    slide.addText(component.text, {
      ...box,
      ...baseText,
      bold: component.variant === "heading" || component.variant === "callout",
      fontSize: theme.typography[component.variant].ppt,
    });
    return;
  }
  if (component.type === "insight") {
    const emphasisColor = {
      positive: theme.colors.positive,
      negative: theme.colors.negative,
      warning: theme.colors.warning,
      neutral: theme.colors.muted,
    }[component.emphasis];
    slide.addShape(pptx.ShapeType.rect, {
      ...box,
      fill: { color: theme.colors.surface },
      line: { color: theme.colors.surface },
    });
    slide.addShape(pptx.ShapeType.rect, {
      x: box.x,
      y: box.y,
      w: 0.05,
      h: box.h,
      fill: { color: theme.colors.accent },
      line: { color: theme.colors.accent },
    });
    slide.addText(component.statement, {
      ...box,
      ...baseText,
      x: box.x + 0.25,
      w: box.w - 0.5,
      bold: true,
      color: emphasisColor,
      fontSize: theme.typography.callout.ppt,
    });
    return;
  }
  if (component.type === "metric") {
    const metricColor = component.value.value < 0
      ? theme.colors.negative
      : theme.colors.accent;
    slide.addShape(pptx.ShapeType.rect, {
      ...box,
      fill: { color: theme.colors.surface },
      line: { color: theme.colors.surface, pt: 0 },
    });
    slide.addShape(pptx.ShapeType.rect, {
      x: box.x,
      y: box.y,
      w: box.w,
      h: 0.04,
      fill: { color: metricColor },
      line: { color: metricColor, pt: 0 },
    });
    slide.addText(component.value.displayedValue, {
      ...box,
      ...baseText,
      y: box.y + 0.15,
      h: box.h * 0.58,
      bold: true,
      color: metricColor,
      fontSize: theme.typography.metric.ppt,
      align: "center",
    });
    slide.addText(component.label, {
      ...box,
      ...baseText,
      y: box.y + box.h * 0.66,
      h: box.h * 0.22,
      color: theme.colors.muted,
      fontSize: theme.typography.body.ppt - 2,
      align: "center",
    });
    return;
  }
  if (component.type === "table") {
    slide.addTable(
      tableRows(component, theme),
      {
        ...box,
        border: { color: theme.table.border, pt: 1 },
        color: theme.colors.ink,
        fill: theme.table.bodyFill,
        fontFace: theme.fonts.body,
        fontSize: component.rows.length > 8 ? 16 : 18,
        margin: 0.08,
        rowH: Math.min(0.48, box.h / (component.rows.length + 1)),
      },
    );
    return;
  }
  if (component.type === "chart") {
    const series = component.series.map((item) => ({
      name: item.name,
      labels: component.categories,
      values: item.values.map((value) => value.value),
    }));
    slide.addChart(chartType(pptx, component.chartType, warnings), series, {
      ...box,
      catAxisLabelFontFace: theme.fonts.body,
      catAxisLabelFontSize: 14,
      chartColors: theme.chart.palette,
      showCatName: false,
      showValAxisTitle: false,
      showLegend: series.length > 1,
      showTitle: false,
      showValue: true,
      valAxisLabelFontFace: theme.fonts.body,
      valAxisLabelFontSize: 14,
    });
    return;
  }
  if (component.type === "image") {
    slide.addImage({
      ...imageSource(component.assetRef, assets),
      ...box,
      altText: component.altText,
    });
    return;
  }
  throw new Error(`Unsupported component type: ${component.type}`);
}

export class PptxPresentationExporter {
  format = "pptx";
  mediaType = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  fileExtension = ".pptx";

  async export(deckSpec, { assets = {} } = {}) {
    if (!Array.isArray(deckSpec?.slides) || deckSpec.slides.length === 0) {
      throw new Error("deckSpec must contain at least one slide");
    }

    const pptx = new PptxGenJS();
    const warnings = [];
    const theme = resolvePresentationTheme(deckSpec.themeId);
    pptx.author = "financialSlidesGenerator";
    pptx.company = "financialSlidesGenerator";
    pptx.subject = deckSpec.subtitle ?? deckSpec.title;
    pptx.title = deckSpec.title;
    pptx.lang = "en-US";
    pptx.layout = "LAYOUT_WIDE";
    pptx.theme = {
      headFontFace: theme.fonts.heading,
      bodyFontFace: theme.fonts.body,
      lang: "en-US",
    };

    for (const spec of [...deckSpec.slides].sort((a, b) => a.order - b.order)) {
      const slide = pptx.addSlide();
      slide.background = { color: theme.colors.canvas };
      const title = displayTitle(spec.title);
      const isTitleSlide = spec.layoutId === "title";
      slide.addText(title, {
        x: isTitleSlide ? 1 : theme.spacing.slideMarginX,
        y: isTitleSlide ? 1.98 : theme.spacing.titleY,
        w: isTitleSlide ? 11.33 : 13.33 - theme.spacing.slideMarginX * 2,
        h: isTitleSlide ? 1.82 : theme.spacing.titleHeight,
        bold: true,
        color: theme.colors.ink,
        fontFace: theme.fonts.heading,
        fontSize: isTitleSlide ? theme.typography.deckTitle.ppt : theme.typography.title.ppt,
        margin: 0,
        breakLine: false,
        valign: isTitleSlide ? "mid" : "top",
      });
      if (!isTitleSlide) {
        slide.addShape(pptx.ShapeType.line, {
          x: theme.spacing.slideMarginX,
          y: theme.spacing.titleRuleY,
          w: 13.33 - theme.spacing.slideMarginX * 2,
          h: 0,
          line: { color: theme.colors.accent, pt: 1.5 },
        });
      }
      spec.components.forEach((component) => {
        addComponent(
          pptx,
          slide,
          component,
          componentBox(component, spec.layoutId),
          assets,
          warnings,
          theme,
        );
      });
      const sources = formatSourceReferences(spec);
      if (sources) {
        slide.addText(sources, {
          x: theme.spacing.slideMarginX,
          y: theme.spacing.footerY,
          w: 13.33 - theme.spacing.slideMarginX * 2,
          h: theme.spacing.footerHeight,
          color: theme.sourceNote.color,
          fontFace: theme.fonts.body,
          fontSize: theme.sourceNote.pptFontSize,
          margin: 0,
        });
      }
      const notes = speakerNotes(spec, title);
      if (notes) slide.addNotes(notes);
    }

    const data = await pptx.write({ outputType: "nodebuffer", compression: true });
    return {
      data: Buffer.from(data),
      format: this.format,
      mediaType: this.mediaType,
      fileExtension: this.fileExtension,
      warnings: [...new Set(warnings)],
    };
  }

  async render(deckSpec, { outputPath, assets = {} } = {}) {
    if (!outputPath) throw new Error("outputPath is required");
    const artifact = await this.export(deckSpec, { assets });
    await writeFile(outputPath, artifact.data);
    return { outputPath, warnings: artifact.warnings };
  }
}

export class PresentationRenderer extends PptxPresentationExporter {}

export function createPresentationExporter(format = "pptx") {
  const normalized = String(format).trim().toLowerCase();
  if (normalized === "pptx") return new PptxPresentationExporter();
  throw new Error(`Unsupported presentation export format: ${format}`);
}

export async function exportPresentation(deckSpec, { format = "pptx", ...options } = {}) {
  return createPresentationExporter(format).export(deckSpec, options);
}

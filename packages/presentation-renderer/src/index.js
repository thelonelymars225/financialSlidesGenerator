import PptxGenJS from "pptxgenjs";

import { resolvePresentationTheme } from "@financial-slides/presentation-harness";

function componentBox(index, count, theme) {
  const { componentGap: gap, contentHeight, contentY, slideMarginX } = theme.spacing;
  const height = (contentHeight - gap * Math.max(count - 1, 0)) / count;
  return {
    x: slideMarginX,
    y: contentY + index * (height + gap),
    w: 13.33 - slideMarginX * 2,
    h: height,
  };
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

function sourceNote(spec) {
  const references = new Map();
  for (const component of spec.components) {
    for (const source of component.sources ?? []) {
      const label = `${source.documentId} p.${source.pageNumber}`;
      references.set(label, label);
    }
  }
  const text = [...references.values()].join("; ");
  return text ? `Sources: ${text}` : "";
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
      line: { color: theme.colors.border },
      radius: 0.08,
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
    slide.addShape(pptx.ShapeType.roundRect, {
      ...box,
      fill: { color: theme.colors.surface },
      line: { color: theme.colors.border, pt: 1 },
      radius: 0.08,
    });
    slide.addText(component.value.displayedValue, {
      ...box,
      ...baseText,
      y: box.y + 0.15,
      h: box.h * 0.58,
      bold: true,
      color: theme.colors.accent,
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
        fontSize: 18,
        margin: 0.08,
        rowH: Math.min(0.55, box.h / (component.rows.length + 1)),
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

export class PresentationRenderer {
  async render(deckSpec, { outputPath, assets = {} } = {}) {
    if (!outputPath) throw new Error("outputPath is required");
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
      slide.addText(spec.title, {
        x: theme.spacing.slideMarginX,
        y: theme.spacing.titleY,
        w: 13.33 - theme.spacing.slideMarginX * 2,
        h: theme.spacing.titleHeight,
        bold: true,
        color: theme.colors.ink,
        fontFace: theme.fonts.heading,
        fontSize: theme.typography.title.ppt,
        margin: 0,
        breakLine: false,
      });
      slide.addShape(pptx.ShapeType.line, {
        x: theme.spacing.slideMarginX,
        y: theme.spacing.titleRuleY,
        w: 13.33 - theme.spacing.slideMarginX * 2,
        h: 0,
        line: { color: theme.colors.accent, pt: 1.5 },
      });
      spec.components.forEach((component, index) => {
        addComponent(
          pptx,
          slide,
          component,
          componentBox(index, spec.components.length, theme),
          assets,
          warnings,
          theme,
        );
      });
      const sources = sourceNote(spec);
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
      if (spec.speakerNotes) slide.addNotes(spec.speakerNotes);
    }

    await pptx.writeFile({ fileName: outputPath, compression: true });
    return { outputPath, warnings: [...new Set(warnings)] };
  }
}

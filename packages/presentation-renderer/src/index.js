import PptxGenJS from "pptxgenjs";

const COLOR = {
  navy: "17324D",
  teal: "0D9488",
  green: "15803D",
  red: "B91C1C",
  amber: "B45309",
  slate: "475569",
  pale: "E2E8F0",
  white: "FFFFFF",
};
const TEXT_SIZE = { heading: 28, body: 20, caption: 16, callout: 24 };

function componentBox(index, count) {
  const gap = 0.22;
  const height = (5.4 - gap * Math.max(count - 1, 0)) / count;
  return { x: 0.75, y: 1.45 + index * (height + gap), w: 11.83, h: height };
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

function addComponent(pptx, slide, component, box, assets, warnings) {
  const baseText = {
    color: COLOR.navy,
    fontFace: "Aptos",
    margin: 0.08,
    valign: "mid",
  };

  if (component.type === "text") {
    slide.addText(component.text, {
      ...box,
      ...baseText,
      bold: component.variant === "heading" || component.variant === "callout",
      fontSize: TEXT_SIZE[component.variant],
    });
    return;
  }
  if (component.type === "insight") {
    const emphasisColor = {
      positive: COLOR.green,
      negative: COLOR.red,
      warning: COLOR.amber,
      neutral: COLOR.slate,
    }[component.emphasis];
    slide.addShape(pptx.ShapeType.rect, {
      ...box,
      fill: { color: "F8FAFC" },
      line: { color: COLOR.pale },
      radius: 0.08,
    });
    slide.addText(component.statement, {
      ...box,
      ...baseText,
      x: box.x + 0.25,
      w: box.w - 0.5,
      bold: true,
      color: emphasisColor,
      fontSize: 24,
    });
    return;
  }
  if (component.type === "metric") {
    slide.addText(component.value.displayedValue, {
      ...box,
      ...baseText,
      y: box.y + 0.15,
      h: box.h * 0.58,
      bold: true,
      color: COLOR.teal,
      fontSize: 42,
      align: "center",
    });
    slide.addText(component.label, {
      ...box,
      ...baseText,
      y: box.y + box.h * 0.66,
      h: box.h * 0.22,
      fontSize: 18,
      align: "center",
    });
    return;
  }
  if (component.type === "table") {
    slide.addTable(
      [component.columns, ...component.rows.map((row) => row.map(tableValue))],
      {
        ...box,
        border: { color: COLOR.pale, pt: 1 },
        color: COLOR.navy,
        fill: COLOR.white,
        fontFace: "Aptos",
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
      catAxisLabelFontFace: "Aptos",
      catAxisLabelFontSize: 14,
      chartColors: [COLOR.teal, COLOR.navy, COLOR.amber],
      showLegend: series.length > 1,
      showTitle: false,
      showValue: true,
      valAxisLabelFontFace: "Aptos",
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
    pptx.author = "financialSlidesGenerator";
    pptx.company = "financialSlidesGenerator";
    pptx.subject = deckSpec.subtitle ?? deckSpec.title;
    pptx.title = deckSpec.title;
    pptx.lang = "en-US";
    pptx.layout = "LAYOUT_WIDE";
    pptx.theme = {
      headFontFace: "Aptos Display",
      bodyFontFace: "Aptos",
      lang: "en-US",
    };

    for (const spec of [...deckSpec.slides].sort((a, b) => a.order - b.order)) {
      const slide = pptx.addSlide();
      slide.background = { color: COLOR.white };
      slide.addText(spec.title, {
        x: 0.75,
        y: 0.42,
        w: 11.83,
        h: 0.62,
        bold: true,
        color: COLOR.navy,
        fontFace: "Aptos Display",
        fontSize: 35,
        margin: 0,
        breakLine: false,
      });
      slide.addShape(pptx.ShapeType.line, {
        x: 0.75,
        y: 1.17,
        w: 11.83,
        h: 0,
        line: { color: COLOR.teal, pt: 1.5 },
      });
      spec.components.forEach((component, index) => {
        addComponent(
          pptx,
          slide,
          component,
          componentBox(index, spec.components.length),
          assets,
          warnings,
        );
      });
      if (spec.speakerNotes) slide.addNotes(spec.speakerNotes);
    }

    await pptx.writeFile({ fileName: outputPath, compression: true });
    return { outputPath, warnings: [...new Set(warnings)] };
  }
}

export const DEFAULT_PREFLIGHT_POLICY = Object.freeze({
  minFontSize: 16,
  minLineHeight: 1.1,
  minSpacing: 4,
  maxAutoFitPasses: 2,
  maxRepairAttempts: 2,
});

const FALLBACK_LAYOUTS = Object.freeze({
  "executive-summary": "insight",
  "kpi-grid": "insight",
});

function overlaps(left, right) {
  return (
    left.left < right.right - 1 &&
    left.right > right.left + 1 &&
    left.top < right.bottom - 1 &&
    left.bottom > right.top + 1
  );
}

function outside(element, slide) {
  return (
    element.left < slide.left - 1 ||
    element.top < slide.top - 1 ||
    element.right > slide.right + 1 ||
    element.bottom > slide.bottom + 1
  );
}

export function analyzeMeasurements(snapshot) {
  const failures = [];
  for (const slide of snapshot.slides ?? []) {
    for (const element of slide.elements ?? []) {
      if (element.assetMissing) {
        failures.push({
          code: "missing-asset",
          slideId: slide.slideId,
          componentId: element.componentId,
          details: "Image did not load.",
        });
      }
      if (outside(element.bounds, slide.bounds)) {
        failures.push({
          code: "out-of-bounds",
          slideId: slide.slideId,
          componentId: element.componentId,
          details: "Component extends beyond the slide canvas.",
        });
      }
      if (
        element.scrollWidth > element.clientWidth + 1 ||
        element.scrollHeight > element.clientHeight + 1
      ) {
        failures.push({
          code: "overflow",
          slideId: slide.slideId,
          componentId: element.componentId,
          clipped: element.overflowX === "hidden" || element.overflowY === "hidden",
          details: "Content exceeds its component box.",
        });
      }
    }

    const visible = (slide.elements ?? []).filter((element) => element.region !== "background");
    for (let left = 0; left < visible.length; left += 1) {
      for (let right = left + 1; right < visible.length; right += 1) {
        if (overlaps(visible[left].bounds, visible[right].bounds)) {
          failures.push({
            code: "overlap",
            slideId: slide.slideId,
            componentIds: [visible[left].componentId, visible[right].componentId],
            details: "Components overlap.",
          });
        }
      }
    }
  }
  return failures;
}

export function deriveFitOverrides(snapshot, failures, current = {}, policy = {}) {
  const rules = { ...DEFAULT_PREFLIGHT_POLICY, ...policy };
  const overflowIds = new Set(
    failures.filter(({ code }) => code === "overflow").map(({ componentId }) => componentId),
  );
  const next = structuredClone(current);

  for (const slide of snapshot.slides ?? []) {
    for (const element of slide.elements ?? []) {
      if (!overflowIds.has(element.componentId)) continue;
      const widthRatio = element.clientWidth / Math.max(element.scrollWidth, 1);
      const heightRatio = element.clientHeight / Math.max(element.scrollHeight, 1);
      const scale = Math.min(widthRatio, heightRatio, 0.95);
      const fontSize = Math.max(rules.minFontSize, Math.floor(element.fontSize * scale));
      const lineHeight = Math.max(
        rules.minLineHeight,
        Math.min(element.lineHeight / Math.max(element.fontSize, 1), 1.3),
      );
      const padding = Math.max(rules.minSpacing, Math.floor(element.padding * scale));
      next[element.componentId] = { fontSize, lineHeight, padding };
    }
  }
  return next;
}

function groupedFailures(failures) {
  const groups = new Map();
  for (const failure of failures) {
    const group = groups.get(failure.slideId) ?? {
      slideId: failure.slideId,
      reasons: new Set(),
      componentIds: new Set(),
    };
    group.reasons.add(failure.code);
    if (failure.componentId) group.componentIds.add(failure.componentId);
    for (const componentId of failure.componentIds ?? []) group.componentIds.add(componentId);
    groups.set(failure.slideId, group);
  }
  return [...groups.values()].map((group) => ({
    slideId: group.slideId,
    reasons: [...group.reasons].sort(),
    componentIds: [...group.componentIds].sort(),
  }));
}

export function createRepairPlan(
  deckSpec,
  failures,
  { attempt = 0, policy = {}, layoutRegistry = {} } = {},
) {
  const rules = { ...DEFAULT_PREFLIGHT_POLICY, ...policy };
  const requests = groupedFailures(failures);
  if (attempt < rules.maxRepairAttempts) {
    return {
      status: "repair-required",
      attempt,
      attemptsRemaining: rules.maxRepairAttempts - attempt,
      requests,
    };
  }

  const replacements = new Map();
  const errors = [];
  for (const request of requests) {
    const slide = deckSpec.slides.find(({ id }) => id === request.slideId);
    if (!slide) {
      errors.push({
        slideId: request.slideId,
        reasons: request.reasons,
        componentIds: request.componentIds,
        message: "Failing slide is missing from the deck specification.",
      });
      continue;
    }
    const fallbackId = FALLBACK_LAYOUTS[slide.layoutId];
    const fallback = layoutRegistry[fallbackId];
    if (
      fallback &&
      slide.components.every(({ type }) => fallback.allowedComponents.includes(type))
    ) {
      replacements.set(slide.id, fallbackId);
    } else {
      errors.push({
        slideId: request.slideId,
        reasons: request.reasons,
        componentIds: request.componentIds,
        message: `No safe fallback for layout ${slide.layoutId}.`,
      });
    }
  }

  if (errors.length > 0) {
    return { status: "failed", attempt, errors };
  }
  return {
    status: "fallback",
    attempt,
    fallbacks: [...replacements].map(([slideId, layoutId]) => ({ slideId, layoutId })),
    deckSpec: {
      ...deckSpec,
      slides: deckSpec.slides.map((slide) =>
        replacements.has(slide.id)
          ? { ...slide, layoutId: replacements.get(slide.id) }
          : slide,
      ),
    },
  };
}

export async function measureBrowserPage(page, html) {
  if (!page?.setContent || !page?.evaluate) {
    throw new TypeError("A browser page with setContent and evaluate is required");
  }
  await page.setContent(html, { waitUntil: "load" });
  return page.evaluate(() => ({
    slides: [...document.querySelectorAll(".slide")].map((slide) => {
      const slideBounds = slide.getBoundingClientRect();
      return {
        slideId: slide.dataset.slideId,
        bounds: {
          left: slideBounds.left,
          top: slideBounds.top,
          right: slideBounds.right,
          bottom: slideBounds.bottom,
        },
        elements: [...slide.querySelectorAll(".component")].map((element) => {
          const bounds = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            componentId: element.dataset.componentId,
            region: element.dataset.region,
            bounds: {
              left: bounds.left,
              top: bounds.top,
              right: bounds.right,
              bottom: bounds.bottom,
            },
            clientWidth: element.clientWidth,
            clientHeight: element.clientHeight,
            scrollWidth: element.scrollWidth,
            scrollHeight: element.scrollHeight,
            fontSize: Number.parseFloat(style.fontSize),
            lineHeight: Number.parseFloat(style.lineHeight),
            padding: Number.parseFloat(style.paddingTop),
            overflowX: style.overflowX,
            overflowY: style.overflowY,
            assetMissing:
              element.tagName === "IMG" &&
              (!element.complete || element.naturalWidth === 0),
          };
        }),
      };
    }),
  }));
}

export async function preflightBrowserDeck({
  page,
  deckSpec,
  compile,
  layoutRegistry,
  policy = {},
  repairAttempt = 0,
}) {
  const rules = { ...DEFAULT_PREFLIGHT_POLICY, ...policy };
  let fitOverrides = {};
  let snapshot;
  let failures;

  for (let pass = 0; pass <= rules.maxAutoFitPasses; pass += 1) {
    snapshot = await measureBrowserPage(page, compile(fitOverrides));
    failures = analyzeMeasurements(snapshot);
    if (failures.length === 0) {
      return { status: "passed", passes: pass + 1, fitOverrides, failures: [] };
    }
    if (pass === rules.maxAutoFitPasses) break;
    const next = deriveFitOverrides(snapshot, failures, fitOverrides, rules);
    if (JSON.stringify(next) === JSON.stringify(fitOverrides)) break;
    fitOverrides = next;
  }

  return {
    status: "failed-preflight",
    fitOverrides,
    failures,
    repair: createRepairPlan(deckSpec, failures, {
      attempt: repairAttempt,
      policy: rules,
      layoutRegistry,
    }),
  };
}

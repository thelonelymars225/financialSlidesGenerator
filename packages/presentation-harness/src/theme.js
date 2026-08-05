const DEFAULT_THEME_ID = "theme-corporate-default";

function freezeTheme(value) {
  for (const nested of Object.values(value)) {
    if (nested && typeof nested === "object") freezeTheme(nested);
  }
  return Object.freeze(value);
}

export const defaultPresentationTheme = freezeTheme({
  id: DEFAULT_THEME_ID,
  fonts: {
    heading: "Aptos Display",
    body: "Aptos",
    fallback: "Arial, sans-serif",
  },
  colors: {
    canvas: "FFFFFF",
    surface: "F6F8F7",
    ink: "17324D",
    muted: "52616B",
    accent: "0F766E",
    accentSoft: "DDEFEA",
    positive: "137333",
    negative: "B3261E",
    warning: "8A560F",
    border: "D7E0DC",
    tableStripe: "F3F7F5",
  },
  typography: {
    deckTitle: { ppt: 50, web: 64 },
    title: { ppt: 35, web: 44 },
    heading: { ppt: 28, web: 32 },
    body: { ppt: 20, web: 24 },
    caption: { ppt: 14, web: 16 },
    callout: { ppt: 24, web: 28 },
    metric: { ppt: 42, web: 56 },
  },
  spacing: {
    slideMarginX: 0.75,
    titleY: 0.42,
    titleHeight: 0.62,
    titleRuleY: 1.17,
    contentY: 1.45,
    contentHeight: 5.35,
    componentGap: 0.22,
    footerY: 7.12,
    footerHeight: 0.2,
  },
  chart: {
    palette: ["0F766E", "17324D", "C46A2B", "5C6AC4", "52616B"],
  },
  table: {
    headerFill: "17324D",
    headerText: "FFFFFF",
    bodyFill: "FFFFFF",
    stripeFill: "F3F7F5",
    border: "D7E0DC",
  },
  sourceNote: {
    color: "52616B",
    pptFontSize: 9,
    webFontSize: 12,
  },
});

export function resolvePresentationTheme(themeId = DEFAULT_THEME_ID) {
  if (themeId !== DEFAULT_THEME_ID) {
    throw new Error(`Unknown presentation theme: ${themeId}`);
  }
  return defaultPresentationTheme;
}

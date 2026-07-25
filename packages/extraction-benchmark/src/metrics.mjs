function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("en");
}

function levenshtein(left, right) {
  if (!left.length) return right.length;
  if (!right.length) return left.length;
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);

  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      current[rightIndex] = Math.min(
        current[rightIndex - 1] + 1,
        previous[rightIndex] + 1,
        previous[rightIndex - 1] + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1),
      );
    }
    previous = current;
  }
  return previous[right.length];
}

function similarity(expected, observed) {
  const left = normalizeText(expected);
  const right = normalizeText(observed);
  const longest = Math.max(left.length, right.length);
  return longest === 0 ? 1 : 1 - levenshtein(left, right) / longest;
}

function blocks(document) {
  return (document.pages ?? []).flatMap((page) =>
    [...(page.blocks ?? [])]
      .sort((left, right) => left.order - right.order)
      .map((block) => ({ page, block })),
  );
}

function blockText(block) {
  if (block.type === "text") return block.text;
  if (block.type === "table") return block.cells.map((cell) => cell.text).join(" ");
  return block.altText ?? "";
}

function tableCells(document) {
  return blocks(document).flatMap(({ page, block }) =>
    block.type === "table"
      ? block.cells.map((cell) => ({
          key: `${page.pageNumber}:${block.order}:${cell.row}:${cell.column}`,
          text: normalizeText(cell.text),
        }))
      : [],
  );
}

function numericValues(document) {
  return blocks(document).flatMap(({ block }) => {
    const values = [...(block.numericValues ?? [])];
    for (const cell of block.cells ?? []) {
      if (cell.numericValue) values.push(cell.numericValue);
    }
    return values;
  });
}

function canonicalNumber(value) {
  return JSON.stringify({
    displayedValue: normalizeText(value.displayedValue),
    value: value.value,
    unit: value.unit ?? null,
    currency: value.currency ?? null,
    scaleFactor: value.scaleFactor ?? null,
    period: value.period ?? null,
  });
}

function locationValues(document) {
  return blocks(document).flatMap(({ page, block }) => {
    const values = [{
      key: `${page.pageNumber}:${block.order}:block`,
      source: block.source,
    }];
    for (const cell of block.cells ?? []) {
      values.push({
        key: `${page.pageNumber}:${block.order}:${cell.row}:${cell.column}`,
        source: cell.source,
      });
    }
    return values.map(({ key, source }) => JSON.stringify({
      key,
      sourceId: source?.sourceId ?? null,
      pageNumber: source?.pageNumber ?? null,
      sectionPath: source?.sectionPath ?? [],
      boundingBox: source?.boundingBox ?? null,
    }));
  });
}

function exactSetAccuracy(expected, observed) {
  if (!expected.length && !observed.length) return 1;
  const observedCounts = new Map();
  for (const value of observed) observedCounts.set(value, (observedCounts.get(value) ?? 0) + 1);
  let matches = 0;
  for (const value of expected) {
    const count = observedCounts.get(value) ?? 0;
    if (count > 0) {
      matches += 1;
      observedCounts.set(value, count - 1);
    }
  }
  return matches / Math.max(expected.length, observed.length);
}

export function textAccuracy(expected, observed) {
  const expectedText = blocks(expected).map(({ block }) => blockText(block)).join("\n");
  const observedText = blocks(observed).map(({ block }) => blockText(block)).join("\n");
  return similarity(expectedText, observedText);
}

export function tableCellAccuracy(expected, observed) {
  return exactSetAccuracy(
    tableCells(expected).map((cell) => JSON.stringify(cell)),
    tableCells(observed).map((cell) => JSON.stringify(cell)),
  );
}

export function numericFidelity(expected, observed) {
  return exactSetAccuracy(
    numericValues(expected).map(canonicalNumber),
    numericValues(observed).map(canonicalNumber),
  );
}

export function readingOrderAccuracy(expected, observed) {
  const sequence = (document) => blocks(document).map(({ page, block }) =>
    `${page.pageNumber}:${block.order}:${block.type}:${normalizeText(blockText(block))}`,
  );
  const expectedOrder = sequence(expected);
  const observedOrder = sequence(observed);
  if (!expectedOrder.length && !observedOrder.length) return 1;
  const matches = expectedOrder.filter((value, index) => observedOrder[index] === value).length;
  return matches / Math.max(expectedOrder.length, observedOrder.length);
}

export function sourceLocationAccuracy(expected, observed) {
  return exactSetAccuracy(locationValues(expected), locationValues(observed));
}

export function criticalValueChecks(observed, criticalValues = []) {
  const values = numericValues(observed);
  return Object.fromEntries(criticalValues.map((check) => {
    const numericMatch = values.some((value) =>
      value.displayedValue === check.displayedValue
      && value.value === check.value
      && (check.unit === undefined || value.unit === check.unit)
      && (check.currency === undefined || value.currency === check.currency)
      && (check.period === undefined || value.period === check.period),
    );
    return [check.id, numericMatch];
  }));
}

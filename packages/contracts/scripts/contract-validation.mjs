import { readFile } from "node:fs/promises";

import Ajv2020 from "ajv/dist/2020.js";

import { calculationError, normalizationError } from "./financial-calculations.mjs";

const schemaUrls = {
  "analysis:0.1": new URL("../schemas/analysis-v0.1.schema.json", import.meta.url),
  "analysis:0.2": new URL("../schemas/analysis-v0.2.schema.json", import.meta.url),
  "extractedDocument:0.1": new URL(
    "../schemas/extracted-document-v0.1.schema.json",
    import.meta.url,
  ),
  "extractedDocument:0.2": new URL(
    "../schemas/extracted-document-v0.2.schema.json",
    import.meta.url,
  ),
  slideSpec: new URL("../schemas/slide-spec-v0.1.schema.json", import.meta.url),
};

const validators = new Map();

async function getValidator(contractName) {
  if (validators.has(contractName)) {
    return validators.get(contractName);
  }

  const schemaUrl = schemaUrls[contractName];
  if (!schemaUrl) {
    throw new Error(`Unknown contract: ${contractName}`);
  }

  const schema = JSON.parse(await readFile(schemaUrl, "utf8"));
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  if (contractName === "extractedDocument:0.2") {
    const previousSchema = JSON.parse(
      await readFile(schemaUrls["extractedDocument:0.1"], "utf8"),
    );
    ajv.addSchema(previousSchema);
  }
  const validator = ajv.compile(schema);
  validators.set(contractName, validator);
  return validator;
}

function semanticExtractionErrors(document) {
  const errors = [];
  const pageNumbers = new Set();
  const blockIds = new Set();

  for (const page of document.pages ?? []) {
    if (pageNumbers.has(page.pageNumber)) {
      errors.push(`duplicate page number ${page.pageNumber}`);
    }
    pageNumbers.add(page.pageNumber);

    const orders = new Set();
    for (const block of page.blocks ?? []) {
      if (blockIds.has(block.id)) {
        errors.push(`duplicate block id ${block.id}`);
      }
      blockIds.add(block.id);

      if (orders.has(block.order)) {
        errors.push(`page ${page.pageNumber} has duplicate block order ${block.order}`);
      }
      orders.add(block.order);

      validateSourceLocation(block.source, page, `block ${block.id}`, errors);

      if (block.type === "table") {
        const cellPositions = new Set();
        for (const cell of block.cells ?? []) {
          const position = `${cell.row}:${cell.column}`;
          if (cellPositions.has(position)) {
            errors.push(`table ${block.id} has duplicate cell origin ${position}`);
          }
          cellPositions.add(position);

          if (cell.row + cell.rowSpan > block.rowCount) {
            errors.push(`table ${block.id} cell ${position} exceeds rowCount`);
          }
          if (cell.column + cell.columnSpan > block.columnCount) {
            errors.push(`table ${block.id} cell ${position} exceeds columnCount`);
          }
          validateSourceLocation(cell.source, page, `table ${block.id} cell ${position}`, errors);
        }
      }
    }
  }

  if (document.schemaVersion === "0.2") {
    validateFinancialFacts(document, blockIds, errors);
  }

  return errors;
}

function validateFinancialFacts(document, blockIds, errors) {
  const factIds = new Set();
  const pageNumbers = new Set((document.pages ?? []).map((page) => page.pageNumber));
  const findingFactIds = new Set(
    (document.factValidation ?? []).flatMap((finding) => finding.factIds ?? []),
  );

  for (const fact of document.financialFacts ?? []) {
    if (factIds.has(fact.id)) {
      errors.push(`duplicate financial fact id ${fact.id}`);
    }
    factIds.add(fact.id);

    if (fact.evidence.sourceId !== document.source.sourceId) {
      errors.push(`financial fact ${fact.id} references a different source`);
    }
    if (!pageNumbers.has(fact.evidence.pageNumber)) {
      errors.push(`financial fact ${fact.id} references unknown page ${fact.evidence.pageNumber}`);
    }
    if (!blockIds.has(fact.evidence.blockId)) {
      errors.push(`financial fact ${fact.id} references unknown block ${fact.evidence.blockId}`);
    }
    if (fact.evidence.tableId && fact.evidence.tableId !== fact.evidence.blockId) {
      errors.push(`financial fact ${fact.id} tableId must match its blockId`);
    }

    const numericFields = [fact.parsedValue, fact.normalizedValue, fact.scaleFactor];
    if (numericFields.every((value) => value !== null)) {
      const expected = fact.parsedValue * fact.scaleFactor;
      if (Math.abs(expected - fact.normalizedValue) > Math.max(1e-9, Math.abs(expected) * 1e-12)) {
        errors.push(`financial fact ${fact.id} normalizedValue must equal parsedValue × scaleFactor`);
      }
    } else if (numericFields.some((value) => value !== null)) {
      errors.push(`financial fact ${fact.id} numeric fields must be all populated or all null`);
    }

    const warningCodes = new Set((fact.warnings ?? []).map((warning) => warning.code));
    if (fact.parsedValue === null && !warningCodes.has("numeric.parse_failed")) {
      errors.push(`financial fact ${fact.id} must flag numeric.parse_failed`);
    }
    if (fact.period.type === "unknown" && !warningCodes.has("period.missing")) {
      errors.push(`financial fact ${fact.id} must flag period.missing`);
    }
    if (fact.unit === null && !warningCodes.has("unit.missing")) {
      errors.push(`financial fact ${fact.id} must flag unit.missing`);
    }

    for (const relatedId of [
      ...(fact.relations?.duplicateOf ?? []),
      ...(fact.relations?.conflictsWith ?? []),
    ]) {
      if (relatedId === fact.id) {
        errors.push(`financial fact ${fact.id} cannot relate to itself`);
      }
    }
  }

  for (const finding of document.factValidation ?? []) {
    for (const factId of finding.factIds ?? []) {
      if (!factIds.has(factId)) {
        errors.push(`fact validation ${finding.code} references unknown fact ${factId}`);
      }
    }
  }
  for (const fact of document.financialFacts ?? []) {
    if (fact.warnings?.length && !findingFactIds.has(fact.id)) {
      errors.push(`financial fact ${fact.id} warnings must appear in factValidation`);
    }
    for (const relatedId of [
      ...(fact.relations?.duplicateOf ?? []),
      ...(fact.relations?.conflictsWith ?? []),
    ]) {
      if (!factIds.has(relatedId)) {
        errors.push(`financial fact ${fact.id} references unknown related fact ${relatedId}`);
      }
    }
  }
}

function validateSourceLocation(source, page, label, errors) {
  if (!source) {
    return;
  }

  if (source.pageNumber !== page.pageNumber) {
    errors.push(`${label} references page ${source.pageNumber} while contained on page ${page.pageNumber}`);
  }

  const box = source.boundingBox;
  if (!box) {
    return;
  }

  if (box.unit !== page.coordinateUnit) {
    errors.push(`${label} bounding-box unit does not match its page`);
  }
  if (box.right <= box.left || box.bottom <= box.top) {
    errors.push(`${label} has an inverted or empty bounding box`);
  }
  if (box.right > page.width || box.bottom > page.height) {
    errors.push(`${label} bounding box exceeds page dimensions`);
  }
}

function semanticAnalysisErrors(analysis) {
  if (analysis.schemaVersion !== "0.2") {
    return [];
  }

  const errors = [];
  const sourceDocumentIds = new Set(analysis.sourceDocumentIds ?? []);
  const metricsById = new Map();
  const findingIds = new Set();
  const slideIds = new Set();

  for (const metric of analysis.metrics ?? []) {
    if (metricsById.has(metric.id)) {
      errors.push(`duplicate metric id ${metric.id}`);
    }
    metricsById.set(metric.id, metric);
    validateEvidence(metric.evidence, sourceDocumentIds, `metric ${metric.id}`, errors);
    validatePeriod(metric.period, `metric ${metric.id}`, errors);
  }

  for (const metric of analysis.metrics ?? []) {
    const normalized = normalizationError(metric);
    if (normalized) {
      errors.push(normalized);
    }
    const calculated = calculationError(metric, metricsById);
    if (calculated) {
      errors.push(calculated);
    }
  }

  for (const finding of analysis.findings ?? []) {
    if (findingIds.has(finding.id)) {
      errors.push(`duplicate finding id ${finding.id}`);
    }
    findingIds.add(finding.id);
    for (const metricId of finding.metricIds ?? []) {
      if (!metricsById.has(metricId)) {
        errors.push(`finding ${finding.id} references unknown metric ${metricId}`);
      }
    }
    validateEvidence(finding.evidence, sourceDocumentIds, `finding ${finding.id}`, errors);
  }

  for (const slide of analysis.slideIntents ?? []) {
    if (slideIds.has(slide.id)) {
      errors.push(`duplicate slide intent id ${slide.id}`);
    }
    slideIds.add(slide.id);

    if ((slide.findingIds?.length ?? 0) + (slide.metricIds?.length ?? 0) === 0) {
      errors.push(`slide intent ${slide.id} must reference at least one finding or metric`);
    }
    for (const findingId of slide.findingIds ?? []) {
      if (!findingIds.has(findingId)) {
        errors.push(`slide intent ${slide.id} references unknown finding ${findingId}`);
      }
    }
    for (const metricId of slide.metricIds ?? []) {
      if (!metricsById.has(metricId)) {
        errors.push(`slide intent ${slide.id} references unknown metric ${metricId}`);
      }
    }
  }

  return errors;
}

const allowedComponentsByLayout = {
  title: new Set(["text", "image"]),
  "executive-summary": new Set(["text", "metric", "insight"]),
  "kpi-grid": new Set(["text", "metric"]),
  "financial-table": new Set(["text", "table"]),
  chart: new Set(["text", "chart", "insight"]),
  insight: new Set(["text", "metric", "insight"]),
  "key-drivers": new Set(["text", "metric", "insight"]),
  "risks-actions": new Set(["text", "insight"]),
  "sources-appendix": new Set(["text", "table"]),
};

function semanticSlideSpecErrors(deck) {
  const errors = [];
  const documentIds = new Set(deck.sourceDocumentIds ?? []);
  const slideIds = new Set();
  const slideOrders = new Set();
  const componentIds = new Set();

  if (deck.slides?.length !== deck.requestedSlideCount) {
    errors.push("slides must match requestedSlideCount");
  }

  for (const slide of deck.slides ?? []) {
    if (slideIds.has(slide.id)) {
      errors.push(`duplicate slide id ${slide.id}`);
    }
    if (slideOrders.has(slide.order)) {
      errors.push(`duplicate slide order ${slide.order}`);
    }
    slideIds.add(slide.id);
    slideOrders.add(slide.order);

    const allowed = allowedComponentsByLayout[slide.layoutId] ?? new Set();
    for (const component of slide.components ?? []) {
      if (componentIds.has(component.id)) {
        errors.push(`duplicate component id ${component.id}`);
      }
      componentIds.add(component.id);
      if (!allowed.has(component.type)) {
        errors.push(`layout ${slide.layoutId} does not allow ${component.type} components`);
      }
      validateSlideSources(component.sources, documentIds, component.id, errors);
      validatePlainContent(component, component.id, errors);
      validateComponentShape(component, errors);
    }
  }

  const expectedOrders = Array.from({ length: slideIds.size }, (_, index) => index + 1);
  if (expectedOrders.some((order) => !slideOrders.has(order))) {
    errors.push("slide order must be contiguous and start at 1");
  }
  return errors;
}

function validateSlideSources(sources, documentIds, componentId, errors) {
  for (const source of sources ?? []) {
    if (!documentIds.has(source.documentId)) {
      errors.push(`component ${componentId} references undeclared document ${source.documentId}`);
    }
  }
}

function validatePlainContent(value, label, errors) {
  for (const nested of Object.values(value ?? {})) {
    if (typeof nested === "string" && /<\/?[a-z][^>]*>|javascript:|data:text\/html/i.test(nested)) {
      errors.push(`${label} contains unsafe markup or a scriptable URL`);
    } else if (nested && typeof nested === "object") {
      validatePlainContent(nested, label, errors);
    }
  }
}

function validateFinancialValue(value, label, errors) {
  const normalized = value.value * value.unit.scaleFactor;
  if (Math.abs(normalized - value.normalizedValue) > 1e-9) {
    errors.push(`${label} normalizedValue must equal value × scaleFactor`);
  }
  validatePeriod(value.period, label, errors);
}

function validateComponentShape(component, errors) {
  if (component.type === "table") {
    for (const [index, row] of component.rows.entries()) {
      if (row.length !== component.columns.length) {
        errors.push(`table ${component.id} row ${index} must match its column count`);
      }
      for (const cell of row) {
        if (cell.kind === "financial") {
          validateFinancialValue(cell.value, `table ${component.id}`, errors);
        }
      }
    }
  }
  if (component.type === "chart") {
    for (const series of component.series) {
      if (series.values.length !== component.categories.length) {
        errors.push(`chart ${component.id} series ${series.id} must match its categories`);
      }
      for (const value of series.values) {
        validateFinancialValue(value, `chart ${component.id} series ${series.id}`, errors);
      }
    }
  }
  if (component.type === "metric") {
    validateFinancialValue(component.value, `metric ${component.metricId}`, errors);
  }
}

function validateEvidence(evidenceItems, sourceDocumentIds, label, errors) {
  for (const evidence of evidenceItems ?? []) {
    if (!sourceDocumentIds.has(evidence.documentId)) {
      errors.push(`${label} references undeclared source document ${evidence.documentId}`);
    }
  }
}

function validatePeriod(period, label, errors) {
  for (const [field, value] of [
    ["startDate", period.startDate],
    ["endDate", period.endDate],
  ]) {
    const parsed = new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
      errors.push(`${label} has invalid ${field} ${value}`);
    }
  }

  if (period.startDate > period.endDate) {
    errors.push(`${label} period starts after it ends`);
  }
  if (period.type === "instant" && period.startDate !== period.endDate) {
    errors.push(`${label} instant period must use the same startDate and endDate`);
  }
}

export async function validateContract(contractName, value) {
  const resolvedContract =
    contractName === "analysis" || contractName === "extractedDocument"
      ? `${contractName}:${value?.schemaVersion ?? "unknown"}`
      : contractName;
  if (!schemaUrls[resolvedContract]) {
    return {
      valid: false,
      errors: [`/schemaVersion unsupported ${contractName} contract version`],
    };
  }

  const validator = await getValidator(resolvedContract);
  const schemaValid = validator(value);
  const errors = schemaValid
    ? []
    : validator.errors.map((error) => `${error.instancePath || "/"} ${error.message}`);

  if (schemaValid && contractName === "extractedDocument") {
    errors.push(...semanticExtractionErrors(value));
  }
  if (schemaValid && contractName === "analysis") {
    errors.push(...semanticAnalysisErrors(value));
  }
  if (schemaValid && contractName === "slideSpec") {
    errors.push(...semanticSlideSpecErrors(value));
  }

  return { valid: errors.length === 0, errors };
}

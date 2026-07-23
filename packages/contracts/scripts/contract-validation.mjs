import { readFile } from "node:fs/promises";

import Ajv2020 from "ajv/dist/2020.js";

import { calculationError, normalizationError } from "./financial-calculations.mjs";

const schemaUrls = {
  "analysis:0.1": new URL("../schemas/analysis-v0.1.schema.json", import.meta.url),
  "analysis:0.2": new URL("../schemas/analysis-v0.2.schema.json", import.meta.url),
  extractedDocument: new URL("../schemas/extracted-document-v0.1.schema.json", import.meta.url),
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

  return errors;
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
    contractName === "analysis" ? `analysis:${value?.schemaVersion ?? "unknown"}` : contractName;
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

  return { valid: errors.length === 0, errors };
}

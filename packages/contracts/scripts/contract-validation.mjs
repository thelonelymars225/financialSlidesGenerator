import { readFile } from "node:fs/promises";

import Ajv2020 from "ajv/dist/2020.js";

const schemaUrls = {
  analysis: new URL("../schemas/analysis-v0.1.schema.json", import.meta.url),
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

export async function validateContract(contractName, value) {
  const validator = await getValidator(contractName);
  const schemaValid = validator(value);
  const errors = schemaValid
    ? []
    : validator.errors.map((error) => `${error.instancePath || "/"} ${error.message}`);

  if (schemaValid && contractName === "extractedDocument") {
    errors.push(...semanticExtractionErrors(value));
  }

  return { valid: errors.length === 0, errors };
}

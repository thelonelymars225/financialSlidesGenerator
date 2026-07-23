const TOLERANCE = 1e-9;

function nearlyEqual(left, right) {
  const scale = Math.max(1, Math.abs(left), Math.abs(right));
  return Math.abs(left - right) <= TOLERANCE * scale;
}

function unitKey(metric) {
  return `${metric.unit.kind}:${metric.unit.code}`;
}

function assertCompatibleOperands(operands) {
  const firstUnit = unitKey(operands[0]);
  if (operands.some((operand) => unitKey(operand) !== firstUnit)) {
    throw new Error("calculation operands must use compatible units");
  }
}

export function expectedNormalizedValue(metric) {
  return metric.value * metric.unit.scaleFactor;
}

export function normalizationError(metric) {
  const expected = expectedNormalizedValue(metric);
  return nearlyEqual(expected, metric.normalizedValue)
    ? null
    : `metric ${metric.id} normalizedValue must equal value × scaleFactor (${expected})`;
}

export function calculateDerivedValue(metric, metricsById) {
  const { operation, operandMetricIds } = metric.calculation;
  const operands = operandMetricIds.map((id) => {
    const operand = metricsById.get(id);
    if (!operand) {
      throw new Error(`metric ${metric.id} references unknown calculation operand ${id}`);
    }
    return operand;
  });

  assertCompatibleOperands(operands);
  const values = operands.map((operand) => operand.normalizedValue);

  if (operation === "sum") {
    if (metric.unit.kind !== operands[0].unit.kind || metric.unit.code !== operands[0].unit.code) {
      throw new Error(`metric ${metric.id} sum output must preserve the operand unit`);
    }
    return values.reduce((total, value) => total + value, 0);
  }

  if (operation === "difference") {
    if (values.length !== 2) {
      throw new Error(`metric ${metric.id} difference requires exactly two operands`);
    }
    if (metric.unit.kind !== operands[0].unit.kind || metric.unit.code !== operands[0].unit.code) {
      throw new Error(`metric ${metric.id} difference output must preserve the operand unit`);
    }
    return values[0] - values[1];
  }

  if (operation === "ratio") {
    if (values.length !== 2) {
      throw new Error(`metric ${metric.id} ratio requires exactly two operands`);
    }
    if (values[1] === 0) {
      throw new Error(`metric ${metric.id} ratio denominator cannot be zero`);
    }
    if (metric.unit.kind !== "ratio") {
      throw new Error(`metric ${metric.id} ratio output must use a ratio unit`);
    }
    return values[0] / values[1];
  }

  if (operation === "percentage_change") {
    if (values.length !== 2) {
      throw new Error(`metric ${metric.id} percentage_change requires exactly two operands`);
    }
    if (values[0] === 0) {
      throw new Error(`metric ${metric.id} percentage_change baseline cannot be zero`);
    }
    if (metric.unit.kind !== "percentage") {
      throw new Error(`metric ${metric.id} percentage_change output must use a percentage unit`);
    }
    return (values[1] - values[0]) / Math.abs(values[0]);
  }

  throw new Error(`metric ${metric.id} uses unsupported calculation ${operation}`);
}

export function calculationError(metric, metricsById) {
  if (!metric.calculation) {
    return null;
  }

  try {
    const expected = calculateDerivedValue(metric, metricsById);
    return nearlyEqual(expected, metric.normalizedValue)
      ? null
      : `metric ${metric.id} calculation result must equal ${expected}`;
  } catch (error) {
    return error.message;
  }
}

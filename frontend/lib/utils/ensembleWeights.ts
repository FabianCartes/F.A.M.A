/**
 * Utilidades para cálculo y rebalanceo de ponderaciones de ensamble dinámico.
 */

/**
 * Rebalancea las ponderaciones de un ensamble cuando el usuario mueve un slider,
 * garantizando que la suma de ponderaciones siempre sea exactamente 1.0.
 *
 * @param weights Lista actual de ponderaciones
 * @param changedIndex Índice del modelo cuya ponderación fue modificada
 * @param newWeight Nuevo valor de ponderación deseado para el modelo
 * @returns Lista de ponderaciones normalizadas y rebalanceadas
 */
export function rebalanceWeights(
  weights: number[],
  changedIndex: number,
  newWeight: number
): number[] {
  const n = weights.length;
  if (n <= 1) {
    return [1.0];
  }

  // Clamping de newWeight a [0.0, 1.0]
  const clampedWeight = Math.max(0.0, Math.min(1.0, newWeight));
  const remaining = 1.0 - clampedWeight;

  // Suma de los otros pesos actuales
  let sumOthers = 0;
  for (let i = 0; i < n; i++) {
    if (i !== changedIndex) {
      sumOthers += weights[i] || 0;
    }
  }

  const nextWeights = [...weights];
  nextWeights[changedIndex] = clampedWeight;

  const numOthers = n - 1;

  if (sumOthers > 1e-7) {
    for (let i = 0; i < n; i++) {
      if (i !== changedIndex) {
        nextWeights[i] = (weights[i] / sumOthers) * remaining;
      }
    }
  } else {
    // Si todos los otros pesos eran 0, distribuimos equitativamente
    const equalShare = remaining / numOthers;
    for (let i = 0; i < n; i++) {
      if (i !== changedIndex) {
        nextWeights[i] = equalShare;
      }
    }
  }

  return nextWeights;
}

/**
 * Genera ponderaciones iniciales equitativas para N modelos (1/N para cada uno).
 */
export function getInitialWeights(count: number): number[] {
  if (count <= 1) return [1.0];
  const share = 1.0 / count;
  return Array.from({ length: count }, () => share);
}

/**
 * Suma valores de ponderación numéricos o en cadena tolerando estados vacíos.
 */
export function sumWeights(weights: (number | string)[]): number {
  return weights.reduce((acc: number, w) => {
    const val = typeof w === "number" ? w : parseFloat(w);
    return acc + (isNaN(val) ? 0 : val);
  }, 0);
}

/**
 * Normaliza una lista de porcentajes para que su suma sea exactamente 100%.
 */
export function normalizeWeightsTo100(weights: (number | string)[]): number[] {
  const count = weights.length;
  if (count <= 0) return [];
  if (count === 1) return [100];

  const numeric = weights.map((w) => {
    const val = typeof w === "number" ? w : parseFloat(w);
    return isNaN(val) || val < 0 ? 0 : val;
  });

  const sum = numeric.reduce((acc, v) => acc + v, 0);
  if (sum === 0) {
    const share = Math.floor(100 / count);
    const res = Array(count).fill(share);
    const diff = 100 - share * count;
    res[0] += diff;
    return res;
  }

  const normalized = numeric.map((v) => Math.round((v / sum) * 100));
  const newSum = normalized.reduce((acc, v) => acc + v, 0);
  if (newSum !== 100 && normalized.length > 0) {
    normalized[0] += 100 - newSum;
  }
  return normalized;
}


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

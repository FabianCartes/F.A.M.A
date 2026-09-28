/**
 * Módulo de utilidades matemáticas y trazado SVG para curvas de entrenamiento (IS_02).
 * Provee funciones puras de normalización, auto-escalado dinámico de pérdida (Loss)
 * y segmentación discontinua de modelos para ensambles bioacústicos.
 */

export interface MetricPoint {
  epoca: number;
  train_loss: number;
  val_loss: number;
  train_acc: number;
  val_acc: number;
  tiempo_epoca: number;
  architecture?: string;
  model_index?: number;
}

export interface ChartPoint {
  x: number;
  yAcc: number;
  yLoss: number;
  metric: MetricPoint;
}

export interface ChartSegment {
  modelIndex: number;
  architecture: string;
  accPolyline: string;
  lossPolyline: string;
  points: ChartPoint[];
}

export interface ModelSeparator {
  x: number;
  modelIndex: number;
  label: string;
}

export interface ChartOptions {
  width?: number; // Ancho del viewBox (default: 300)
  height?: number; // Alto del viewBox (default: 100)
  paddingTop?: number; // Padding superior de seguridad (default: 14)
  paddingBottom?: number; // Padding inferior de seguridad (default: 14)
  totalEpochs?: number; // Total de épocas esperadas para el modelo activo (default: 10)
  activeModelFilter?: "all" | "current" | number | string;
  currentModelIndex?: number;
  modelsConfig?: Array<{ architecture: string; epochs?: number }>;
}

export interface ChartResult {
  segments: ChartSegment[];
  separators: ModelSeparator[];
  maxLoss: number;
  totalPoints: number;
  maxPoints: number;
  filteredMetrics: MetricPoint[];
}

/**
 * Normaliza un valor numérico a coordenadas Y dentro del viewBox SVG,
 * garantizando que nunca se desborde fuera de [paddingTop, height - paddingBottom].
 *
 * @param val Valor numérico de entrada (ej: val_acc, val_loss)
 * @param minVal Límite inferior del rango de datos (ej: 0.0)
 * @param maxVal Límite superior del rango de datos (ej: 100.0 o maxLoss)
 * @param height Altura total del viewBox SVG
 * @param paddingTop Margen superior de seguridad para evitar recorte de trazos
 * @param paddingBottom Margen inferior de seguridad para evitar recorte contra el piso
 * @param invert Si es true (por defecto para gráficos), valores altos se dibujan arriba (menor Y).
 */
export function normalizePoint(
  val: number,
  minVal: number,
  maxVal: number,
  height: number,
  paddingTop: number,
  paddingBottom: number,
  invert: boolean = true
): number {
  if (isNaN(val) || !isFinite(val)) {
    return height - paddingBottom;
  }

  const range = maxVal - minVal;
  const clampedVal = Math.max(minVal, Math.min(maxVal, val));
  const norm = range > 0 ? (clampedVal - minVal) / range : 0;
  const usableHeight = Math.max(0, height - paddingTop - paddingBottom);

  if (invert) {
    return height - paddingBottom - norm * usableHeight;
  }
  return paddingTop + norm * usableHeight;
}

/**
 * Infiere y enriquece cada punto de métrica con su model_index y architecture
 * para asegurar compatibilidad retroactiva si no vienen del backend.
 */
function enrichMetrics(
  metrics: MetricPoint[],
  modelsConfig?: Array<{ architecture: string; epochs?: number }>
): MetricPoint[] {
  let currentModelIdx = 1;
  let prevEpoca = 0;

  return metrics.map((m, idx) => {
    let mIdx = m.model_index;
    if (mIdx === undefined || mIdx === null) {
      if (idx > 0 && m.epoca <= prevEpoca) {
        currentModelIdx += 1;
      }
      mIdx = currentModelIdx;
    } else {
      currentModelIdx = mIdx;
    }
    prevEpoca = m.epoca;

    const arch =
      m.architecture ||
      (modelsConfig && modelsConfig[mIdx - 1]?.architecture) ||
      `Modelo ${mIdx}`;

    return {
      ...m,
      model_index: mIdx,
      architecture: arch,
    };
  });
}

/**
 * Procesa la serie de métricas y calcula las coordenadas de polylines SVG,
 * separadores de modelos y puntos interactivos con márgenes de seguridad.
 */
export function getChartPaths(
  metrics: MetricPoint[],
  options: ChartOptions = {}
): ChartResult {
  const width = options.width ?? 300;
  const height = options.height ?? 100;
  const paddingTop = options.paddingTop ?? 14;
  const paddingBottom = options.paddingBottom ?? 14;
  const defaultEpochs = options.totalEpochs ?? 10;
  const filter = options.activeModelFilter ?? "current";
  const modelsConfig = options.modelsConfig;

  if (!metrics || metrics.length === 0) {
    return {
      segments: [],
      separators: [],
      maxLoss: 1.0,
      totalPoints: 0,
      maxPoints: defaultEpochs,
      filteredMetrics: [],
    };
  }

  const enriched = enrichMetrics(metrics, modelsConfig);

  // Determinar los índices de modelos presentes
  const availableModelIndices = Array.from(
    new Set(enriched.map((m) => m.model_index ?? 1))
  ).sort((a, b) => a - b);

  // Auto-escalado dinámico de Loss: mínimo 1.0, o el máximo observado
  const allValLosses = enriched.map((m) => m.val_loss).filter((l) => !isNaN(l) && isFinite(l));
  const maxObservedLoss = allValLosses.length > 0 ? Math.max(...allValLosses) : 1.0;
  const maxLoss = Math.max(1.0, Math.ceil(maxObservedLoss * 10) / 10);

  // Filtrado según activeModelFilter
  let targetModelIndex: number | "all" = "all";
  if (filter === "all") {
    targetModelIndex = "all";
  } else if (filter === "current") {
    targetModelIndex =
      options.currentModelIndex ??
      availableModelIndices[availableModelIndices.length - 1] ??
      1;
  } else if (typeof filter === "number") {
    targetModelIndex = filter;
  } else if (typeof filter === "string") {
    const parsed = parseInt(filter, 10);
    if (!isNaN(parsed)) {
      targetModelIndex = parsed;
    } else {
      const match = enriched.find((m) => m.architecture === filter);
      targetModelIndex = match ? (match.model_index ?? 1) : 1;
    }
  }

  const filtered =
    targetModelIndex === "all"
      ? enriched
      : enriched.filter((m) => m.model_index === targetModelIndex);

  if (filtered.length === 0) {
    return {
      segments: [],
      separators: [],
      maxLoss,
      totalPoints: 0,
      maxPoints: defaultEpochs,
      filteredMetrics: [],
    };
  }

  // Agrupar por model_index
  const groupedByModel = new Map<number, MetricPoint[]>();
  for (const m of filtered) {
    const idx = m.model_index ?? 1;
    if (!groupedByModel.has(idx)) {
      groupedByModel.set(idx, []);
    }
    groupedByModel.get(idx)!.push(m);
  }

  const segments: ChartSegment[] = [];
  const separators: ModelSeparator[] = [];

  if (targetModelIndex !== "all") {
    // Modo Modelo Único: X escala de 0 a width sobre las épocas de este modelo
    const pointsList = filtered;
    const modelExpectedEpochs =
      (modelsConfig && modelsConfig[targetModelIndex - 1]?.epochs) ||
      defaultEpochs;
    const span = Math.max(1, modelExpectedEpochs - 1, pointsList.length - 1);

    const chartPoints: ChartPoint[] = pointsList.map((m, i) => {
      const x = (i / span) * width;
      const yAcc = normalizePoint(m.val_acc, 0, 100, height, paddingTop, paddingBottom, true);
      const yLoss = normalizePoint(m.val_loss, 0, maxLoss, height, paddingTop, paddingBottom, true);
      return { x, yAcc, yLoss, metric: m };
    });

    const accPolyline = chartPoints.map((p) => `${p.x.toFixed(1)},${p.yAcc.toFixed(1)}`).join(" ");
    const lossPolyline = chartPoints.map((p) => `${p.x.toFixed(1)},${p.yLoss.toFixed(1)}`).join(" ");

    segments.push({
      modelIndex: targetModelIndex,
      architecture: filtered[0]?.architecture || `Modelo ${targetModelIndex}`,
      accPolyline,
      lossPolyline,
      points: chartPoints,
    });

    return {
      segments,
      separators: [],
      maxLoss,
      totalPoints: filtered.length,
      maxPoints: modelExpectedEpochs,
      filteredMetrics: filtered,
    };
  }

  // Modo "Todos" (Ensamble Multi-Modelo):
  // Calcular la capacidad global de épocas y los offsets por modelo
  const totalModelsCount = modelsConfig?.length || availableModelIndices.length;
  const modelCapacities: number[] = [];

  for (let i = 0; i < totalModelsCount; i++) {
    const configuredEpochs = modelsConfig?.[i]?.epochs;
    const modelIdx = i + 1;
    const pointsInModel = groupedByModel.get(modelIdx)?.length || 0;
    const cap = Math.max(configuredEpochs || defaultEpochs, pointsInModel);
    modelCapacities.push(cap);
  }

  const totalGlobalEpochs = modelCapacities.reduce((sum, c) => sum + c, 0);
  const globalSpan = Math.max(1, totalGlobalEpochs - 1, filtered.length - 1);

  // Calcular offsets acumulados
  const modelOffsets: number[] = [0];
  for (let i = 0; i < modelCapacities.length - 1; i++) {
    modelOffsets.push(modelOffsets[i] + modelCapacities[i]);
  }

  // Generar separadores visuales entre modelos
  for (let i = 1; i < totalModelsCount; i++) {
    const sepSlot = modelOffsets[i];
    const sepX = (sepSlot / globalSpan) * width;
    const archLabel = modelsConfig?.[i]?.architecture || `Modelo ${i + 1}`;
    separators.push({
      x: sepX,
      modelIndex: i + 1,
      label: archLabel,
    });
  }

  // Construir segmentos independientes para cada modelo
  for (const [modelIdx, pointsList] of Array.from(groupedByModel.entries()).sort(
    ([a], [b]) => a - b
  )) {
    const offset = modelOffsets[modelIdx - 1] ?? 0;

    const chartPoints: ChartPoint[] = pointsList.map((m, i) => {
      const globalSlot = offset + i;
      const x = Math.min(width, (globalSlot / globalSpan) * width);
      const yAcc = normalizePoint(m.val_acc, 0, 100, height, paddingTop, paddingBottom, true);
      const yLoss = normalizePoint(m.val_loss, 0, maxLoss, height, paddingTop, paddingBottom, true);
      return { x, yAcc, yLoss, metric: m };
    });

    const accPolyline = chartPoints.map((p) => `${p.x.toFixed(1)},${p.yAcc.toFixed(1)}`).join(" ");
    const lossPolyline = chartPoints.map((p) => `${p.x.toFixed(1)},${p.yLoss.toFixed(1)}`).join(" ");

    segments.push({
      modelIndex: modelIdx,
      architecture: pointsList[0]?.architecture || `Modelo ${modelIdx}`,
      accPolyline,
      lossPolyline,
      points: chartPoints,
    });
  }

  return {
    segments,
    separators,
    maxLoss,
    totalPoints: filtered.length,
    maxPoints: totalGlobalEpochs,
    filteredMetrics: filtered,
  };
}

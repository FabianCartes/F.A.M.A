import { API_BASE_URL } from "@/lib/api";
import {
  HardwareStatus,
  HardwareStatusSchema,
  TrainingDataset,
  DatasetsResponseSchema,
  StartTrainingRequest,
  StartTrainingInput,
  StartTrainingRequestSchema,
  StartTrainingResponse,
  StartTrainingResponseSchema,
  TrainingProgress,
  TrainingProgressSchema,
  StopTrainingResponse,
  StopTrainingResponseSchema,
  ModelHistoryItem,
  HistoryResponseSchema,
  ActivateModelResponse,
  ActivateModelResponseSchema,
} from "@/lib/schemas/training";
import { ZodError } from "zod";

// ============================================================================
// DOMAIN ERROR CLASSES
// ============================================================================

export class ApiConnectionError extends Error {
  public readonly statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = "ApiConnectionError";
    this.statusCode = statusCode;
  }
}

export class TrainingBusyError extends Error {
  constructor(message: string = "Ya existe un proceso de entrenamiento en ejecución.") {
    super(message);
    this.name = "TrainingBusyError";
  }
}

export class ValidationError extends Error {
  public readonly issues: unknown[];

  constructor(message: string, issues: unknown[] = []) {
    super(message);
    this.name = "ValidationError";
    this.issues = issues;
  }
}

/**
 * Helper to handle fetch calls and error normalization
 */
async function request<T>(
  url: string,
  options?: RequestInit,
  schemaParser?: (data: unknown) => T
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, options);
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    throw new ApiConnectionError(`Error de red al conectar con el servidor: ${errorMsg}`);
  }

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const errDetail =
      (typeof data === "object" && data !== null && "detail" in data)
        ? String((data as { detail: unknown }).detail)
        : res.statusText || `HTTP ${res.status}`;

    if (res.status === 400 && errDetail.toLowerCase().includes("ejecución")) {
      throw new TrainingBusyError(errDetail);
    }

    throw new ApiConnectionError(errDetail, res.status);
  }

  if (schemaParser) {
    try {
      return schemaParser(data);
    } catch (parseErr: unknown) {
      if (parseErr instanceof ZodError) {
        throw new ValidationError("Error de validación en respuesta del servidor", parseErr.issues);
      }
      throw new ValidationError("Estructura de respuesta inválida");
    }
  }

  return data as T;
}

// ============================================================================
// TRAINING API SEAM CLIENT (RF_04, CU_INV_02, CU_INV_03, CU_INV_04, CU_INV_05)
// ============================================================================

/**
 * Consulta la telemetría de hardware (GPU/CPU, VRAM, RAM, temperatura).
 */
export async function getHardwareStatus(): Promise<HardwareStatus> {
  return request(
    `${API_BASE_URL}/api/training/hardware`,
    { method: "GET" },
    (data) => HardwareStatusSchema.parse(data)
  );
}

/**
 * Consulta el catálogo de datasets listos para entrenar.
 */
export async function getDatasets(): Promise<TrainingDataset[]> {
  const result = await request(
    `${API_BASE_URL}/api/training/datasets`,
    { method: "GET" },
    (data) => DatasetsResponseSchema.parse(data)
  );
  return result.datasets;
}

/**
 * Inicia un ciclo de entrenamiento asíncrono en segundo plano.
 */
export async function startTraining(
  params: StartTrainingInput
): Promise<StartTrainingResponse> {
  let validatedParams: StartTrainingRequest;
  try {
    validatedParams = StartTrainingRequestSchema.parse(params);
  } catch (err: unknown) {
    if (err instanceof ZodError) {
      throw new ValidationError("Parámetros de entrenamiento inválidos", err.issues);
    }
    throw new ValidationError("Parámetros de entrenamiento inválidos");
  }

  return request(
    `${API_BASE_URL}/api/training/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(validatedParams),
    },
    (data) => StartTrainingResponseSchema.parse(data)
  );
}

/**
 * Consulta una instantánea del progreso del entrenamiento en tiempo real.
 */
export async function getProgress(): Promise<TrainingProgress> {
  return request(
    `${API_BASE_URL}/api/training/progress`,
    { method: "GET" },
    (data) => TrainingProgressSchema.parse(data)
  );
}

/**
 * Solicita la detención cooperativa del proceso de entrenamiento en curso.
 */
export async function stopTraining(): Promise<StopTrainingResponse> {
  return request(
    `${API_BASE_URL}/api/training/stop`,
    { method: "POST" },
    (data) => StopTrainingResponseSchema.parse(data)
  );
}

/**
 * Consulta el historial de modelos entrenados y registrados en PostgreSQL.
 */
export async function getHistory(): Promise<ModelHistoryItem[]> {
  const result = await request(
    `${API_BASE_URL}/api/training/history`,
    { method: "GET" },
    (data) => HistoryResponseSchema.parse(data)
  );
  return result.history;
}

/**
 * Marca un modelo como el activo para inferencia acústica.
 */
export async function activateModel(modelId: number): Promise<ActivateModelResponse> {
  return request(
    `${API_BASE_URL}/api/training/models/${modelId}/activate`,
    { method: "POST" },
    (data) => ActivateModelResponseSchema.parse(data)
  );
}

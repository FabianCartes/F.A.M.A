import { API_BASE_URL } from "@/lib/api";
import {
  FeedbackCreateRequest,
  FeedbackCreateRequestSchema,
  FeedbackResponse,
  FeedbackResponseSchema,
  PendingFeedbackItem,
  PendingFeedbackListSchema,
  FeedbackStats,
  FeedbackStatsSchema,
  ApproveFeedbackResponse,
  ApproveFeedbackResponseSchema,
  RejectFeedbackResponse,
  RejectFeedbackResponseSchema,
} from "@/lib/schemas/feedback";
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

export class NotFoundError extends Error {
  public readonly statusCode: number = 404;

  constructor(message: string = "Recurso no encontrado.") {
    super(message);
    this.name = "NotFoundError";
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
 * Generic HTTP request wrapper with error handling and Zod schema parsing.
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
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText || `HTTP ${res.status}`;

    if (res.status === 404) {
      throw new NotFoundError(errDetail);
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
// RF_06 FEEDBACK API CLIENT
// ============================================================================

/**
 * Submits field feedback for an inference prediction.
 * If the prediction was wrong (`fue_correcta: false`), `etiqueta_corregida` is required.
 */
export async function sendFeedback(payload: unknown): Promise<FeedbackResponse> {
  let validatedPayload: FeedbackCreateRequest;
  try {
    validatedPayload = FeedbackCreateRequestSchema.parse(payload);
  } catch (err: unknown) {
    if (err instanceof ZodError) {
      throw new ValidationError("Error de validación en datos de retroalimentación", err.issues);
    }
    throw new ValidationError("Datos de retroalimentación inválidos");
  }

  return request(
    `${API_BASE_URL}/api/feedback`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(validatedPayload),
    },
    (data) => FeedbackResponseSchema.parse(data)
  );
}

/**
 * Fetches uncurated pending feedback items for human-in-the-loop review.
 */
export async function getPendingFeedback(limit: number = 50): Promise<PendingFeedbackItem[]> {
  return request(
    `${API_BASE_URL}/api/feedback/pending?limit=${limit}`,
    {
      method: "GET",
    },
    (data) => PendingFeedbackListSchema.parse(data)
  );
}

/**
 * Approves a feedback recording and integrates it into the raw training dataset.
 */
export async function approveFeedback(
  idRetroalimentacion: number,
  datasetName: string = "AvesChilenas"
): Promise<ApproveFeedbackResponse> {
  const query = encodeURIComponent(datasetName);
  return request(
    `${API_BASE_URL}/api/feedback/${idRetroalimentacion}/approve?dataset_name=${query}`,
    {
      method: "POST",
    },
    (data) => ApproveFeedbackResponseSchema.parse(data)
  );
}

/**
 * Rejects and discards a feedback recording without touching the training dataset.
 */
export async function rejectFeedback(
  idRetroalimentacion: number
): Promise<RejectFeedbackResponse> {
  return request(
    `${API_BASE_URL}/api/feedback/${idRetroalimentacion}/reject`,
    {
      method: "POST",
    },
    (data) => RejectFeedbackResponseSchema.parse(data)
  );
}

/**
 * Retrieves consolidated metrics and telemetry for active field feedback.
 */
export async function getFeedbackStats(): Promise<FeedbackStats> {
  return request(
    `${API_BASE_URL}/api/feedback/stats`,
    {
      method: "GET",
    },
    (data) => FeedbackStatsSchema.parse(data)
  );
}

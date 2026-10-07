import { z } from "zod";

// ============================================================================
// RF_06 ACTIVE FEEDBACK LOOP & HUMAN-IN-THE-LOOP CURATION SCHEMAS
// ============================================================================

/**
 * Payload schema for submitting field feedback on a prediction.
 */
export const FeedbackCreateRequestSchema = z
  .object({
    id_prediccion: z.number().int().positive("El ID de predicción debe ser un entero positivo"),
    fue_correcta: z.boolean(),
    etiqueta_corregida: z.string().nullable().optional(),
    id_usuario: z.number().int().positive().optional().default(1),
  })
  .refine(
    (data) => {
      if (!data.fue_correcta) {
        return (
          typeof data.etiqueta_corregida === "string" &&
          data.etiqueta_corregida.trim().length > 0
        );
      }
      return true;
    },
    {
      message: "Field 'etiqueta_corregida' is required when 'fue_correcta' is false.",
      path: ["etiqueta_corregida"],
    }
  );

export type FeedbackCreateRequest = z.infer<typeof FeedbackCreateRequestSchema>;

/**
 * Response schema when feedback is recorded.
 */
export const FeedbackResponseSchema = z.object({
  id_retroalimentacion: z.number().int(),
  id_prediccion: z.number().int(),
  id_usuario: z.number().int().optional().default(1),
  fue_correcta: z.boolean(),
  etiqueta_corregida: z.string().nullable().optional(),
  procesado: z.boolean(),
  fecha_retroalimentacion: z.string().nullable().optional(),
});

export type FeedbackResponse = z.infer<typeof FeedbackResponseSchema>;

/**
 * Schema for an uncurated item waiting in the curation queue.
 */
export const PendingFeedbackItemSchema = z.object({
  // Missing legacy snapshots are unknown, never an implicit dataset choice.
  dataset_name: z.string().nullable().optional(),
  id_retroalimentacion: z.number().int(),
  id_prediccion: z.number().int(),
  ruta_audio_prueba: z.string(),
  etiqueta_predicha: z.string(),
  confianza: z.number(),
  etiqueta_corregida: z.string().nullable().optional(),
  fecha_retroalimentacion: z.string().nullable().optional(),
  fue_correcta: z.boolean(),
  procesado: z.boolean(),
  id_usuario: z.number().int().optional().default(1),
  audio_filename: z.string().nullable().optional(),
  fecha_carga: z.string().nullable().optional(),
});

export type PendingFeedbackItem = z.infer<typeof PendingFeedbackItemSchema>;

export const PendingFeedbackListSchema = z.array(PendingFeedbackItemSchema);
export type PendingFeedbackList = z.infer<typeof PendingFeedbackListSchema>;

/**
 * Breakdown of corrected labels telemetry.
 */
export const CorrectionBreakdownItemSchema = z
  .object({
    etiqueta_corregida: z.string().nullable().optional(),
    count: z.number().optional(),
  })
  .passthrough();

export type CorrectionBreakdownItem = z.infer<typeof CorrectionBreakdownItemSchema>;

/**
 * Telemetry and aggregated statistics for the active feedback loop.
 */
export const FeedbackStatsSchema = z.object({
  total_validated: z.number().int(),
  correct_count: z.number().int(),
  corrected_count: z.number().int(),
  accuracy_rate: z.number(),
  pending_curation_count: z.number().int(),
  corrections_breakdown: z.array(CorrectionBreakdownItemSchema),
});

export type FeedbackStats = z.infer<typeof FeedbackStatsSchema>;

/**
 * Response when a pending feedback audio is approved and moved to the raw dataset.
 */
export const ApproveFeedbackResponseSchema = z.object({
  status: z.literal("approved"),
  id_retroalimentacion: z.number().int(),
  destination_path: z.string(),
  clase: z.string(),
  filename: z.string().nullable().optional(),
  local_status: z.literal("incorporated"),
  sync_status: z.enum(["pending", "synced"]),
  message: z.string().optional(),
});

export type ApproveFeedbackResponse = z.infer<typeof ApproveFeedbackResponseSchema>;

/** Accepted local milestone and persisted cloud acknowledgement, not an existence audit. */
export const FeedbackSyncStateSchema = z.object({
  id_retroalimentacion: z.number().int(),
  id_prediccion: z.number().int(),
  dataset_name: z.string(),
  storage_class: z.string(),
  class_label: z.string(),
  local_status: z.literal("incorporated"),
  sync_status: z.enum(["pending", "synced"]),
  attempts: z.number().int().nonnegative(),
  error_code: z.enum(["upload_failed", "integrity_mismatch"]).nullable(),
});
export type FeedbackSyncState = z.infer<typeof FeedbackSyncStateSchema>;
export const FeedbackSyncListSchema = z.array(FeedbackSyncStateSchema);

/**
 * Response when a pending feedback audio is rejected/discarded.
 */
export const RejectFeedbackResponseSchema = z.object({
  status: z.string(),
  id_retroalimentacion: z.number().int().optional(),
  message: z.string().optional(),
});

export type RejectFeedbackResponse = z.infer<typeof RejectFeedbackResponseSchema>;

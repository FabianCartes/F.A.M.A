import { z } from "zod";

// ============================================================================
// HARDWARE STATUS SCHEMA (Figura 6.8)
// ============================================================================
export const HardwareStatusSchema = z.object({
  cuda_available: z.boolean(),
  device_name: z.string(),
  vram_total_gb: z.number(),
  vram_used_gb: z.number(),
  vram_percent: z.number(),
  cpu_percent: z.number().optional(),
  cpu_cores: z.number().optional(),
  host_ram_total_gb: z.number().optional(),
  host_ram_used_gb: z.number().optional(),
  host_ram_percent: z.number().optional(),
  temperature_c: z.number().nullable().optional(),
  load_status: z.string().optional(),
  load_level: z.enum(["normal", "warning", "danger"]).or(z.string()).optional(),
  status: z.string(),
});
export type HardwareStatus = z.infer<typeof HardwareStatusSchema>;

// ============================================================================
// DATASET SCHEMAS (CU_INV_02)
// ============================================================================
export const TrainingDatasetSchema = z.object({
  id: z.string(),
  name: z.string(),
  audio_count: z.number(),
  class_count: z.number().optional().default(15),
  classes: z.array(z.string()).optional().default([]),
  size_mb: z.number().optional().default(0),
  estado: z.string().optional().default("sincronizado"),
  domain: z.string().optional(),
  domain_label: z.string().optional(),
  db_id: z.number().nullable().optional(),
});
export type TrainingDataset = z.infer<typeof TrainingDatasetSchema>;

export const DatasetsResponseSchema = z.object({
  datasets: z.array(TrainingDatasetSchema),
});
export type DatasetsResponse = z.infer<typeof DatasetsResponseSchema>;

// ============================================================================
// TRAINING LIFECYCLE SCHEMAS (CU_INV_03)
// ============================================================================
export const ModelEnsembleItemSchema = z.object({
  architecture: z.string(),
  weight: z.number().min(0).max(1),
  epochs: z.number().int().min(1, "Model epochs must be at least 1").max(1000, "Model epochs must be at most 1000").optional(),
});
export type ModelEnsembleItem = z.infer<typeof ModelEnsembleItemSchema>;

export const AudioConfigSchema = z.object({
  target_sr: z.number().int().min(8000).max(48000).default(22050),
  duration_seconds: z.number().min(0.5).max(30.0).default(5.0),
  f_min: z.number().min(0.0).default(0.0),
  f_max: z.number().min(100.0).default(10000.0),
  n_mels: z.number().int().min(32).max(256).default(128),
  n_fft: z.number().int().min(256).default(2048),
  hop_length: z.number().int().min(64).default(512),
}).refine((data) => data.f_max <= data.target_sr / 2, {
  message: "Violación de Nyquist: f_max no puede superar target_sr / 2",
  path: ["f_max"],
}).refine((data) => data.f_min < data.f_max, {
  message: "f_min debe ser estrictamente menor que f_max",
  path: ["f_min"],
});
export type AudioConfig = z.infer<typeof AudioConfigSchema>;

export const WindowingConfigSchema = z.object({
  hop_seconds: z.number().positive().default(1.0),
  aggregation_mode: z.enum(["max", "mean"]).default("max"),
  gem_p: z.number().min(1.0).max(10.0).default(3.0),
  vad_threshold: z.number().min(0.0).max(1.0).default(0.0),
});
export type WindowingConfig = z.infer<typeof WindowingConfigSchema>;

export const RegularizationConfigSchema = z.object({
  loss_type: z.enum(["focal", "cross_entropy"]).default("focal"),
  focal_gamma: z.number().min(0.0).default(2.0),
  mixup_enabled: z.boolean().default(false),
  mixup_alpha: z.number().min(0.0).default(0.2),
  pitch_shift_enabled: z.boolean().default(false),
});
export type RegularizationConfig = z.infer<typeof RegularizationConfigSchema>;

export const StartTrainingRequestSchema = z.object({
  dataset_name: z.string().min(1, "Dataset name is required"),
  architecture: z.string().optional().default("EfficientNet-B0"),
  epochs: z.number().int().min(1, "Epochs must be at least 1").max(1000, "Epochs must be at most 1000").default(10),
  learning_rate: z.number().positive().default(0.001),
  weight_decay: z.number().min(0, "Weight decay must be non-negative").max(1, "Weight decay must be at most 1.0").optional().default(0.01),
  batch_size: z.number().int().positive().default(16),
  framework: z.string().default("pytorch"),
  is_tri_model: z.boolean().optional().default(false),
  models: z.array(ModelEnsembleItemSchema).min(1).max(3).optional(),
  audio_config: AudioConfigSchema.optional(),
  windowing_config: WindowingConfigSchema.optional(),
  regularization_config: RegularizationConfigSchema.optional(),
});
export type StartTrainingRequest = z.infer<typeof StartTrainingRequestSchema>;
export type StartTrainingInput = z.input<typeof StartTrainingRequestSchema>;


export const StartTrainingResponseSchema = z.object({
  status: z.string(),
  job_id: z.string(),
  message: z.string(),
});
export type StartTrainingResponse = z.infer<typeof StartTrainingResponseSchema>;

export const MetricPointSchema = z.object({
  epoca: z.number(),
  train_loss: z.number(),
  val_loss: z.number(),
  train_acc: z.number(),
  val_acc: z.number(),
  tiempo_epoca: z.number().optional(),
});
export type MetricPoint = z.infer<typeof MetricPointSchema>;

export const LogItemObjectSchema = z.object({
  id: z.string().optional(),
  timestamp: z.string().optional(),
  level: z.string().optional().default("INFO"),
  message: z.string(),
});

export const LogEntrySchema = z.union([
  LogItemObjectSchema,
  z.string().transform((msg) => ({
    id: Math.random().toString(36).substring(2, 9),
    timestamp: new Date().toLocaleTimeString(),
    level: "INFO",
    message: msg,
  })),
]);
export type LogEntry = z.infer<typeof LogItemObjectSchema>;

export const TrainingProgressSchema = z.object({
  status: z.string(),
  job_id: z.string().nullable().optional(),
  is_tri_model: z.boolean().optional().default(false),
  current_model_index: z.number().optional().default(1),
  total_models: z.number().optional().default(1),
  current_architecture: z.string().optional().default(""),
  epoch: z.number().default(0),
  total_epochs: z.number().default(10),
  train_loss: z.number().default(0.0),
  val_loss: z.number().default(0.0),
  train_acc: z.number().default(0.0),
  val_acc: z.number().default(0.0),
  metrics_history: z.array(MetricPointSchema).optional().default([]),
  logs: z.array(LogEntrySchema).optional().default([]),
  elapsed_seconds: z.number().optional().default(0),
  error_message: z.string().nullable().optional(),
});
export type TrainingProgress = z.infer<typeof TrainingProgressSchema>;

export const StopTrainingResponseSchema = z.object({
  status: z.string(),
  message: z.string(),
});
export type StopTrainingResponse = z.infer<typeof StopTrainingResponseSchema>;

// ============================================================================
// MODEL HISTORY & ACTIVATION SCHEMAS (CU_INV_04 / CU_INV_05)
// ============================================================================
export const ModelHistoryItemSchema = z.object({
  id: z.number(),
  architecture: z.string(),
  epochs: z.number(),
  accuracy: z.number().nullable().optional(),
  loss: z.number().nullable().optional(),
  active: z.boolean(),
  status: z.string(),
  filename: z.string(),
  created_at: z.string().nullable().optional(),
});
export type ModelHistoryItem = z.infer<typeof ModelHistoryItemSchema>;

export const HistoryResponseSchema = z.object({
  history: z.array(ModelHistoryItemSchema),
});
export type HistoryResponse = z.infer<typeof HistoryResponseSchema>;

export const ActivateModelResponseSchema = z.object({
  success: z.boolean(),
  active_model_id: z.number().optional(),
  architecture: z.string().optional(),
  error: z.string().optional(),
});
export type ActivateModelResponse = z.infer<typeof ActivateModelResponseSchema>;

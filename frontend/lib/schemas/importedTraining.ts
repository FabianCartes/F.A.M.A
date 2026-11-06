import { z } from 'zod';

export const importedProfileSchema = z.object({
  architecture: z.enum(['audio_cnn', 'panns_cnn14', 'efficientnet_b0', 'convnext_nano', 'resnet34d']),
  channels: z.literal(1), preprocessing: z.string(), windowing: z.string(),
  window_hop_seconds: z.number().positive(),
  audio: z.object({ target_sr: z.number(), duration_seconds: z.number(), n_mels: z.number(),
    n_fft: z.number(), hop_length: z.number(), f_min: z.number(), f_max: z.number(),
    use_gpu_frontend: z.boolean() }),
});
export const importedPreparationSchema = z.object({
  snapshot_id: z.string(), prepared_version: z.string(), eligible: z.boolean(),
  reasons: z.array(z.string()), profile: importedProfileSchema, warnings: z.array(z.unknown()),
  seed: z.number().int().min(0).max(2**32-1).optional(),
  policy: z.object({name:z.string(),target:z.array(z.number())}).optional(),
  provenance: z.record(z.string(),z.unknown()).optional(),
});
export const importedDatasetSchema = z.object({
  source_type: z.literal('imported'), id: z.string(), name: z.string(),
  eligible: z.boolean(), reasons: z.array(z.string()), preparations: z.array(importedPreparationSchema),
});
export const snapshotSchema = z.object({id:z.string(), dataset_id:z.string(), state:z.literal('ready'), name:z.string(), file_count:z.number()});
export const membersSchema = z.object({snapshot_id:z.string(),members:z.array(z.object({member_id:z.string(),class_name:z.string(),original_path:z.string(),size_bytes:z.number(),sha256:z.string()})).max(20000)});
export const preparedResourceSchema = z.object({snapshot_id:z.string(),version_id:z.string(),state:z.literal('ready'),profile:importedProfileSchema,class_to_index:z.record(z.string(),z.number()),warnings:z.array(z.unknown()),seed:z.number()});
export type ImportedProfile = z.infer<typeof importedProfileSchema>;
export type ImportedPreparation = z.infer<typeof importedPreparationSchema>;
export type ImportedDataset = z.infer<typeof importedDatasetSchema>;
export type ImportedSelection = ImportedPreparation & { dataset_id: string };

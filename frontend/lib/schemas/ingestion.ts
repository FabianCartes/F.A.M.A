import { z } from "zod";

const count = z.number().int().nonnegative();

/**
 * Local versus GCS content check of one dataset.
 * `count_size` is automatic (no hashing), `checksum` is the explicit verification
 * against the provider checksums, `download` is derived from a finished download.
 */
export const ContentCheckSchema = z.object({
  level: z.enum(["count_size", "checksum", "download"]),
  status: z.enum(["match", "differences"]),
  local_count: count.nullable(),
  gcs_count: count,
  matching: count,
  missing_local: count,
  only_local: count.nullable(),
  size_mismatch: count,
  checksum_mismatch: count,
  unverified: count,
  failed: count.optional(),
});

export type ContentCheck = z.infer<typeof ContentCheckSchema>;

import { z } from "zod";

const count = z.number().int().nonnegative();

/** Result of comparing one dataset's local audio with its GCS objects. */
export const DatasetComparisonSchema = z.object({
  dataset: z.string(),
  status: z.enum(["match", "differences"]),
  local_count: count,
  gcs_count: count,
  missing_local: count,
  missing_gcs: count,
  size_mismatch: count,
  hash_mismatch: count,
  hash_unverified: count,
  hash_verified: count,
});

export type DatasetComparison = z.infer<typeof DatasetComparisonSchema>;

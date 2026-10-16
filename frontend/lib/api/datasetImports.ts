import { API_BASE_URL } from "@/lib/api";
import { z } from "zod";

export const audioSchema = z.object({
  id: z.string(), relative_path: z.string(),
  original_path: z.string(), class_name: z.string(), sha256: z.string(),
  size_bytes: z.number(), duplicate: z.boolean(), existing: z.boolean().optional(),
});
const previewSchema = z.object({
  root: z.string().optional(),
  file_count: z.number(), class_count: z.number(), error_count: z.number(), warning_count: z.number(),
  total_size_bytes: z.number(), synced_count: z.number(),
  new_count: z.number().optional(), duplicate_count: z.number().optional(), duplicate_collection: z.boolean().optional(),
});
export const issueSchema = z.object({ id: z.string(), severity: z.enum(["error", "warning"]),
  path: z.string(), code: z.string(), action: z.string().nullable() });
export const pageMetadataSchema = z.object({ total: z.number().int().nonnegative(), next_cursor: z.string().nullable(),
  snapshot: z.union([z.string(), z.number()]).nullable() });
export const filesPageSchema = pageMetadataSchema.extend({ files: z.array(audioSchema).max(200) });
export const classesPageSchema = pageMetadataSchema.extend({ classes: z.array(z.string()).max(200) });
export const issuesPageSchema = pageMetadataSchema.extend({ issues: z.array(issueSchema).max(200) });
export const jobSchema = z.object({
  id: z.string(), status: z.string(), sync_status: z.string(), dataset_id: z.string().nullable(),
  added_count: z.number(), preview_token: z.string().nullable(), preview: previewSchema, error: z.string().nullable(),
});
export const datasetSchema = z.object({ id: z.string(), name: z.string(), file_count: z.number() });
export const datasetsPageSchema = pageMetadataSchema.extend({ datasets: z.array(datasetSchema).max(200) });
export const jobsPageSchema = pageMetadataSchema.extend({ imports: z.array(jobSchema).max(200) });
export const limitsSchema = z.object({
  received_bytes: z.number(), expanded_bytes: z.number(), entries: z.number(), depth: z.number(),
  path_bytes: z.number(), audio_bytes: z.number(), audio_seconds: z.number(),
  validation_seconds: z.number(), free_bytes: z.number(), ttl_seconds: z.number(),
  concurrent_imports: z.number(),
});
export type ImportJob = z.infer<typeof jobSchema>;
export type ImportDataset = z.infer<typeof datasetSchema>;
export type ImportLimits = z.infer<typeof limitsSchema>;

export async function importRequest(token: string, path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = typeof data === "object" && data !== null && "detail" in data && typeof data.detail === "string"
      ? data.detail : "No se completó la solicitud. Consulta su estado antes de reintentar.";
    throw new Error(`${response.status}: ${detail}`);
  }
  return response;
}

export function jsonRequest(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const importBase = "/api/ingestion/imports";

export async function saveDownload(response: Response, filename: string) {
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

import { API_BASE_URL, apiFetch } from "@/lib/api";
import { DatasetComparisonSchema, type DatasetComparison } from "@/lib/schemas/ingestion";

/** Compare local and GCS content of one dataset; the server hashes local files, so call it on demand only. */
export async function compareDataset(name: string, signal?: AbortSignal): Promise<DatasetComparison> {
  const response = await apiFetch(`${API_BASE_URL}/api/ingestion/datasets/${encodeURIComponent(name)}/compare`,
    { method: "POST", signal });
  let value: unknown;
  try { value = await response.json(); } catch { value = null; }
  if (!response.ok) {
    const detail = value && typeof value === "object" && "detail" in value && typeof value.detail === "string" ? value.detail : null;
    throw new Error(detail ?? "No se pudo comparar el contenido.");
  }
  const parsed = DatasetComparisonSchema.safeParse(value);
  if (!parsed.success) throw new Error("La respuesta de la comparación no es válida.");
  return parsed.data;
}

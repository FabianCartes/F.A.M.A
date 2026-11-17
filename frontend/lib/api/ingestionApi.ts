import { API_BASE_URL, apiFetch } from "@/lib/api";
import { ContentCheckSchema, type ContentCheck } from "@/lib/schemas/ingestion";

/** Verify local content against the GCS checksums; the server hashes local files, so call it on demand only. */
export async function verifyDatasetContent(name: string, signal?: AbortSignal): Promise<ContentCheck> {
  const response = await apiFetch(`${API_BASE_URL}/api/ingestion/datasets/${encodeURIComponent(name)}/compare`,
    { method: "POST", signal });
  let value: unknown;
  try { value = await response.json(); } catch { value = null; }
  if (!response.ok) {
    const detail = value && typeof value === "object" && "detail" in value && typeof value.detail === "string" ? value.detail : null;
    throw new Error(detail ?? "No se pudo verificar el contenido.");
  }
  const parsed = ContentCheckSchema.safeParse(value);
  if (!parsed.success) throw new Error("La respuesta de la verificación no es válida.");
  return parsed.data;
}

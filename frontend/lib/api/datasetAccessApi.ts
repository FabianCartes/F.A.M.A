import { z } from 'zod';
import { API_BASE_URL, apiFetch } from '@/lib/api';

const status = z.enum(['pending', 'approved', 'rejected']);
const identity = { user_id: z.number().int().positive(), dataset_id: z.number().int().positive(), status };
const pagination = { total: z.number().int().nonnegative(), limit: z.number().int().positive(), offset: z.number().int().nonnegative() };
const cataloguePage = z.object({ ...pagination, datasets: z.array(z.object({
  dataset_id: z.number().int().positive(), name: z.string(), purpose: z.string(),
  audio_count: z.number().int().nonnegative(), size_bytes: z.number().nonnegative(),
  assigned: z.boolean(), request_status: status.nullable(),
})) });
const inboxPage = z.object({ ...pagination, requests: z.array(z.object({ ...identity,
  user_name: z.string(), dataset_name: z.string(), requested_at: z.number(),
  decided_at: z.number().nullable(), decided_by: z.number().int().nullable(),
})) });
export type CataloguePage = z.infer<typeof cataloguePage>;
export type RequestsPage = z.infer<typeof inboxPage>;

async function read<T>(path: string, schema: z.ZodType<T>, options?: RequestInit): Promise<T> {
  const response = await apiFetch(`${API_BASE_URL}/api/${path}`, options);
  let value: unknown;
  try { value = await response.json(); }
  catch { throw new Error('La respuesta del servidor no es válida. Actualiza el estado antes de continuar.'); }
  if (!response.ok) {
    const message = value && typeof value === 'object' && 'detail' in value && typeof value.detail === 'string' ? value.detail : 'No se pudo confirmar la operación. Actualiza el estado antes de reintentar.';
    throw new Error(message);
  }
  const result = schema.safeParse(value);
  if (!result.success) throw new Error('No se pudo confirmar el resultado. Actualiza el estado antes de continuar.');
  return result.data;
}

export function listCatalogue(offset: number, signal?: AbortSignal) {
  return read(`datasets/catalogue?limit=20&offset=${offset}`, cataloguePage, { signal });
}
export async function requestAccess(datasetId: number, signal?: AbortSignal) {
  const result = await read(`datasets/${datasetId}/requests`, z.object(identity), { method: 'POST', signal });
  if (result.dataset_id !== datasetId || result.status !== 'pending') throw new Error('La solicitud no quedó confirmada. Actualiza el catálogo.');
  return result;
}
export function listRequests(offset: number, state: string, signal?: AbortSignal) {
  return read(`access/requests?limit=20&offset=${offset}&state=${encodeURIComponent(state)}`, inboxPage, { signal });
}
export async function decideRequest(userId: number, datasetId: number, decision: 'approve' | 'reject', signal?: AbortSignal) {
  const result = await read(`access/requests/${userId}/${datasetId}/decision`, z.object({ ...identity, assigned: z.boolean() }), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision }), signal,
  });
  if (result.user_id !== userId || result.dataset_id !== datasetId || result.status !== (decision === 'approve' ? 'approved' : 'rejected')) throw new Error('No se pudo confirmar la decisión solicitada. Actualiza la bandeja.');
  return result;
}

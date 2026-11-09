import { z } from 'zod';
import { API_BASE_URL, apiSessionRevision, notifyUnauthorized } from '@/lib/api';
import { importedDatasetSchema, snapshotSchema, membersSchema, preparedResourceSchema } from '@/lib/schemas/importedTraining';

export class ImportedTrainingError extends Error {
  constructor(message:string, public readonly code?:string) { super(message); }
}

async function request(path: string, body?: unknown, signal?: AbortSignal): Promise<unknown> {
  const revision = apiSessionRevision();
  const base = new URL(API_BASE_URL || '/', window.location.origin);
  if (base.origin !== window.location.origin) throw new Error('Los recursos privados requieren API del mismo origen.');
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal,
      ...(body === undefined ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}),
    });
  } catch {
    throw new ImportedTrainingError('Resultado incierto. Vuelva a seleccionar un recurso existente antes de solicitar otra preparación; no se reintentó la solicitud.');
  }
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized(revision);
    const detail = data?.detail;
    throw new ImportedTrainingError(typeof detail === 'string' ? detail : detail?.message || `No se pudo consultar el recurso (${response.status}).`, typeof detail?.code === 'string' ? detail.code : undefined);
  }
  if (revision !== apiSessionRevision()) throw new Error('La sesión cambió. Vuelva a seleccionar la fuente.');
  return data;
}

const revisedTriadSchema = z.object({id: z.string().min(1), name: z.string(), weights: z.array(z.number()).length(3)});
const CATALOGUE_ID = /^fama_trained_model_(\d+)$/;

export const importedTrainingApi = {
  /** Weights-only revision of a private composition; owner comes from the session, never the body. */
  async reviseTriadWeights(catalogueId: string, weights: number[], signal?: AbortSignal) {
    const match = CATALOGUE_ID.exec(catalogueId);
    if (!match) throw new ImportedTrainingError('Composición importada no disponible.');
    return revisedTriadSchema.parse(await request(`/api/training/models/${match[1]}/triad-weights`, {weights}, signal));
  },
  async catalog(signal?: AbortSignal) {
    const data = await request('/api/training/datasets?include_imported=true', undefined, signal);
    const envelope = z.object({datasets: z.array(z.unknown())}).parse(data);
    return envelope.datasets.filter((row): row is Record<string, unknown> =>
      typeof row === 'object' && row !== null && 'source_type' in row && row.source_type === 'imported')
      .map(row => importedDatasetSchema.parse(row));
  },
  async snapshot(dataset_id: string, signal?: AbortSignal) {
    return snapshotSchema.parse(await request('/api/training/imported/snapshots', {dataset_id, reuse_current: true}, signal));
  },
  async members(snapshot: string, signal?: AbortSignal) {
    return membersSchema.parse(await request(`/api/training/imported/snapshots/${encodeURIComponent(snapshot)}/members`, undefined, signal));
  },
  async prepare(snapshot: string, body: {mapping: unknown[]; provenance: Record<string, unknown>; seed: number; profile: Record<string, unknown>}, signal?: AbortSignal) {
    return preparedResourceSchema.parse(await request(`/api/training/imported/snapshots/${encodeURIComponent(snapshot)}/preparations`, body, signal));
  },
  async preparation(snapshot: string, version: string, signal?: AbortSignal) {
    return preparedResourceSchema.parse(await request(`/api/training/imported/snapshots/${encodeURIComponent(snapshot)}/preparations/${encodeURIComponent(version)}`, undefined, signal));
  },
};

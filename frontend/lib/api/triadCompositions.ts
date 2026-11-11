import { API_BASE_URL, apiFetch } from '@/lib/api';

export interface TriadComposition {
  id: number;
  model_id: string;
  version: number;
  latest: boolean;
  active: boolean;
  components: Array<{ id_modelo: number; catalogue_id: string; weight: number }>;
}

const TRIAD_KEY = /^fama_triad_([1-9][0-9]*)$/;

/** Composition id of an exact `fama_triad_<id>` catalogue key, otherwise null. */
export function triadCompositionId(modelId: string): number | null {
  const match = TRIAD_KEY.exec(modelId);
  return match ? Number(match[1]) : null;
}

function valid(data: unknown): data is TriadComposition {
  const c = data as TriadComposition;
  return !!c && Number.isSafeInteger(c.id) && typeof c.model_id === 'string' && Number.isSafeInteger(c.version)
    && typeof c.latest === 'boolean' && Array.isArray(c.components) && c.components.length === 3
    && c.components.every(x => x && typeof x.catalogue_id === 'string' && typeof x.weight === 'number' && Number.isFinite(x.weight));
}

async function read(response: Response, failure: string): Promise<TriadComposition> {
  if (!response.ok) {
    let detail = '';
    try { const body = await response.json(); if (typeof body?.detail === 'string') detail = body.detail; } catch { /* untrusted body */ }
    throw new Error(detail || `${failure} (HTTP ${response.status}).`);
  }
  const data = await response.json();
  if (!valid(data)) throw new Error('El servidor devolvió una tríada inválida.');
  return data;
}

export async function getTriadComposition(id: number, signal?: AbortSignal): Promise<TriadComposition> {
  return read(await apiFetch(`${API_BASE_URL}/api/triad-compositions/${id}`, { signal }), 'No se pudo cargar la tríada');
}

export async function reviseTriadWeights(id: number, weights: number[]): Promise<TriadComposition> {
  return read(await apiFetch(`${API_BASE_URL}/api/triad-compositions/${id}/weights`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ weights }),
  }), 'No se pudo revisar los pesos');
}

import { API_BASE_URL, apiSessionRevision, notifyUnauthorized } from '@/lib/api';

export interface PredictionHistoryRecord {
  id: number;
  filename: string;
  timestamp: string;
  clase: string;
  confianza: number;
  modelo_id: string;
}
export interface PredictionHistoryPage {
  items: PredictionHistoryRecord[];
  next_cursor: number | null;
}

export async function getPredictionHistory(modelId: string, signal: AbortSignal,
  cursor: number | null = null): Promise<PredictionHistoryPage> {
  const revision = apiSessionRevision();
  const query = new URLSearchParams({ model_id: modelId, limit: '20' });
  if (cursor !== null) query.set('cursor', String(cursor));
  const response = await fetch(`${API_BASE_URL}/api/inference/history?${query}`, {
    credentials: 'same-origin', cache: 'no-store', signal,
  });
  if (response.status === 401 && !signal.aborted) notifyUnauthorized(revision);
  if (!response.ok) throw new Error('No se pudo cargar el historial de este modelo.');
  const data = await response.json();
  const validCursor = data?.next_cursor === null ||
    (Number.isSafeInteger(data?.next_cursor) && data.next_cursor > 0);
  if (!Array.isArray(data?.items) || data.items.length > 20 || !validCursor ||
    !data.items.every((item: PredictionHistoryRecord) =>
      item && Number.isSafeInteger(item.id) && item.id > 0 &&
      typeof item.filename === 'string' && typeof item.clase === 'string' &&
      typeof item.timestamp === 'string' && Number.isFinite(Date.parse(item.timestamp)) &&
      typeof item.confianza === 'number' && Number.isFinite(item.confianza) &&
      item.confianza >= 0 && item.confianza <= 1 && item.modelo_id === modelId)) {
    throw new Error('El servidor devolvió un historial inválido.');
  }
  return data as PredictionHistoryPage;
}

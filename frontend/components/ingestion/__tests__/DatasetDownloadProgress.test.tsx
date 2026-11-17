import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import IngestionView from '@/components/views/IngestionView';

vi.mock('@/lib/api/feedbackApi', () => ({
  getPendingFeedback: vi.fn(async () => []), getFeedbackSync: vi.fn(async () => []),
  approveFeedback: vi.fn(), rejectFeedback: vi.fn(), getFeedbackStats: vi.fn(), sendFeedback: vi.fn(),
}));

const dataset = { id: 'AvesChilenas', name: 'AvesChilenas', file_count: 1220, classes: ['Chucao'], total_size_bytes: 5_900_000_000,
  last_modified: null, local_file_count: 0, is_synced: false, source: 'gcs', gcs_available: true, gcs_file_count: 1220 };
const base = { operation_id: 'op1', datasets: ['AvesChilenas'], current_dataset: 'AvesChilenas', downloaded: 0, skipped: 0,
  failed: 0, processed: 0, total: 1220, error: null, result: null };
const running = (processed: number) => ({ ...base, state: 'running', downloaded: processed, processed });
const finished = (state: string, extra = {}) => ({ ...base, state, current_dataset: null, downloaded: 1220, processed: 1220,
  result: { status: state, total_downloaded: 1220, total_skipped: 0, total_failed: 0, total_preprocessed: 0,
    results: [{ dataset: 'AvesChilenas', downloaded: 1220, skipped: 0, failed: 0, preprocessed: 0, db_persisted: true }] }, ...extra });

type Reply = { status?: number; body?: unknown; fail?: boolean };
let replies: { start: Reply; active: Reply; poll: Reply[] };
let calls: string[];
let datasetsFetches: number;

beforeEach(() => {
  vi.useFakeTimers();
  calls = []; datasetsFetches = 0;
  replies = { start: { status: 202, body: running(0) }, active: { body: { operations: [] } }, poll: [] };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    calls.push(`${init?.method ?? 'GET'} ${path}`);
    const answer = (reply: Reply) => {
      if (reply.fail) throw new TypeError('network down');
      const status = reply.status ?? 200;
      return { ok: status < 400, status, json: async () => reply.body } as Response;
    };
    if (path === '/api/ingestion/sync/start') return answer(replies.start);
    if (path === '/api/ingestion/sync/active') return answer(replies.active);
    if (path.startsWith('/api/ingestion/sync/operations/')) return answer(replies.poll.length > 1 ? replies.poll.shift()! : replies.poll[0]);
    if (path === '/api/ingestion/datasets') { datasetsFetches += 1; return answer({ body: { datasets: [dataset] } }); }
    if (path === '/api/ingestion/imports/access') return answer({ body: { development_mode: true } });
    return answer({ body: { connected: true, bucket: 'b', total_objects: 1, total_bytes: 1 } });
  }));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

const tick = (ms = 2000) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const refresh = () => screen.getByRole('button', { name: 'Actualizar' });
async function open() { await act(async () => { render(<IngestionView />); }); await tick(0); }
async function startDownload() {
  fireEvent.click(screen.getAllByRole('checkbox')[0]);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Descargar desde GCS' })); });
  await act(async () => { fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Descargar' })); });
}

describe('background GCS to local download in the ingestion view', () => {
  it('shows downloaded / total audios while the server reports progress and keeps Actualizar disabled', async () => {
    replies.poll = [{ body: running(340) }, { body: running(600) }];
    await open();
    await startDownload();
    await tick();
    expect(screen.getByText(/Descargando 340 \/ 1220 audios/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(true);
    await tick();
    expect(screen.getByText(/Descargando 600 \/ 1220 audios/)).toBeDefined();
    expect(calls).toContain('POST /api/ingestion/sync/start');
  });

  it('shows the end notice, releases Actualizar and refreshes the counts when the operation ends', async () => {
    replies.poll = [{ body: running(340) }, { body: finished('completed') }];
    await open();
    const before = datasetsFetches;
    await startDownload();
    await tick(); await tick();
    expect(screen.getByText('Descarga completada · GCS → Local: AvesChilenas. 1220 descargados, 0 omitidos, 0 errores. Consulta el detalle en la consola.')).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
    expect(datasetsFetches).toBeGreaterThan(before);
    const polls = calls.filter(call => call.includes('/sync/operations/')).length;
    await tick(6000);
    expect(calls.filter(call => call.includes('/sync/operations/')).length).toBe(polls);
  });

  it('reports a partial end with its new, skipped and failed counts', async () => {
    replies.poll = [{ body: finished('partial', { result: { status: 'partial', total_downloaded: 1200, total_skipped: 5, total_failed: 15, total_preprocessed: 0,
      results: [{ dataset: 'AvesChilenas', downloaded: 1200, skipped: 5, failed: 15, preprocessed: 0, db_persisted: true }] } }) }];
    await open(); await startDownload(); await tick();
    expect(screen.getByText(/Descarga parcial · GCS → Local: AvesChilenas\. 1200 descargados, 5 omitidos, 15 errores\./)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });

  it('reports a failed operation with the server error and releases Actualizar', async () => {
    replies.poll = [{ body: { ...base, state: 'failed', error: 'El dataset no contiene audios descargables en el bucket actual.' } }];
    await open(); await startDownload(); await tick();
    expect(screen.getByText(/No se confirmó la descarga · GCS → Local: AvesChilenas\. El dataset no contiene audios descargables/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });

  it('keeps polling after a transient poll error instead of getting stuck', async () => {
    replies.poll = [{ fail: true }, { status: 500, body: {} }, { body: finished('completed') }];
    await open(); await startDownload();
    await tick(); await tick();
    expect(refresh().hasAttribute('disabled')).toBe(true);
    await tick();
    expect(screen.getByText(/^Descarga completada · GCS → Local/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });

  it('releases the view when the server no longer knows the operation', async () => {
    replies.poll = [{ status: 404, body: {} }];
    await open(); await startDownload(); await tick();
    expect(screen.getByText(/No se confirmó la descarga · GCS → Local: AvesChilenas\./)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });

  it('gives up after repeated poll failures and releases Actualizar', async () => {
    replies.poll = [{ fail: true }];
    await open(); await startDownload();
    await tick(2000 * 31);
    expect(screen.getByText(/No se confirmó la descarga · GCS → Local: AvesChilenas\./)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });

  it('re-attaches to a running download when the view mounts', async () => {
    replies.active = { body: { operations: [running(120)] } };
    replies.poll = [{ body: running(300) }, { body: finished('completed') }];
    await open();
    expect(screen.getByText(/Descargando 120 \/ 1220 audios/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(true);
    await tick();
    expect(screen.getByText(/Descargando 300 \/ 1220 audios/)).toBeDefined();
    await tick();
    expect(screen.getByText(/^Descarga completada · GCS → Local/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });

  it('attaches to the running operation when the server rejects a second start for the same dataset', async () => {
    replies.start = { status: 409, body: { detail: { message: 'Ya hay una descarga en curso para este dataset.', operation_id: 'op1' } } };
    replies.poll = [{ body: running(700) }];
    await open(); await startDownload(); await tick();
    expect(screen.getByText(/Descargando 700 \/ 1220 audios/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(true);
  });

  it('preserves the HTTP error text when the download cannot start', async () => {
    replies.start = { status: 503, body: {} };
    await open(); await startDownload();
    expect(screen.getByText(/No se confirmó la descarga · GCS → Local: AvesChilenas\. Error en el servidor: HTTP 503/)).toBeDefined();
    expect(refresh().hasAttribute('disabled')).toBe(false);
  });
});

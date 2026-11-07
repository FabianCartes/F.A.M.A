import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import IngestionView from '../IngestionView';
import DatasetImportPanel from '@/components/ingestion/DatasetImportPanel';

const originalFetch = global.fetch;
afterEach(() => { cleanup(); global.fetch = originalFetch; vi.restoreAllMocks(); });
it('refreshes without transfer and downloads only confirmed selections without preprocessing', async () => {
  const requests: string[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (init?.method === 'POST') requests.push(String(init.body));
    const body = path.endsWith('/access') ? { development_mode: true }
      : path.endsWith('/imports/datasets') ? { datasets: [], next_cursor: null, total: 0, snapshot: 'empty' }
      : path.endsWith('/datasets') ? { datasets: ['Aves', 'Motor'].map(id => ({ id, name: id, file_count: 2, local_file_count: 0, total_size_bytes: 20, is_synced: false })) }
      : path.endsWith('/status') ? { connected: true, bucket: 'test', total_objects: 4, total_bytes: 40 }
      : { status: 'completed', total_downloaded: 2, total_skipped: 0, total_failed: 0, results: [] };
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  render(<IngestionView />);
  const download = await screen.findByRole('button', { name: 'Descargar seleccionados' });
  await screen.findByText('Aves');
  expect((download as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByLabelText(/Preprocesar/)).toBeNull();
  expect(screen.getByRole('region', { name: 'Importaciones privadas · Local → GCS' })).toBeDefined();
  expect(screen.getByRole('region', { name: 'Catálogo compartido · GCS → Local' })).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar catálogo' }));
  await waitFor(() => expect((screen.getByRole('button', { name: 'Actualizar catálogo' }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar estados' }));
  const all = screen.getByRole('checkbox', { name: 'Seleccionar todos los datasets compartidos' });
  fireEvent.click(all);
  expect(screen.getByText('GCS → Local: Aves, Motor')).toBeDefined();
  fireEvent.click(all);
  expect((download as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(within(screen.getByText('Aves').closest('tr')!).getByRole('checkbox'));
  expect(requests).toEqual([]);
  fireEvent.click(download);
  expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('Aves'));
  expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('Tamaño estimado: 20 B'));
  expect(requests).toEqual([]);
  confirm.mockReturnValue(true);
  fireEvent.click(download);
  await waitFor(() => expect(requests).toEqual([JSON.stringify({ datasets: ['Aves'], preprocess: false })]));
  await screen.findByText(/Descarga completada · GCS → Local: Aves/);
});

it('uploads only the recovered import after named confirmation and reports admission, not completion', async () => {
  const base = '/api/ingestion/imports';
  const source = { id: 'private-import', name: 'Aves privadas', status: 'imported', sync_status: 'pending', dataset_id: 'owned-dataset', added_count: 2,
    preview_token: null, error: null, preview: { root: '', file_count: 2, class_count: 1, error_count: 0, warning_count: 0, total_size_bytes: 20, synced_count: 0 } };
  const execution = { id: 'upload', import_id: source.id, kind: 'sync', status: 'queued', stage: 'queued', progress: 0, result: {}, error: null, status_url: `${base}/${source.id}/jobs/upload` };
  const posts: string[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (init?.method === 'POST') { posts.push(path); return Response.json(execution, { status: 202 }); }
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/limits')) return Response.json({ received_bytes: 1024, expanded_bytes: 4096, entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path === base) return Response.json({ imports: [source], total: 1, next_cursor: null, snapshot: 'history' });
    if (path === execution.status_url) return Response.json(execution);
    throw new Error(`Unexpected ${path}`);
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  render(<DatasetImportPanel datasetNames={{ 'owned-dataset': 'Aves privadas' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Importar dataset' }));
  const start = within(screen.getByRole('dialog')).getByRole('button', { name: 'Importar dataset' });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole('button', { name: /private-import —/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar importaciones' }));
  await waitFor(() => expect((screen.getByRole('button', { name: 'Actualizar importaciones' }) as HTMLButtonElement).disabled).toBe(false));
  expect(posts).toEqual([]);
  const upload = screen.getByRole('button', { name: 'Subir este dataset a GCS' });
  fireEvent.click(upload);
  expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('owned-dataset'));
  expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('Aves privadas'));
  expect(posts).toEqual([]);
  confirm.mockReturnValue(true);
  fireEvent.click(upload);
  await screen.findByText(/Trabajo admitido; pendiente de ejecución/);
  expect(posts).toEqual([`${base}/private-import/sync`]);
  expect(screen.queryByText(/Trabajo completado/)).toBeNull();
});

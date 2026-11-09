import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetImportPanel from '@/components/ingestion/DatasetImportPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each([[32044, '0,03 MB'], [1000000000, '1000 MB'], [1000000001, '1 GB']])('summarizes completed imports without technical IDs or redundant actions (%s bytes)', async (bytes, expected) => {
  const job = { id: 'private-import-id', archive_name: 'birds.zip', status: 'imported', sync_status: 'synced',
    dataset_id: 'private-dataset-id', added_count: 1, preview_token: 'review', error: null,
    execution: { id: 'execution-id', import_id: 'private-import-id', kind: 'confirm', status: 'succeeded',
      stage: 'succeeded', progress: 100, result: {}, error: null, status_url: '/unused' },
    preview: { file_count: 1, class_count: 1, error_count: 0, warning_count: 1, total_size_bytes: bytes, synced_count: 1 } };
  const requests: { path: string; method: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, 'http://localhost').pathname;
    requests.push({ path, method: options?.method || 'GET' });
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/limits')) return Response.json({ received_bytes: 2000000000, expanded_bytes: 2000000000,
      entries: 100, depth: 12, path_bytes: 240, audio_bytes: 100000000, audio_seconds: 600,
      validation_seconds: 900, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path.endsWith('/classes')) return Response.json({ classes: ['synthetic_class'], total: 1, next_cursor: null, snapshot: 'review' });
    return Response.json({ imports: [job], total: 1, next_cursor: null, snapshot: 'history' });
  }));
  render(<DatasetImportPanel datasetNames={{ 'private-dataset-id': 'Aves de prueba' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Importar dataset' }));
  await screen.findByRole('button', { name: 'Descargar ZIP de ejemplo sintético' });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Importar dataset' }));
  fireEvent.click(screen.getByRole('button', { name: /birds.zip —/ }));
  const summary = await screen.findByRole('region', { name: 'Resumen de importación' });
  expect(within(summary).getByText('Aves de prueba')).toBeDefined();
  expect(within(summary).getByText(`Tamaño: ${expected}`)).toBeDefined();
  expect(await within(summary).findByText('synthetic_class')).toBeDefined();
  expect(summary.textContent).toContain('Clases: 1');
  expect(summary.textContent).not.toMatch(/private-import-id|private-dataset-id|succeeded|100%|Bytes únicos/);
  expect(screen.queryByRole('button', { name: 'Subir este dataset a GCS' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Consultar archivos locales' })).toBeNull();
  expect(screen.queryByRole('button', { name: /página de/ })).toBeNull();
  expect(requests.every(request => request.method === 'GET')).toBe(true);
  expect(requests.some(request => /\/(files|issues)$/.test(request.path))).toBe(false);
});

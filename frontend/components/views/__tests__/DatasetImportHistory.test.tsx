import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetImportPanel from '@/components/ingestion/DatasetImportPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('lists only ten recent ZIP names and local dates, retaining opaque recovery IDs internally', async () => {
  const rows = Array.from({ length: 12 }, (_, index) => ({ id: `opaque-uuid-${index}`,
    archive_name: `grabacion_${index}.zip`, created_at: 1700000000 - index,
    status: 'receiving', sync_status: 'pending', dataset_id: null, added_count: 0,
    preview_token: null, error: null, preview: { file_count: 0, class_count: 0,
      error_count: 0, warning_count: 0, total_size_bytes: 0, synced_count: 0 } }));
  const fetcher = vi.fn(async (input: string) => {
    const url = new URL(input, 'http://localhost');
    if (url.pathname.endsWith('/access')) return Response.json({ development_mode: true });
    if (url.pathname.endsWith('/limits')) return Response.json({ received_bytes: 1000, expanded_bytes: 1000,
      entries: 100, depth: 12, path_bytes: 240, audio_bytes: 1000, audio_seconds: 600,
      validation_seconds: 900, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    return Response.json({ imports: rows, next_cursor: 'must-not-be-used', total: 12, snapshot: 'history' });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<DatasetImportPanel sessionToken="owner" />);
  fireEvent.click(screen.getByRole('button', { name: 'Importar dataset' }));
  await screen.findByRole('button', { name: 'Descargar ZIP de ejemplo sintético' });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Importar dataset' }));
  fireEvent.click(screen.getByText('Recuperar importaciones anteriores'));
  const list = screen.getByRole('list', { name: 'Últimas 10 importaciones' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(10);
  const date = new Date(1700000000 * 1000).toLocaleString('es-CL', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  expect(within(list).getByRole('button', { name: `grabacion_0.zip — ${date} — recibiendo` })).toBeDefined();
  expect(list.textContent).not.toContain('opaque-uuid');
  expect(list.textContent).not.toContain('grabacion_10.zip');
  expect(screen.queryByRole('button', { name: /página de importaciones/ })).toBeNull();
  expect(fetcher.mock.calls.some(([url]) => new URL(url, 'http://localhost').searchParams.get('latest') === 'true')).toBe(true);
  fireEvent.click(within(list).getAllByRole('button')[0]);
  expect(screen.getByText('Importación opaque-uuid-0: recibiendo')).toBeDefined();
});

import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import IngestionView from '../IngestionView';

const originalFetch = global.fetch;
afterEach(() => { cleanup(); global.fetch = originalFetch; vi.restoreAllMocks(); });

it.each([
  { count: 2, available: true, source: 'gcs', cloud: '2 audios', state: 'Local y GCS' },
  { count: 3, available: true, source: 'gcs', cloud: '3 audios', state: 'Local y GCS' },
  { count: 0, available: true, source: 'local', cloud: '0 audios', state: 'Solo local' },
  { count: null, available: false, source: 'local', cloud: 'Sin consultar', state: 'GCS sin consultar' },
])('reports local and remote counts independently for $count remote files', async ({ count, available, source, cloud, state }) => {
  const requests: string[] = [];
  global.fetch = vi.fn(async input => {
    const path = new URL(String(input), 'http://localhost').pathname;
    requests.push(path);
    if (path.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'sample', name: 'Muestra',
      file_count: 2, local_file_count: 2, local_size_bytes: 20, total_size_bytes: 20, is_synced: count === 2,
      gcs_file_count: count, gcs_available: available, source }] });
    if (path.endsWith('/status')) return Response.json({ connected: available, bucket: 'test', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  });
  render(<IngestionView />);
  const table = await screen.findByRole('table');
  const row = (await within(table).findByText('Muestra')).closest('tr')!;
  const cells = within(row).getAllByRole('cell');
  expect(cells[2].textContent).toContain('2 audios');
  expect(cells[3].textContent).toContain(cloud);
  expect(within(row).getByText(state)).toBeDefined();
  if (count && count > 0) expect(within(row).getByText('Contenido sin comparar')).toBeDefined();
  expect(screen.getAllByRole('table')).toHaveLength(1);
  expect(requests.some(path => path.includes('/imports/datasets'))).toBe(false);
  expect(screen.queryByRole('button', { name: 'Subir selección a GCS' })).toBeNull();
});

it('refreshes without transfer and downloads only confirmed selections without preprocessing', async () => {
  const posts: string[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (init?.method === 'POST') posts.push(String(init.body));
    const body = path.endsWith('/datasets') ? { datasets: ['Aves', 'Motor'].map(id => ({ id, name: id,
      file_count: 2, local_file_count: 0, total_size_bytes: 20, is_synced: false, source: 'gcs', gcs_available: true })) }
      : path.endsWith('/status') ? { connected: true, bucket: 'test', total_objects: 4, total_bytes: 40 }
      : { status: 'completed', total_downloaded: 2, total_skipped: 0, total_failed: 0, results: [] };
    return Response.json(body);
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  render(<IngestionView />);
  await within(await screen.findByRole('table')).findByText('Aves');
  const download = screen.getByRole('button', { name: 'Descargar desde GCS' }) as HTMLButtonElement;
  expect(download.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }));
  await waitFor(() => expect((screen.getByRole('button', { name: 'Actualizar' }) as HTMLButtonElement).disabled).toBe(false));
  expect(posts).toEqual([]);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar Aves' }));
  fireEvent.click(download);
  expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('Aves'));
  expect(posts).toEqual([]);
  confirm.mockReturnValue(true);
  fireEvent.click(download);
  await waitFor(() => expect(posts).toEqual([JSON.stringify({ datasets: ['Aves'], preprocess: false })]));
  await screen.findByText(/Descarga completada · GCS → Local: Aves/);
});

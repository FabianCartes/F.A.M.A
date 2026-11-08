import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import IngestionView from '../IngestionView';
import DatasetImportPanel from '@/components/ingestion/DatasetImportPanel';

it.each([
  { synced: 1, files: 1, label: 'Subida a GCS registrada (1/1)' },
  { synced: 0, files: 1, label: 'Sin subida a GCS registrada' },
  { synced: 1, files: 3, label: 'Subida a GCS registrada (1/3)' },
])('shows historical private GCS availability: $label', async ({ synced, files, label }) => {
  global.fetch = vi.fn(async input => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/imports/datasets')) return Response.json({ datasets: [{ id: 'reported', name: 'GCS Sync Smoke a7c3e291', description: null, revision: 1, class_count: 1, file_count: files, total_size_bytes: 10, synced_file_count: synced }], next_cursor: null, total: 1, snapshot: 'catalog' });
    if (path.endsWith('/datasets')) return Response.json({ datasets: [] });
    if (path.endsWith('/status')) return Response.json({ connected: false, bucket: '', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  });
  render(<IngestionView />);
  const row = (await screen.findByText('GCS Sync Smoke a7c3e291')).closest('tr')!;
  const table = within(screen.getByRole('table', { name: 'Catálogo' }));
  const headers = table.getAllByRole('columnheader');
  const cells = within(row).getAllByRole('cell');
  expect(cells[headers.indexOf(table.getByRole('columnheader', { name: 'Acuses de subida' }))].textContent).toBe(String(synced));
  expect(cells[headers.indexOf(table.getByRole('columnheader', { name: 'Archivos Locales' }))].textContent).toBe(String(files));
  expect(within(row).queryByText('Importado ZIP')).toBeNull();
  expect(row.querySelector('svg[aria-hidden="true"][data-dataset-folder]')).not.toBeNull();
  expect(table.queryByRole('columnheader', { name: 'Estado' })).toBeNull();
  expect(within(row).getByText('Privado')).toBeDefined();
  expect(within(row).getByText('1 clase(s)')).toBeDefined();
  expect(within(row).getByText(`Copia local catalogada · ${label}`)).toBeDefined();
  expect(screen.getByText(/Acuses de subida: confirmaciones históricas, no una verificación actual del bucket/)).toBeDefined();
});

it.each([
  { metadata: { class_count: 4, classes: ['Zorzal', 'Chincol'] }, expected: '4 clase(s)' },
  { metadata: { classes: ['Zorzal', 'Chincol'] }, expected: '2 clase(s)' },
  { metadata: { class_count: 0, classes: [] }, expected: '0 clase(s)' },
  { metadata: { classes: [] }, expected: '0 clase(s)' },
  { metadata: {}, expected: 'Desconocido' },
  { metadata: { class_count: null, classes: null }, expected: 'Desconocido' },
  { metadata: { class_count: -1, classes: ['Zorzal', 'Chincol'] }, expected: '2 clase(s)' },
])('shows only the shared class total: $expected ($metadata)', async ({ metadata, expected }) => {
  global.fetch = vi.fn(async input => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/imports/datasets')) return Response.json({ datasets: [{ id: 'private', name: 'Privado de prueba', description: null, revision: 1, class_count: 3, file_count: 1, total_size_bytes: 10, synced_file_count: 0 }], next_cursor: null, total: 1, snapshot: 'catalog' });
    if (path.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'shared', name: 'Compartido de prueba', file_count: 2, local_file_count: 0, total_size_bytes: 20, is_synced: false, ...metadata }] });
    if (path.endsWith('/status')) return Response.json({ connected: false, bucket: '', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  });
  render(<IngestionView />);
  const row = (await screen.findByText('Compartido de prueba')).closest('tr')!;
  const table = within(screen.getByRole('table', { name: 'Catálogo compartido' }));
  const classIndex = table.getAllByRole('columnheader').indexOf(table.getByRole('columnheader', { name: 'Clases' }));
  const cell = within(row).getAllByRole('cell')[classIndex];
  expect(cell.textContent).toBe(expected);
  expect(cell.querySelector('span')).toBeNull();
  expect(within(row).queryByText(/Zorzal|Chincol|General|más/)).toBeNull();
  const privateRow = (await screen.findByText('Privado de prueba')).closest('tr')!;
  expect(within(privateRow).getByText('3 clase(s)')).toBeDefined();
});

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
  expect(screen.getByRole('region', { name: 'Catálogo' })).toBeDefined();
  expect(screen.getByRole('table', { name: 'Catálogo' })).toBeDefined();
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
  const source = { id: 'private-import', archive_name: 'private-import.zip', name: 'Aves privadas', status: 'imported', sync_status: 'pending', dataset_id: 'owned-dataset', added_count: 2,
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
  fireEvent.click(await screen.findByRole('button', { name: /private-import.zip —/ }));
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

it('uploads only selected private datasets using paginated history and monitors admission separately', async () => {
  const base = '/api/ingestion/imports';
  const datasets = ['Aves privadas', 'Motor privado'].map((name, index) => ({ id: `dataset-${index}`, name, description: null, revision: 2, class_count: 1, file_count: 2, total_size_bytes: 20, synced_file_count: 0 }));
  const source = (id: string, dataset_id: string) => ({ id, dataset_id, status: 'imported', sync_status: 'pending', added_count: 1, preview_token: null, error: null,
    preview: { file_count: 1, class_count: 1, error_count: 0, warning_count: 0, total_size_bytes: 10, synced_count: 0 } });
  const execution = { id: 'upload', import_id: 'aves-import', kind: 'sync', status: 'queued', stage: 'queued', progress: 0, result: {}, error: null, status_url: `${base}/aves-import/jobs/upload` };
  const posts: { path: string; body: unknown; authorization: string | null }[] = [];
  const historyQueries: string[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    if (init?.method === 'POST') {
      posts.push({ path: url.pathname, body: JSON.parse(String(init.body)), authorization: new Headers(init.headers).get('Authorization') });
      return Response.json(execution, { status: 202 });
    }
    if (url.pathname.endsWith('/access')) return Response.json({ development_mode: false });
    if (url.pathname === `${base}/datasets`) return Response.json({ datasets, next_cursor: null, total: 2, snapshot: 'catalog' });
    if (url.pathname === base) {
      historyQueries.push(url.search);
      return Response.json(url.search ? { imports: [source('aves-import', 'dataset-0'), source('aves-older', 'dataset-0')], total: 3, next_cursor: null, snapshot: 'history' }
        : { imports: [source('motor-import', 'dataset-1')], total: 3, next_cursor: 'next page', snapshot: 'history' });
    }
    if (url.pathname === execution.status_url) return Response.json(execution);
    if (url.pathname.endsWith('/status')) return Response.json({ connected: true, bucket: 'test', total_objects: 0, total_bytes: 0 });
    if (url.pathname.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'shared-aves', name: 'Aves privadas', file_count: 2, local_file_count: 0, total_size_bytes: 20, is_synced: false }] });
    return Response.json([]);
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const view = render(<IngestionView sessionToken="owner" />);
  await screen.findByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' });
  const catalog = screen.getByRole('table', { name: 'Catálogo' });
  expect(within(catalog).getByRole('columnheader', { name: 'Ámbito' })).toBeDefined();
  expect(within(catalog).getByRole('columnheader', { name: 'Disponibilidad' })).toBeDefined();
  const privateHeading = screen.getByRole('heading', { name: 'Catálogo datasets privados' });
  const publicHeading = screen.getByRole('heading', { name: 'Catálogo datasets públicos' });
  expect(privateHeading.className).toBe(publicHeading.className);
  expect(privateHeading.className).toContain('text-xl');
  const sharedHeading = screen.getByRole('heading', { name: 'Compartidos en GCS' });
  expect(screen.getByRole('button', { name: 'Subir selección a GCS' }).compareDocumentPosition(sharedHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(within(catalog).getByRole('columnheader', { name: 'Acuses de subida' })).toBeDefined();
  expect(within(catalog).queryByRole('columnheader', { name: 'Estado' })).toBeNull();
  const duplicates = within(screen.getByRole('region', { name: 'Catálogo' })).getAllByText('Aves privadas');
  expect(duplicates).toHaveLength(2);
  expect(within(duplicates[0].closest('tr')!).getByText('Privado')).toBeDefined();
  expect(within(duplicates[1].closest('tr')!).getByText('Compartido')).toBeDefined();
  const upload = screen.getByRole('button', { name: 'Subir selección a GCS' });
  expect((upload as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' }));
  expect(screen.getByText('Local → GCS: Aves privadas')).toBeDefined();
  fireEvent.click(upload);
  const dialog = screen.getByRole('dialog', { name: 'Confirmar subida privada a GCS' });
  expect(within(dialog).getByText('Aves privadas')).toBeDefined();
  expect(confirm).not.toHaveBeenCalled();
  expect(posts).toEqual([]);
  expect(historyQueries).toEqual([]);
  const cancel = within(dialog).getByRole('button', { name: 'Cancelar' });
  const accept = within(dialog).getByRole('button', { name: 'Confirmar subida' });
  expect(document.activeElement).toBe(cancel);
  fireEvent.keyDown(cancel, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(accept);
  fireEvent.keyDown(accept, { key: 'Tab' });
  expect(document.activeElement).toBe(cancel);
  fireEvent.click(cancel);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(upload);
  expect(posts).toEqual([]);
  fireEvent.click(upload);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(historyQueries).toEqual([]);
  fireEvent.click(upload);
  expect(dialog.getAttribute('aria-modal')).toBe('true');
  expect(view.container.hasAttribute('inert')).toBe(true);
  view.rerender(<IngestionView sessionToken="temporary-owner" />);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(view.container.hasAttribute('inert')).toBe(false);
  expect(historyQueries).toEqual([]);
  view.rerender(<IngestionView sessionToken="owner" />);
  await screen.findByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' }));
  fireEvent.click(screen.getByRole('button', { name: 'Subir selección a GCS' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar subida' }));
  await screen.findByText(/Aves privadas: Trabajo admitido; pendiente de ejecución/);
  expect(posts).toEqual([{ path: `${base}/aves-import/sync`, body: { request_key: expect.any(String) }, authorization: 'Bearer owner' }]);
  expect(historyQueries).toEqual(['', '?cursor=next%20page']);
  expect(screen.queryByText(/Subida completada/)).toBeNull();
  expect((screen.getByRole('button', { name: 'Subir selección a GCS' }) as HTMLButtonElement).disabled).toBe(true);
  view.rerender(<IngestionView sessionToken="other-owner" />);
  await waitFor(() => expect((screen.getByRole('button', { name: 'Subir selección a GCS' }) as HTMLButtonElement).disabled).toBe(true));
  expect(screen.queryByText('Local → GCS: Aves privadas')).toBeNull();
  expect(screen.queryByText(/Aves privadas: Trabajo admitido/)).toBeNull();
});

it.each(['succeeded', 'failed', 'missing-source'])('handles private upload result %s without claiming premature success', async result => {
  const base = '/api/ingestion/imports';
  const dataset = { id: 'private-dataset', name: 'Selección privada', description: null, revision: 1, class_count: 1, file_count: 1, total_size_bytes: 10, synced_file_count: 0 };
  const source = { id: 'source', dataset_id: dataset.id, status: 'imported', sync_status: 'pending', added_count: 1, preview_token: null, error: null,
    preview: { file_count: 1, class_count: 1, error_count: 0, warning_count: 0, total_size_bytes: 10, synced_count: 0 } };
  const execution = { id: 'execution', import_id: source.id, kind: 'sync', status: 'queued', stage: 'queued', progress: 0, result: {}, error: null, status_url: `${base}/source/jobs/execution` };
  const posts: string[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (init?.method === 'POST') { posts.push(path); return Response.json(execution, { status: 202 }); }
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path === `${base}/datasets`) return Response.json({ datasets: [dataset], total: 1, next_cursor: null, snapshot: 'catalog' });
    if (path === base) return Response.json({ imports: result === 'missing-source' ? [] : [source], total: result === 'missing-source' ? 0 : 1, next_cursor: null, snapshot: 'history' });
    if (path === execution.status_url) return Response.json({ ...execution, status: result, progress: result === 'succeeded' ? 100 : 0 });
    if (path.endsWith('/status')) return Response.json({ connected: true, bucket: 'test', total_objects: 0, total_bytes: 0 });
    if (path.endsWith('/datasets')) return Response.json({ datasets: [] });
    return Response.json([]);
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<IngestionView />);
  await screen.findByText(dataset.name);
  const all = screen.getByRole('checkbox', { name: 'Seleccionar todos los datasets privados' });
  fireEvent.click(all);
  expect(screen.getByText('1 dataset(s) privados seleccionados')).toBeDefined();
  // A catalog refresh invalidates selection even if dataset ids are unchanged.
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar estados' }));
  await screen.findByText(dataset.name);
  expect(screen.getByText('0 dataset(s) privados seleccionados')).toBeDefined();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todos los datasets privados' }));
  fireEvent.click(screen.getByRole('button', { name: 'Subir selección a GCS' }));
  // A catalog response while the dialog is open must invalidate its consent.
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar estados', hidden: true }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await screen.findByText(dataset.name);
  expect(posts).toEqual([]);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todos los datasets privados' }));
  fireEvent.click(screen.getByRole('button', { name: 'Subir selección a GCS' }));
  const confirmation = screen.getByRole('dialog');
  expect(within(confirmation).getByText('Tamaño estimado: 10 B')).toBeDefined();
  expect(within(confirmation).getByText(/Se conserva la copia local y no se publica/)).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar subida' }));
  if (result === 'missing-source') {
    await screen.findByText(/No hay una importación confirmada/);
    expect(posts).toEqual([]);
  } else {
    await screen.findByText(/Trabajo admitido; pendiente de ejecución/);
    expect(screen.queryByText(/Subida completada/)).toBeNull();
    await screen.findByText(result === 'succeeded' ? /Subida completada para la revisión sincronizada/ : /Subida fallida/, {}, { timeout: 3000 });
    expect(posts).toEqual([`${base}/source/sync`]);
    if (result === 'failed') expect(screen.queryByText(/Subida completada/)).toBeNull();
  }
});

it.each([
  { count: 2, available: true, source: 'gcs', label: 'GCS listado', presence: 'Archivos listados en GCS' },
  { count: 3, available: true, source: 'gcs', label: 'GCS listado', presence: 'Archivos listados en GCS' },
  { count: 0, available: true, source: 'local', label: 'Sin archivos en GCS', presence: 'Sin archivos en GCS' },
  { count: null, available: false, source: 'local', label: 'GCS desconocido', presence: 'GCS desconocido' },
])('reports last remote listing honestly for $count files', async ({ count, available, source, label, presence }) => {
  global.fetch = vi.fn(async input => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/imports/datasets')) return Response.json({ datasets: [], next_cursor: null, total: 0, snapshot: 'empty' });
    if (path.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'sample', name: 'Muestra', file_count: 2, local_file_count: 2, total_size_bytes: 20, is_synced: count === 2, gcs_file_count: count, gcs_available: available, source }] });
    if (path.endsWith('/status')) return Response.json({ connected: available, bucket: 'test', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  });
  render(<IngestionView />);
  const row = (await screen.findByText('Muestra')).closest('tr')!;
  expect(within(row).getByText(`Local · ${label}`)).toBeDefined();
  expect(within(row).getAllByRole('cell')[1].textContent).toBe('Muestra');
  expect(within(row).getAllByRole('cell')[1].textContent).not.toContain(presence);
  expect(row.querySelector('svg[aria-hidden="true"][data-dataset-folder]')).not.toBeNull();
  expect(within(row).queryByText(/Bioacústica|Industrial/)).toBeNull();
  expect(within(screen.getByRole('table', { name: 'Catálogo compartido' })).queryByRole('columnheader', { name: 'Estado' })).toBeNull();
  const remote = within(row).getByTitle('Conteo del listado remoto; desconocido si no fue posible consultar GCS.');
  expect(remote.textContent).toBe(count === null ? 'Desconocido' : String(count));
  expect(within(row).queryByText('Cloud GCS')).toBeNull();
  expect(within(row).queryByText('Sincronizado')).toBeNull();
  expect(within(row).getAllByRole('cell')[6].textContent).toBe('2');
});
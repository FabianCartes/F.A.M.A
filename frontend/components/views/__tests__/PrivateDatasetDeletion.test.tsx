import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import IngestionView from '../IngestionView';

const originalFetch = global.fetch;
afterEach(() => { cleanup(); global.fetch = originalFetch; vi.restoreAllMocks(); });
const base = '/api/ingestion/imports';
const owned = ['Aves privadas', 'Motor privado'].map((name, index) => ({
  id: `opaque-${index}`, name, description: null, revision: 7, class_count: 1,
  file_count: 1, total_size_bytes: 20, synced_file_count: 1,
}));

function mockHttp(options: { remove?: () => Promise<Response>; reload?: () => Response } = {}) {
  const deletes: RequestInit[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (init?.method === 'DELETE') { deletes.push(init); return options.remove ? options.remove() : new Response(null, { status: 204 }); }
    if (path.endsWith('/access')) return Response.json({ development_mode: false });
    if (path.endsWith('/files')) return Response.json({ files: [{ id: 'audio', relative_path: 'bird/call.wav', original_path: 'bird/call.wav', class_name: 'bird', sha256: 'hash', size_bytes: 20, duplicate: false, is_feedback: false }], classes: ['bird'], has_feedback: false, next_cursor: null, total: 1, snapshot: 'files' });
    if (path === `${base}/datasets`) return deletes.length && options.reload ? options.reload() : Response.json({ datasets: deletes.length ? owned.slice(1) : owned, next_cursor: null, total: deletes.length ? 1 : 2, snapshot: 'catalog' });
    if (path.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'shared', name: 'Compartido', file_count: 1, local_file_count: 0, total_size_bytes: 20, is_synced: false }] });
    if (path.endsWith('/status')) return Response.json({ connected: false, bucket: '', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  });
  return deletes;
}

it('offers deletion only on private rows and cancellation sends no DELETE', async () => {
  const deletes = mockHttp();
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  render(<IngestionView sessionToken="owner" />);
  const remove = await screen.findByRole('button', { name: 'Eliminar Aves privadas' });
  expect(within(screen.getByRole('table', { name: 'Catálogo compartido' })).queryByRole('button', { name: /Eliminar/ })).toBeNull();
  expect(screen.getAllByRole('button', { name: /^Eliminar / })).toHaveLength(2);
  fireEvent.click(remove);
  const dialog = screen.getByRole('dialog', { name: 'Confirmar archivado de dataset' });
  expect(dialog.textContent).toContain('Aves privadas');
  expect(dialog.textContent).toContain('quedará archivado');
  expect(dialog.textContent).toContain('Sus archivos locales');
  expect(dialog.textContent).toContain('no libera espacio');
  expect(dialog.textContent).not.toContain('opaque-0');
  expect(confirm).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Cancelar' }));
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(remove);
  expect(remove.closest('td')).not.toBe(within(remove.closest('tr')!).getByRole('button', { name: 'Consultar audios' }).closest('td'));
  expect(within(screen.getByRole('table', { name: 'Catálogo' })).getByRole('columnheader', { name: 'Eliminar' })).toBeDefined();
  fireEvent.click(remove);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar' }));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(deletes).toEqual([]);
});

it('blocks duplicate actions while DELETE is pending, then refreshes and preserves other selections', async () => {
  let finish!: (response: Response) => void;
  const deletes = mockHttp({ remove: () => new Promise(resolve => { finish = resolve; }) });
  render(<IngestionView sessionToken="owner" />);
  const remove = await screen.findByRole('button', { name: 'Eliminar Aves privadas' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todos los datasets privados' }));
  const shared = within(screen.getByRole('table', { name: 'Catálogo compartido' })).getByRole('checkbox');
  fireEvent.click(shared);
  fireEvent.click(remove);
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar archivado' }));
  fireEvent.click(remove);
  expect(deletes).toHaveLength(1);
  expect((remove as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: 'Subir selección a GCS' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: 'Eliminar Motor privado' }) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => { finish(new Response(null, { status: 204 })); });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Eliminar Aves privadas' })).toBeNull());
  expect((screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Motor privado' }) as HTMLInputElement).checked).toBe(true);
  expect((shared as HTMLInputElement).checked).toBe(true);
  expect(screen.getByText('Local → GCS: Motor privado')).toBeDefined();
  expect(screen.queryByText('Local → GCS: Aves privadas, Motor privado')).toBeNull();
  expect(JSON.parse(String(deletes[0].body))).toEqual({ revision: 7 });
  expect(new Headers(deletes[0].headers).get('Authorization')).toBe('Bearer owner');
  const catalogReads = vi.mocked(global.fetch).mock.calls.filter(([url, init]) => String(url).endsWith(`${base}/datasets`) && !init?.method);
  expect(catalogReads).toHaveLength(2);
});

it.each([404, 409, 503])('keeps the row, selection and audio preview after server rejection %s', async status => {
  const deletes = mockHttp({ remove: async () => Response.json({ detail: 'No se puede eliminar en este estado.' }, { status }) });
  render(<IngestionView sessionToken="owner" />);
  const remove = await screen.findByRole('button', { name: 'Eliminar Aves privadas' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' }));
  fireEvent.click(within(remove.closest('tr')!).getByRole('button', { name: 'Consultar audios' }));
  await screen.findByRole('button', { name: 'Descargar call.wav' });
  fireEvent.click(remove);
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar archivado' }));
  await screen.findByText(`${status}: No se puede eliminar en este estado.`);
  expect(deletes).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Eliminar Aves privadas' })).toBeDefined();
  expect((screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' }) as HTMLInputElement).checked).toBe(true);
  expect(await screen.findByRole('button', { name: 'Descargar call.wav' })).toBeDefined();
  expect(screen.queryByText(/«Aves privadas» archivado/)).toBeNull();
});

it.each(['Aves privadas', 'Motor privado'])('clears only the deleted audio preview, preserving preview for %s when unrelated', async name => {
  mockHttp();
  render(<IngestionView sessionToken="owner" />);
  const previewRow = (await screen.findByRole('button', { name: `Eliminar ${name}` })).closest('tr')!;
  fireEvent.click(within(previewRow).getByRole('button', { name: 'Consultar audios' }));
  await screen.findByRole('button', { name: 'Descargar call.wav' });
  fireEvent.click(screen.getByRole('button', { name: 'Eliminar Aves privadas' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar archivado' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Eliminar Aves privadas' })).toBeNull());
  if (name === 'Aves privadas') {
    expect(screen.queryByRole('button', { name: 'Descargar call.wav' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cerrar consulta de audios' })).toBeNull();
  } else {
    expect(await screen.findByRole('button', { name: 'Descargar call.wav' })).toBeDefined();
  }
});

it('reports refresh failure honestly after confirmed deletion without restoring stale actions', async () => {
  mockHttp({ reload: () => Response.json({ detail: 'Catálogo temporalmente inaccesible.' }, { status: 503 }) });
  render(<IngestionView sessionToken="owner" />);
  const remove = await screen.findByRole('button', { name: 'Eliminar Aves privadas' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar todos los datasets privados' }));
  fireEvent.click(remove);
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar archivado' }));
  await screen.findByText(/Catálogo privado no disponible: 503: Catálogo temporalmente inaccesible/);
  expect(screen.getByText(/«Aves privadas» archivado/)).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Eliminar Aves privadas' })).toBeNull();
  expect((screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Motor privado' }) as HTMLInputElement).checked).toBe(true);
});

it('disables deletion during a known private upload without stopping its admitted execution', async () => {
  const deletes = mockHttp();
  const fallback = global.fetch;
  const execution = { id: 'upload', import_id: 'source', kind: 'sync', status: 'queued', stage: 'queued', progress: 0, result: {}, error: null, status_url: `${base}/source/jobs/upload` };
  global.fetch = vi.fn(async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (path === base) return Response.json({ imports: [{ id: 'source', dataset_id: 'opaque-0', status: 'imported', sync_status: 'pending', added_count: 1, preview_token: null, error: null, preview: { file_count: 1, class_count: 1, error_count: 0, warning_count: 0, total_size_bytes: 20, synced_count: 0 } }], next_cursor: null, total: 1, snapshot: 'history' });
    if (path.endsWith('/sync') || path === execution.status_url) return Response.json(execution);
    return fallback(input, init);
  });
  render(<IngestionView sessionToken="owner" />);
  const remove = await screen.findByRole('button', { name: 'Eliminar Aves privadas' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar dataset privado Aves privadas' }));
  fireEvent.click(screen.getByRole('button', { name: 'Subir selección a GCS' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar subida' }));
  await screen.findByText(/Aves privadas: Trabajo admitido; pendiente de ejecución/);
  expect((remove as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(remove);
  expect(deletes).toEqual([]);
  expect(screen.getByText(/Aves privadas: Trabajo admitido; pendiente de ejecución/)).toBeDefined();
});

it('ignores a late deletion response after the owner changes', async () => {
  let finish!: (response: Response) => void;
  mockHttp({ remove: () => new Promise(resolve => { finish = resolve; }) });
  const view = render(<IngestionView sessionToken="first-owner" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Eliminar Aves privadas' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar archivado' }));
  view.rerender(<IngestionView sessionToken="second-owner" />);
  await screen.findByRole('button', { name: 'Eliminar Motor privado' });
  await act(async () => { finish(new Response(null, { status: 204 })); });
  expect(screen.queryByText(/«Aves privadas» archivado/)).toBeNull();
  expect((screen.getByRole('button', { name: 'Eliminar Motor privado' }) as HTMLButtonElement).disabled).toBe(false);
});

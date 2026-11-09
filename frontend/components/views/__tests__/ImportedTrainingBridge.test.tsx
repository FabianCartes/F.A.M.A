import { File } from 'node:buffer';
import { webcrypto } from 'node:crypto';
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react';
import { it, expect, vi, afterEach } from 'vitest';
import Home from '@/app/page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows the confirmed owner import after navigating to training with blocking reasons and no automatic preparation', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const base = '/api/ingestion/imports';
  const preview = { auto_import: true, root: '', file_count: 1, class_count: 1,
    error_count: 0, warning_count: 1, total_size_bytes: 100, synced_count: 0, new_count: 1 };
  const execution = { id: 'exec', import_id: 'source', kind: 'preview', status: 'succeeded',
    stage: 'succeeded', progress: 100, result: { dataset_id: 'owner-import', added_count: 1 },
    error: null, status_url: `${base}/source/jobs/exec` };
  const source = { id: 'source', status: 'receiving', sync_status: 'pending', dataset_id: null,
    added_count: 0, preview_token: 'a'.repeat(64), preview, error: null, execution: null };
  let confirmed = false;
  const writes: string[] = [];
  const page = (key: string, rows: unknown[]) => ({ [key]: rows, total: rows.length,
    next_cursor: null, snapshot: 'a'.repeat(64) });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = new URL(String(input), 'http://synthetic.test');
    const path = url.pathname;
    if (options?.method && options.method !== 'GET') writes.push(path);
    if (path.endsWith('/auth/web/me')) return Response.json({ id: 1, email: 'owner@example.test',
      nombre_completo: 'Owner', rol: 'investigador', activo: true });
    if (path === '/api/training/datasets' && url.searchParams.get('include_imported') === 'true')
      return Response.json({ datasets: confirmed ? [{ source_type: 'imported', id: 'owner-import',
        name: 'Owner confirmed WAV', eligible: false, reasons: ['preparation_required'], preparations: [] }] : [] });
    if (path === '/api/training/datasets') return Response.json({ datasets: [] });
    if (path.endsWith('/history')) return Response.json({ history: [] });
    if (path.endsWith('/progress')) return Response.json({ status: 'idle', logs: [] });
    if (path === `${base}/access`) return Response.json({ development_mode: false });
    if (path === `${base}/limits`) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path === base) return Response.json(options?.method ? source : page('imports', []));
    if (path.endsWith('/receipt')) return Response.json({ import_id: 'source', name: 'birds.zip',
      size_bytes: 3, received_bytes: 0, reserved_bytes: 4099, chunk_bytes: 16 * 1024 ** 2, status: 'receiving' });
    if (path.endsWith('/chunks/0') || path.endsWith('/finalize')) return Response.json({ import_id: 'source',
      name: 'birds.zip', size_bytes: 3, received_bytes: 3, reserved_bytes: 4099,
      chunk_bytes: 16 * 1024 ** 2, status: path.endsWith('/finalize') ? 'sealed' : 'receiving' });
    if (path === `${base}/source/preview`) return Response.json({ ...execution, status: 'running' }, { status: 202 });
    if (path === execution.status_url) { confirmed = true; return Response.json(execution); }
    if (path === `${base}/source`) return Response.json(confirmed
      ? { ...source, status: 'imported', dataset_id: 'owner-import', added_count: 1, execution }
      : { ...source, status: 'validating' });
    if (path.endsWith('/classes')) return Response.json(page('classes', ['bird']));
    if (path.endsWith('/files')) return Response.json(page('files', []));
    if (path.endsWith('/issues')) return Response.json(page('issues', []));
    if (path === `${base}/datasets`) return Response.json({ datasets: [] });
    if (path === '/api/models') return Response.json({ models: [], total: 0, default_model_id: '' });
    return Response.json({});
  }));
  render(<Home />);
  await screen.findByText('Owner');
  fireEvent.click(screen.getByRole('button', { name: 'Entrenamiento' }));
  fireEvent.click(await screen.findByRole('combobox',{name:'Dataset para entrenamiento'}));
  await waitFor(() => expect(screen.queryByRole('option', { name: /Owner confirmed WAV/ })).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: 'Gestión de audios' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Importar ZIP' }));
  const dialog = screen.getByRole('dialog');
  const start = within(dialog).getByRole('button', { name: 'Importar dataset' });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.change(screen.getByLabelText('Nombre del dataset'), { target: { value: 'Owner confirmed WAV' } });
  fireEvent.change(screen.getByLabelText('Archivo ZIP'), { target: { files: [new File(['zip'], 'birds.zip')] } });
  fireEvent.click(within(dialog).getByRole('button', { name: /^(Importar|Validar) ZIP$/ }));
  await screen.findByText(/Importada localmente: 1 archivo/);
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar importación' }));
  fireEvent.click(screen.getByRole('button', { name: 'Entrenamiento' }));
  fireEvent.click(screen.getByRole('combobox',{name:'Dataset para entrenamiento'}));
  await screen.findByRole('option', { name: /Owner confirmed WAV.*Privado/ });
  fireEvent.click(screen.getByRole('option',{name:'Owner confirmed WAV — Privado'}));
  await screen.findByText(/Necesita preparación/);
  fireEvent.click(screen.getByRole('combobox',{name:'Dataset para entrenamiento'}));
  expect(screen.getByRole('option',{name:'Owner confirmed WAV — Privado'})).toBeTruthy();
  expect(screen.queryByRole('option', { name: /Foreign/ })).toBeNull();
  fireEvent.keyDown(screen.getByLabelText('Buscar dataset por nombre'),{key:'Escape'});
  expect(screen.queryByLabelText('Preparación existente')).toBeNull();
  expect(screen.queryByLabelText('Mapa explícito JSON')).toBeNull();
  expect(screen.queryByLabelText('Perfil explícito JSON')).toBeNull();
  expect((screen.getByRole('button', { name: 'Preparar dataset' }) as HTMLButtonElement).disabled).toBe(false);
  expect((screen.getByRole('button', { name: 'Iniciar Entrenamiento Local (1 Modelo)' }) as HTMLButtonElement).disabled).toBe(true);
  expect(writes.filter(path => path.includes('/training/'))).toEqual([]);
});

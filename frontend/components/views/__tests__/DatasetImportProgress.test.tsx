import { File as BrowserFile } from "node:buffer";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetImportPanel from '@/components/ingestion/DatasetImportPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each(['queued', 'running'])('summarizes %s import without technical stages, IDs or quota arithmetic', async status => {
  const job = { id: 'opaque-import', archive_name: 'aves.zip', status: 'validating', sync_status: 'pending',
    dataset_id: null, added_count: 0, preview_token: null, error: null,
    execution: { id: 'opaque-execution', import_id: 'opaque-import', kind: 'preview', status,
      stage: 'verifying_manifest_internal', progress: 20, result: {}, error: null, status_url: '/unused' },
    preview: { auto_import: true, file_count: 0, class_count: 0, error_count: 0, warning_count: 0, total_size_bytes: 0, synced_count: 0 } };
  const requests: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    requests.push(options?.method || 'GET');
    const path = new URL(input, 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/limits')) return Response.json({ received_bytes: 2000000000, expanded_bytes: 2000000000,
      entries: 100, depth: 12, path_bytes: 240, audio_bytes: 100000000, audio_seconds: 600,
      validation_seconds: 900, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path.includes('/jobs/')) return new Promise<Response>(() => {});
    return Response.json({ imports: [job], total: 1, next_cursor: null, snapshot: 'history' });
  }));
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Importar dataset' }));
  await screen.findByRole('button', { name: 'Descargar ZIP de ejemplo sintético' });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Importar dataset' }));
  fireEvent.click(screen.getByRole('button', { name: /aves.zip —/ }));
  const summary = screen.getByRole('region', { name: 'Importación en curso' });
  expect(summary.textContent).toContain('aves.zip');
  expect(summary.textContent).toContain(status === 'queued' ? 'En espera para importar' : 'Validando los audios');
  expect(summary.textContent).not.toMatch(/opaque-|verifying_manifest_internal|Sincronización|Bytes únicos|Duplicados internos/);
  expect(screen.queryByRole('button', { name: /página de/ })).toBeNull();
  if (status === 'queued') expect(screen.getByRole('button', { name: 'Cancelar trabajo pendiente' })).toBeDefined();
  expect(requests.every(method => method === 'GET')).toBe(true);
});

it('shows only acknowledged upload progress in MB while a subsequent chunk is pending', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const source = { id: 'upload-id', status: 'receiving', sync_status: 'pending', dataset_id: null,
    added_count: 0, preview_token: null, error: null, preview: { auto_import: true, file_count: 0,
      class_count: 0, error_count: 0, warning_count: 0, total_size_bytes: 0, synced_count: 0 } };
  const receipt = { import_id: 'upload-id', name: 'aves.zip', size_bytes: 1000000, reserved_bytes: 1000000,
    received_bytes: 0, chunk_bytes: 500000, status: 'receiving' };
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/limits')) return Response.json({ received_bytes: 2000000, expanded_bytes: 2000000,
      entries: 100, depth: 12, path_bytes: 240, audio_bytes: 1000000, audio_seconds: 600,
      validation_seconds: 900, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path.endsWith('/imports')) return Response.json(options?.method ? source : { imports: [], total: 0, next_cursor: null, snapshot: 'history' });
    if (path.endsWith('/receipt')) return Response.json(receipt);
    if (path.endsWith('/chunks/0')) return Response.json({ ...receipt, received_bytes: 500000 });
    if (path.endsWith('/chunks/1')) return new Promise<Response>(() => {});
    throw new Error('Unexpected ' + path);
  }));
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Importar dataset' }));
  await screen.findByRole('button', { name: 'Descargar ZIP de ejemplo sintético' });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Importar dataset' }));
  fireEvent.change(screen.getByLabelText('Nombre del dataset'), { target: { value: 'Aves' } });
  fireEvent.change(screen.getByLabelText('Archivo ZIP'), { target: { files: [new BrowserFile([new Uint8Array(1000000)], 'aves.zip')] } });
  fireEvent.click(screen.getByRole('button', { name: 'Importar ZIP' }));
  expect(await screen.findByText('Subido: 0,5 MB de 1 MB')).toBeDefined();
  expect(screen.queryByText(/Bytes reconocidos|500000/)).toBeNull();
  expect(screen.queryByText('Subido: 1 MB de 1 MB')).toBeNull();
});

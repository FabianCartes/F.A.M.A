import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import IngestionView from '../IngestionView';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('uses the shared inventory without the withdrawn private import-date table', async () => {
  const requests: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    requests.push(path);
    if (path.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'shared', name: 'Aves compartidas',
      file_count: 1, local_file_count: 1, gcs_file_count: 1, total_size_bytes: 100,
      last_modified: '2024-01-15T12:00:00Z' }] });
    if (path.endsWith('/status')) return Response.json({ connected: false, bucket: '', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  }));
  render(<IngestionView />);
  const inventory = within(await screen.findByRole('table', { name: 'Inventario de datasets' }));
  await inventory.findByText('Aves compartidas');
  expect(inventory.getByRole('columnheader', { name: 'En este equipo' })).toBeDefined();
  expect(inventory.getByRole('columnheader', { name: 'En GCS' })).toBeDefined();
  expect(screen.queryByRole('columnheader', { name: 'Fecha de importación' })).toBeNull();
  expect(requests.some(path => path.includes('/imports/datasets'))).toBe(false);
});

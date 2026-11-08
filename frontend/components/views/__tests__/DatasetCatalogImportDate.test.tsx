import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import IngestionView from '../IngestionView';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each([1700000000, null, undefined])('shows private import date or explicit absence without changing shared modification dates (%s)', async imported_at => {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/imports/datasets')) return Response.json({ datasets: [{ id: 'private', name: 'Aves privadas',
      description: null, revision: 2, class_count: 15, file_count: 1195, total_size_bytes: 7940000000,
      synced_file_count: 0, imported_at }], total: 1, next_cursor: null, snapshot: 'catalog' });
    if (path.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'shared', name: 'Aves compartidas',
      class_count: 1, file_count: 1, local_file_count: 1, total_size_bytes: 100,
      last_modified: '2024-01-15T12:00:00Z' }] });
    if (path.endsWith('/status')) return Response.json({ connected: false, bucket: '', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  }));
  render(<IngestionView />);
  const row = (await screen.findByText('Aves privadas')).closest('tr')!;
  const table = within(screen.getByRole('table', { name: 'Catálogo' }));
  const index = table.getAllByRole('columnheader').indexOf(table.getByRole('columnheader', { name: 'Fecha de importación' }));
  const expected = imported_at == null ? 'No disponible' : new Date(imported_at * 1000).toLocaleDateString('es-CL', { year: 'numeric', month: 'short', day: 'numeric' });
  expect(within(row).getAllByRole('cell')[index].textContent).toBe(expected);
  expect(table.queryByRole('columnheader', { name: 'Última Modificación' })).toBeNull();
  const shared = within(screen.getByRole('table', { name: 'Catálogo compartido' }));
  expect(shared.getByRole('columnheader', { name: 'Última Modificación' })).toBeDefined();
  expect(shared.queryByRole('columnheader', { name: 'Fecha de importación' })).toBeNull();
});

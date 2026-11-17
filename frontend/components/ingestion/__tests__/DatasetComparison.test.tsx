import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetInventory, { type DatasetItem } from '../DatasetInventory';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const item: DatasetItem = { id: 'Aves', name: 'Aves', file_count: 1217, total_size_bytes: 20, last_modified: null,
  local_file_count: 1217, gcs_file_count: 1217, gcs_available: true, source: 'gcs' };
const base = { dataset: 'Aves', status: 'match', local_count: 1217, gcs_count: 1217, missing_local: 0, missing_gcs: 0,
  size_mismatch: 0, hash_mismatch: 0, hash_unverified: 0, hash_verified: 1217 };

async function compareWith(result: object) {
  const calls: { url: string; method?: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input, init) => { calls.push({ url: String(input), method: init?.method }); return Response.json(result); }));
  render(<DatasetInventory datasets={[item]} loading={false} busy={false} onRefresh={() => {}} onDownload={() => {}} onInspect={() => {}} />);
  expect(screen.getByText('Contenido sin comparar')).toBeDefined();
  expect(calls).toEqual([]);
  fireEvent.click(screen.getByRole('button', { name: 'Comparar contenido de Aves' }));
  const cell = (await screen.findAllByRole('cell'))[5];
  return { calls, cell };
}

it('shows «Coincide» and drops the permanent notice once a comparison matched', async () => {
  const { calls, cell } = await compareWith(base);
  expect(await within(cell).findByText('Coincide (recuento, tamaño y huellas registradas)')).toBeDefined();
  expect(screen.queryByText('Contenido sin comparar')).toBeNull();
  expect(calls).toEqual([{ url: '/api/ingestion/datasets/Aves/compare', method: 'POST' }]);
});

it('lists the differences found and flags audios without a registered fingerprint', async () => {
  const { cell } = await compareWith({ ...base, status: 'differences', local_count: 1210, missing_local: 7,
    size_mismatch: 2, hash_mismatch: 1, hash_unverified: 3 });
  for (const text of ['Faltan 7 en local', '2 con tamaño distinto', '1 con huella distinta', '3 sin huella registrada'])
    expect(await within(cell).findByText(text)).toBeDefined();
  expect(screen.queryByText('Contenido sin comparar')).toBeNull();
  expect(within(cell).queryByText(/^Coincide/)).toBeNull();
});

it('reports a match on count and size only when some audios have no registered fingerprint', async () => {
  const { cell } = await compareWith({ ...base, hash_unverified: 5, hash_verified: 1212 });
  expect(await within(cell).findByText('Coincide en recuento y tamaño · 5 sin huella registrada')).toBeDefined();
});

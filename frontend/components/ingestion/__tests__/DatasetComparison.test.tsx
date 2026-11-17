import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetInventory, { type DatasetItem } from '../DatasetInventory';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const check = { level: 'count_size', status: 'match', local_count: 1217, gcs_count: 1217, matching: 1217, missing_local: 0,
  only_local: 0, size_mismatch: 0, checksum_mismatch: 0, unverified: 0 };
const item = (content_check: object | null = check): DatasetItem => ({ id: 'Aves', name: 'Aves', file_count: 1217, total_size_bytes: 20,
  last_modified: null, local_file_count: 1217, gcs_file_count: 1217, gcs_available: true, source: 'gcs',
  content_check: content_check as DatasetItem['content_check'] });

function show(dataset: DatasetItem, onDownload = vi.fn(), downloadChecks = {}) {
  render(<DatasetInventory datasets={[dataset]} loading={false} busy={false} onRefresh={() => {}} onDownload={onDownload}
    onInspect={() => {}} downloadChecks={downloadChecks} />);
  return { cell: screen.getAllByRole('cell')[5], onDownload };
}

it('shows the automatic count and size result without any click and no permanent «sin comparar» notice', () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  const { cell } = show(item());
  expect(within(cell).getByText('Coincide (recuento y tamaño)')).toBeDefined();
  expect(screen.queryByText('Contenido sin comparar')).toBeNull();
  expect(screen.queryByRole('button', { name: /Corregir descargando desde GCS/ })).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
});

it('renders the differences in the row and offers «Corregir descargando desde GCS», which starts the download flow', () => {
  const { cell, onDownload } = show(item({ ...check, status: 'differences', local_count: 1211, matching: 1208, missing_local: 7,
    only_local: 1, size_mismatch: 2 }));
  for (const text of ['Faltan 7 en local', '1 solo en local', '2 con tamaño distinto'])
    expect(within(cell).getByText(text)).toBeDefined();
  fireEvent.click(within(cell).getByRole('button', { name: 'Corregir descargando desde GCS Aves' }));
  expect(onDownload).toHaveBeenCalledWith(['Aves']);
});

it('does not offer the correction when audios are only local', () => {
  const { cell } = show(item({ ...check, status: 'differences', only_local: 3 }));
  expect(within(cell).getByText('3 solo en local')).toBeDefined();
  expect(screen.queryByRole('button', { name: /Corregir descargando desde GCS/ })).toBeNull();
});

it('«Verificar contenido» asks the server on demand and shows the verified result', async () => {
  const calls: { url: string; method?: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input, init) => { calls.push({ url: String(input), method: init?.method });
    return Response.json({ ...check, dataset: 'Aves', level: 'checksum' }); }));
  const { cell } = show(item());
  expect(calls).toEqual([]);
  fireEvent.click(within(cell).getByRole('button', { name: 'Verificar contenido de Aves' }));
  expect(await within(cell).findByText('Coincide (contenido verificado)')).toBeDefined();
  expect(within(cell).queryByText('Coincide (recuento y tamaño)')).toBeNull();
  expect(calls).toEqual([{ url: '/api/ingestion/datasets/Aves/compare', method: 'POST' }]);
});

it('flags a verified match whose objects expose no checksum instead of claiming verified content', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...check, dataset: 'Aves', level: 'checksum', unverified: 4 })));
  const { cell } = show(item());
  fireEvent.click(within(cell).getByRole('button', { name: 'Verificar contenido de Aves' }));
  expect(await within(cell).findByText('4 sin checksum para verificar')).toBeDefined();
  expect(within(cell).queryByText('Coincide (contenido verificado)')).toBeNull();
});

it('shows a checksum mismatch found by the verification and offers the correction', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...check, dataset: 'Aves', level: 'checksum', status: 'differences', checksum_mismatch: 2 })));
  const { cell } = show(item());
  fireEvent.click(within(cell).getByRole('button', { name: 'Verificar contenido de Aves' }));
  expect(await within(cell).findByText('2 con contenido distinto')).toBeDefined();
  expect(within(cell).getByRole('button', { name: 'Corregir descargando desde GCS Aves' })).toBeDefined();
});

it('shows the verdict derived from a finished download in the row', () => {
  const download = { ...check, level: 'download', local_count: null, only_local: null };
  const { cell } = show(item(), vi.fn(), { Aves: download });
  expect(within(cell).getByText('Coincide (contenido verificado en la descarga)')).toBeDefined();
  expect(within(cell).queryByText('Coincide (recuento y tamaño)')).toBeNull();
});

it('shows how many audios failed in the download', () => {
  const download = { ...check, level: 'download', status: 'differences', local_count: null, only_local: null, failed: 15, matching: 1202 };
  const { cell } = show(item(), vi.fn(), { Aves: download });
  expect(within(cell).getByText('15 fallaron en la descarga')).toBeDefined();
});

import { afterEach, expect, it, vi } from 'vitest';
import { deletePrivateDataset } from '../datasetImports';

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

it('sends the confirmed revision with the cookie session and never parses a 204 body', async () => {
  const json = vi.fn(() => { throw new Error('204 has no JSON'); });
  global.fetch = vi.fn(async () => ({ ok: true, status: 204, json }) as unknown as Response);
  await deletePrivateDataset({ id: 'opaque/id', revision: 7 });
  const [url, options] = vi.mocked(global.fetch).mock.calls[0];
  expect(String(url)).toMatch(/\/api\/ingestion\/imports\/datasets\/opaque%2Fid$/);
  expect(options?.method).toBe('DELETE');
  expect(JSON.parse(String(options?.body))).toEqual({ revision: 7 });
  expect(new Headers(options?.headers).get('Authorization')).toBeNull();
  expect(new Headers(options?.headers).get('Content-Type')).toBe('application/json');
  expect(options?.cache).toBe('no-store');
  expect(json).not.toHaveBeenCalled();
});

it('uses the same-origin browser session without inventing an Authorization identity', async () => {
  global.fetch = vi.fn(async () => new Response(null, { status: 204 }));
  await deletePrivateDataset({ id: 'private', revision: 0 });
  const [url, options] = vi.mocked(global.fetch).mock.calls[0];
  expect(String(url)).toBe('/api/ingestion/imports/datasets/private');
  expect(new Headers(options?.headers).has('Authorization')).toBe(false);
  expect(options?.credentials).toBe('same-origin');
});

it.each([404, 409, 503])('propagates safe detail from %s without parsing it as success', async status => {
  global.fetch = vi.fn(async () => Response.json({ detail: 'El dataset no está disponible para eliminar.' }, { status }));
  await expect(deletePrivateDataset({ id: 'private', revision: 7 })).rejects.toThrow(`${status}: El dataset no está disponible para eliminar.`);
});

it('does not accept an unexpected successful status as confirmed deletion', async () => {
  global.fetch = vi.fn(async () => Response.json({}));
  await expect(deletePrivateDataset({ id: 'private', revision: 7 })).rejects.toThrow('No se confirmó la eliminación local');
});

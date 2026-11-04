import { afterEach, describe, expect, it, vi } from 'vitest';
import { importedTrainingApi } from '../importedTrainingApi';

afterEach(() => vi.unstubAllGlobals());
describe('imported training HTTP client', () => {
  it('uses the existing same-origin cookie and never turns a private 401 into an empty catalog', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: 'Autenticación requerida.'}), {status: 401}));
    vi.stubGlobal('fetch', transport);
    await expect(importedTrainingApi.catalog()).rejects.toThrow('Autenticación requerida.');
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][1]).toMatchObject({credentials: 'same-origin'});
  });
  it('does not accept a pending or malformed snapshot as a completed resource', async()=>{
    const transport=vi.fn().mockResolvedValue(new Response(JSON.stringify({id:'snapshot',state:'pending'})));
    vi.stubGlobal('fetch',transport);
    await expect(importedTrainingApi.snapshot('dataset')).rejects.toThrow();
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it('never retries preparation after an uncertain network failure', async () => {
    const transport = vi.fn().mockRejectedValue(new TypeError('disconnected'));
    vi.stubGlobal('fetch', transport);
    await expect(importedTrainingApi.prepare('snapshot', {mapping: [], provenance: {}, seed: 1, profile: {}})).rejects.toThrow(/Vuelva a seleccionar/);
    expect(transport).toHaveBeenCalledTimes(1);
  });
});

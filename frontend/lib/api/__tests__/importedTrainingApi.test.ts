import { afterEach, describe, expect, it, vi } from 'vitest';
import { importedTrainingApi } from '../importedTrainingApi';

afterEach(() => vi.unstubAllGlobals());
describe('historical imported composition revision HTTP client', () => {
  it('uses the existing same-origin cookie and preserves a private revision 401', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: 'Autenticación requerida.'}), {status: 401}));
    vi.stubGlobal('fetch', transport);
    await expect(importedTrainingApi.reviseTriadWeights('fama_trained_model_4', [0.2, 0.3, 0.5])).rejects.toThrow('Autenticación requerida.');
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][1]).toMatchObject({credentials: 'same-origin'});
  });
  it('never retries a weight revision after an uncertain network failure', async () => {
    const transport = vi.fn().mockRejectedValue(new TypeError('disconnected'));
    vi.stubGlobal('fetch', transport);
    await expect(importedTrainingApi.reviseTriadWeights('fama_trained_model_4', [0.2, 0.3, 0.5])).rejects.toThrow(/Vuelva a seleccionar/);
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it('posts exact float weights for the numeric model id and parses the new version', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify({id: 'fama_trained_model_9', name: 'Tríada importada', weights: [0.1, 0.4, 0.5]})));
    vi.stubGlobal('fetch', transport);
    const result = await importedTrainingApi.reviseTriadWeights('fama_trained_model_4', [0.1, 0.4, 0.5]);
    expect(result.id).toBe('fama_trained_model_9');
    expect(String(transport.mock.calls[0][0])).toMatch(/\/api\/training\/models\/4\/triad-weights$/);
    expect(transport.mock.calls[0][1]).toMatchObject({method: 'POST', credentials: 'same-origin', body: '{"weights":[0.1,0.4,0.5]}'});
  });
  it('rejects a non-composition catalogue id without any request and surfaces server detail', async () => {
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: 'Composición importada no disponible.'}), {status: 404}));
    vi.stubGlobal('fetch', transport);
    await expect(importedTrainingApi.reviseTriadWeights('machine-model', [1, 0, 0])).rejects.toThrow('Composición importada no disponible.');
    expect(transport).not.toHaveBeenCalled();
    await expect(importedTrainingApi.reviseTriadWeights('fama_trained_model_4', [1, 0, 0])).rejects.toThrow('Composición importada no disponible.');
    expect(transport).toHaveBeenCalledTimes(1);
  });
});

import { expect, it, vi } from 'vitest';
import { apiSessionRevision, confirmApiSession, onUnauthorized } from '@/lib/api';
import { getPredictionHistory } from '../predictionHistory';

it('does not invalidate a new session when an old history request returns 401', async () => {
  let finish!: (response: Response) => void;
  const listener = vi.fn();
  const unsubscribe = onUnauthorized(listener);
  const previous = global.fetch;
  global.fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
  try {
    const request = getPredictionHistory('fama_trained_model_301', new AbortController().signal);
    const caught = request.catch(error => error);
    confirmApiSession();
    const revision = apiSessionRevision();
    finish(new Response(null, { status: 401 }));
    expect(await caught).toBeInstanceOf(Error);
    expect(listener).not.toHaveBeenCalled();
    expect(apiSessionRevision()).toBe(revision);
    global.fetch = vi.fn(async () => new Response(null, { status: 401 }));
    await expect(getPredictionHistory('fama_trained_model_301', new AbortController().signal)).rejects.toThrow('No se pudo cargar');
    expect(listener).toHaveBeenCalledTimes(1);
  } finally { global.fetch = previous; unsubscribe(); }
});

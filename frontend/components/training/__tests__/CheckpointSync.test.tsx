import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { CheckpointSyncButton } from '../CheckpointSync';

const originalFetch = global.fetch;
const result = (action: string) => ({ model_id: 1, filename: 'sample.pt', sha256: 'a'.repeat(64), size_bytes: 20000,
  local: 'valid', cloud: 'available', generation: '17', transfer_verified: true, action });
afterEach(() => { cleanup(); global.fetch = originalFetch; });

function renderButton(synced = false) {
  const onSynced = vi.fn();
  render(<CheckpointSyncButton modelId={1} synced={synced} onSynced={onSynced} />);
  return onSynced;
}

describe('Sincronizar checkpoint', () => {
  it.each([
    ['uploaded', /Se respaldó el checkpoint en GCS/],
    ['restored', /Se recuperó el checkpoint desde GCS en este equipo/],
    ['already_synced', /ya estaban sincronizadas/],
  ])('informa en una ventana modal la acción %s y marca el modelo como sincronizado', async (action, message) => {
    const requests: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(`${init?.method} ${String(input)}`);
      return new Response(JSON.stringify(result(action)));
    });
    const onSynced = renderButton();
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizar en GCS' }));
    const dialog = await screen.findByRole('dialog', { name: 'Checkpoint sincronizado' });
    expect(dialog.textContent).toMatch(message);
    expect(requests).toEqual([expect.stringMatching(/^POST .*\/api\/training\/models\/1\/checkpoint\/sync$/)]);
    expect(onSynced).toHaveBeenCalledWith(action);
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('muestra el motivo del fallo y no marca el modelo', async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify({
      detail: 'No hay copia local ni respaldo en GCS de este checkpoint; no se puede sincronizar.' }), { status: 409 }));
    const onSynced = renderButton();
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizar en GCS' }));
    const dialog = await screen.findByRole('dialog', { name: 'No se pudo sincronizar' });
    expect(dialog.textContent).toContain('No hay copia local ni respaldo en GCS de este checkpoint; no se puede sincronizar.');
    expect(onSynced).not.toHaveBeenCalled();
  });

  it('no confirma una respuesta sin transferencia verificada', async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify({ ...result('uploaded'), transfer_verified: false })));
    const onSynced = renderButton();
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizar en GCS' }));
    expect(await screen.findByRole('dialog', { name: 'No se pudo sincronizar' })).toBeTruthy();
    expect(onSynced).not.toHaveBeenCalled();
  });

  it('rotula «Sincronizado» y se deshabilita mientras sincroniza', async () => {
    let resolve: (response: Response) => void = () => { throw new Error('request not started'); };
    global.fetch = vi.fn(() => new Promise<Response>(done => { resolve = done; }));
    renderButton(true);
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizado' }));
    expect((screen.getByRole('button', { name: 'Sincronizando…' }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { resolve(new Response(JSON.stringify(result('already_synced')))); });
    expect(screen.getByRole('dialog', { name: 'Checkpoint sincronizado' })).toBeTruthy();
  });
});

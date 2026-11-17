import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CheckpointSyncButton, TriadCheckpointSyncButton, useCheckpointSyncStatus } from '../CheckpointSync';

const originalFetch = global.fetch;
const result = (action: string) => ({ model_id: 1, filename: 'sample.pt', sha256: 'a'.repeat(64), size_bytes: 20000,
  local: 'valid', cloud: 'available', generation: '17', transfer_verified: true, action });
afterEach(() => { cleanup(); global.fetch = originalFetch; });

function renderButton(synced = false, remoteOnly = false) {
  const onSynced = vi.fn();
  render(<CheckpointSyncButton modelId={1} synced={synced} remoteOnly={remoteOnly} onSynced={onSynced} />);
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

describe('Rótulo según las copias disponibles', () => {
  it('ofrece «Descargar desde GCS» cuando solo existe el respaldo remoto y rotula «Descargando…» al trabajar', async () => {
    let resolve: (response: Response) => void = () => { throw new Error('request not started'); };
    global.fetch = vi.fn(() => new Promise<Response>(done => { resolve = done; }));
    renderButton(false, true);
    expect(screen.queryByRole('button', { name: 'Sincronizar en GCS' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Descargar desde GCS' }));
    expect((screen.getByRole('button', { name: 'Descargando…' }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { resolve(new Response(JSON.stringify(result('restored')))); });
    expect(screen.getByRole('dialog', { name: 'Checkpoint sincronizado' })).toBeTruthy();
  });

  it('mantiene «Sincronizar en GCS» cuando hay copia local', () => {
    renderButton(false, false);
    expect(screen.getByRole('button', { name: 'Sincronizar en GCS' })).toBeTruthy();
  });

  function Probe() {
    const { remoteOnly, markSynced } = useCheckpointSyncStatus([1, 2, 3]);
    return <>{[1, 2, 3].map(id => <span key={id} data-testid={`m${id}`}>{remoteOnly.has(id) ? 'remote' : 'other'}</span>)}
      <button onClick={() => markSynced(1)}>marcar</button></>;
  }

  it('solo marca como remoto el modelo sin copia local pero con respaldo, y deja de hacerlo al sincronizar', async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify({ models: [
      { model_id: 1, synced: false, local: false, remote: true },
      { model_id: 2, synced: false, local: true, remote: false },
      { model_id: 3, synced: false },
    ] })));
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('m1').textContent).toBe('remote'));
    expect(screen.getByTestId('m2').textContent).toBe('other');
    expect(screen.getByTestId('m3').textContent).toBe('other');
    fireEvent.click(screen.getByRole('button', { name: 'marcar' }));
    expect(screen.getByTestId('m1').textContent).toBe('other');
  });

  it('mantiene «Sincronizar en GCS» si GCS no se puede consultar', async () => {
    global.fetch = vi.fn(async () => new Response('{}', { status: 503 }));
    render(<Probe />);
    await act(async () => { await Promise.resolve(); });
    expect(['m1', 'm2', 'm3'].map(id => screen.getByTestId(id).textContent)).toEqual(['other', 'other', 'other']);
  });
});


describe('Sincronizar la tríada completa', () => {
  const models = [{ id: 4, label: 'EfficientNet-B0' }, { id: 5, label: 'ConvNeXt-Nano' }, { id: 6, label: 'ResNet-34d' }];
  const synced = (id: number) => new Response(JSON.stringify({ ...result('uploaded'), model_id: id }));
  const requested = (input: RequestInfo | URL) => Number(String(input).match(/models\/(\d+)\/checkpoint\/sync$/)?.[1]);

  it('sincroniza los tres modelos en orden, muestra el avance y confirma en una ventana modal', async () => {
    const pending: Array<() => void> = [];
    const order: number[] = [];
    global.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe('POST');
      const id = requested(input);
      order.push(id);
      return new Promise<Response>(done => { pending.push(() => done(synced(id))); });
    });
    const onSynced = vi.fn();
    render(<TriadCheckpointSyncButton models={models} allSynced={false} onSynced={onSynced} />);
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizar en GCS' }));
    for (const step of [1, 2, 3]) {
      const button = await screen.findByRole('button', { name: `Sincronizando ${step} / 3…` });
      expect((button as HTMLButtonElement).disabled).toBe(true);
      await act(async () => { pending.shift()?.(); });
    }
    const dialog = await screen.findByRole('dialog', { name: 'Tríada sincronizada' });
    expect(dialog.textContent).toContain('Los 3 modelos de la tríada quedaron sincronizados en GCS.');
    expect(order).toEqual([4, 5, 6]);
    expect(onSynced.mock.calls).toEqual([[4, 'uploaded'], [5, 'uploaded'], [6, 'uploaded']]);
  });

  it('nombra solo los modelos que fallaron y reintenta solo esos', async () => {
    const order: number[] = [];
    let failing = true;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const id = requested(input);
      order.push(id);
      if (id === 6 && failing) return new Response(JSON.stringify({
        detail: 'No se pudo comprobar o transferir el checkpoint. Revisa GCS, la conexión y el espacio local; puedes reintentar.' }), { status: 503 });
      return synced(id);
    });
    const onSynced = vi.fn();
    render(<TriadCheckpointSyncButton models={models} allSynced={false} onSynced={onSynced} />);
    fireEvent.click(screen.getByRole('button', { name: 'Sincronizar en GCS' }));
    const dialog = await screen.findByRole('dialog', { name: 'No se pudo sincronizar la tríada' });
    expect(dialog.textContent).toContain('2 de 3 modelos quedaron sincronizados.');
    expect(dialog.textContent).toContain('No se pudo sincronizar ResNet-34d (modelo 6): No se pudo comprobar o transferir el checkpoint.');
    expect(dialog.textContent).not.toContain('ConvNeXt-Nano (modelo 5)');
    expect(onSynced.mock.calls.map(call => call[0])).toEqual([4, 5]);
    failing = false;
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByRole('dialog', { name: 'Tríada sincronizada' })).toBeTruthy();
    expect(order).toEqual([4, 5, 6, 6]);
    expect(onSynced).toHaveBeenLastCalledWith(6, 'uploaded');
  });

  it('rotula «Sincronizado» cuando los tres modelos ya tienen ambas copias', () => {
    render(<TriadCheckpointSyncButton models={models} allSynced onSynced={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Sincronizado' })).toBeTruthy();
  });
});

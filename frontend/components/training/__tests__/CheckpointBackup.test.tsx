import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import CheckpointBackup from '../CheckpointBackup';

const originalFetch = global.fetch;
const status = { model_id: 1, filename: 'sample.pt', sha256: 'a'.repeat(64), size_bytes: 20000,
  local: 'missing', cloud: 'available', generation: '17', transfer_verified: false };
afterEach(() => { cleanup(); global.fetch = originalFetch; });

describe('Copias del checkpoint', () => {
  it('recupera una copia ausente y avisa al historial después de verificarla', async () => {
    const restored = vi.fn();
    global.fetch = vi.fn(async input => new Response(JSON.stringify(String(input).endsWith('/restore')
      ? { ...status, local: 'valid', transfer_verified: true } : status)));
    render(<CheckpointBackup modelId={1} onRestored={restored} />);
    fireEvent.click(screen.getByRole('button', { name: 'Comprobar copias' }));
    expect(await screen.findByText('Sin copia local')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Recuperar en este equipo' }));
    expect(await screen.findByText(/Checkpoint recuperado y verificado/)).toBeTruthy();
    expect(restored).toHaveBeenCalledOnce();
  });

  it.each([503, 200])('no confirma una transferencia HTTP %s fallida o sin verificar', async code => {
    const restored = vi.fn();
    global.fetch = vi.fn(async input => new Response(JSON.stringify(String(input).endsWith('/restore')
      ? code === 503 ? { detail: 'GCS temporalmente inaccesible' } : status : status),
      { status: String(input).endsWith('/restore') ? code : 200 }));
    render(<CheckpointBackup modelId={1} onRestored={restored} />);
    fireEvent.click(screen.getByRole('button', { name: 'Comprobar copias' }));
    await screen.findByText('Sin copia local');
    fireEvent.click(screen.getByRole('button', { name: 'Recuperar en este equipo' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByText(/Checkpoint recuperado y verificado/)).toBeNull();
    expect(restored).not.toHaveBeenCalled();
  });

  it('ignora una respuesta anterior cuando se abre otro modelo', async () => {
    let resolveOld: (response: Response) => void = () => { throw new Error('request not started'); };
    global.fetch = vi.fn(async input => String(input).includes('/models/1/')
      ? new Promise<Response>(resolve => { resolveOld = resolve; })
      : new Response(JSON.stringify({ ...status, model_id: 2, local: 'valid', cloud: 'missing' })));
    const view = render(<CheckpointBackup modelId={1} onRestored={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Comprobar copias' }));
    view.rerender(<CheckpointBackup modelId={2} onRestored={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Comprobar copias' }));
    await screen.findByText('Sin respaldo en GCS');
    await act(async () => { resolveOld(new Response(JSON.stringify(status))); });
    expect(screen.queryByText('Sin copia local')).toBeNull();
    expect(screen.getByText('Sin respaldo en GCS')).toBeTruthy();
  });
});

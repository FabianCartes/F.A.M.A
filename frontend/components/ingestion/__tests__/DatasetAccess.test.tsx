import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetCatalogue from '../DatasetCatalogue';
import RequestsPanel from '@/components/account/RequestsPanel';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Descubrimiento y solicitudes por HTTP', () => {
  it('solicita acceso mostrando solo metadatos y conserva el estado pendiente al actualizar', async () => {
    let pending = false;
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input, init) => {
      const url = String(input); calls.push(url);
      if (url.includes('/api/datasets/10/requests') && init.method === 'POST') {
        pending = true; return json({ user_id: 2, dataset_id: 10, status: 'pending' });
      }
      return json({ datasets: [{ dataset_id: 10, name: 'Aves de prueba', purpose: 'Investigación',
        audio_count: 2, size_bytes: 2048, assigned: false, request_status: pending ? 'pending' : null }],
        total: 1, offset: 0, limit: 20 });
    }));
    await act(async () => { render(<DatasetCatalogue />); });
    expect(screen.getByText('Aves de prueba')).toBeDefined();
    expect(screen.queryByRole('button', { name: /Descargar|Ver archivos/ })).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Solicitar acceso a Aves de prueba' })); });
    expect(screen.getByText('Solicitud pendiente')).toBeDefined();
    expect(calls.some(url => url.includes('/api/ingestion/'))).toBe(false);
    expect(calls.filter(url => url.endsWith('/requests'))).toHaveLength(1);
  });

  it('el administrador confirma la solicitud y la bandeja se actualiza con la decisión del servidor', async () => {
    const commands: { url: string; body: string }[] = [];
    let decided = false;
    vi.stubGlobal('fetch', vi.fn(async (input, init) => {
      const url = String(input);
      if (init.method === 'POST') { commands.push({ url, body: init.body }); decided = true;
        return json({ user_id: 2, dataset_id: 10, status: 'approved', assigned: true }); }
      return json({ requests: decided ? [] : [{ user_id: 2, dataset_id: 10, user_name: 'Persona de prueba',
        dataset_name: 'Aves de prueba', status: 'pending', requested_at: 1790000000, decided_at: null, decided_by: null }],
        total: decided ? 0 : 1, limit: 20, offset: 0 });
    }));
    await act(async () => { render(<RequestsPanel />); });
    const row = within(screen.getByRole('row', { name: /Persona de prueba/ }));
    await act(async () => { fireEvent.click(row.getByRole('button', { name: 'Aprobar acceso' })); });
    expect(commands).toEqual([{ url: '/api/access/requests/2/10/decision', body: JSON.stringify({ decision: 'approve' }) }]);
    expect(screen.getByRole('status').textContent).toContain('Acceso concedido');
    expect(screen.queryByRole('button', { name: 'Aprobar acceso' })).toBeNull();
  });

  it('no anuncia acceso concedido si una aprobación antigua ya perdió su asignación', async () => {
    let refreshed = false;
    vi.stubGlobal('fetch', vi.fn(async (input, init) => {
      if (init.method === 'POST') { refreshed = true; return json({ user_id: 2, dataset_id: 10, status: 'approved', assigned: false }); }
      return json({ requests: refreshed ? [] : [{ user_id: 2, dataset_id: 10, user_name: 'Otra persona',
        dataset_name: 'Aves', status: 'pending', requested_at: 1790000000, decided_at: null, decided_by: null }],
        total: refreshed ? 0 : 1, offset: 0, limit: 20 });
    }));
    await act(async () => { render(<RequestsPanel />); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Aprobar acceso' })); });
    expect(screen.getByRole('status').textContent).toContain('no tiene una asignación actual');
    expect(screen.queryByText(/Acceso concedido/)).toBeNull();
  });
});

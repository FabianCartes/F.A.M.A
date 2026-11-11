import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { it, expect, vi, afterEach } from 'vitest';
import Home from '@/app/page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('al navegar a entrenamiento muestra el ZIP publicado como dataset registrado sin preparar ni iniciar automáticamente', async () => {
  const writes: string[] = [];
  const reads: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = new URL(String(input), 'http://synthetic.test');
    const path = url.pathname;
    reads.push(String(input));
    if (options?.method && options.method !== 'GET') writes.push(path);
    if (path.endsWith('/auth/me')) return Response.json({ id: 1, email: 'owner@example.test', nombre_completo: 'Owner', rol: 'investigador', activo: true });
    if (path === '/api/training/datasets') return Response.json({ datasets: [{ source_type: 'legacy', record_id: 'legacy:7', id: 'ZIP_Publicado', name: 'ZIP publicado', audio_count: 9, class_count: 3, eligible: true, eligibility_state: 'current_flow_compatible', reasons: [] }] });
    if (path.endsWith('/history')) return Response.json({ history: [] });
    if (path.endsWith('/progress')) return Response.json({ status: 'idle', logs: [] });
    if (path === '/api/models') return Response.json({ models: [], total: 0, default_model_id: '' });
    return Response.json({});
  }));
  render(<Home />);
  await screen.findByText('Owner');
  fireEvent.click(screen.getByRole('button', { name: 'Entrenamiento' }));
  const selector = await screen.findByRole('combobox', { name: 'Dataset para entrenamiento' });
  expect(selector.textContent).toBe('Buscar o seleccionar dataset…');
  fireEvent.click(selector);
  fireEvent.click(await screen.findByRole('option', { name: 'ZIP publicado' }));
  expect(screen.getByRole('region', { name: 'Particiones de entrenamiento' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Gestionar particiones' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Preparar dataset' })).toBeNull();
  const start = screen.getByRole('button', { name: 'Iniciar Entrenamiento Local (1 Modelo)' });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  expect(writes.filter(path => path.includes('/training/'))).toEqual([]);
  expect(reads.some(url => url.includes('/datasets?include_imported') || url.includes('/imported/'))).toBe(false);
});

import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { it, expect, vi, afterEach } from 'vitest';
import TrainingView from '@/components/views/TrainingView';
import Boundary from '@/components/auth/SessionBoundary';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('conserva la tríada estándar y los parámetros por modelo para un ZIP publicado con sesión', async () => {
  const version = 'b'.repeat(64);
  const transport = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/auth/me')) return Response.json({ id: 1, email: 'owner@example.test', nombre_completo: 'Owner', rol: 'investigador', activo: true });
    if (url.includes('/history')) return Response.json({ history: [] });
    if (url.includes('/progress')) return Response.json({ status: 'idle', logs: [] });
    if (url.endsWith('/start')) return Response.json({ status: 'started' });
    if (url.endsWith('/partitions')) return Response.json({ versions: [{ version, counts: { train: 6, val: 2, test: 1 }, warnings: [] }] });
    if (url.includes('/datasets')) return Response.json({ datasets: [{ id: 'ZIP_Publicado', name: 'ZIP publicado', record_id: 'legacy:7', source_type: 'legacy', audio_count: 9, class_count: 3, eligible: true, eligibility_state: 'current_flow_compatible', reasons: [] }] });
    return Response.json({});
  });
  vi.stubGlobal('fetch', transport);
  render(<Boundary><TrainingView /></Boundary>);
  fireEvent.click(await screen.findByRole('combobox', { name: 'Dataset para entrenamiento' }));
  fireEvent.click(await screen.findByRole('option', { name: 'ZIP publicado' }));
  fireEvent.click(screen.getByRole('button', { name: '3 Modelos (Tríada)' }));
  for (const [index, weight] of [50, 30, 20].entries()) {
    fireEvent.change(screen.getByLabelText(`Ponderación del Modelo #${index + 1}`), { target: { value: String(weight) } });
  }
  fireEvent.change(screen.getByLabelText('Épocas del Modelo #1'), { target: { value: '7' } });
  fireEvent.change(screen.getByLabelText('Learning Rate del Modelo #1'), { target: { value: '0.003' } });
  fireEvent.change(screen.getByLabelText('Batch Size del Modelo #1'), { target: { value: '4' } });
  fireEvent.click(screen.getByRole('button', { name: 'Gestionar particiones' }));
  await screen.findByRole('option', { name: /bbbbbbbbbbbb/ });
  fireEvent.change(screen.getByLabelText('Versión para entrenar'), { target: { value: version } });
  expect(screen.queryByRole('button', { name: 'Preparar dataset' })).toBeNull();
  const start = screen.getByRole('button', { name: 'Iniciar Pipeline de Tri Ensamble (3 Modelos)' });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(start);
  await waitFor(() => expect(transport.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(true));
  const call = transport.mock.calls.find(([url]) => String(url).endsWith('/start'))!;
  const body = JSON.parse(String(call[1]?.body));
  expect(body).toMatchObject({ dataset_name: 'ZIP_Publicado', partition_version: version, is_tri_model: true, seed: 42 });
  expect(body.models).toEqual([
    { architecture: 'EfficientNet-B0', epochs: 7, learning_rate: 0.003, batch_size: 4, weight: 0.5 },
    { architecture: 'ConvNeXt-Nano', epochs: 12, learning_rate: 0.0005, batch_size: 16, weight: 0.3 },
    { architecture: 'ResNet-34d', epochs: 15, learning_rate: 0.0003, batch_size: 8, weight: 0.2 },
  ]);
  expect(JSON.stringify(body)).not.toMatch(/imported_dataset_id|snapshot_id|imported_prepared_version/);
  expect(transport.mock.calls.some(([url]) => String(url).includes('/imported/') || String(url).includes('/datasets?include_imported'))).toBe(false);
});

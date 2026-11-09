import { modelOptions } from '../../prediction/__tests__/selectorActions';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import PredictionView from '../PredictionView';
import { confirmApiSession } from '@/lib/api';

const session = vi.hoisted(() => ({ user: null as null | { id: number } }));
vi.mock('@/components/auth/SessionBoundary', () => ({ useOptionalWebSession: () => session.user }));
const model = { id: 'owned-opaque', name: 'Mi clasificador', classes: ['ants', 'zebra'], dataset_name: 'custom-private', has_weights: true };
beforeEach(() => { session.user = null; vi.restoreAllMocks(); URL.createObjectURL = vi.fn(() => 'blob:test'); URL.revokeObjectURL = vi.fn(); });

it('does not request a private catalogue or infer anonymously; login lists arbitrary private classes in Mis modelos', async () => {
  const fetcher = vi.fn(async () => Response.json({ models: [model], default_model_id: '' }));
  global.fetch = fetcher;
  const view = render(<PredictionView />);
  await act(async () => {});
  expect(fetcher.mock.calls.length).toBe(0);
  session.user = { id: 1 }; confirmApiSession();
  await act(async () => { view.rerender(<PredictionView />); });
  modelOptions();
  expect(screen.getByRole('group', { name: 'Mis modelos' })).toBeDefined();
  expect((screen.getByLabelText('Modelo:') as HTMLButtonElement).value).toBe(model.id);
  const call = (fetcher.mock.calls as unknown as [string, RequestInit][]).find(([url]) => url.includes('/api/models'))!;
  expect(call[0]).toContain('private_only=true');
  expect(call[1].credentials).toBe('same-origin');
  session.user = null; confirmApiSession();
  await act(async () => { view.rerender(<PredictionView />); });
  modelOptions();
  expect(screen.queryByRole('option', { name: model.name })).toBeNull();
  expect((screen.getByLabelText('Modelo:') as HTMLButtonElement).value).toBe('');
  fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ }));
  expect((fetcher.mock.calls as unknown as [string][]).some(([url]) => url.includes('/api/predict'))).toBe(false);
});

it('clears private prediction/history on owner switch and ignores an in-flight prediction JSON', async () => {
  session.user = { id: 1 };
  let finish!: (data: unknown) => void;
  let pending = false;
  const prediction = { filename: 'private.wav', db_id: 99, clase: 'ants', confianza: 0.9, gcp_upload: true };
  global.fetch = vi.fn(async (url) => {
    if (String(url).includes('/api/models')) return Response.json({ models: [model] });
    if (String(url).includes('/api/predict')) return pending
      ? { ok: true, json: () => new Promise(resolve => { finish = resolve; }) } as Response
      : Response.json(prediction);
    return Response.json({});
  });
  const view = render(<PredictionView />);
  await act(async () => {});
  await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(['wav'], 'private.wav')] } }); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); });
  expect(screen.getByText('ID de predicción: 99')).toBeDefined();
  pending = true;
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); });
  session.user = { id: 2 }; confirmApiSession();
  await act(async () => { view.rerender(<PredictionView />); finish(prediction); });
  expect(screen.queryByText('ID de predicción: 99')).toBeNull();
  expect(screen.queryByRole('region', { name: 'Validar resultado' })).toBeNull();
  expect(screen.queryByText('private.wav')).toBeNull();
});

it('ignores an old owner catalogue even when its JSON finishes after a session change', async () => {
  let finish!: (data: unknown) => void;
  session.user = { id: 1 };
  global.fetch = vi.fn(async (url) => String(url).includes('/api/models')
    ? { ok: true, json: () => new Promise(resolve => { finish = resolve; }) } as Response
    : Response.json({}));
  const view = render(<PredictionView />);
  await act(async () => {});
  session.user = null; confirmApiSession();
  await act(async () => { view.rerender(<PredictionView />); finish({ models: [model] }); });
  modelOptions();
  expect(screen.queryByRole('option', { name: model.name })).toBeNull();
});


it('reports confirmed local audio without claiming GCS and keeps review available', async () => {
  session.user = { id: 1 };
  global.fetch = vi.fn(async (url) => {
    if (String(url).includes('/api/models')) return Response.json({ models: [model] });
    if (String(url).includes('/api/predict')) return Response.json({
      filename: 'local.wav', db_id: 100, clase: 'ants', confianza: 0.9,
      gcp_upload: false, local_audio_saved: true, cloud_status: 'deferred',
      detalles: { dataset_name: 'imported:' + 'a'.repeat(32) },
    });
    return Response.json({});
  });
  const view = render(<PredictionView />);
  await act(async () => {});
  await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(['wav'], 'local.wav')] } }); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); });
  expect(screen.getByText('Guardado local · GCS diferido')).toBeDefined();
  expect(screen.queryByText('● Google Cloud Storage')).toBeNull();
  expect(screen.getByRole('region', { name: 'Validar resultado' })).toBeDefined();
});

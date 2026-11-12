import { chooseModel } from "../../prediction/__tests__/selectorActions";
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import PredictionView from '../PredictionView';
import { confirmApiSession } from '@/lib/api';

const session = vi.hoisted(() => ({ user: { id: 1 } as { id: number } | null }));
vi.mock('@/components/auth/SessionBoundary', () => ({ useOptionalWebSession: () => session.user }));
const models = [301, 302].map(id => ({ id: `fama_trained_model_${id}`, name: `Birds v${id}`,
  classes: ['bird'], dataset_name: 'AvesChilenas', has_weights: true }));
const item = (id: number, model = 301) => ({ id, filename: `saved-${id}.wav`,
  timestamp: '2026-01-01T12:00:00Z', clase: 'bird', confianza: .8, modelo_id: `fama_trained_model_${model}` });
beforeEach(() => { session.user = { id: 1 }; vi.restoreAllMocks();
  URL.createObjectURL = vi.fn(() => 'blob:test'); URL.revokeObjectURL = vi.fn(); });

it('loads saved records after mounting and remounting, paginates, and separates models', async () => {
  global.fetch = vi.fn(async (input) => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models });
    if (url.includes('/api/inference/history')) {
      if (url.includes('302')) return Response.json({ items: [item(30, 302)], next_cursor: null });
      if (url.includes('cursor=20')) return Response.json({ items: [item(19)], next_cursor: null });
      return Response.json({ items: [item(20)], next_cursor: 20 });
    }
    return Response.json({});
  });
  const view = render(<PredictionView />); await act(async () => {});
  expect(screen.getByText('saved-20.wav')).toBeDefined();
  const request = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/api/inference/history'))!;
  expect(String(request[0])).toContain('model_id=fama_trained_model_301');
  expect(request[1]?.credentials).toBe('same-origin');
  const catalogue = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/api/models'))!;
  expect(String(catalogue[0])).toMatch(/\/api\/models$/);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Cargar más predicciones' })); });
  expect(screen.getByText('saved-19.wav')).toBeDefined();
  await chooseModel(models[1].name);
  expect(screen.queryByText('saved-20.wav')).toBeNull();
  expect(screen.getByText('saved-30.wav')).toBeDefined();
  view.unmount();
  render(<PredictionView />); await act(async () => {});
  expect(screen.getByText('saved-20.wav')).toBeDefined();
});

it('ignores a late history JSON after model or session changes', async () => {
  let finish!: (data: unknown) => void;
  global.fetch = vi.fn(async input => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models });
    if (url.includes('/api/inference/history') && url.includes('301'))
      return { ok: true, json: () => new Promise(resolve => { finish = resolve; }) } as Response;
    return Response.json({ items: [item(30, 302)], next_cursor: null });
  });
  const view = render(<PredictionView />); await act(async () => {});
  await chooseModel(models[1].name);
  await act(async () => { finish({ items: [item(20)], next_cursor: null }); });
  expect(screen.queryByText('saved-20.wav')).toBeNull();
  expect(screen.getByText('saved-30.wav')).toBeDefined();
  session.user = null; confirmApiSession();
  await act(async () => { view.rerender(<PredictionView />); });
  expect(screen.queryByText('saved-30.wav')).toBeNull();
});


it('refreshes persisted history after local inference without duplicating the record', async () => {
  let saved = false;
  global.fetch = vi.fn(async input => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models });
    if (url.includes('/api/inference/history')) return Response.json({ items: saved ? [item(21), item(20)] : [item(20)], next_cursor: null });
    if (url.includes('/api/predict?')) {
      saved = true;
      return Response.json({ filename: 'saved-21.wav', db_id: 21, clase: 'bird', confianza: .8,
        modelo_id: models[0].id, gcp_upload: false, local_audio_saved: true, cloud_status: 'deferred' });
    }
    return Response.json({});
  });
  const view = render(<PredictionView />); await act(async () => {});
  await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!,
    { target: { files: [new File(['wav'], 'upload.wav')] } }); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); });
  expect(screen.getAllByRole('row', { name: /saved-21\.wav/ })).toHaveLength(1);
  expect(screen.getByText('saved-20.wav')).toBeDefined();
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/api/inference/history'))).toHaveLength(2);
});

it('clears private history and ignores pending JSON when the account changes', async () => {
  let finish!: (data: unknown) => void;
  global.fetch = vi.fn(async input => {
    if (String(input).includes('/api/models')) return Response.json({ models });
    return { ok: true, json: () => new Promise(resolve => { finish = resolve; }) } as Response;
  });
  const view = render(<PredictionView />); await act(async () => {});
  const old = finish;
  session.user = { id: 2 }; confirmApiSession();
  await act(async () => { view.rerender(<PredictionView />); });
  await act(async () => { old({ items: [item(20)], next_cursor: null }); });
  expect(screen.queryByText('saved-20.wav')).toBeNull();
});

it('distinguishes a history loading failure from an empty history', async () => {
  global.fetch = vi.fn(async input => String(input).includes('/api/models')
    ? Response.json({ models }) : new Response(null, { status: 503 }));
  render(<PredictionView />); await act(async () => {});
  expect(screen.getByText('No se pudo cargar el historial de este modelo.')).toBeDefined();
  expect(screen.queryByText('Sin predicciones guardadas para este modelo.')).toBeNull();
});


it.each([[302, false, false], [301, false, false], [301, true, true]] as const)('uses persisted history only for response model=%s local=%s refreshFailure=%s', async (executed, local, failRefresh) => {
  let requests = 0;
  global.fetch = vi.fn(async input => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models });
    if (url.includes('/api/inference/history')) {
      if (requests++ > 0 && failRefresh) return new Response(null, { status: 503 });
      return Response.json({ items: [item(20)], next_cursor: null });
    }
    if (url.includes('/api/predict?')) return Response.json({ filename: 'wrong-model.wav', db_id: 99,
      modelo_id: `fama_trained_model_${executed}`, clase: 'bird', confianza: .8, gcp_upload: false, local_audio_saved: local });
    return Response.json({});
  });
  const view = render(<PredictionView />); await act(async () => {});
  await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!,
    { target: { files: [new File(['wav'], 'upload.wav')] } }); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); });
  expect(screen.queryByRole('row', { name: /wrong-model\.wav/ })).toBeNull();
  expect(screen.getByText('saved-20.wav')).toBeDefined();
});


it('refreshes persisted history for a declared standard model after inference', async () => {
  const declared = { id: 'declared-birds', name: 'Birds declared', classes: ['bird'],
    dataset_name: 'AvesChilenas', has_weights: true };
  const saved = { ...item(40), modelo_id: declared.id };
  let historyRequests = 0;
  global.fetch = vi.fn(async input => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models: [declared], default_model_id: declared.id });
    if (url.includes('/api/inference/history')) {
      historyRequests += 1;
      return Response.json({ items: historyRequests > 1 ? [saved] : [], next_cursor: null });
    }
    if (url.includes('/api/predict?')) return Response.json({ filename: 'optimistic.wav', db_id: 40,
      modelo_id: declared.id, clase: 'bird', confianza: .8, gcp_upload: false, local_audio_saved: true });
    return Response.json({});
  });
  const view = render(<PredictionView />); await act(async () => {});
  await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!,
    { target: { files: [new File(['wav'], 'upload.wav')] } }); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); });
  expect(historyRequests).toBe(2);
  expect(screen.getByText('saved-40.wav')).toBeDefined();
  expect(screen.queryByText('optimistic.wav')).toBeNull();
});

it('shows saved predictions as a table that becomes labelled cards on narrow screens', async () => {
  global.fetch = vi.fn(async (input) => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models });
    if (url.includes('/api/inference/history')) return Response.json({ items: [item(20)], next_cursor: null });
    return Response.json({});
  });
  render(<PredictionView />); await act(async () => {});
  const table = screen.getByRole('table', { name: 'Historial de predicciones' });
  const headers = within(table).getAllByRole('columnheader').map(cell => cell.textContent);
  expect(headers).toEqual(['Archivo', 'Diagnóstico', 'Modelo', 'Confianza']);
  // Wide screens show the header row; narrow screens hide it and label every cell instead.
  expect(table.querySelector('thead')!.className).toContain('hidden md:table-header-group');
  const row = within(table).getByRole('row', { name: /saved-20\.wav/ });
  expect(row.className).toContain('md:table-row');
  expect(within(row).getByText('80.0%')).toBeDefined();
  expect(table.textContent).not.toMatch(/ID de predicción/);
  ['Diagnóstico', 'Modelo', 'Confianza'].forEach(label =>
    expect(within(row).getByText(label).className).toContain('md:hidden'));
});

it('wraps long model names in the history instead of widening the column', async () => {
  const modelo = 'gatos y perros · Tríada 1 — EfficientNet-B0 + ConvNeXt-Nano + ResNet-34d';
  global.fetch = vi.fn(async (input) => {
    const url = String(input);
    if (url.includes('/api/models')) return Response.json({ models: [{ ...models[0], name: modelo }] });
    if (url.includes('/api/inference/history')) return Response.json({ items: [item(20)], next_cursor: null });
    return Response.json({});
  });
  render(<PredictionView />); await act(async () => {});
  const badge = within(screen.getByRole('table', { name: 'Historial de predicciones' })).getByText(modelo);
  expect(badge.className).not.toContain('break-all');
  expect(badge.className).toContain('break-words');
  // Table cells ignore max-width in auto layout, so the limit lives on content inside the cell.
  expect(badge.className).toMatch(/md:max-w-\[\d+rem\]/);
  const file = screen.getByText('saved-20.wav').closest<HTMLElement>("[class*='md:max-w-']")!;
  expect(screen.getByText('saved-20.wav').closest('td')!.contains(file)).toBe(true);
});

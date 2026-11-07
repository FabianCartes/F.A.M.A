import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import SessionBoundary from '../SessionBoundary';
import PredictionView from '@/components/views/PredictionView';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
const user = { id: 1, email: 'owner@example.test', nombre_completo: 'Owner', rol: 'investigador', activo: true };
const model = { id: 'private-model', name: 'Dataset propio · AudioCNN', dataset_name: 'dataset-propio', classes: ['ants', 'zebra'], has_weights: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(['focus', 'visibilitychange'])('keeps the selected private model while %s revalidates the same session and refreshes its catalogue', async (event) => {
  let refreshing = false;
  let finishSession!: (response: Response) => void;
  const catalogues: ((response: Response) => void)[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/api/auth/web/me')) return refreshing
      ? new Promise<Response>(resolve => { finishSession = resolve; }) : Response.json(user);
    if (url.includes('/api/models')) return refreshing
      ? new Promise<Response>(resolve => { catalogues.push(resolve); }) : Response.json({ models: [model] });
    return Response.json({});
  }));
  render(<SessionBoundary><PredictionView /></SessionBoundary>);
  await screen.findByRole('option', { name: model.name });
  refreshing = true;
  await act(async () => { fireEvent(event === 'focus' ? window : document, new Event(event)); });
  expect((screen.getByLabelText('Modelo:') as HTMLSelectElement).value).toBe(model.id);
  await act(async () => { finishSession(Response.json(user)); });
  expect(screen.queryByRole('option', { name: 'Sin modelos disponibles' })).toBeNull();
  expect((screen.getByLabelText('Modelo:') as HTMLSelectElement).value).toBe(model.id);
  await act(async () => { catalogues.forEach(resolve => resolve(Response.json({ models: [model] }))); });
  expect((screen.getByLabelText('Modelo:') as HTMLSelectElement).value).toBe(model.id);
});


it.each(['other-owner', 'unauthorized', 'logout'])('clears the private selection on %s and rejects late previous-owner catalogue responses', async (transition) => {
  let refreshing = false;
  let finishSession!: (response: Response) => void;
  const catalogues: ((response: Response) => void)[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/api/auth/web/logout')) return new Response(null, { status: 204 });
    if (url.endsWith('/api/auth/web/me')) return refreshing
      ? new Promise<Response>(resolve => { finishSession = resolve; }) : Response.json(user);
    if (url.includes('/api/models')) return refreshing
      ? new Promise<Response>(resolve => { catalogues.push(resolve); }) : Response.json({ models: [model] });
    return Response.json({});
  }));
  render(<SessionBoundary><PredictionView /></SessionBoundary>);
  await screen.findByRole('option', { name: model.name });
  refreshing = true;
  await act(async () => { fireEvent.focus(window); });
  await act(async () => {
    if (transition === 'logout') fireEvent.click(screen.getByRole('button', { name: 'Cerrar sesión' }));
    else finishSession(transition === 'unauthorized' ? Response.json({}, { status: 401 }) : Response.json({ ...user, id: 2 }));
  });
  expect(screen.queryByRole('option', { name: model.name })).toBeNull();
  await act(async () => { catalogues.forEach((resolve, index) => resolve(Response.json({ models: index === 0 ? [model] : [] }))); });
  expect(screen.queryByRole('option', { name: model.name })).toBeNull();
  if (transition === 'other-owner') expect((screen.getByLabelText('Modelo:') as HTMLSelectElement).value).toBe('');
  else expect(screen.queryByLabelText('Modelo:')).toBeNull();
});

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import FeedbackSyncPanel from '@/components/feedback/FeedbackSyncPanel';
import * as feedbackApi from '@/lib/api/feedbackApi';
import type { FeedbackSyncState } from '@/lib/schemas/feedback';

vi.mock('@/lib/api/feedbackApi', () => ({ getFeedbackSync: vi.fn() }));
const record: FeedbackSyncState = {
  id_retroalimentacion: 7, id_prediccion: 12, dataset_name: 'AvesChilenas',
  storage_class: 'rayadito', class_label: 'Rayadito', local_status: 'incorporated',
  sync_status: 'pending', attempts: 0, error_code: null,
};
const refresh = () => fireEvent.click(screen.getByRole('button', { name: 'Actualizar sincronización' }));
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
};
async function open() { await act(async () => { render(<FeedbackSyncPanel refreshKey={0} />); }); }

describe('accepted feedback synchronization through the rendered panel', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([record]);
  });

  it('distinguishes automatic upload retry, manual integrity attention and durable cloud acknowledgement', async () => {
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([
      { ...record, attempts: 2, error_code: 'upload_failed' },
      { ...record, id_retroalimentacion: 8, error_code: 'integrity_mismatch', attempts: 3 },
      { ...record, id_retroalimentacion: 9, sync_status: 'synced', attempts: 1 },
    ]);
    await open();
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText(/Subida fallida.*reintento automático/)).toBeDefined();
    expect(within(rows[1]).getByText(/Integridad inconsistente.*atención manual/)).toBeDefined();
    expect(within(rows[2]).getByText('Copia cloud confirmada')).toBeDefined();
    expect(rows[0].textContent).toContain('Feedback #7');
    expect(rows[0].textContent).toContain('Predicción #12');
    expect(rows[0].textContent).toContain('Directorio: rayadito');
    expect(within(rows[0]).getByRole('cell', { name: '2' })).toBeDefined();
    expect(screen.getByText(/no una auditoría física actual.*no una comprobación de existencia actual/)).toBeDefined();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('refreshes when focus returns or the document becomes visible, not while hidden', async () => {
    await open();
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([{ ...record, sync_status: 'synced' }]);
    await act(async () => { fireEvent(window, new Event('focus')); });
    expect(screen.getByText('Copia cloud confirmada')).toBeDefined();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await act(async () => { fireEvent(document, new Event('visibilitychange')); fireEvent(window, new Event('focus')); });
    expect(feedbackApi.getFeedbackSync).toHaveBeenCalledTimes(2);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([{ ...record, attempts: 4 }]);
    await act(async () => { fireEvent(document, new Event('visibilitychange')); });
    expect(screen.getByRole('cell', { name: '4' })).toBeDefined();
    vi.restoreAllMocks();
  });

  it('reports loading and an initial failure without claiming the records are empty', async () => {
    const pending = deferred<FeedbackSyncState[]>();
    vi.mocked(feedbackApi.getFeedbackSync).mockReturnValueOnce(pending.promise);
    await open();
    expect(screen.getByRole('status').textContent).toContain('Consultando');
    expect(screen.queryByText(/No hay registros/)).toBeNull();
    await act(async () => { pending.reject(new Error('503')); });
    expect(screen.getByRole('alert').textContent).toContain('No se pudo consultar');
    expect(screen.queryByText(/No hay registros/)).toBeNull();
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([]);
    await act(async () => { refresh(); });
    expect(screen.getByText('No hay registros recientes de sincronización.')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('preserves the last records on query failure and clears the error on successful refresh', async () => {
    await open();
    vi.mocked(feedbackApi.getFeedbackSync).mockRejectedValueOnce(new Error('offline'));
    await act(async () => { refresh(); });
    expect(screen.getByText('Rayadito')).toBeDefined();
    expect(screen.getByRole('alert').textContent).toContain('última consulta');
    await act(async () => { refresh(); });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it.each(['success', 'error'])('ignores an obsolete %s even if the API mock does not honor abort', async outcome => {
    const old = deferred<FeedbackSyncState[]>();
    vi.mocked(feedbackApi.getFeedbackSync).mockReturnValueOnce(old.promise);
    await open();
    const signal = vi.mocked(feedbackApi.getFeedbackSync).mock.calls[0][1]!;
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([{ ...record, sync_status: 'synced' }]);
    await act(async () => { refresh(); });
    expect(signal.aborted).toBe(true);
    await act(async () => {
      if (outcome === 'success') old.resolve([record]);
      else old.reject(new Error('late failure'));
    });
    expect(screen.getByText('Copia cloud confirmada')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('Pendiente de copia cloud')).toBeNull();
  });

  it('refreshes on parent invalidation and aborts requests and removes listeners on unmount', async () => {
    let unmount!: () => void;
    let rerender!: (element: React.ReactNode) => void;
    await act(async () => { ({ unmount, rerender } = render(<FeedbackSyncPanel refreshKey={0} />)); });
    const next = deferred<FeedbackSyncState[]>();
    vi.mocked(feedbackApi.getFeedbackSync).mockReturnValueOnce(next.promise);
    await act(async () => { rerender(<FeedbackSyncPanel refreshKey={1} />); });
    expect(screen.getByText('Rayadito')).toBeDefined();
    const signal = vi.mocked(feedbackApi.getFeedbackSync).mock.calls[1][1]!;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => {
      fireEvent(window, new Event('focus'));
      fireEvent(document, new Event('visibilitychange'));
      next.resolve([]);
    });
    expect(feedbackApi.getFeedbackSync).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('region')).toBeNull();
  });
});

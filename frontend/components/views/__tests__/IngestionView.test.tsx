import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import IngestionView from '../IngestionView';
import * as feedbackApi from '@/lib/api/feedbackApi';

vi.mock('@/lib/api/feedbackApi', () => ({ getPendingFeedback: vi.fn(), getFeedbackSync: vi.fn(), approveFeedback: vi.fn(), rejectFeedback: vi.fn(), getFeedbackStats: vi.fn(), sendFeedback: vi.fn() }));
const mockStatus = { connected: true, bucket: 'fama-audio-records-2026', total_objects: 120, total_bytes: 10485760, error: null };
const mockDatasets = [{ id: 'AvesChilenas', name: 'AvesChilenas', file_count: 45, classes: ['Chucao', 'rayadito'], total_size_bytes: 25000000, last_modified: null, local_file_count: 45, is_synced: true }];
const item = { id_retroalimentacion: 42, id_prediccion: 101, dataset_name: 'AvesChilenas', ruta_audio_prueba: 'test.wav', etiqueta_predicha: 'Chincol', etiqueta_corregida: 'Chucao', confianza: 0.942, fue_correcta: false, procesado: false, id_usuario: 1 };
const queue = () => within(screen.getByRole('region', { name: 'Revisar audios' }));
const incorporate = () => queue().getByRole('button', { name: 'Incorporar al dataset' });
const discard = () => queue().getByRole('button', { name: 'Descartar de la cola' });
async function open() { await act(async () => { render(<IngestionView />); }); }

describe('IngestionView persisted inference dataset and curation', () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValue([]);
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([]);
    vi.mocked(feedbackApi.approveFeedback).mockResolvedValue({ status: 'approved', local_status: 'incorporated', sync_status: 'pending', id_retroalimentacion: 42, destination_path: 'datasets/AvesChilenas/Chucao/test.wav', clase: 'Chucao', filename: 'test.wav' });
    vi.mocked(feedbackApi.rejectFeedback).mockResolvedValue({ status: 'rejected', id_retroalimentacion: 42 });
    global.fetch = vi.fn(async input => ({ ok: true, json: async () => String(input).includes('/datasets') ? { datasets: mockDatasets } : mockStatus }) as Response);
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('keeps accepted local audio visible separately while cloud is pending after approval', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([item]).mockResolvedValue([]);
    vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValueOnce([]).mockResolvedValue([{
      id_retroalimentacion: 42, id_prediccion: 101, dataset_name: 'AvesChilenas',
      storage_class: 'chucao', class_label: 'Chucao', local_status: 'incorporated',
      sync_status: 'pending', attempts: 0, error_code: null,
    }]);
    await open();
    await act(async () => { fireEvent.click(incorporate()); });
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
    const sync = within(screen.getByRole('region', { name: 'Sincronización de audios incorporados' }));
    expect(sync.getByText('AvesChilenas')).toBeDefined();
    expect(sync.getByText('Incorporado localmente')).toBeDefined();
    expect(sync.getByText(/Pendiente de copia cloud/)).toBeDefined();
    expect(screen.getByText(/puede preparar entrenamiento sin esperar GCS/)).toBeDefined();
    expect(screen.queryByText(/incorporado al dataset .* en GCS y en el dataset local/)).toBeNull();
  });

  it('only claims cloud acknowledgement when the approval response is synced', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([item]).mockResolvedValue([]);
    vi.mocked(feedbackApi.approveFeedback).mockResolvedValue({ status: 'approved', local_status: 'incorporated', sync_status: 'synced', id_retroalimentacion: 42, destination_path: 'datasets/AvesChilenas/Chucao/feedback_42.wav', clase: 'Chucao' });
    await open();
    await act(async () => { fireEvent.click(incorporate()); });
    expect(screen.getByText(/Audio #42 incorporado al dataset local.*Copia cloud confirmada/)).toBeDefined();
  });

  it('manual global refresh reads sync state without calling approval, discard or dataset download', async () => {
    await open();
    await act(async () => { fireEvent.click(screen.getByTitle('Refrescar estado de GCS y datos')); });
    expect(feedbackApi.getFeedbackSync).toHaveBeenCalledTimes(2);
    expect(feedbackApi.approveFeedback).not.toHaveBeenCalled();
    expect(feedbackApi.rejectFeedback).not.toHaveBeenCalled();
    expect(vi.mocked(global.fetch).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  });

  it('refreshes uncurated items on visible focus and does not restore a stale initial queue', async () => {
    let finish!: (items: typeof item[]) => void;
    vi.mocked(feedbackApi.getPendingFeedback).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValue([]);
    let unmount!: () => void;
    await act(async () => { ({ unmount } = render(<IngestionView />)); });
    const signal = vi.mocked(feedbackApi.getPendingFeedback).mock.calls[0][1];
    await act(async () => { fireEvent(window, new Event('focus')); });
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
    expect(signal?.aborted).toBe(true);
    await act(async () => { finish([item]); });
    expect(queue().queryByText('test.wav')).toBeNull();
    unmount();
    await act(async () => { fireEvent(window, new Event('focus')); fireEvent(document, new Event('visibilitychange')); });
    expect(feedbackApi.getPendingFeedback).toHaveBeenCalledTimes(2);
  });

  it('preserves prior uncurated items when a refresh fails and aborts an in-flight query on unmount', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([item]).mockRejectedValueOnce(new Error('offline'));
    let unmount!: () => void;
    await act(async () => { ({ unmount } = render(<IngestionView />)); });
    await act(async () => { fireEvent.click(screen.getByTitle('Actualizar cola de curación')); });
    expect(queue().getByText('test.wav')).toBeDefined();
    expect(screen.getByRole('alert').textContent).toContain('offline');
    vi.mocked(feedbackApi.getPendingFeedback).mockReturnValueOnce(new Promise(() => {}));
    await act(async () => { fireEvent.click(screen.getByTitle('Actualizar cola de curación')); });
    const signal = vi.mocked(feedbackApi.getPendingFeedback).mock.calls[2][1];
    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it('ignores late queue errors, preserves the current queue and refreshes only when visible', async () => {
    let fail!: (error: Error) => void;
    vi.mocked(feedbackApi.getPendingFeedback).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; })).mockResolvedValue([item]);
    await open();
    await act(async () => { fireEvent(window, new Event('focus')); });
    await act(async () => { fail(new Error('obsolete failure')); });
    expect(queue().getByText('test.wav')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await act(async () => { fireEvent(document, new Event('visibilitychange')); fireEvent(window, new Event('focus')); });
    expect(feedbackApi.getPendingFeedback).toHaveBeenCalledTimes(2);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValue([]);
    await act(async () => { fireEvent(document, new Event('visibilitychange')); });
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
    vi.restoreAllMocks();
  });

  it('removes blind direct upload and places review after dataset table', async () => {
    await open();
    expect(document.getElementById('panel-carga-audios')).toBeNull();
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByText(/Carga Jerárquica al Data Lake/)).toBeNull();
    expect(screen.queryByText(/Subir audios a GCS/)).toBeNull();
    expect(screen.getByRole('table').compareDocumentPosition(screen.getByRole('region', { name: 'Revisar audios' }))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('explains empty queue and navigates to prediction', async () => {
    const navigate = vi.fn();
    await act(async () => { render(<IngestionView onNavigate={navigate} />); });
    const empty = screen.getByTestId('curation-queue-empty');
    expect(empty.getAttribute('role')).toBe('status');
    expect(empty.getAttribute('aria-live')).toBe('polite');
    expect(screen.getByText(/No hay audios enviados a revisión pendientes/)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: /Ir a Inferencia Acústica/ }));
    expect(navigate).toHaveBeenCalledWith('predict');
  });

  it('shows pending snapshot automatically without selector and approves Rayadito despite lowercase directory catalog', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([{ ...item, etiqueta_predicha: 'Rayadito', etiqueta_corregida: null, fue_correcta: true }]).mockResolvedValueOnce([]);
    await open();
    expect(queue().queryByRole('combobox')).toBeNull();
    expect(queue().getByText('Dataset de inferencia')).toBeDefined();
    expect(queue().getByText('AvesChilenas')).toBeDefined();
    expect((incorporate() as HTMLButtonElement).disabled).toBe(false);
    await act(async () => { fireEvent.click(incorporate()); });
    expect(feedbackApi.approveFeedback).toHaveBeenCalledWith(42);
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
  });

  it('renders corrected and correct pending recordings and refreshes after incorporation and discard', async () => {
    const second = { ...item, id_retroalimentacion: 43, id_prediccion: 102, ruta_audio_prueba: 'second.wav', etiqueta_predicha: 'Rayadito', etiqueta_corregida: null, fue_correcta: true };
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([item, second]).mockResolvedValueOnce([second]).mockResolvedValueOnce([]);
    await open();
    expect(screen.getByText('test.wav')).toBeDefined();
    expect(queue().getByText('Chucao')).toBeDefined();
    expect(queue().getAllByText('94.2%')).toHaveLength(2);
    expect(queue().getAllByRole('button', { name: 'Incorporar al dataset' })).toHaveLength(2);
    await act(async () => { fireEvent.click(queue().getAllByRole('button', { name: 'Incorporar al dataset' })[0]); });
    expect(feedbackApi.approveFeedback).toHaveBeenCalledWith(42);
    await act(async () => { fireEvent.click(discard()); });
    expect(feedbackApi.rejectFeedback).toHaveBeenCalledWith(43);
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
  });

  it.each([null, undefined, ''])('explains missing association (%s), disables incorporation and still permits discard without guessing', async dataset_name => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([{ ...item, dataset_name }]).mockResolvedValueOnce([]);
    await open();
    expect(queue().queryByRole('combobox')).toBeNull();
    expect(queue().queryByText('AvesChilenas')).toBeNull();
    expect(queue().getByText(/Sin dataset de inferencia asociado/)).toBeDefined();
    expect((incorporate() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(incorporate());
    expect(feedbackApi.approveFeedback).not.toHaveBeenCalled();
    expect((discard() as HTMLButtonElement).disabled).toBe(false);
    await act(async () => { fireEvent.click(discard()); });
    expect(feedbackApi.rejectFeedback).toHaveBeenCalledWith(42);
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
  });

  it.each([undefined, [], ['Chincol']])('leaves class catalog validation to backend (%s) and uses the pending dataset ID, not display name', async classes => {
    global.fetch = vi.fn(async input => ({ ok: true, json: async () => String(input).includes('/datasets') ? { datasets: [{ ...mockDatasets[0], name: 'Visible name', classes }] } : mockStatus }) as Response);
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([item]).mockResolvedValueOnce([]);
    await open();
    expect(queue().getByText('AvesChilenas')).toBeDefined();
    expect(queue().queryByText('Visible name')).toBeNull();
    expect((incorporate() as HTMLButtonElement).disabled).toBe(false);
    await act(async () => { fireEvent.click(incorporate()); });
    expect(feedbackApi.approveFeedback).toHaveBeenCalledWith(42);
  });

  it.each(['empty', 'failed'])('does not require ingestion catalog when association is persisted (%s)', async mode => {
    global.fetch = vi.fn(async input => String(input).includes('/datasets') ? { ok: mode !== 'failed', status: 503, json: async () => ({ datasets: [] }) } as Response : { ok: true, json: async () => mockStatus } as Response);
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValue([item]);
    await open();
    expect(queue().getByText('AvesChilenas')).toBeDefined();
    expect((incorporate() as HTMLButtonElement).disabled).toBe(false);
  });

  it('blocks a missing validated class while allowing discard', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValue([{ ...item, etiqueta_corregida: null }]);
    await open();
    expect(queue().getByText(/No hay una clase validada/)).toBeDefined();
    expect((incorporate() as HTMLButtonElement).disabled).toBe(true);
    expect((discard() as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps failures pending, reports finalized conflicts and allows refreshing the queue', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValue([item]);
    vi.mocked(feedbackApi.approveFeedback).mockRejectedValueOnce(new Error('GCS no disponible'));
    vi.mocked(feedbackApi.rejectFeedback).mockRejectedValueOnce(Object.assign(new Error('Ya finalizado'), { statusCode: 409 }));
    await open();
    expect(screen.getByRole('heading', { name: 'Gestión de audios' })).toBeDefined();
    expect(screen.getByText(/Incorporar guarda el audio localmente.*sin esperar GCS/)).toBeDefined();
    await act(async () => { fireEvent.click(incorporate()); });
    expect(screen.getByRole('alert').textContent).toContain('GCS no disponible');
    expect(screen.getByText('test.wav')).toBeDefined();
    await act(async () => { fireEvent.click(discard()); });
    expect(screen.getByRole('alert').textContent).toContain('409');
    expect(screen.getByRole('alert').textContent).toContain('finalizado');
    expect(screen.getByText('test.wav')).toBeDefined();
    await act(async () => { fireEvent.click(screen.getByTitle('Actualizar cola de curación')); });
    expect(feedbackApi.getPendingFeedback).toHaveBeenCalledTimes(2);
  });

  it('retries by the same feedback ID after partial failure, blocks duplicate actions and refreshes datasets and queue', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([item]).mockResolvedValueOnce([item]).mockResolvedValueOnce([]);
    let reject!: (err: Error) => void;
    vi.mocked(feedbackApi.approveFeedback).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    await open();
    const button = incorporate();
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(discard());
    expect(feedbackApi.approveFeedback).toHaveBeenCalledTimes(1);
    expect(feedbackApi.rejectFeedback).not.toHaveBeenCalled();
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { reject(Object.assign(new Error('Escritura parcial'), { statusCode: 503 })); });
    expect(screen.getByRole('alert').textContent).toContain('sigue pendiente');
    await act(async () => { fireEvent.click(screen.getByTitle('Actualizar cola de curación')); });
    expect(queue().getByText('AvesChilenas')).toBeDefined();
    expect(queue().queryByRole('combobox')).toBeNull();
    await act(async () => { fireEvent.click(incorporate()); });
    expect(vi.mocked(feedbackApi.approveFeedback).mock.calls).toEqual([[42], [42]]);
    expect(screen.queryByText('test.wav')).toBeNull();
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes('/api/ingestion/datasets'))).toHaveLength(2);
  });

  it('does not represent a failed queue query as processed empty queue and supports retry', async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockRejectedValueOnce(new Error('Sin conexión')).mockResolvedValueOnce([]);
    await open();
    expect(screen.getByRole('alert').textContent).toContain('No fue posible cargar');
    expect(screen.queryByTestId('curation-queue-empty')).toBeNull();
    await act(async () => { fireEvent.click(screen.getByTitle('Actualizar cola de curación')); });
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByTestId('curation-queue-empty')).toBeDefined();
  });

  it('handles disconnected GCS and local dataset badge', async () => {
    global.fetch = vi.fn(async input => ({ ok: true, json: async () => String(input).includes('/datasets') ? { datasets: [{ ...mockDatasets[0], source: 'local', gcs_available: false }] } : { ...mockStatus, connected: false, error: 'Sin conexión' } }) as Response);
    await open();
    expect(screen.getByText(/GCP: Desconectado/)).toBeDefined();
    expect(screen.getByText(/Data Lake en modo local/)).toBeDefined();
    expect(screen.getByText('AvesChilenas')).toBeDefined();
    expect(screen.getByText('Local')).toBeDefined();
  });
});

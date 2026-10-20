import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, act, within } from "@testing-library/react";
import PredictionView from "../PredictionView";

const mockModels = [
  { id: 'chilean-birds-ensemble', name: 'Aves Chilenas · Super-Ensamble', description: 'Bioacústico', target_sr: 22050, duration_seconds: 5, classes: ['Chucao', 'Rayadito'], is_default: true, has_weights: true },
  { id: 'machine-model', name: 'Clasificador de maquinaria', description: 'Individual', target_sr: 22050, duration_seconds: 5, classes: ['alarm', 'normal'], is_default: false, has_weights: true },
  { id: 'car-engine-diagnostics-resnet34d-v2', name: 'ResNet-34d Industrial v2', description: 'Industrial', target_sr: 32000, duration_seconds: 1.5, classes: ['bad_ignition', 'low_oil'], is_default: false, has_weights: true },
];
const panel = () => within(screen.getByRole('region', { name: 'Validar resultado' }));
const choice = (name: string) => panel().getByRole('button', { name });
const submit = () => panel().getByRole('button', { name: 'Enviar a revisión' });

async function preparePrediction({ classes = ['alarm', 'normal'], dbId = 201, dataset = 'maquinaria-canonical' }: { classes?: string[]; dbId?: number | null; dataset?: string | null } = {}) {
  let nextId = dbId;
  let feedbackResponse: () => Promise<Response> = async () => ({ ok: true, json: async () => ({ id_retroalimentacion: 50, id_prediccion: nextId, fue_correcta: false, procesado: false }) }) as Response;
  let predictionResponse: () => Promise<Response> = async () => ({ ok: true, json: async () => ({ filename: 'machine.wav', db_id: nextId, clase: 'alarm', confianza: 0.9, gcp_upload: true, detalles: { dataset_name: dataset } }) }) as Response;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (url.includes('/api/models')) return { ok: true, json: async () => ({ models: mockModels.map(m => m.id === 'machine-model' ? { ...m, classes } : m) }) } as Response;
    if (url.includes('/api/model-info')) return { ok: false } as Response;
    if (url.includes('/api/predict')) return predictionResponse();
    if (url.endsWith('/api/feedback')) return feedbackResponse();
    throw new Error(`Unexpected URL ${url} ${options?.method}`);
  });
  global.fetch = fetchMock;
  URL.createObjectURL = vi.fn().mockReturnValue('blob:test');
  URL.revokeObjectURL = vi.fn();
  let view!: ReturnType<typeof render>;
  await act(async () => { view = render(<PredictionView />); });
  fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: 'machine-model' } });
  await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(['audio'], 'machine.wav')] } }); });
  const infer = async () => { await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ })); }); };
  await infer();
  return { infer, setId: (id: number) => { nextId = id; }, setFeedback: (response: () => Promise<Response>) => { feedbackResponse = response; }, setPrediction: (response: () => Promise<Response>) => { predictionResponse = response; }, predictionCalls: () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/predict')), feedbackCalls: () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/feedback')) };
}

describe('PredictionView validation and responsive controls', () => {
  beforeEach(() => { vi.resetAllMocks(); global.fetch = vi.fn(async (input) => String(input).includes('/api/models') ? { ok: true, json: async () => ({ models: mockModels }) } as Response : { ok: false } as Response); });

  it('shows response identity, uncalibrated score and real history IDs without synthetic badges', async () => {
    const api = await preparePrediction();
    api.setPrediction(async () => Response.json({ filename: 'actual.wav', db_id: 305, modelo: 'Executed CNN', clase: 'alarm', confianza: 0.8, gcp_upload: false }));
    await api.infer();
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain('Executed CNN');
    expect(screen.getByText('Puntuación del modelo (sin calibración acreditada):')).toBeDefined();
    expect(screen.getByText('ID de predicción: 305')).toBeDefined();
    expect(screen.queryByText(/AVE-|ENG-/)).toBeNull();
    api.setPrediction(async () => Response.json({ filename: 'unpersisted.wav', db_id: null, clase: 'alarm', confianza: 0.7, gcp_upload: false }));
    await api.infer();
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain('No informado por la API');
    expect(screen.getByText('ID de predicción no disponible')).toBeDefined();
  });

  it('warns when executed identity differs from the request snapshot, not the current selection', async () => {
    const api = await preparePrediction();
    let resolve!: (response: Response) => void;
    api.setPrediction(() => new Promise(done => { resolve = done; }));
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ }));
    fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: mockModels[2].id } });
    await act(async () => { resolve(Response.json({ filename: 'different.wav', modelo_id: mockModels[2].id, modelo: 'Executed industrial', clase: 'bad_ignition', confianza: 0.8, gcp_upload: false })); });
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain(mockModels[2].id);
    expect(screen.getByRole('alert').textContent).toContain('difiere del modelo solicitado');
    expect(screen.getByRole('alert').textContent).toContain('machine-model');
    api.setPrediction(async () => Response.json({ filename: 'matching.wav', modelo_id: mockModels[2].id, modelo: 'Executed industrial', clase: 'bad_ignition', confianza: 0.8, gcp_upload: false }));
    await api.infer();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('does not invent model health, metrics, versions or ensemble participants for an individual result', async () => {
    const api = await preparePrediction();
    expect(screen.getByText('Dispositivo de esta selección: No comprobado')).toBeDefined();
    expect(screen.queryByText(/Sin métricas publicadas|Accuracy histórica|F1 histórico|Precision histórica|Evaluación en test set/)).toBeNull();
    expect(screen.queryByText('v3.0.0')).toBeNull();
    expect(screen.queryByText(/Dispositivo: CPU/)).toBeNull();
    api.setPrediction(async () => Response.json({ filename: 'individual.wav', clase: 'alarm', confianza: 0.8, gcp_upload: false, modelos_activos: ['Invented participant (55%)'] }));
    await api.infer();
    expect(screen.queryByText(/Invented participant/)).toBeNull();
    fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: 'chilean-birds-ensemble' } });
    expect(screen.queryByText(/Invented participant/)).toBeNull();
    expect(screen.getByText('Veredicto del Modelo')).toBeDefined();
  });

  it('keeps ensemble participants attached to the executed result after selection changes', async () => {
    const api = await preparePrediction();
    fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: 'chilean-birds-ensemble' } });
    api.setPrediction(async () => Response.json({ filename: 'ensemble.wav', clase: 'Chucao', confianza: 0.8, gcp_upload: false, modelo: 'Executed ensemble', modelos_activos: ['Actual CNN (42%)'] }));
    await api.infer();
    expect(screen.getByText('✓ Actual CNN (42%)')).toBeDefined();
    fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: 'machine-model' } });
    expect(screen.getByText('✓ Actual CNN (42%)')).toBeDefined();
    expect(screen.getByText('Veredicto del Super-Ensamble')).toBeDefined();
    expect(screen.getByText('Audio original · canal 1 (mono/estéreo)')).toBeDefined();
    expect(screen.queryByText(/Escaneando:|Re-escanear/)).toBeNull();
  });

  it('does not fabricate an acoustic contract when catalogue fields are absent', async () => {
    global.fetch = vi.fn(async (input) => String(input).includes('/api/models')
      ? Response.json({ models: [{ id: 'efficientnet', name: 'EfficientNet', classes: ['Chucao'] }] })
      : new Response('', { status: 503 }));
    await act(async () => { render(<PredictionView />); });
    expect(screen.getByText(/Contrato publicado: Audios de duración no publicada a frecuencia no publicada/)).toBeDefined();
    expect(screen.queryByText(/5\.0s|22 kHz|Operativo|55%/)).toBeNull();
    expect(screen.getByText('Tiempo total de solicitud: no disponible')).toBeDefined();
  });

  it('rejects oversized WAV before browser decoding or prediction HTTP', async () => {
    const api = await preparePrediction();
    const file = new File(['audio'], 'large.wav');
    Object.defineProperty(file, 'size', { value: 104857601 });
    const decode = vi.fn();
    Object.defineProperty(file, 'arrayBuffer', { value: decode });
    await act(async () => { fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } }); });
    expect(screen.getByText(/El archivo supera el límite de 100 MiB/)).toBeDefined();
    expect(decode).not.toHaveBeenCalled();
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('region', { name: 'Validar resultado' })).toBeNull();
    await api.infer();
    expect(api.predictionCalls()).toHaveLength(1);
  });

  it.each([
    [new Response('<html>Bad gateway</html>', { status: 502 }), 'Error HTTP 502'],
    [new Response('', { status: 413 }), 'Error HTTP 413'],
    [new Response('upstream unavailable', { status: 503 }), 'Error HTTP 503'],
    [Response.json({ detail: 'Audio demasiado grande' }, { status: 413 }), 'Audio demasiado grande'],
    [Response.json({ detail: { message: 'Catálogo incompleto', errors: [] } }, { status: 503 }), 'Catálogo incompleto'],
    [Response.json({ detail: [{ msg: 'Campo requerido' }] }, { status: 422 }), 'Campo requerido'],
    [Response.json({ detail: { unknown: true } }, { status: 500 }), 'Error HTTP 500'],
    [Response.json({}), 'Respuesta de inferencia inválida'],
    [Response.json({ filename: 'bad.wav', clase: 'alarm', confianza: '0.9', gcp_upload: true }), 'Respuesta de inferencia inválida'],
    [Response.json({ filename: 'bad.wav', clase: 'alarm', confianza: 2, gcp_upload: true }), 'Respuesta de inferencia inválida'],
    [new Response('not json'), 'Respuesta de inferencia inválida'],
  ])('reports HTTP and malformed success honestly (%s)', async (response, message) => {
    const api = await preparePrediction();
    api.setPrediction(async () => response);
    await api.infer();
    expect(screen.getByText(message, { exact: false })).toBeDefined();
    expect(screen.queryByRole('region', { name: 'Validar resultado' })).toBeNull();
    expect(screen.queryByText(/<html>|Unexpected token|\[object Object\]/)).toBeNull();
  });

  it('accepts the exact inclusive file limit', async () => {
    const api = await preparePrediction();
    const file = new File(['audio'], 'boundary.wav');
    Object.defineProperty(file, 'size', { value: 104857600 });
    await act(async () => { fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } }); });
    await api.infer();
    expect(api.predictionCalls()).toHaveLength(2);
    expect(screen.getByRole('region', { name: 'Validar resultado' })).toBeDefined();
  });

  it('offers compact wrapping Check/X buttons with explicit pressed state, separate submit and no default', async () => {
    const api = await preparePrediction();
    const correct = choice('Correcta');
    const incorrect = choice('Incorrecta');
    expect(panel().queryByRole('radio')).toBeNull();
    // Structural CSS regression only: jsdom does not measure rendered button sizes.
    expect(correct.parentElement).toBe(incorrect.parentElement);
    expect(correct.parentElement?.classList.contains('flex')).toBe(true);
    expect(correct.parentElement?.classList.contains('flex-wrap')).toBe(true);
    expect(correct.parentElement?.classList.contains('grid')).toBe(false);
    for (const button of [correct, incorrect]) {
      expect(button.getAttribute('type')).toBe('button');
      expect(button.getAttribute('aria-pressed')).toBe('false');
      for (const token of ['px-3', 'py-2', 'rounded-lg', 'text-xs', 'gap-2', 'border']) {
        expect(button.classList.contains(token)).toBe(true);
      }
      for (const token of ['min-h-16', 'px-5', 'py-4', 'text-base', 'border-2', 'w-full', 'flex-1']) {
        expect(button.classList.contains(token)).toBe(false);
      }
      expect(button.querySelector('svg')?.getAttribute('class')).toBe('w-4 h-4');
      expect(button.className).toContain('focus-visible:');
      expect(button.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    }
    expect(correct.className).toContain('emerald');
    expect(incorrect.className).toContain('red');
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    expect(submit().className).toBe('px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed');
    correct.focus();
    expect(document.activeElement).toBe(correct);
    fireEvent.click(correct);
    expect(correct.getAttribute('aria-pressed')).toBe('true');
    expect(incorrect.getAttribute('aria-pressed')).toBe('false');
    expect(api.feedbackCalls()).toHaveLength(0);
    await act(async () => { fireEvent.click(submit()); });
    expect(JSON.parse(String(api.feedbackCalls()[0][1]?.body))).toEqual({ id_prediccion: 201, fue_correcta: true, etiqueta_corregida: null, id_usuario: 1 });
    expect(screen.getByText(/Enviado a revisión/)).toBeDefined();
    expect(panel().queryByRole('button', { name: 'Enviar a revisión' })).toBeNull();
  });

  it('shows the executed dataset snapshot and freezes nonbird correction catalog after model changes', async () => {
    const api = await preparePrediction();
    expect(screen.getByText(/Dataset de inferencia/).parentElement?.textContent).toContain('maquinaria-canonical');
    fireEvent.click(choice('Incorrecta'));
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    const correction = panel().getByLabelText('Clase correcta');
    expect(within(correction).getAllByRole('option').map(o => o.getAttribute('value'))).toEqual(['', 'alarm', 'normal']);
    fireEvent.change(correction, { target: { value: 'normal' } });
    fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: mockModels[2].id } });
    expect(panel().getByLabelText('Clase correcta')).toBe(correction);
    expect(panel().queryByRole('option', { name: 'low_oil' })).toBeNull();
    expect(screen.getByText(/Dataset de inferencia/).parentElement?.textContent).toContain('maquinaria-canonical');
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain('No informado por la API');
    await act(async () => { fireEvent.click(submit()); });
    expect(JSON.parse(String(api.feedbackCalls()[0][1]?.body))).toEqual({ id_prediccion: 201, fue_correcta: false, etiqueta_corregida: 'normal', id_usuario: 1 });
  });

  it.each([null, undefined])('does not infer missing result association (%s) from model, class or filename', async dataset => {
    const api = await preparePrediction({ dataset: null });
    api.setPrediction(async () => ({ ok: true, json: async () => ({ filename: 'AvesChilenas.wav', db_id: 202, clase: 'Rayadito', confianza: 0.9, gcp_upload: true, ...(dataset === undefined ? {} : { detalles: { dataset_name: dataset } }) }) }) as Response);
    await api.infer();
    expect(screen.getByText(/Sin dataset de inferencia asociado/)).toBeDefined();
    expect(screen.queryByText('maquinaria-canonical')).toBeNull();
  });

  it('disables duplicate submission and preserves correction and selection after network failure', async () => {
    const api = await preparePrediction();
    fireEvent.click(choice('Incorrecta'));
    fireEvent.change(panel().getByLabelText('Clase correcta'), { target: { value: 'normal' } });
    let reject!: (reason: Error) => void;
    api.setFeedback(() => new Promise((_, fail) => { reject = fail; }));
    fireEvent.click(submit());
    fireEvent.click(panel().getByRole('button', { name: 'Enviando a revisión…' }));
    expect(api.feedbackCalls()).toHaveLength(1);
    expect(choice('Incorrecta').matches(':disabled')).toBe(true);
    expect(choice('Correcta').matches(':disabled')).toBe(true);
    await act(async () => { reject(new Error('Sin conexión')); });
    expect(screen.getByRole('alert').textContent).toContain('Sin conexión');
    expect(choice('Incorrecta').getAttribute('aria-pressed')).toBe('true');
    expect((panel().getByLabelText('Clase correcta') as HTMLSelectElement).value).toBe('normal');
    api.setFeedback(async () => ({ ok: true, json: async () => ({ id_retroalimentacion: 50, id_prediccion: 201, fue_correcta: false, etiqueta_corregida: 'normal', procesado: false }) }) as Response);
    await act(async () => { fireEvent.click(submit()); });
    expect(api.feedbackCalls()).toHaveLength(2);
    expect(api.feedbackCalls()[0][1]?.body).toBe(api.feedbackCalls()[1][1]?.body);
  });

  it('does not carry submitted state or an old response into a new prediction', async () => {
    const api = await preparePrediction();
    fireEvent.click(choice('Correcta'));
    let resolve!: (response: Response) => void;
    api.setFeedback(() => new Promise(done => { resolve = done; }));
    fireEvent.click(submit());
    api.setId(202);
    await api.infer();
    await act(async () => { resolve({ ok: true, json: async () => ({ id_retroalimentacion: 50, id_prediccion: 201, fue_correcta: true, procesado: false }) } as Response); });
    expect(screen.queryByText(/Enviado a revisión/)).toBeNull();
    expect(choice('Correcta').getAttribute('aria-pressed')).toBe('false');
    expect(choice('Incorrecta').getAttribute('aria-pressed')).toBe('false');
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    api.setFeedback(async () => ({ ok: true, json: async () => ({ id_retroalimentacion: 51, id_prediccion: 202, fue_correcta: true, procesado: false }) }) as Response);
    fireEvent.click(choice('Correcta'));
    await act(async () => { fireEvent.click(submit()); });
    expect(JSON.parse(String(api.feedbackCalls()[1][1]?.body)).id_prediccion).toBe(202);
    api.setId(203);
    await api.infer();
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
  });

  it('freezes catalog at request time and takes dataset from response even when model changes in flight', async () => {
    const api = await preparePrediction();
    let resolve!: (response: Response) => void;
    api.setPrediction(() => new Promise(done => { resolve = done; }));
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar inferencia/ }));
    fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: mockModels[2].id } });
    await act(async () => { resolve({ ok: true, json: async () => ({ filename: 'machine.wav', db_id: 202, clase: 'alarm', confianza: 0.9, gcp_upload: true, detalles: { dataset_name: 'executed-target' } }) } as Response); });
    fireEvent.click(choice('Incorrecta'));
    expect(panel().getByRole('option', { name: 'normal' })).toBeDefined();
    expect(screen.getByText(/Dataset de inferencia/).parentElement?.textContent).toContain('executed-target');
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain('No informado por la API');
  });

  it('honestly disables correction with missing catalog but allows correct feedback', async () => {
    const api = await preparePrediction({ classes: [] });
    fireEvent.click(choice('Incorrecta'));
    expect(screen.getByText(/Catálogo de clases no disponible/)).toBeDefined();
    expect(panel().queryByLabelText('Clase correcta')).toBeNull();
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(choice('Correcta'));
    await act(async () => { fireEvent.click(submit()); });
    expect(api.feedbackCalls()).toHaveLength(1);
  });

  it('does not submit without a persisted prediction ID', async () => {
    const api = await preparePrediction({ dbId: null });
    expect(screen.getByText(/no tiene un ID de predicción válido/)).toBeDefined();
    expect(choice('Correcta').matches(':disabled')).toBe(true);
    fireEvent.click(choice('Correcta'));
    fireEvent.click(submit());
    expect(api.feedbackCalls()).toHaveLength(0);
  });

  it('locks choices and retries on finalized conflicts', async () => {
    const api = await preparePrediction();
    api.setFeedback(async () => ({ ok: false, status: 409, json: async () => ({ detail: 'Predicción finalizada' }) }) as Response);
    fireEvent.click(choice('Correcta'));
    await act(async () => { fireEvent.click(submit()); });
    expect(screen.getByRole('alert').textContent).toContain('409');
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    expect(choice('Correcta').matches(':disabled')).toBe(true);
    expect(choice('Incorrecta').matches(':disabled')).toBe(true);
  });

  it('renders responsive heading, model groups, latency and deterministic inference contracts', async () => {
    render(<PredictionView />);
    expect(screen.getByText('Predicción y Monitoreo Acústico')).toBeDefined();
    const select = await screen.findByLabelText('Modelo:');
    await screen.findByRole('option', { name: mockModels[2].name });
    expect(select.className).toContain('truncate');
    expect(select.className).toContain('min-w-0');
    const latency = screen.getByText('Tiempo total de solicitud: no disponible').closest('div');
    expect(latency?.className).toContain('shrink-0');
    expect(latency?.className).toContain('whitespace-nowrap');
    expect(select.querySelector('optgroup[label="Bioacústica (Aves Chilenas)"]')).not.toBeNull();
    expect(select.querySelector('optgroup[label="Diagnóstico Industrial (Motores)"]')).not.toBeNull();
    expect(screen.getByText(/Audios de 5\.0s a 22\.050 Hz/)).toBeDefined();
    await act(async () => { fireEvent.change(select, { target: { value: mockModels[2].id } }); });
    expect(screen.getByText(/Grupo seleccionado: Diagnóstico Acústico de Motores/)).toBeDefined();
    expect(screen.getByText('2 Fallas Mecánicas')).toBeDefined();
    expect(screen.getByText('1.5s @ 32 kHz')).toBeDefined();
    expect(screen.getByText(/Audios de 1\.5s a 32\.000 Hz/)).toBeDefined();
    expect(screen.getByText('Falla de Encendido / Combustión Irregular')).toBeDefined();
    expect(screen.getByText(/Especificaciones del Modelo Individual Seleccionado/)).toBeDefined();
    expect(screen.queryByText(/55%/)).toBeNull();
    expect(screen.queryByText(/30%/)).toBeNull();
    expect(screen.queryByText(/15%/)).toBeNull();
    expect(screen.queryByText(/Tríada Completa Habilitada/)).toBeNull();
  });

  it('does not invent operational triad cards, historical scores or an unmeasured latency', async () => {
    await act(async () => { render(<PredictionView />); });

    expect(screen.queryAllByText('Entrenado y Operativo')).toHaveLength(0);
    expect(screen.queryByText(/Tríada Completa Habilitada/)).toBeNull();
    expect(screen.queryByText(/Super-Ensamble Activo/)).toBeNull();
    expect(screen.queryAllByText(/88\.68%|88\.31%|81\.44%/)).toHaveLength(0);
    expect(screen.getByText('Tiempo total de solicitud: no disponible')).toBeDefined();
    expect(screen.getByText('Estado del servicio legacy no disponible para esta selección.')).toBeDefined();
    expect(screen.getByRole('option', { name: mockModels[0].name })).toBeDefined();
  });

  it('renders registration, local availability and observed load as separate facts', async () => {
    const status = { state_scope: 'legacy_bioacoustic_service', domain_supported: true, selected_domain: 'AvesChilenas',
      device: 'cpu', active_mode: 'individual', ensemble_ready: false, is_fallback: false,
      model_name: 'ConvNeXt-Nano (Modo Individual)', active_models: [], total_classes: 2, classes: ['Chucao', 'Rayadito'],
      triad_status: [
        { name: 'EfficientNet-B0', weight: null, is_ready: false, is_loaded: false, is_registered: true,
          weights_available: false, weights_source: 'registered_reference', accuracy: 0, loss: 0,
          recorded_checkpoint: 'registered.pt', loaded_checkpoint: null, metrics_source: 'database_record' },
        { name: 'ConvNeXt-Nano', weight: 1, is_ready: true, is_loaded: true, is_registered: true,
          weights_available: true, weights_source: 'loaded_checkpoint_file', accuracy: null, loss: null,
          recorded_checkpoint: 'different.pt', loaded_checkpoint: 'loaded.pt', metrics_source: 'database_record' },
        { name: 'ResNet-34d', weight: null, is_ready: false, is_loaded: false, is_registered: null,
          weights_available: null, accuracy: null, loss: null, recorded_checkpoint: null, loaded_checkpoint: null },
      ] };
    global.fetch = vi.fn(async input => ({ ok: true, json: async () => String(input).includes('/api/models')
      ? { models: mockModels } : status }) as Response);

    await act(async () => { render(<PredictionView />); });

    const state = within(screen.getByRole('region', { name: 'Estado del ensamble legacy' }));
    const registered = within(state.getByRole('article', { name: 'EfficientNet-B0' }));
    expect(registered.getByText('Registro BD: Registrado')).toBeDefined();
    expect(registered.getByText('Archivo local: Ausente')).toBeDefined();
    expect(registered.getByText('No cargado')).toBeDefined();
    expect(registered.getByText('0.0%')).toBeDefined();
    expect(registered.getByText('registered.pt')).toBeDefined();
    const loaded = within(state.getByRole('article', { name: 'ConvNeXt-Nano' }));
    expect(loaded.getByText('Cargado en memoria')).toBeDefined();
    expect(loaded.getByText('Peso cargado: 100%')).toBeDefined();
    expect(loaded.getByText('different.pt')).toBeDefined();
    expect(loaded.getByText('Checkpoint cargado: loaded.pt')).toBeDefined();
    expect(screen.queryByText(/Entrenado y Operativo|Tríada Completa Habilitada/)).toBeNull();
  });

  it('does not fabricate industrial components when the legacy service does not cover that domain', async () => {
    const engine = { ...mockModels[2], id: 'car-engine-diagnostics-super-ensemble', name: 'Engine ensemble' };
    global.fetch = vi.fn(async input => ({ ok: true, json: async () => String(input).includes('/api/models')
      ? { models: [...mockModels, engine] }
      : { state_scope: 'legacy_bioacoustic_service', domain_supported: false, selected_domain: 'engine_diagnostics',
          triad_status: [], active_models: [], classes: [], total_classes: 0, model_name: null, device: 'cpu', is_fallback: false } }) as Response);
    await act(async () => { render(<PredictionView />); });

    await act(async () => { fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: engine.id } }); });

    expect(screen.getByText('Estado del servicio legacy no disponible para esta selección.')).toBeDefined();
    expect(screen.queryAllByText('Entrenado y Operativo')).toHaveLength(0);
    expect(screen.queryByText('Peso cargado: 40%')).toBeNull();
    expect(screen.getByRole('option', { name: engine.name })).toBeDefined();
  });

  it('uses the execution list rather than unrelated legacy active-component labels', async () => {
    const api = await preparePrediction();
    api.setPrediction(async () => ({ ok: true, json: async () => ({ filename: 'machine.wav', db_id: 202,
      clase: 'alarm', confianza: 0.9, gcp_upload: true, modelo: 'Actual executed predictor',
      modelos_activos: ['Wrong legacy component (100%)'], modelos_ejecutados: ['Actual executed predictor'],
      detalles: { dataset_name: 'maquinaria-canonical' } }) }) as Response);

    await api.infer();

    expect(screen.queryByText(/Wrong legacy component/)).toBeNull();
    expect(screen.getByText('✓ Actual executed predictor')).toBeDefined();
  });

  it('does not apply the legacy service device or an assumed test split to an individual selection', async () => {
    await act(async () => { render(<PredictionView />); });
    await act(async () => { fireEvent.change(screen.getByLabelText('Modelo:'), { target: { value: 'machine-model' } }); });

    expect(screen.queryByText('Dispositivo: CPU')).toBeNull();
    expect(screen.queryByText('Evaluación en test set')).toBeNull();
    expect(screen.getByText('Dispositivo de esta selección: No comprobado')).toBeDefined();
  });

  it('does not invent an audio contract when the catalogue has no selectable model', async () => {
    global.fetch = vi.fn(async input => String(input).includes('/api/models')
      ? { ok: true, json: async () => ({ models: [] }) } as Response : { ok: false } as Response);

    await act(async () => { render(<PredictionView />); });

    expect(screen.queryByText('5.0s @ 22 kHz')).toBeNull();
    expect(screen.getByText('duración no publicada @ frecuencia no publicada')).toBeDefined();
    expect((screen.getByRole('button', { name: /Ejecutar inferencia/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('reports an observed legacy fallback without attributing it to the selected predictor', async () => {
    const status = { state_scope: 'legacy_bioacoustic_service', domain_supported: true, selected_domain: 'AvesChilenas',
      device: 'cpu', active_mode: 'fallback', ensemble_ready: false, is_fallback: true, model_name: 'AudioCNN (Fallback)',
      active_models: [{ name: 'AudioCNN', weight: 1, checkpoint: 'augmented_best.pt' }], total_classes: 2,
      classes: ['Chucao', 'Rayadito'], triad_status: ['EfficientNet-B0', 'ConvNeXt-Nano', 'ResNet-34d'].map(name => ({
        name, weight: null, is_ready: false, is_loaded: false, is_registered: false, weights_available: false,
        accuracy: null, loss: null, checkpoint: null, updated_at: null })) };
    global.fetch = vi.fn(async input => ({ ok: true, json: async () => String(input).includes('/api/models')
      ? { models: mockModels } : status }) as Response);

    await act(async () => { render(<PredictionView />); });

    expect(screen.getByText(/Fallback cargado en el servicio legacy: AudioCNN/)).toBeDefined();
    expect(screen.getByText(/No confirma uso por el predictor seleccionado/)).toBeDefined();
    expect(screen.queryAllByText('Entrenado y Operativo')).toHaveLength(0);
  });
});

// Independent U7 / S4 baseline-preservation regression.
describe("U7IndependentStable", () => {
  it.each([false, true])("keeps feedback and checkpoint identity after refresh failure=%s", async failed => {
    const api = await preparePrediction();
    api.setPrediction(async () => Response.json({ filename: "stable.wav", db_id: 902, clase: "alarm",
      confianza: 0, gcp_upload: false, modelo: "Stable predictor", modelo_id: "machine-model",
      detalles: { dataset_name: "maquinaria-canonical", loaded_checkpoint_sha256: "d".repeat(64) } }));
    await api.infer();
    const checkpoint = screen.getByRole("region", { name: "Identidad del checkpoint del resultado" }).textContent;
    const originalFetch = fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) =>
      String(input).includes("/api/models")
        ? failed ? new Response(null, { status: 503 }) : Response.json({ models: [mockModels[2]] })
        : originalFetch(input, options));
    fireEvent.change(screen.getByLabelText("Modelo:"), { target: { value: mockModels[2].id } });
    await act(async () => { fireEvent(window, new Event("focus")); });
    expect(screen.getByRole("region", { name: "Identidad del checkpoint del resultado" }).textContent).toBe(checkpoint);
    expect(checkpoint).toContain("d".repeat(64));
    expect(screen.getByText("Modelo ejecutado:").parentElement?.textContent).toBe("Modelo ejecutado:Stable predictor (machine-model)");
    expect(screen.getByText("ID de predicción: 902")).toBeDefined();
    if (failed) expect(screen.getByRole("alert").textContent).toBe("No se pudo actualizar el catálogo de modelos (HTTP 503). Se conserva el último catálogo disponible; vuelve a esta ventana para reintentar.");
    fireEvent.click(choice("Incorrecta"));
    expect(within(panel().getByLabelText("Clase correcta")).getAllByRole("option").map(option => option.getAttribute("value"))).toEqual(["", "alarm", "normal"]);
    fireEvent.change(panel().getByLabelText("Clase correcta"), { target: { value: "normal" } });
    api.setFeedback(async () => Response.json({ id_retroalimentacion: 72, id_prediccion: 902, fue_correcta: false, procesado: false }));
    await act(async () => { fireEvent.click(submit()); });
    expect(api.predictionCalls()).toHaveLength(2);
    expect(api.feedbackCalls()).toHaveLength(1);
    expect(JSON.parse(String(api.feedbackCalls()[0][1]?.body))).toEqual({ id_prediccion: 902, fue_correcta: false, etiqueta_corregida: "normal", id_usuario: 1 });
  });
});

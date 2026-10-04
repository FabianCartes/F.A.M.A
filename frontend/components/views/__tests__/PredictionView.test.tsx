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
  return { infer, setId: (id: number) => { nextId = id; }, setFeedback: (response: () => Promise<Response>) => { feedbackResponse = response; }, setPrediction: (response: () => Promise<Response>) => { predictionResponse = response; }, feedbackCalls: () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/feedback')) };
}

describe('PredictionView validation and responsive controls', () => {
  beforeEach(() => { vi.resetAllMocks(); global.fetch = vi.fn(async (input) => String(input).includes('/api/models') ? { ok: true, json: async () => ({ models: mockModels }) } as Response : { ok: false } as Response); });

  it('offers large semantic Check/X buttons with explicit pressed state, separate submit and no default', async () => {
    const api = await preparePrediction();
    const correct = choice('Correcta');
    const incorrect = choice('Incorrecta');
    expect(panel().queryByRole('radio')).toBeNull();
    for (const button of [correct, incorrect]) {
      expect(button.getAttribute('type')).toBe('button');
      expect(button.getAttribute('aria-pressed')).toBe('false');
      expect(button.className).toContain('min-h-');
      expect(button.className).toContain('focus-visible:');
      expect(button.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    }
    expect(correct.className).toContain('emerald');
    expect(incorrect.className).toContain('red');
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
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
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain('Clasificador de maquinaria');
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
    expect(screen.getByText('Modelo ejecutado:').parentElement?.textContent).toContain('Clasificador de maquinaria');
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
    const latency = screen.getByText(/Latencia:\s*0\.14s/).closest('div');
    expect(latency?.className).toContain('shrink-0');
    expect(latency?.className).toContain('whitespace-nowrap');
    expect(select.querySelector('optgroup[label="Bioacústica (Aves Chilenas)"]')).not.toBeNull();
    expect(select.querySelector('optgroup[label="Diagnóstico Industrial (Motores)"]')).not.toBeNull();
    expect(screen.getByText(/Audios de 5\.0s a 22\.050 Hz/)).toBeDefined();
    await act(async () => { fireEvent.change(select, { target: { value: mockModels[2].id } }); });
    expect(screen.getByText(/Dominio Activo: Diagnóstico Acústico de Motores/)).toBeDefined();
    expect(screen.getByText('2 Fallas Mecánicas')).toBeDefined();
    expect(screen.getByText('1.5s @ 32 kHz')).toBeDefined();
    expect(screen.getByText(/Audios de 1\.5s a 32\.000 Hz/)).toBeDefined();
    expect(screen.getByText('Falla de Encendido / Combustión Irregular')).toBeDefined();
    expect(screen.getByText(/Especificaciones del Modelo Individual Activo/)).toBeDefined();
    expect(screen.queryByText(/55%/)).toBeNull();
    expect(screen.queryByText(/30%/)).toBeNull();
    expect(screen.queryByText(/15%/)).toBeNull();
    expect(screen.queryByText(/Tríada Completa Habilitada/)).toBeNull();
  });
});

import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { it, expect, vi, afterEach, describe } from 'vitest';
import TrainingView from '@/components/views/TrainingView';
import Boundary from '@/components/auth/SessionBoundary';
import SidebarSession from '@/components/SidebarSession';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const VERSION: Record<string, string> = { efficientnet_b0: 'a', convnext_nano: 'b', resnet34d: 'c', audio_cnn: 'd', panns_cnn14: 'e' };
const hex = (arch: string) => VERSION[arch].repeat(64);
const audio = { target_sr: 22050, duration_seconds: 5, n_mels: 128, n_fft: 2048, hop_length: 512, f_min: 800, f_max: 10000, use_gpu_frontend: false };
const profileOf = (architecture: string) => ({ architecture, channels: 1, preprocessing: 'mono_mel', windowing: 'energy_peak_pad', window_hop_seconds: 1, audio });
const restored = (architecture: string) => ({
  snapshot_id: 'snapshot', prepared_version: hex(architecture), eligible: true, reasons: [], profile: profileOf(architecture), warnings: [],
  seed: 42, policy: { name: 'per-wav-stratified-70-15-15-v1', target: [0.7, 0.15, 0.15] }, provenance: { source: 'per-wav-independent-assumption-v1' },
});

function setup(opts: { preparations?: unknown[]; progress?: () => unknown } = {}) {
  let started = false;
  const transport = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    let data: unknown = {};
    if (url.includes('/auth/me')) data = { id: 1, email: 'owner@example.test', nombre_completo: 'Owner', rol: 'investigador', activo: true };
    else if (url.includes('/history')) data = { history: [] };
    else if (url.includes('/progress')) data = started ? opts.progress?.() : { status: 'idle', logs: [] };
    else if (url.endsWith('/start')) { started = true; data = { status: 'started' }; }
    else if (url.endsWith('/members')) data = { snapshot_id: 'snapshot', members: [{ member_id: 'm', class_name: 'ants', original_path: 'ants/a.wav', size_bytes: 44, sha256: 'h' }] };
    else if (url.endsWith('/snapshots')) data = { id: 'snapshot', dataset_id: 'arbitrary', name: 'Arbitrary WAV', state: 'ready', file_count: 1 };
    else if (url.endsWith('/preparations')) {
      const body = JSON.parse(String(init?.body));
      data = { snapshot_id: 'snapshot', version_id: hex(body.profile.architecture), state: 'ready', profile: body.profile, class_to_index: { ants: 0 }, warnings: [], seed: body.seed };
    } else if (url.includes('include_imported=true')) data = { datasets: [{ source_type: 'imported', id: 'arbitrary', name: 'Arbitrary WAV', eligible: true, reasons: [], preparations: opts.preparations ?? [] }] };
    else if (url.includes('/datasets')) data = { datasets: [] };
    return new Response(JSON.stringify(data));
  });
  vi.stubGlobal('fetch', transport);
  vi.stubGlobal('alert', vi.fn());
  const calls = (suffix: string) => transport.mock.calls.filter(c => String(c[0]).endsWith(suffix)) as unknown as [string, RequestInit][];
  return { transport, calls };
}

async function openTriad() {
  render(<Boundary><SidebarSession isCollapsed={false} onToggleCollapsed={() => {}} /><TrainingView /></Boundary>);
  await screen.findByText('Owner');
  fireEvent.click(screen.getByRole('combobox', { name: 'Dataset para entrenamiento' }));
  await screen.findByRole('option', { name: /Arbitrary WAV.*Privado/ });
  fireEvent.click(screen.getByRole('option', { name: 'Arbitrary WAV — Privado' }));
  fireEvent.click(screen.getByRole('button', { name: '3 Modelos (Tríada)' }));
}
const percents = () => [1, 2, 3].map(n => screen.getByLabelText(`Porcentaje del componente ${n}`) as HTMLInputElement);
const setPercents = (values: string[]) => values.forEach((v, i) => fireEvent.change(percents()[i], { target: { value: v } }));
const prepareButton = () => screen.getByRole('button', { name: 'Preparar dataset' }) as HTMLButtonElement;
const startButton = () => screen.getByRole('button', { name: 'Iniciar Pipeline de Tri Ensamble (3 Modelos)' }) as HTMLButtonElement;
async function prepared() {
  fireEvent.click(prepareButton());
  await screen.findByText(/Tríada preparada para entrenar/);
  await waitFor(() => expect(startButton().disabled).toBe(false));
}
async function startTriad() {
  await prepared();
  fireEvent.click(startButton());
  await screen.findByRole('button', { name: 'Detener' });
}

describe('private triad training flow', () => {
  it('selecting the triad opens three architecture selectors and a percentage per component', async () => {
    setup();
    await openTriad();
    const selectors = [1, 2, 3].map(n => screen.getByLabelText(`Arquitectura del componente ${n}`) as HTMLSelectElement);
    expect(selectors.map(s => s.value)).toEqual(['EfficientNet-B0', 'ConvNeXt-Nano', 'ResNet-34d']);
    expect(percents().map(p => p.value)).toEqual(['34', '33', '33']);
    expect(screen.getByText('Total: 100 %')).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Arquitectura de Red Neuronal' })).toBeNull();
  });

  it('blocks preparation and start unless the total is exactly 100 % and never rescales', async () => {
    const { calls } = setup();
    await openTriad();
    setPercents(['50', '33', '33']);
    expect(screen.getByText(/Total: 116 %/)).toBeTruthy();
    expect(prepareButton().disabled).toBe(true);
    expect(startButton().disabled).toBe(true);
    expect(screen.queryByRole('button', { name: 'Ajustar a 100%' })).toBeNull();
    expect(percents()[0].value).toBe('50');
    expect(calls('/preparations')).toHaveLength(0);
  });

  it('one prepare action creates three preparations on the same snapshot and seed', async () => {
    const { calls } = setup();
    await openTriad();
    await prepared();
    expect(calls('/snapshots')).toHaveLength(1);
    const preps = calls('/preparations');
    expect(preps).toHaveLength(3);
    expect(new Set(preps.map(([url]) => url)).size).toBe(1);
    const bodies = preps.map(([, init]) => JSON.parse(String(init.body)));
    expect(bodies.map(b => b.profile.architecture)).toEqual(['efficientnet_b0', 'convnext_nano', 'resnet34d']);
    expect(bodies.every(b => b.seed === 42)).toBe(true);
  });

  it('reuses a matching existing preparation per component', async () => {
    const { calls } = setup({ preparations: [restored('efficientnet_b0')] });
    await openTriad();
    fireEvent.click(prepareButton());
    await screen.findByText(/Tríada preparada para entrenar/);
    expect(calls('/preparations').map(([, i]) => JSON.parse(String(i.body)).profile.architecture)).toEqual(['convnext_nano', 'resnet34d']);
  });

  it('keeps preparations on a percentage-only change and invalidates only the changed architecture', async () => {
    const { calls } = setup();
    await openTriad();
    await prepared();
    setPercents(['20', '30', '50']);
    expect(screen.getByText(/Tríada preparada para entrenar/)).toBeTruthy();
    expect(startButton().disabled).toBe(false);
    fireEvent.change(screen.getByLabelText('Arquitectura del componente 3'), { target: { value: 'AudioCNN' } });
    await waitFor(() => expect(screen.queryByText(/Tríada preparada para entrenar/)).toBeNull());
    expect(startButton().disabled).toBe(true);
    fireEvent.click(prepareButton());
    await screen.findByText(/Tríada preparada para entrenar/);
    const archs = calls('/preparations').map(([, i]) => JSON.parse(String(i.body)).profile.architecture);
    expect(archs).toEqual(['efficientnet_b0', 'convnext_nano', 'resnet34d', 'audio_cnn']);
    expect(calls('/snapshots')).toHaveLength(2);
  });

  it('a seed change invalidates every preparation', async () => {
    setup();
    await openTriad();
    await prepared();
    fireEvent.change(screen.getByLabelText('Semilla aleatoria'), { target: { value: '7' } });
    await waitFor(() => expect(screen.queryByText(/Tríada preparada para entrenar/)).toBeNull());
    expect(startButton().disabled).toBe(true);
  });

  it('start stays disabled until all three preparations are ready', async () => {
    const { calls } = setup();
    await openTriad();
    expect(startButton().disabled).toBe(true);
    await prepared();
    expect(startButton().disabled).toBe(false);
    expect(calls('/start')).toHaveLength(0);
  });

  it('sends the exact triad request with float weights and no top-level prepared version', async () => {
    const { calls } = setup();
    await openTriad();
    setPercents(['20', '30', '50']);
    await prepared();
    fireEvent.click(startButton());
    await waitFor(() => expect(calls('/start')).toHaveLength(1));
    const body = JSON.parse(String(calls('/start')[0][1].body));
    expect(body.imported_dataset_id).toBe('arbitrary');
    expect(body.snapshot_id).toBe('snapshot');
    expect(body.seed).toBe(42);
    expect(body).not.toHaveProperty('imported_prepared_version');
    expect(body).not.toHaveProperty('dataset_name');
    expect(body).not.toHaveProperty('is_tri_model');
    expect(body.models.map((m: Record<string, unknown>) => m.weight)).toEqual([0.2, 0.3, 0.5]);
    expect(body.models.map((m: Record<string, unknown>) => m.architecture)).toEqual(['EfficientNet-B0', 'ConvNeXt-Nano', 'ResNet-34d']);
    expect(body.models.map((m: Record<string, unknown>) => m.imported_prepared_version)).toEqual([hex('efficientnet_b0'), hex('convnext_nano'), hex('resnet34d')]);
    for (const m of body.models) {
      expect(m.audio_config).toEqual(audio);
      expect(m.windowing_config).toEqual({ hop_seconds: 1, aggregation_mode: 'max', gem_p: 3, vad_threshold: 0 });
    }
  });

  describe('progress', () => {
    const base = { logs: [], total_models: 3, is_tri_model: true, composition_model_id: null };
    it('shows component i of 3 while components train', async () => {
      let progress: unknown = { logs: [], total_models: 3, status: 'training', current_phase: 'training', component_results: [], ensemble_available: false };
      setup({ progress: () => progress });
      await openTriad();
      await startTriad();
      progress = { ...base, status: 'training', current_phase: 'training', current_model_index: 2, current_architecture: 'ConvNeXt-Nano', component_results: [{ model_index: 1, architecture: 'EfficientNet-B0', model_id: 1 }], ensemble_available: false };
      expect(await screen.findByText(/Componente 2 de 3/, {}, { timeout: 2500 })).toBeTruthy();
      expect(screen.queryByText('Tríada disponible para inferencia')).toBeNull();
    });

    it('shows the joint evaluation phase without claiming availability', async () => {
      let progress: unknown = { logs: [], total_models: 3, status: 'training', current_phase: 'training', component_results: [], ensemble_available: false };
      setup({ progress: () => progress });
      await openTriad();
      await startTriad();
      progress = { ...base, status: 'evaluating', current_phase: 'joint_evaluation', current_model_index: 3, component_results: [{}, {}, {}].map((_, i) => ({ model_index: i + 1 })), ensemble_available: false };
      expect(await screen.findByText(/Evaluación conjunta de la tríada/, {}, { timeout: 2500 })).toBeTruthy();
      expect(screen.queryByText('Tríada disponible para inferencia')).toBeNull();
    });

    it('announces availability only when ensemble_available is true', async () => {
      let progress: unknown = { logs: [], total_models: 3, status: 'training', current_phase: 'training', component_results: [], ensemble_available: false };
      setup({ progress: () => progress });
      await openTriad();
      await startTriad();
      progress = { ...base, status: 'completed', current_phase: 'completed', component_results: [], ensemble_available: true, composition_model_id: 9 };
      expect(await screen.findByText('Tríada disponible para inferencia', {}, { timeout: 2500 })).toBeTruthy();
    });

    it('reports the triad as unavailable when a stage fails and does not average metrics', async () => {
      let progress: unknown = { logs: [], total_models: 3, status: 'training', current_phase: 'training', component_results: [], ensemble_available: false };
      setup({ progress: () => progress });
      await openTriad();
      await startTriad();
      progress = { ...base, status: 'failed', current_phase: 'failed', current_model_index: 2, val_acc: 91, component_results: [{ model_index: 1, architecture: 'EfficientNet-B0', model_id: 1 }], ensemble_available: false };
      const message = await screen.findByText(/La tríada no está disponible para inferencia/, {}, { timeout: 2500 });
      expect(message).toBeTruthy();
      expect(screen.queryByText('Tríada disponible para inferencia')).toBeNull();
      const summary = screen.getByRole('region', { name: 'Progreso de la tríada' });
      expect(within(summary).getByText(/Componente 1: EfficientNet-B0 · completado/)).toBeTruthy();
      expect(summary.textContent).not.toMatch(/91|promedio/i);
    });
  });
});

it('individual imported flow request is unchanged', async () => {
  const { calls } = setup();
  render(<Boundary><SidebarSession isCollapsed={false} onToggleCollapsed={() => {}} /><TrainingView /></Boundary>);
  await screen.findByText('Owner');
  fireEvent.click(screen.getByRole('combobox', { name: 'Dataset para entrenamiento' }));
  await screen.findByRole('option', { name: /Arbitrary WAV.*Privado/ });
  fireEvent.click(screen.getByRole('option', { name: 'Arbitrary WAV — Privado' }));
  fireEvent.click(prepareButton());
  await screen.findByText(/Preparado para entrenar/);
  expect(calls('/preparations')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar Entrenamiento Local (1 Modelo)' }));
  await waitFor(() => expect(calls('/start')).toHaveLength(1));
  const body = JSON.parse(String(calls('/start')[0][1].body));
  expect(body.imported_prepared_version).toBe(hex('efficientnet_b0'));
  expect(body.models).toEqual([{ architecture: 'EfficientNet-B0', weight: 1, epochs: 10, learning_rate: 0.001, batch_size: 16 }]);
  expect(body.audio_config).toEqual(audio);
  expect(body).not.toHaveProperty('is_tri_model');
});

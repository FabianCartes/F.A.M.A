import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, within, fireEvent } from '@testing-library/react';
import DashboardView from '../DashboardView';

afterEach(() => { vi.unstubAllGlobals(); });

describe('DashboardView truthful observations', () => {
  it('shows initial loading and publishes metrics without waiting for hardware telemetry', async () => {
    let resolveStats!: (response: Response) => void;
    const pendingStats = new Promise<Response>(resolve => { resolveStats = resolve; });
    vi.stubGlobal('fetch', vi.fn(input => String(input).includes('/dashboard/stats')
      ? pendingStats : new Promise<Response>(() => {})));
    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });
    expect(screen.getByRole('status').textContent).toContain('Cargando métricas');
    expect(screen.queryByText(/Datos actuales del dashboard no disponibles/)).toBeNull();
    expect(screen.queryByText('Sin métricas registradas')).toBeNull();
    await act(async () => { resolveStats(new Response(JSON.stringify({
      kpis: { accuracy: 50, loss: 11.64, total_datasets: 1, total_audios: 12, total_predictions: 1,
        avg_confidence: 0, latest_model_name: 'Modelo de prueba', metrics_source: 'latest_registered_model' },
      training_curves: [], recent_activity: [], super_ensemble: { ready: null, active_mode: 'unknown', models: [] },
      system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU' },
    }))); });
    expect(within(screen.getByRole('region', { name: 'Métricas registradas' })).getByText('50.00%')).toBeDefined();
    expect(screen.getByText('Modelo de prueba')).toBeDefined();
    expect(screen.queryByText('Cargando métricas…')).toBeNull();
  });

  it('does not fabricate metrics, activity, hardware health or ensemble readiness while unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })));

    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });

    expect(screen.queryAllByText('88.31%')).toHaveLength(0);
    expect(screen.queryByText('1,211')).toBeNull();
    expect(screen.queryByText('Inferencia: Chucao')).toBeNull();
    expect(screen.queryByText('Carga Normal')).toBeNull();
    expect(screen.queryByText('PostgreSQL & GCS Operativos')).toBeNull();
    expect(screen.queryByText('Tríada Operativa')).toBeNull();
    expect(screen.getAllByText('No disponible').length).toBeGreaterThan(0);
  });

  it('makes a single registered epoch visible and explains why it is not a convergence curve', async () => {
    vi.stubGlobal('fetch', vi.fn(async input => String(input).includes('/dashboard/stats')
      ? { ok: true, json: async () => ({
        kpis: { accuracy: 50, loss: 11.64, total_datasets: 1, total_audios: 12, total_predictions: 1,
          avg_confidence: 0, latest_model_name: 'Modelo de prueba', metrics_source: 'latest_registered_model' },
        training_curves: [{ epoch: 1, accuracy: 50, loss: 11.64 }], recent_activity: [],
        super_ensemble: { ready: null, active_mode: 'unknown', models: [] },
        system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU' },
      }) } : { ok: false, status: 503 }));
    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });
    expect(screen.getByText('Una época registrada. Se necesitan al menos dos para observar la evolución.')).toBeDefined();
    const chart = screen.getByRole('img', { name: 'Convergencia del modelo' });
    expect(within(chart).getByRole('img', { name: 'Época 1: precisión 50.0%, pérdida 11.6400' })).toBeDefined();
  });

  it('shows the recorded evolution when there are multiple epochs', async () => {
    vi.stubGlobal('fetch', vi.fn(async input => String(input).includes('/dashboard/stats')
      ? { ok: true, json: async () => ({
        kpis: { accuracy: 75, loss: 0.3, total_datasets: 1, total_audios: 12, total_predictions: 1,
          avg_confidence: 0, latest_model_name: 'Modelo de dos épocas', metrics_source: 'latest_registered_model' },
        training_curves: [{ epoch: 1, accuracy: 50, loss: 0.7 }, { epoch: 2, accuracy: 75, loss: 0.3 }], recent_activity: [],
        super_ensemble: { ready: null, active_mode: 'unknown', models: [] },
        system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU' },
      }) } : { ok: false, status: 503 }));
    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });
    const chart = within(screen.getByRole('img', { name: 'Convergencia del modelo' }));
    expect(chart.getByRole('img', { name: 'Época 1: precisión 50.0%, pérdida 0.7000' })).toBeDefined();
    expect(chart.getByRole('img', { name: 'Época 2: precisión 75.0%, pérdida 0.3000' })).toBeDefined();
    expect(screen.queryByText(/Una época registrada/)).toBeNull();
  });

  it('preserves zero observations and labels latest-model metrics without claiming activation', async () => {
    const stats = {
      kpis: { accuracy: 0, loss: 0, total_datasets: 0, total_audios: 0, total_predictions: 0,
        avg_confidence: 0, latest_model_name: 'Synthetic latest', metrics_source: 'latest_registered_model' },
      training_curves: [], recent_activity: [], super_ensemble: { ready: null, active_mode: 'unknown', models: [] },
      system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU fixture' },
    };
    vi.stubGlobal('fetch', vi.fn(async input => String(input).includes('/dashboard/stats')
      ? { ok: true, json: async () => stats } : { ok: false, status: 503 }));

    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });

    const kpis = within(screen.getByRole('region', { name: 'Métricas registradas' }));
    expect(kpis.getByText('0.00%')).toBeDefined();
    expect(kpis.getByText('0.0000')).toBeDefined();
    expect(kpis.getAllByText('0')).toHaveLength(2);
    expect(kpis.getByText('0 dataset(s) registrados')).toBeDefined();
    expect(kpis.getByText('Confianza prom.: 0.0%')).toBeDefined();
    expect(kpis.getByText('Synthetic latest')).toBeDefined();
    expect(screen.queryByText('Precisión Activa')).toBeNull();
    expect(screen.queryByText('Época 10')).toBeNull();
    expect(screen.getByText('Sin épocas registradas para mostrar el gráfico.')).toBeDefined();
    expect(screen.queryByRole('img', { name: 'Convergencia del modelo' })).toBeNull();
  });

  const baseStats = {
    kpis: { accuracy: null, loss: null, total_datasets: 2, total_audios: 0, total_predictions: 0,
      avg_confidence: null, latest_model_name: null, metrics_source: null },
    training_curves: [], recent_activity: [], best_models: [],
    super_ensemble: { ready: null, active_mode: 'none', composition_id: null, dataset_name: null, version: null, default: false, models: [] },
    system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU fixture' },
  };
  const renderWith = async (stats: object) => {
    vi.stubGlobal('fetch', vi.fn(async input => String(input).includes('/dashboard/stats')
      ? { ok: true, json: async () => stats } : { ok: false, status: 503 }));
    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });
  };

  it('shows the best registered model per dataset with the source of its metric', async () => {
    await renderWith({ ...baseStats, best_models: [
      { dataset_id: 1, dataset_name: 'AvesChilenas', model_id: 1, architecture: 'EfficientNet-B0',
        accuracy: 88.31, macro_f1: 88.68, source: 'test_evaluation' },
      { dataset_id: 2, dataset_name: 'Motores', model_id: 4, architecture: 'ResNet',
        accuracy: 55.5, macro_f1: null, source: 'training_validation' },
    ] });

    const birds = within(screen.getByRole('article', { name: 'Mejor modelo de AvesChilenas' }));
    expect(birds.getByText('EfficientNet-B0')).toBeDefined();
    expect(birds.getByText('88.31%')).toBeDefined();
    expect(birds.getByText('88.68%')).toBeDefined();
    expect(birds.getByText('Evaluación en test')).toBeDefined();
    const engines = within(screen.getByRole('article', { name: 'Mejor modelo de Motores' }));
    expect(engines.getByText('Validación del entrenamiento')).toBeDefined();
    expect(engines.getByText('No evaluado')).toBeDefined();
    expect(screen.queryByText(/Referencia experimental histórica/)).toBeNull();
    expect(within(screen.getByRole('region', { name: 'Métricas registradas' })).queryByText('88.31%')).toBeNull();
  });

  it('explains that there are no models instead of showing references', async () => {
    await renderWith(baseStats);
    expect(screen.getByText('Aún no hay modelos registrados con métricas en tus datasets.')).toBeDefined();
  });

  it('shows the registered triad, its members and whether the catalogue loaded it', async () => {
    await renderWith({ ...baseStats, super_ensemble: { ready: true, active_mode: 'triad', composition_id: 7,
      dataset_name: 'AvesChilenas', version: 2, default: true, models: [
        { name: 'EfficientNet-B0', model_id: 1, weight: 0.55, ready: null, accuracy: 70 },
        { name: 'ResNet', model_id: 2, weight: 0.3, ready: null, accuracy: 90 },
        { name: 'PANNs', model_id: 3, weight: 0.15, ready: null, accuracy: null }] } });

    const card = within(screen.getByRole('region', { name: 'Super-Ensamble Tri-Modelo' }));
    expect(card.getByText('Cargada en el catálogo')).toBeDefined();
    expect(card.getByText('AvesChilenas · versión 2 · predeterminada')).toBeDefined();
    expect(card.getByText('55%')).toBeDefined();
    expect(card.getByText('Acc: 90.0%')).toBeDefined();
  });

  it.each([
    [{ ready: false }, 'No cargada en el catálogo'],
    [{ ready: null }, 'Catálogo sin consultar'],
  ])('reports triad readiness %o without inventing it', async (state, label) => {
    await renderWith({ ...baseStats, super_ensemble: { ...baseStats.super_ensemble, ...state, active_mode: 'triad',
      composition_id: 7, dataset_name: 'Motores', version: 1, models: [] } });
    expect(within(screen.getByRole('region', { name: 'Super-Ensamble Tri-Modelo' })).getByText(label)).toBeDefined();
  });

  it('says when no triad is registered', async () => {
    await renderWith(baseStats);
    expect(within(screen.getByRole('region', { name: 'Super-Ensamble Tri-Modelo' }))
      .getByText('No hay tríadas registradas en tus datasets.')).toBeDefined();
  });

  it.each([['connected', 'GCS conectado'], ['unavailable', 'GCS sin conexión'], ['unknown', 'GCS no configurado']])(
    'shows the probed storage state %s', async (storage, label) => {
      await renderWith({ ...baseStats, system_health: { ...baseStats.system_health, storage } });
      expect(screen.getByText(new RegExp(label))).toBeDefined();
    });

  it('marks the retained snapshot as stale when a refresh fails', async () => {
    let offline = false;
    const stats = {
      kpis: { accuracy: 12, loss: 0.5, total_datasets: 0, total_audios: 0, total_predictions: 0,
        avg_confidence: null, latest_model_name: 'Retained snapshot model', metrics_source: 'latest_registered_model' },
      training_curves: [], recent_activity: [], super_ensemble: { ready: null, active_mode: 'unknown', models: [] },
      system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU fixture' },
    };
    vi.stubGlobal('fetch', vi.fn(async input => !offline && String(input).includes('/dashboard/stats')
      ? { ok: true, json: async () => stats } : { ok: false, status: 503 }));
    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });
    offline = true;

    await act(async () => { fireEvent.click(screen.getByTitle('Actualizar métricas en tiempo real')); });

    expect(screen.getByRole('status').textContent).toContain('se conserva la última lectura');
    expect(screen.getByText('Retained snapshot model')).toBeDefined();
    expect(screen.getByText(/BD no confirmada/)).toBeDefined();
  });
});

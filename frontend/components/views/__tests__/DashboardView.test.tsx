import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, within, fireEvent } from '@testing-library/react';
import DashboardView from '../DashboardView';

afterEach(() => { vi.unstubAllGlobals(); });

describe('DashboardView truthful observations', () => {
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
  });

  it('keeps historical references separate from unknown current metrics', async () => {
    const stats = {
      kpis: { accuracy: null, loss: null, total_datasets: 0, total_audios: 0, total_predictions: 0,
        avg_confidence: null, latest_model_name: null, metrics_source: null },
      training_curves: [], recent_activity: [], super_ensemble: { ready: null, active_mode: 'unknown', models: [] },
      system_health: { database: 'operational', storage: 'unknown', inference_engine: 'unknown', device: 'CPU fixture' },
      domain_champions: { bioacoustic: { title: 'Synthetic reference', architecture: 'Reference architecture',
        accuracy: 88.31, macro_f1: 88.68, classes_count: 15, source: 'historical_reference' } },
    };
    vi.stubGlobal('fetch', vi.fn(async input => String(input).includes('/dashboard/stats')
      ? { ok: true, json: async () => stats } : { ok: false, status: 503 }));

    await act(async () => { render(<DashboardView onNavigate={vi.fn()} />); });

    const kpis = within(screen.getByRole('region', { name: 'Métricas registradas' }));
    expect(kpis.queryByText('88.31%')).toBeNull();
    expect(kpis.getAllByText('No disponible').length).toBeGreaterThan(0);
    const reference = within(screen.getByRole('article', { name: 'Referencia bioacoustic' }));
    expect(reference.getByText('88.31%')).toBeDefined();
    expect(reference.getByText(/no acredita disponibilidad actual/)).toBeDefined();
    expect(screen.queryByText('Inferencia: Chucao')).toBeNull();
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

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TriadWeightRevision, { triadCompositionWeights } from '../TriadWeightRevision';
import { importedTrainingApi } from '@/lib/api/importedTrainingApi';

vi.mock('@/lib/api/importedTrainingApi', () => ({ importedTrainingApi: { reviseTriadWeights: vi.fn() } }));
const revise = vi.mocked(importedTrainingApi.reviseTriadWeights);
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const input = (n: number) => screen.getByLabelText(`Porcentaje del componente ${n}`);
const setAll = (a: string, b: string, c: string) => [a, b, c].forEach((v, i) => fireEvent.change(input(i + 1), { target: { value: v } }));
const mount = (onRevised = vi.fn()) => render(<TriadWeightRevision modelId="fama_trained_model_4" weights={[0.1, 0.4, 0.5]} onRevised={onRevised} />);

describe('triadCompositionWeights', () => {
  it('only recognises a composition with three finite weights', () => {
    expect(triadCompositionWeights({ architecture: 'ImportedTriad', metrics: { weights: [0.1, 0.4, 0.5] } })).toEqual([0.1, 0.4, 0.5]);
    expect(triadCompositionWeights({ architecture: 'ResNet-34d', metrics: { weights: [0.1, 0.4, 0.5] } })).toBeNull();
    expect(triadCompositionWeights({ architecture: 'ImportedTriad', metrics: { weights: [1, 0] } })).toBeNull();
    expect(triadCompositionWeights(undefined)).toBeNull();
  });
});

describe('TriadWeightRevision', () => {
  it.each([
    [0.1, 0.4, 0.5],
    [0.333333333333, 0.333333333333, 0.333333333334],
  ])('recognises applied weights, including displayed rounding (%j)', (...weights) => {
    render(<TriadWeightRevision modelId="fama_trained_model_4" weights={weights} onRevised={vi.fn()} />);
    expect(screen.getByText('Esta versión ya está evaluada con estos pesos.')).toBeDefined();
    expect((screen.getByRole('button', { name: 'Pesos aplicados' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(screen.getByRole('form', { name: 'Ajustar pesos de la tríada' }));
    expect(revise).not.toHaveBeenCalled();
  });

  it('enables changed weights and blocks submitting after restoring numeric equivalents', () => {
    mount();
    setAll('70', '20', '10');
    expect(screen.getByText('Estos pesos requieren evaluar una nueva versión.')).toBeDefined();
    expect((screen.getByRole('button', { name: 'Evaluar nuevos pesos' }) as HTMLButtonElement).disabled).toBe(false);
    setAll('10.0', '40.00', '50.0');
    expect((screen.getByRole('button', { name: 'Pesos aplicados' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(screen.getByRole('form', { name: 'Ajustar pesos de la tríada' }));
    expect(revise).not.toHaveBeenCalled();
  });

  it('shows current percentages and the new-version explanation', () => {
    mount();
    expect(screen.getByText(/Pesos actuales: 10 % · 40 % · 50 %/)).toBeDefined();
    expect(screen.getByText(/nueva versión evaluada y conserva la anterior/)).toBeDefined();
  });

  it('blocks a total other than exactly 100 %', () => {
    mount();
    setAll('10', '40', '40');
    expect((screen.getByRole('button', { name: 'Evaluar nuevos pesos' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/debe sumar exactamente 100 %/)).toBeDefined();
    fireEvent.submit(screen.getByRole('form', { name: 'Ajustar pesos de la tríada' }));
    expect(revise).not.toHaveBeenCalled();
  });

  it('sends exact floats, shows busy state, then reports the new version', async () => {
    let finish!: (v: { id: string; name: string; weights: number[] }) => void;
    revise.mockReturnValue(new Promise(r => { finish = r; }));
    const onRevised = vi.fn();
    mount(onRevised);
    setAll('70', '20', '10');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Evaluar nuevos pesos' })); });
    expect(revise).toHaveBeenCalledExactlyOnceWith('fama_trained_model_4', [0.7, 0.2, 0.1]);
    expect(screen.getByText('Evaluando nueva combinación…')).toBeDefined();
    expect((screen.getByRole('button', { name: 'Evaluar nuevos pesos' }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { finish({ id: 'fama_trained_model_9', name: 'Tríada importada', weights: [0.7, 0.2, 0.1] }); });
    expect(onRevised).toHaveBeenCalledExactlyOnceWith('fama_trained_model_9');
    expect(screen.queryByText('Evaluando nueva combinación…')).toBeNull();
  });

  it('shows a readable Spanish error and does not select anything', async () => {
    revise.mockRejectedValue(new Error('Composición importada no disponible.'));
    const onRevised = vi.fn();
    mount(onRevised);
    setAll('100', '0', '0');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Evaluar nuevos pesos' })); });
    expect(screen.getByRole('alert').textContent).toBe('Composición importada no disponible.');
    expect(onRevised).not.toHaveBeenCalled();
  });
});

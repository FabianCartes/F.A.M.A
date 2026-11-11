import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import TrainingView from "../TrainingView";

const historicalModel = {
  id: 41, name: "Modelo sin metadatos", version: 1, dataset: "Aves Chilenas",
  architecture: "EfficientNet-B0", epochs: 10, accuracy: 75, loss: 0.4,
  active: false, status: "entrenado", filename: "historical.pt", created_at: null,
  hyperparameters: { learning_rate: 0.002, batch_size: 8, optimizer: null, loss_type: null },
  audio_specs: null, classes: [], classes_count: null, file_size_bytes: null,
};

async function openSheet(model: object) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true,
    json: async () => url.includes("/history") ? { history: [model] }
      : url.includes("/datasets") ? { datasets: [] }
      : { cuda_available: false, device_name: "CPU", vram_total_gb: 8,
          vram_used_gb: 1, vram_percent: 12.5, status: "ready" },
  })));
  await act(async () => { render(<TrainingView />); });
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name: /Ficha Técnica/i }));
  });
  return within(screen.getByTestId("modal-ficha-tecnica"));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Ficha técnica del historial", () => {
  it("muestra datos desconocidos sin inventar parámetros de aves ni tamaño", async () => {
    const sheet = await openSheet(historicalModel);

    expect(sheet.getAllByText("No disponible").length).toBeGreaterThanOrEqual(8);
    expect(sheet.queryByText("AdamW")).toBeNull();
    expect(sheet.queryByText("Focal Loss")).toBeNull();
    expect(sheet.queryByText("22050 Hz")).toBeNull();
    expect(sheet.queryByText("46.56 MB")).toBeNull();
    expect(sheet.queryByText("15 clases")).toBeNull();
    expect(sheet.getByText("0.002")).toBeDefined();
  });

  it("muestra los datos explícitos y conserva valores conocidos iguales a cero", async () => {
    const sheet = await openSheet({
      ...historicalModel,
      hyperparameters: { learning_rate: 0.002, batch_size: 8, optimizer: "AdamW", loss_type: "CrossEntropy" },
      audio_specs: { target_sr: 16000, duration_seconds: 2, n_mels: 80,
                     n_fft: 512, hop_length: 128, fmin: 0, fmax: 7000 },
      classes: ["Clase A", "Clase B"], classes_count: 2, file_size_bytes: 0,
    });

    expect(sheet.getByText("16000 Hz")).toBeDefined();
    expect(sheet.getByText("2 s")).toBeDefined();
    expect(sheet.getByText("80 mels (FFT 512)")).toBeDefined();
    expect(sheet.getByText("0 - 7000 Hz")).toBeDefined();
    expect(sheet.getByText("0.00 MB")).toBeDefined();
    expect(sheet.getByText("CrossEntropy")).toBeDefined();
    expect(sheet.getByText("Clase A")).toBeDefined();
    expect(sheet.queryByText("No disponible")).toBeNull();
  });

  it("muestra épocas, precisión y pérdida en la ficha sin ocultar ceros", async () => {
    const sheet = await openSheet({ ...historicalModel, accuracy: 0, loss: 0 });
    const row = screen.getAllByRole("row").find((element) =>
      element.textContent?.includes(historicalModel.name));
    expect(row).toBeDefined();
    expect(within(row!).getByText("0.00%")).toBeDefined();
    expect(within(row!).queryByText("0.0000")).toBeNull();

    expect(sheet.getByText("Épocas:")).toBeDefined();
    expect(sheet.getByText("10")).toBeDefined();
    expect(sheet.getByText("Pérdida (Loss):")).toBeDefined();
    expect(sheet.getByText("0.0000")).toBeDefined();
    expect(sheet.getByText("Precisión (Val Acc):")).toBeDefined();
  });

  it("muestra todos los hiperparámetros y la física del audio registrados", async () => {
    const sheet = await openSheet({
      ...historicalModel,
      hyperparameters: { learning_rate: 0.002, batch_size: 8, optimizer: "AdamW", loss_type: "Focal Loss",
        weight_decay: 0.05, early_stopping: true, early_stopping_patience: 5, focal_gamma: 2, mixup_enabled: true,
        mixup_alpha: 0.2, pitch_shift_enabled: false, seed: 7, initialization_mode: "pretrained_constructor",
        checkpoint_epoch: 4, ensemble_weight: 0.5 },
      audio_specs: { target_sr: 16000, duration_seconds: 2, n_mels: 80, n_fft: 512, hop_length: 128, fmin: 0, fmax: 7000 },
      windowing: { hop_seconds: 0.5, aggregation_mode: "mean", gem_p: 3, vad_threshold: 0.1 },
    });

    for (const [label, value] of [
      ["Weight Decay:", "0.05"], ["Early Stopping:", "Activo (paciencia 5 épocas)"], ["Focal Gamma:", "2"],
      ["Mixup:", "Activo (α 0.2)"], ["Pitch Shift:", "Desactivado"], ["Semilla:", "7"],
      ["Inicialización:", "Preentrenado"], ["Época del checkpoint:", "4"], ["Peso en la tríada:", "0.5"],
      ["Hop Length:", "128 muestras"], ["Salto entre ventanas:", "0.5 s"], ["Agregación temporal:", "mean (GeM p 3)"],
      ["Umbral VAD:", "0.1"],
    ]) {
      const row = sheet.getByText(label).parentElement!;
      expect(within(row).getByText(value)).toBeDefined();
    }
  });

  it("indica los parámetros que un checkpoint antiguo no registró", async () => {
    const sheet = await openSheet(historicalModel);
    for (const label of ["Weight Decay:", "Early Stopping:", "Semilla:", "Hop Length:", "Salto entre ventanas:"]) {
      expect(within(sheet.getByText(label).parentElement!).getByText("No registrado")).toBeDefined();
    }
  });
});

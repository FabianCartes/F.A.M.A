import { afterEach, describe, expect, it, vi } from "vitest";
import { getHistory } from "../trainingApi";

afterEach(() => vi.unstubAllGlobals());

describe("Contrato de ficha técnica del historial", () => {
  it("conserva física, clases e hiperparámetros explícitos del backend", async () => {
    const model = {
      id: 41, name: "Modelo parametrizado", version: 2, dataset: "Motores",
      architecture: "EfficientNet-B0", epochs: 10, accuracy: 75, loss: 0.4,
      active: false, status: "entrenado", filename: "model.pt", created_at: null,
      hyperparameters: { learning_rate: 0.002, batch_size: 8, optimizer: "AdamW", loss_type: "CrossEntropy" },
      audio_specs: { target_sr: 16000, duration_seconds: 2, n_mels: 80,
                     n_fft: 512, hop_length: 128, fmin: 0, fmax: 7000 },
      classes: ["Clase A", "Clase B"], classes_count: 2, file_size_bytes: 1024,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ history: [model] }) })));

    const [result] = await getHistory();

    expect(result).toEqual(model);
  });

  it("conserva campos desconocidos como null sin fabricar defaults", async () => {
    const model = {
      id: 42, architecture: "EfficientNet-B0", epochs: 10, active: false,
      status: "entrenado", filename: "missing.pt",
      hyperparameters: { learning_rate: 0.002, batch_size: 8, optimizer: null, loss_type: null },
      audio_specs: null, classes: [], classes_count: null, file_size_bytes: null,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ history: [model] }) })));

    const [result] = await getHistory();

    expect(result).toEqual(model);
  });
});

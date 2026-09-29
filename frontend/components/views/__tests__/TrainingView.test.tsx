import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, within } from "@testing-library/react";
import TrainingView from "../TrainingView";
import { API_BASE_URL } from "@/lib/api";

describe("TrainingView (Dynamic Ensemble Selector)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetAllMocks();
    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("/api/training/hardware")) {
        return {
          ok: true,
          json: async () => ({
            cuda_available: true,
            device_name: "NVIDIA RTX 4090",
            vram_total_gb: 24,
            vram_used_gb: 4,
            vram_percent: 16.7,
            status: "ready",
          }),
        };
      }
      if (url.includes("/api/training/datasets")) {
        return {
          ok: true,
          json: async () => ({
            datasets: [
              {
                id: "AvesChilenas",
                name: "AvesChilenas (1211 audios)",
                audio_count: 1211,
                class_count: 15,
                size_mb: 340.5,
              },
            ],
          }),
        };
      }
      if (url.includes("/api/training/history")) {
        return {
          ok: true,
          json: async () => ({
            history: [
              {
                id: 1,
                name: "Motores · EfficientNet-B0 (v1)",
                version: 1,
                dataset: "Motores",
                architecture: "EfficientNet-B0",
                epochs: 10,
                accuracy: 68.12,
                loss: 1.0297,
                active: false,
                status: "entrenado",
                filename: "fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt",
                hyperparameters: {
                  learning_rate: 0.001,
                  batch_size: 16,
                  optimizer: "AdamW",
                  loss_type: "Focal Loss",
                },
                audio_specs: {
                  target_sr: 32000,
                  duration_seconds: 1.5,
                  n_mels: 128,
                  n_fft: 2048,
                  hop_length: 512,
                  fmin: 50,
                  fmax: 16000,
                },
                classes: ["Crankshaft", "Piston", "Bearing"],
                classes_count: 13,
                file_size_bytes: 48822960,
                created_at: "2026-09-29T00:52:14Z",
              },
              {
                id: 6,
                name: "Aves Chilenas · EfficientNet-B0 (v1)",
                version: 1,
                dataset: "Aves Chilenas",
                architecture: "EfficientNet-B0",
                epochs: 10,
                accuracy: 77.78,
                loss: 0.35,
                active: true,
                status: "entrenado",
                filename: "fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt",
                hyperparameters: {
                  learning_rate: 0.001,
                  batch_size: 32,
                  optimizer: "AdamW",
                  loss_type: "Focal Loss",
                },
                audio_specs: {
                  target_sr: 22050,
                  duration_seconds: 5.0,
                  n_mels: 128,
                  n_fft: 2048,
                  hop_length: 512,
                  fmin: 50,
                  fmax: 11025,
                },
                classes: ["Canastero", "Chercán", "Chincol"],
                classes_count: 15,
                file_size_bytes: 48822960,
                created_at: "2026-09-29T00:06:31Z",
              },
            ],
          }),
        };
      }
      if (url.includes("/api/training/start")) {
        return {
          ok: true,
          json: async () => ({
            status: "started",
            job_id: "test_job_123",
            message: "Entrenamiento iniciado",
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({}),
      };
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("renders the 1, 2, and 3 model topology options", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    expect(screen.getByText("1 Modelo (Individual)")).toBeDefined();
    expect(screen.getByText("2 Modelos (Dúo)")).toBeDefined();
    expect(screen.getByText("3 Modelos (Tríada)")).toBeDefined();
  });

  it("switches to Duo Ensemble and reveals 2 models with sliders", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const duoBtn = screen.getByText("2 Modelos (Dúo)");
    await act(async () => {
      fireEvent.click(duoBtn);
    });

    expect(screen.getByText("Composición y Ponderación del Ensamble (2 Modelos)")).toBeDefined();
    expect(screen.getByText(/Modelo #1:/)).toBeDefined();
    expect(screen.getByText(/Modelo #2:/)).toBeDefined();
    expect(screen.queryByText(/Modelo #3:/)).toBeNull();
  });

  it("switches to Trio Ensemble and reveals 3 models", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const trioBtn = screen.getByText("3 Modelos (Tríada)");
    await act(async () => {
      fireEvent.click(trioBtn);
    });

    expect(screen.getByText("Composición y Ponderación del Ensamble (3 Modelos)")).toBeDefined();
    expect(screen.getByText(/Modelo #1:/)).toBeDefined();
    expect(screen.getByText(/Modelo #2:/)).toBeDefined();
    expect(screen.getByText(/Modelo #3:/)).toBeDefined();
  });

  it("sends models array in payload when starting Duo Ensemble training", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Cambiar a Dúo Ensamble
    const duoBtn = screen.getByText("2 Modelos (Dúo)");
    await act(async () => {
      fireEvent.click(duoBtn);
    });

    // Iniciar entrenamiento
    const startBtn = screen.getByText("Iniciar Pipeline Dúo Ensamble (2 Modelos)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    // Verificar que se llamó a POST /api/training/start con la lista de 2 modelos
    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeDefined();
    const payload = JSON.parse(postCall[1].body);

    expect(payload.models).toBeDefined();
    expect(payload.models).toHaveLength(2);
    expect(payload.models[0].architecture).toBe("EfficientNet-B0");
    expect(payload.models[1].architecture).toBe("ConvNeXt-Nano");
    const totalWeight = payload.models.reduce((acc: number, m: any) => acc + m.weight, 0);
    expect(totalWeight).toBeCloseTo(1.0, 2);
  });

  it("renders audio physics panel with domain presets and sends multi-domain config in payload", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Panel exists
    expect(screen.getByText("Física de Audio y Adaptación al Dominio")).toBeDefined();
    expect(screen.getByText("Tos Médica")).toBeDefined();
    expect(screen.getByText("Diagnóstico Industrial")).toBeDefined();

    // Click Tos Médica preset
    const coughBtn = screen.getByText("Tos Médica");
    await act(async () => {
      fireEvent.click(coughBtn);
    });

    // Verify sample rate input value is 16000
    const srInput = screen.getByLabelText(/Tasa de Muestreo/i) as HTMLInputElement;
    expect(srInput.value).toBe("16000");

    // Start training
    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeDefined();
    const payload = JSON.parse(postCall[1].body);

    expect(payload.audio_config).toBeDefined();
    expect(payload.audio_config.target_sr).toBe(16000);
    expect(payload.audio_config.f_max).toBe(4000);
    expect(payload.windowing_config).toBeDefined();
    expect(payload.windowing_config.hop_seconds).toBe(0.5);
    expect(payload.regularization_config).toBeDefined();
    expect(payload.regularization_config.loss_type).toBe("focal");
  });

  it("displays Nyquist warning when f_max > target_sr / 2", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const fMaxInput = screen.getByLabelText(/Frecuencia Máxima/i) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(fMaxInput, { target: { value: "15000" } });
    });

    // Target SR default is 22050 -> Nyquist is 11025. 15000 > 11025, should show warning
    expect(screen.getByText(/Violación de Nyquist/i)).toBeDefined();
  });

  it("renders model filter pills in chart when Duo Ensemble is selected", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const duoBtn = screen.getByText("2 Modelos (Dúo)");
    await act(async () => {
      fireEvent.click(duoBtn);
    });

    // Chart should show filter pills
    expect(screen.getByRole("button", { name: "Modelo Actual" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Modelo 1" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Modelo 2" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Todos" })).toBeDefined();

    // Toggle to Modelo 1
    const m1Btn = screen.getByRole("button", { name: "Modelo 1" });
    await act(async () => {
      fireEvent.click(m1Btn);
    });
    expect(m1Btn.className).toContain("bg-cyan-600");

    // Toggle to Todos
    const allBtn = screen.getByRole("button", { name: "Todos" });
    await act(async () => {
      fireEvent.click(allBtn);
    });
    expect(allBtn.className).toContain("bg-emerald-600");
  });

  it("removes the 'Activar' button and 'Activo (Inferencia)' tag from the models table", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Verify "Activar" button is completely gone
    expect(screen.queryByRole("button", { name: /^Activar$/i })).toBeNull();
    // Verify "Activo (Inferencia)" badge is completely gone
    expect(screen.queryByText(/Activo \(Inferencia\)/i)).toBeNull();
    expect(screen.queryByText(/✓ En uso/i)).toBeNull();
  });

  it("renders friendly model names with version badges v1 and domain badges", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    expect(screen.getByText("Motores · EfficientNet-B0 (v1)")).toBeDefined();
    expect(screen.getByText("Aves Chilenas · EfficientNet-B0 (v1)")).toBeDefined();
    expect(screen.getAllByText("v1").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Aves Chilenas")).toBeDefined();
    expect(screen.getByText("Motores")).toBeDefined();
  });

  it("opens technical sheet modal when clicking 'Ficha Técnica' displaying all 3 specification cards", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const sheetButtons = screen.getAllByRole("button", { name: /Ficha Técnica/i });
    expect(sheetButtons.length).toBeGreaterThanOrEqual(1);

    // Click the first model's Ficha Técnica button
    await act(async () => {
      fireEvent.click(sheetButtons[0]);
    });

    // Modal is opened
    const modal = screen.getByTestId("modal-ficha-tecnica");
    expect(modal).toBeDefined();

    // 1) Hiperparámetros de entrenamiento
    expect(within(modal).getByText(/Hiperparámetros de Entrenamiento/i)).toBeDefined();
    expect(within(modal).getByText("AdamW")).toBeDefined();
    expect(within(modal).getByText("Focal Loss")).toBeDefined();

    // 2) Parámetros de física de audio
    expect(within(modal).getByText(/Parámetros de Física de Audio/i)).toBeDefined();
    expect(within(modal).getByText(/32000 Hz/i)).toBeDefined();
    expect(within(modal).getByText(/1.5 s/i)).toBeDefined();

    // 3) Especificaciones del artefacto
    expect(within(modal).getByText(/Especificaciones del Artefacto/i)).toBeDefined();
    expect(within(modal).getByText("fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt")).toBeDefined();
    expect(within(modal).getByText(/13 clases/i)).toBeDefined();

    // Close modal
    const closeBtn = within(modal).getAllByRole("button", { name: /Cerrar/i })[0];
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(screen.queryByTestId("modal-ficha-tecnica")).toBeNull();
  });

  it("renders AdamW Weight Decay input and passes configured weight_decay in payload", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const wdInput = screen.getByLabelText(/Weight Decay/i) as HTMLInputElement;
    expect(wdInput).toBeDefined();
    expect(wdInput.value).toBe("0.01");

    await act(async () => {
      fireEvent.change(wdInput, { target: { value: "0.05" } });
    });
    expect(wdInput.value).toBe("0.05");

    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeDefined();
    const payload = JSON.parse(postCall[1].body);
    expect(payload.weight_decay).toBe(0.05);
  });

  it("synchronizes architecture when changing to PANNs-CNN14 and sends PANNs-CNN14 in start payload", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Cambiar la arquitectura a PANNs-CNN14 en el desplegable individual
    const archSelect = screen.getByTestId("architecture-select") as HTMLSelectElement;
    expect(archSelect).toBeDefined();

    await act(async () => {
      fireEvent.change(archSelect, { target: { value: "PANNs-CNN14" } });
    });
    expect(archSelect.value).toBe("PANNs-CNN14");

    // Verificar que la tarjeta de selección de dataset refleja la arquitectura seleccionada
    const datasetCard = screen.getByTestId("dataset-selection-card");
    expect(datasetCard).toBeDefined();
    expect(within(datasetCard).getByText(/PANNs-CNN14/i)).toBeDefined();

    // Iniciar entrenamiento individual
    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeDefined();
    const payload = JSON.parse(postCall[1].body);
    expect(payload.architecture).toBe("PANNs-CNN14");
    expect(payload.models[0].architecture).toBe("PANNs-CNN14");
  });

  it("displays architecture utilized in the technical sheet modal specifications", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Abrir modal de ficha técnica del modelo histórico #1
    const fichaButtons = screen.getAllByRole("button", { name: /Ficha Técnica/i });
    await act(async () => {
      fireEvent.click(fichaButtons[0]);
    });

    const modal = screen.getByTestId("modal-ficha-tecnica");
    expect(modal).toBeDefined();

    // Verificar que dentro de la ficha técnica se muestra la arquitectura utilizada
    expect(within(modal).getByText("Arquitectura:")).toBeDefined();
    expect(within(modal).getAllByText("EfficientNet-B0").length).toBeGreaterThan(0);
  });
});





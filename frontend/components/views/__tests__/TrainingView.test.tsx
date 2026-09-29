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
    expect(screen.getAllByText(/Violación de Nyquist/i).length).toBeGreaterThanOrEqual(1);
    expect(fMaxInput.className).toContain("border-red-500");
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

  it("allows setting custom epochs per model in Duo/Trio ensemble and sends them in payload", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // 1. Switch to Duo Ensemble
    const duoBtn = screen.getByText("2 Modelos (Dúo)");
    await act(async () => {
      fireEvent.click(duoBtn);
    });

    // 2. Locate epochs input for Model #1 and Model #2
    const model1Epochs = screen.getByLabelText("Épocas del Modelo #1") as HTMLInputElement;
    const model2Epochs = screen.getByLabelText("Épocas del Modelo #2") as HTMLInputElement;

    expect(model1Epochs).toBeDefined();
    expect(model2Epochs).toBeDefined();

    // 3. Set Model #1 epochs to 35 and Model #2 epochs to 20
    await act(async () => {
      fireEvent.change(model1Epochs, { target: { value: "35" } });
      fireEvent.change(model2Epochs, { target: { value: "20" } });
    });

    expect(model1Epochs.value).toBe("35");
    expect(model2Epochs.value).toBe("20");

    // 4. Start training
    const startBtn = screen.getByText("Iniciar Pipeline Dúo Ensamble (2 Modelos)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeDefined();
    const payload = JSON.parse(postCall[1].body);

    expect(payload.models[0].epochs).toBe(35);
    expect(payload.models[1].epochs).toBe(20);
  });

  it("allows setting arbitrary percentage combination 60%, 30%, 10% in Trio Ensemble without shifting other values", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const trioBtn = screen.getByText("3 Modelos (Tríada)");
    await act(async () => {
      fireEvent.click(trioBtn);
    });

    const weight1 = screen.getByLabelText("Ponderación del Modelo #1") as HTMLInputElement;
    const weight2 = screen.getByLabelText("Ponderación del Modelo #2") as HTMLInputElement;
    const weight3 = screen.getByLabelText("Ponderación del Modelo #3") as HTMLInputElement;

    await act(async () => {
      fireEvent.change(weight1, { target: { value: "60" } });
      fireEvent.change(weight2, { target: { value: "30" } });
      fireEvent.change(weight3, { target: { value: "10" } });
    });

    expect(weight1.value).toBe("60");
    expect(weight2.value).toBe("30");
    expect(weight3.value).toBe("10");

    expect(screen.getByText(/Total: 100%/)).toBeDefined();

    const startBtn = screen.getByText(/Iniciar Pipeline.*Tri Ensamble \(3 Modelos\)/i);
    await act(async () => {
      fireEvent.click(startBtn);
    });

    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeDefined();
    const payload = JSON.parse(postCall[1].body);

    expect(payload.models[0].weight).toBeCloseTo(0.6, 2);
    expect(payload.models[1].weight).toBeCloseTo(0.3, 2);
    expect(payload.models[2].weight).toBeCloseTo(0.1, 2);
  });

  it("allows completely clearing input fields to empty string and highlights them on validation with natural language message", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const epochsInput = screen.getByLabelText("Épocas de Entrenamiento") as HTMLInputElement;

    await act(async () => {
      fireEvent.change(epochsInput, { target: { value: "" } });
    });

    expect(epochsInput.value).toBe("");

    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    expect(epochsInput.className).toContain("border-red-500");
    expect(
      screen.getAllByText(/El campo 'Épocas de Entrenamiento' no puede estar vacío/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("highlights sampling window duration in red when set to 0 seconds and prevents training", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const durationInput = screen.getByLabelText("Duración de Ventana (s)") as HTMLInputElement;
    expect(durationInput).toBeDefined();

    // Cambiar duración a 0 segundos
    await act(async () => {
      fireEvent.change(durationInput, { target: { value: "0" } });
    });

    expect(durationInput.value).toBe("0");

    // Verificar que la casilla se destaca en rojo reactivamente
    expect(durationInput.className).toContain("border-red-500");
    expect(screen.getAllByText(/No puede ser 0 segundos ni negativa/i).length).toBeGreaterThanOrEqual(1);

    // Intentar iniciar entrenamiento
    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    // La llamada al API no debe haberse realizado
    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeUndefined();
  });

  it("validates hop_seconds, gem_p, vad_threshold and focal_gamma inline without top banner when empty or out of range", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const hopInput = screen.getByLabelText("Salto Temporal (s)") as HTMLInputElement;
    const gemInput = screen.getByLabelText("Exponente GeM (p)") as HTMLInputElement;
    const vadInput = screen.getByLabelText("Umbral VAD Energético") as HTMLInputElement;
    const gammaInput = screen.getByLabelText("Parámetro Gamma (Focal)") as HTMLInputElement;

    // 1. Dejar campos vacíos
    await act(async () => {
      fireEvent.change(hopInput, { target: { value: "" } });
      fireEvent.change(gemInput, { target: { value: "" } });
      fireEvent.change(vadInput, { target: { value: "" } });
      fireEvent.change(gammaInput, { target: { value: "" } });
    });

    expect(hopInput.value).toBe("");
    expect(gemInput.value).toBe("");
    expect(vadInput.value).toBe("");
    expect(gammaInput.value).toBe("");

    // Intentar iniciar entrenamiento
    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });

    // Verificar que los errores se muestran inline debajo de cada casilla
    expect(screen.getByText("El campo 'Salto Temporal' no puede estar vacío.")).toBeDefined();
    expect(screen.getByText("El campo 'Exponente GeM (p)' no puede estar vacío.")).toBeDefined();
    expect(screen.getByText("El campo 'Umbral VAD Energético' no puede estar vacío.")).toBeDefined();
    expect(screen.getByText("El campo 'Parámetro Gamma (Focal)' no puede estar vacío.")).toBeDefined();

    // Comprobar que NO existe ningún banner grande superior con múltiples errores
    expect(screen.queryByTestId("physics-validation-banner")).toBeNull();

    // 2. Probar valores fuera de rango: GeM = 0 (no permitido), hop = 0, vad = 2, gamma = 10
    await act(async () => {
      fireEvent.change(hopInput, { target: { value: "0" } });
      fireEvent.change(gemInput, { target: { value: "0" } });
      fireEvent.change(vadInput, { target: { value: "2" } });
      fireEvent.change(gammaInput, { target: { value: "10" } });
    });

    await act(async () => {
      fireEvent.click(startBtn);
    });

    expect(screen.getByText(/Salto Temporal: Debe ser entre 0.1 s y 10.0 s/i)).toBeDefined();
    expect(screen.getByText(/Exponente GeM: Debe estar entre 1.0 y 10.0 \(no puede ser 0\)/i)).toBeDefined();
    expect(screen.getByText(/Umbral VAD: Debe estar entre 0.0 y 1.0/i)).toBeDefined();
    expect(screen.getByText(/Parámetro Gamma: Debe estar entre 0.0 y 5.0/i)).toBeDefined();
  });

  it("implements Option B hybrid validation: immediate dynamic red highlighting on out-of-range/physics violations and onBlur/submit highlighting when empty", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const fMinInput = screen.getByLabelText("Frecuencia Mínima (Hz)") as HTMLInputElement;
    expect(fMinInput).toBeDefined();

    // 1. Violación física inmediata (onChange): frecuencia negativa (-50)
    await act(async () => {
      fireEvent.change(fMinInput, { target: { value: "-50" } });
    });
    expect(fMinInput.className).toContain("border-red-500");
    expect(screen.getByText("Frecuencia Mínima: No puede ser negativa.")).toBeDefined();

    // 2. Corrección inmediata a valor válido (500 Hz)
    await act(async () => {
      fireEvent.change(fMinInput, { target: { value: "500" } });
    });
    expect(fMinInput.className).not.toContain("border-red-500");
    expect(screen.queryByText(/Frecuencia Mínima: No puede ser negativa/i)).toBeNull();

    // 3. Dejar campo vacío y hacer onBlur: se marca en rojo dinámicamente con mensaje explicativo
    await act(async () => {
      fireEvent.change(fMinInput, { target: { value: "" } });
      fireEvent.blur(fMinInput);
    });
    expect(fMinInput.className).toContain("border-red-500");
    expect(screen.getByText("El campo 'Frecuencia Mínima' no puede estar vacío.")).toBeDefined();

    // 4. Intentar iniciar entrenamiento: bloquea y mantiene el recuadro resaltado en rojo
    const startBtn = screen.getByText("Iniciar Entrenamiento Local (1 Modelo)");
    await act(async () => {
      fireEvent.click(startBtn);
    });
    expect(fMinInput.className).toContain("border-red-500");
    expect(screen.getByText("El campo 'Frecuencia Mínima' no puede estar vacío.")).toBeDefined();

    const postCall = (global.fetch as any).mock.calls.find(
      (c: any[]) => c[0] === `${API_BASE_URL}/api/training/start`
    );
    expect(postCall).toBeUndefined();
  });

  it("allows setting epochs up to 1000 and displays inline error if greater than 1000", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const epochsInput = screen.getByLabelText("Épocas de Entrenamiento") as HTMLInputElement;
    expect(epochsInput).toBeDefined();

    // 1. Configurar en 1000: válido, sin error
    await act(async () => {
      fireEvent.change(epochsInput, { target: { value: "1000" } });
    });
    expect(epochsInput.className).not.toContain("border-red-500");
    expect(screen.queryByText(/El campo 'Épocas de Entrenamiento' debe ser entre 1 y 1000/i)).toBeNull();

    // 2. Configurar en 1001: fuera de rango, error inline inmediato
    await act(async () => {
      fireEvent.change(epochsInput, { target: { value: "1001" } });
    });
    expect(epochsInput.className).toContain("border-red-500");
    expect(screen.getByText("El campo 'Épocas de Entrenamiento' debe ser entre 1 y 1000.")).toBeDefined();
  });

  it("resets single model epochs error and value when switching to ensemble topology", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const epochsInput = screen.getByLabelText("Épocas de Entrenamiento") as HTMLInputElement;

    // Provocar error en modo individual
    await act(async () => {
      fireEvent.change(epochsInput, { target: { value: "1001" } });
      fireEvent.blur(epochsInput);
    });
    expect(screen.getByText("El campo 'Épocas de Entrenamiento' debe ser entre 1 y 1000.")).toBeDefined();

    // Cambiar a 3 Modelos (Tríada)
    const trioBtn = screen.getByText("3 Modelos (Tríada)");
    await act(async () => {
      fireEvent.click(trioBtn);
    });

    // El error debe haberse limpiado y el valor haberse reseteado
    expect(screen.queryByText(/El campo 'Épocas de Entrenamiento' debe ser entre 1 y 1000/i)).toBeNull();
    expect(epochsInput.value).not.toBe("1001");
  });

  it("applies Option B hybrid validation to ensemble model epochs inputs", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Cambiar a Tríada
    const trioBtn = screen.getByText("3 Modelos (Tríada)");
    await act(async () => {
      fireEvent.click(trioBtn);
    });

    const modelEpochs0 = screen.getByLabelText("Épocas del Modelo #1") as HTMLInputElement;
    expect(modelEpochs0).toBeDefined();

    // 1. Violación inmediata en onChange: valor fuera de rango (>1000 o <=0)
    await act(async () => {
      fireEvent.change(modelEpochs0, { target: { value: "1001" } });
    });
    expect(modelEpochs0.className).toContain("border-red-500");
    expect(screen.getByText("El campo 'Épocas del Modelo #1' debe ser entre 1 y 1000.")).toBeDefined();

    // 2. Corrección inmediata a valor válido
    await act(async () => {
      fireEvent.change(modelEpochs0, { target: { value: "35" } });
    });
    expect(modelEpochs0.className).not.toContain("border-red-500");
    expect(screen.queryByText(/El campo 'Épocas del Modelo #1' debe ser entre 1 y 1000/i)).toBeNull();

    // 3. Dejar vacío y desenfocar (onBlur): resalta en rojo con mensaje obligatorio
    await act(async () => {
      fireEvent.change(modelEpochs0, { target: { value: "" } });
      fireEvent.blur(modelEpochs0);
    });
    expect(modelEpochs0.className).toContain("border-red-500");
    expect(screen.getByText("El campo 'Épocas del Modelo #1' no puede estar vacío.")).toBeDefined();
  });
});







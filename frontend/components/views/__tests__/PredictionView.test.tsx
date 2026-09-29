import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, act } from "@testing-library/react";
import PredictionView from "../PredictionView";

const mockModels = [
  {
    id: "chilean-birds-ensemble",
    name: "Aves Chilenas · Super-Ensamble Tri-Modelo (88.68% F1)",
    description: "Super-Ensamble bayesiano bioacústico",
    target_sr: 22050,
    duration_seconds: 5.0,
    classes: ["Chucao", "Rayadito", "Chercán"],
    is_default: true,
    has_weights: true,
    metrics: { f1_macro: 0.8868, accuracy: 0.8831 },
  },
  {
    id: "fama_trained_model_6",
    name: "EfficientNet-B0 (Entrenado #6)",
    description: "Modelo individual entrenado en F.A.M.A.",
    target_sr: 22050,
    duration_seconds: 5.0,
    classes: ["Chucao", "Rayadito", "Chercán"],
    is_default: false,
    has_weights: true,
    metrics: { f1_macro: 0.865, accuracy: 0.871 },
  },
  {
    id: "car-engine-diagnostics-super-ensemble",
    name: "Fallas de Motores · Super-Ensamble (81.16% Acc)",
    description: "Super-Ensamble All-RMS para diagnóstico de fallas mecánicas",
    target_sr: 32000,
    duration_seconds: 2.0,
    classes: [
      "bad_ignition",
      "dead_battery",
      "low_oil",
      "no oil_serpentine belt",
      "normal_brakes",
      "normal_engine_idle",
      "normal_engine_startup",
      "power steering combined_no oil",
      "power steering combined_no oil_serpentine belt",
      "power steering combined_serpentine belt",
      "power_steering",
      "serpentine_belt",
      "worn_out_brakes",
    ],
    is_default: false,
    has_weights: true,
    metrics: { accuracy: 0.8116, f1_macro: 0.8144 },
  },
  {
    id: "car-engine-diagnostics-resnet34d-v2",
    name: "ResNet-34d Industrial v2",
    description: "Modelo convolucional residual profundo para diagnóstico de motores",
    target_sr: 32000,
    duration_seconds: 1.5,
    classes: [
      "bad_ignition",
      "dead_battery",
      "low_oil",
      "no oil_serpentine belt",
      "normal_brakes",
      "normal_engine_idle",
      "normal_engine_startup",
      "power steering combined_no oil",
      "power steering combined_no oil_serpentine belt",
      "power steering combined_serpentine belt",
      "power_steering",
      "serpentine_belt",
      "worn_out_brakes",
    ],
    is_default: false,
    has_weights: true,
    metrics: { accuracy: 0.809, f1_macro: 0.805 },
  },
];

describe("PredictionView responsive header and controls", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/models")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              models: mockModels,
              default_model_id: "chilean-birds-ensemble",
            }),
        });
      }
      if (url.includes("/api/model-info")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              is_fallback: false,
              model_name: "Super-Ensamble",
              device: "cuda",
              active_models: [],
              total_classes: 15,
              classes: ["Chucao"],
            }),
        });
      }
      return Promise.resolve({ ok: false });
    });
  });

  it("renders the view heading and accessible controls container", async () => {
    render(<PredictionView />);
    expect(screen.getByText("Predicción y Monitoreo Acústico")).toBeDefined();
    expect(await screen.findByLabelText(/Modelo:/i)).toBeDefined();
    expect(screen.getByText(/Latencia:\s*0\.14s/i)).toBeDefined();
  });

  it("applies responsive layout classes to model selector and latency box", async () => {
    render(<PredictionView />);
    const modelSelect = await screen.findByLabelText(/Modelo:/i);
    expect(modelSelect.className).toContain("truncate");
    expect(modelSelect.className).toContain("min-w-0");

    const latencyContainer = screen.getByText(/Latencia:\s*0\.14s/i).closest("div");
    expect(latencyContainer?.className).toContain("shrink-0");
    expect(latencyContainer?.className).toContain("whitespace-nowrap");
  });

  it("Test case 1: Selecting car-engine-diagnostics-resnet34d-v2 dynamically switches the view to Diagnóstico Acústico de Motores, displays 13 Fallas Mecánicas, displays 1.5s @ 32 kHz, and populates the class filter with engine classes", async () => {
    render(<PredictionView />);
    const modelSelect = (await screen.findByLabelText(/Modelo:/i)) as HTMLSelectElement;

    await act(async () => {
      fireEvent.change(modelSelect, {
        target: { value: "car-engine-diagnostics-resnet34d-v2" },
      });
    });

    expect(screen.getByText(/Dominio Activo:\s*Diagnóstico Acústico de Motores/i)).toBeDefined();
    expect(screen.getByText("13 Fallas Mecánicas")).toBeDefined();
    expect(screen.getByText("1.5s @ 32 kHz")).toBeDefined();

    // Verify class filter contains engine classes
    const classFilter = screen.getByRole("combobox", {
      name: "",
    }) || screen.getAllByRole("combobox")[1];
    expect(classFilter).toBeDefined();
    expect(screen.getByText("Falla de Encendido / Combustión Irregular")).toBeDefined();
  });

  it("Test case 2: The select id=model-select renders optgroup for Bioacústica (Aves Chilenas) and Diagnóstico Industrial (Motores)", async () => {
    render(<PredictionView />);
    const modelSelect = (await screen.findByLabelText(/Modelo:/i)) as HTMLSelectElement;

    const bioGroup = modelSelect.querySelector('optgroup[label="Bioacústica (Aves Chilenas)"]');
    const engineGroup = modelSelect.querySelector('optgroup[label="Diagnóstico Industrial (Motores)"]');

    expect(bioGroup).not.toBeNull();
    expect(engineGroup).not.toBeNull();
  });

  it("Test case 3: When an individual model is selected (not an ensemble), the architecture panel adapts to show individual model specifications instead of false triad branch weights", async () => {
    render(<PredictionView />);
    const modelSelect = (await screen.findByLabelText(/Modelo:/i)) as HTMLSelectElement;

    // Switch to individual engine model
    await act(async () => {
      fireEvent.change(modelSelect, {
        target: { value: "car-engine-diagnostics-resnet34d-v2" },
      });
    });

    // Should display individual model specifications card
    expect(screen.getByText(/Especificaciones del Modelo Individual Activo/i)).toBeDefined();
    expect(screen.getAllByText("ResNet-34d Industrial v2").length).toBeGreaterThan(0);

    // Should NOT display false triad branch weights (55%/30%/15%)
    expect(screen.queryByText(/55%/)).toBeNull();
    expect(screen.queryByText(/30%/)).toBeNull();
    expect(screen.queryByText(/15%/)).toBeNull();
    expect(screen.queryByText(/Tríada Completa Habilitada/i)).toBeNull();
  });

  it("Test case 4: Renders deterministic inference contract text (22.050 Hz and 32.000 Hz) avoiding SSR hydration mismatch", async () => {
    render(<PredictionView />);
    // By default (chilean birds), should render 22.050 Hz deterministically
    expect(screen.getByText(/Audios de 5\.0s a 22\.050 Hz/i)).toBeDefined();

    // After switching to engine model (32000 Hz), should render 32.000 Hz deterministically
    const modelSelect = (await screen.findByLabelText(/Modelo:/i)) as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(modelSelect, {
        target: { value: "car-engine-diagnostics-resnet34d-v2" },
      });
    });
    expect(await screen.findByText(/Audios de 1\.5s a 32\.000 Hz/i)).toBeDefined();
  });
});


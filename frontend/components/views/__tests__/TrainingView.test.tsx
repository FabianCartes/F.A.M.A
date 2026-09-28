import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
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
          json: async () => ({ history: [] }),
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
});

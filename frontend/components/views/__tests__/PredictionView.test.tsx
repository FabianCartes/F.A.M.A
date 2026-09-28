import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import PredictionView from "../PredictionView";

describe("PredictionView responsive header and controls", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/models")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              models: [
                {
                  id: "chilean-birds-ensemble",
                  name: "Aves Chilenas · Super-Ensamble Tri-Modelo (88.68% F1)",
                  description: "Ensamble",
                  target_sr: 22050,
                  duration_seconds: 5.0,
                  classes: ["Chucao"],
                  is_default: true,
                },
              ],
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
    // The select element must have truncate, min-w-0, and responsive max-w to prevent blowout
    expect(modelSelect.className).toContain("truncate");
    expect(modelSelect.className).toContain("min-w-0");

    // The latency element must have shrink-0 and whitespace-nowrap
    const latencyContainer = screen.getByText(/Latencia:\s*0\.14s/i).closest("div");
    expect(latencyContainer?.className).toContain("shrink-0");
    expect(latencyContainer?.className).toContain("whitespace-nowrap");
  });
});

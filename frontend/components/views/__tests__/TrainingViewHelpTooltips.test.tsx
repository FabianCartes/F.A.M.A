import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, within } from "@testing-library/react";
import TrainingView from "../TrainingView";

// Mock fetch for TrainingView initialization
global.fetch = vi.fn();

describe("TrainingView - Parameter Help & Explanations Tooltips", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        is_training: false,
        status: "idle",
        metrics: [],
        models: [],
      }),
    });
  });

  it("renders help question mark triggers for audio features and hyperparameters", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    // Check that help triggers exist for key parameters
    expect(screen.getByRole("button", { name: /ver ayuda: target_sr/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /ver ayuda: duration_seconds/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /ver ayuda: learning_rate/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /ver ayuda: weight_decay/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /ver ayuda: epochs/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /ver ayuda: batch_size/i })).toBeDefined();
  });

  it("shows explanation on hover and hides on mouse leave for an audio parameter (target_sr)", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const trigger = screen.getByRole("button", { name: /ver ayuda: target_sr/i });

    // Initially hidden
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Hover in
    fireEvent.mouseEnter(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toBeDefined();
    expect(within(tooltip).getByText(/límite de Nyquist/i)).toBeDefined();
    expect(within(tooltip).getByText(/16 kHz para voz/i)).toBeDefined();

    // Hover out
    fireEvent.mouseLeave(trigger);

    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("shows explanation on hover and hides on mouse leave for a hyperparameter (learning_rate)", async () => {
    await act(async () => {
      render(<TrainingView />);
    });

    const trigger = screen.getByRole("button", { name: /ver ayuda: learning_rate/i });

    // Hover in
    fireEvent.mouseEnter(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toBeDefined();
    expect(within(tooltip).getByText(/tamaño del paso de actualización/i)).toBeDefined();
    expect(within(tooltip).getByText(/AdamW/i)).toBeDefined();

    // Hover out
    fireEvent.mouseLeave(trigger);

    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

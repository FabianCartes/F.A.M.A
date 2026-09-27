import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTrainingLifecycle } from "../useTrainingLifecycle";
import * as trainingApi from "@/lib/api/trainingApi";

vi.mock("@/lib/api/trainingApi");

describe("useTrainingLifecycle (ODD Lifecycle Hook Tests)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();

    vi.mocked(trainingApi.getHardwareStatus).mockResolvedValue({
      cuda_available: false,
      device_name: "CPU Host",
      vram_total_gb: 16,
      vram_used_gb: 4,
      vram_percent: 25,
      cpu_percent: 20,
      load_status: "Carga Normal",
      load_level: "normal",
      status: "ready",
    });

    vi.mocked(trainingApi.getDatasets).mockResolvedValue([
      {
        id: "AvesChilenas",
        name: "AvesChilenas (1211 audios)",
        audio_count: 1211,
        class_count: 15,
        classes: ["Chercán"],
        size_mb: 340,
        estado: "sincronizado",
      },
    ]);

    vi.mocked(trainingApi.getHistory).mockResolvedValue([
      {
        id: 1,
        architecture: "AudioCNN",
        epochs: 10,
        accuracy: 75,
        loss: 0.5,
        active: true,
        status: "activo",
        filename: "test.pt",
        created_at: null,
      },
    ]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("initializes and loads hardware, datasets and history with 'online' status", async () => {
    const { result } = renderHook(() => useTrainingLifecycle());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.connectionStatus).toBe("online");
    expect(result.current.hardware?.device_name).toBe("CPU Host");
    expect(result.current.datasets).toHaveLength(1);
    expect(result.current.history).toHaveLength(1);
  });

  it("handles network failure with backoff and marks status as reconnecting and offline", async () => {
    vi.mocked(trainingApi.getHardwareStatus).mockRejectedValue(
      new trainingApi.ApiConnectionError("Server unreachable")
    );
    vi.mocked(trainingApi.getDatasets).mockRejectedValue(
      new trainingApi.ApiConnectionError("Server unreachable")
    );
    vi.mocked(trainingApi.getHistory).mockRejectedValue(
      new trainingApi.ApiConnectionError("Server unreachable")
    );

    const { result } = renderHook(() => useTrainingLifecycle());

    await act(async () => {
      await Promise.resolve();
    });

    // With multiple failures on mount, status becomes reconnecting or offline
    expect(["reconnecting", "offline"]).toContain(result.current.connectionStatus);
    expect(result.current.lastError).toBeTruthy();
  });

  it("starts training, updates active state, and starts polling", async () => {
    vi.mocked(trainingApi.startTraining).mockResolvedValue({
      status: "started",
      job_id: "test_job_1",
      message: "Training started",
    });

    vi.mocked(trainingApi.getProgress).mockResolvedValue({
      status: "training",
      job_id: "test_job_1",
      is_tri_model: false,
      current_model_index: 1,
      total_models: 1,
      current_architecture: "EfficientNet-B0",
      epoch: 1,
      total_epochs: 10,
      train_loss: 0.9,
      val_loss: 0.8,
      train_acc: 50,
      val_acc: 55,
      metrics_history: [],
      logs: [{ timestamp: "12:00:00", level: "INFO", message: "Epoch 1 start" }],
      elapsed_seconds: 2,
      error_message: null,
    });

    const { result } = renderHook(() => useTrainingLifecycle());

    await act(async () => {
      await Promise.resolve();
    });

    let success = false;
    await act(async () => {
      success = await result.current.start({
        dataset_name: "AvesChilenas",
        architecture: "EfficientNet-B0",
        epochs: 10,
        learning_rate: 0.001,
        batch_size: 16,
        framework: "pytorch",
        is_tri_model: false,
      });
    });

    expect(success).toBe(true);
    expect(result.current.isTraining).toBe(true);
    expect(result.current.trainingJobId).toBe("test_job_1");

    // Advance 1s timer to trigger progress poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.currentEpoch).toBe(1);
    expect(result.current.logs).toHaveLength(1);
    expect(result.current.logs[0].message).toBe("Epoch 1 start");
  });

  it("handles training completion gracefully and refreshes history", async () => {
    vi.mocked(trainingApi.startTraining).mockResolvedValue({
      status: "started",
      job_id: "test_job_2",
      message: "Started",
    });

    vi.mocked(trainingApi.getProgress).mockResolvedValue({
      status: "completed",
      job_id: "test_job_2",
      is_tri_model: false,
      current_model_index: 1,
      total_models: 1,
      current_architecture: "AudioCNN",
      epoch: 10,
      total_epochs: 10,
      train_loss: 0.2,
      val_loss: 0.25,
      train_acc: 90,
      val_acc: 88,
      metrics_history: [],
      logs: [],
      elapsed_seconds: 20,
      error_message: null,
    });

    const { result } = renderHook(() => useTrainingLifecycle());

    await act(async () => {
      await result.current.start({
        dataset_name: "AvesChilenas",
        architecture: "AudioCNN",
        epochs: 10,
        learning_rate: 0.001,
        batch_size: 16,
        framework: "pytorch",
        is_tri_model: false,
      });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.isTraining).toBe(false);
    expect(trainingApi.getHistory).toHaveBeenCalled();
  });
});

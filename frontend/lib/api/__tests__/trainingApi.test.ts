import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getHardwareStatus,
  getDatasets,
  startTraining,
  getProgress,
  stopTraining,
  getHistory,
  activateModel,
  ApiConnectionError,
  TrainingBusyError,
  ValidationError,
} from "../trainingApi";
import { API_BASE_URL } from "../../api";

describe("trainingApi (TDD Contract Tests)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe("getHardwareStatus", () => {
    it("fetches hardware status successfully and parses schema", async () => {
      const mockData = {
        cuda_available: true,
        device_name: "NVIDIA GeForce RTX 4090",
        vram_total_gb: 24.0,
        vram_used_gb: 6.5,
        vram_percent: 27.1,
        cpu_percent: 18.5,
        cpu_cores: 16,
        host_ram_total_gb: 64.0,
        host_ram_used_gb: 20.0,
        host_ram_percent: 31.25,
        temperature_c: 54,
        load_status: "Carga Normal",
        load_level: "normal",
        status: "ready",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockData,
      });

      const result = await getHardwareStatus();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/hardware`,
        expect.objectContaining({ method: "GET" })
      );
      expect(result.cuda_available).toBe(true);
      expect(result.device_name).toBe("NVIDIA GeForce RTX 4090");
      expect(result.vram_percent).toBe(27.1);
    });

    it("throws ApiConnectionError when network request fails", async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error("Network failed"));

      await expect(getHardwareStatus()).rejects.toThrow(ApiConnectionError);
    });

    it("throws ValidationError when payload does not conform to schema", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ invalid_payload: true }),
      });

      await expect(getHardwareStatus()).rejects.toThrow(ValidationError);
    });
  });

  describe("getDatasets", () => {
    it("fetches available training datasets list", async () => {
      const mockResponse = {
        datasets: [
          {
            id: "AvesChilenas",
            name: "AvesChilenas (1211 audios)",
            audio_count: 1211,
            class_count: 15,
            classes: ["Canastero", "Chercán"],
            size_mb: 340.5,
            estado: "sincronizado",
            domain: "bioacoustic",
          },
          {
            id: "engine_diagnostics",
            name: "Motores Vehiculares (1380 audios)",
            audio_count: 1380,
            class_count: 13,
            classes: ["biela", "cigueñal"],
            size_mb: 420.0,
            estado: "sincronizado",
            domain: "industrial",
          },
        ],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      });

      const datasets = await getDatasets();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/datasets`,
        expect.objectContaining({ method: "GET" })
      );
      expect(datasets).toHaveLength(2);
      expect(datasets[0].id).toBe("AvesChilenas");
      expect(datasets[1].id).toBe("engine_diagnostics");
    });

    it("throws ApiConnectionError on 500 server error", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => ({ detail: "Database unavailable" }),
      });

      await expect(getDatasets()).rejects.toThrow(ApiConnectionError);
    });
  });

  describe("startTraining", () => {
    const validParams = {
      dataset_name: "AvesChilenas",
      architecture: "EfficientNet-B0",
      epochs: 10,
      learning_rate: 0.001,
      weight_decay: 0.01,
      batch_size: 16,
      framework: "pytorch",
      is_tri_model: false,
    };

    it("starts training successfully with valid parameters", async () => {
      const mockStartResponse = {
        status: "started",
        job_id: "fama_efficientnet_123",
        message: "Entrenamiento iniciado",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockStartResponse,
      });

      const res = await startTraining(validParams);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/start`,
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(validParams),
        })
      );
      expect(res.status).toBe("started");
      expect(res.job_id).toBe("fama_efficientnet_123");
    });

    it("throws TrainingBusyError when training is already in progress (400)", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: async () => ({
          detail: "Ya existe un proceso de entrenamiento en ejecución.",
        }),
      });

      await expect(startTraining(validParams)).rejects.toThrow(TrainingBusyError);
    });

    it("throws ValidationError when dataset_name is empty", async () => {
      const invalid = { ...validParams, dataset_name: "" };
      await expect(startTraining(invalid)).rejects.toThrow(ValidationError);
    });

    it("throws ValidationError when epochs is non-positive", async () => {
      const invalid = { ...validParams, epochs: 0 };
      await expect(startTraining(invalid)).rejects.toThrow(ValidationError);
    });

    it("passes weight_decay successfully in payload when provided", async () => {
      const mockStartResponse = {
        status: "started",
        job_id: "fama_adamw_456",
        message: "Entrenamiento iniciado con AdamW",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockStartResponse,
      });

      const paramsWithWeightDecay = {
        ...validParams,
        weight_decay: 0.05,
      };

      const res = await startTraining(paramsWithWeightDecay);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/start`,
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...validParams,
            weight_decay: 0.05,
          }),
        })
      );
      expect(res.status).toBe("started");
    });

    it("throws ValidationError when weight_decay is negative or greater than 1", async () => {
      const invalidNegative = { ...validParams, weight_decay: -0.01 };
      await expect(startTraining(invalidNegative)).rejects.toThrow(ValidationError);

      const invalidExcessive = { ...validParams, weight_decay: 1.5 };
      await expect(startTraining(invalidExcessive)).rejects.toThrow(ValidationError);
    });

    it("validates and sends model epochs in payload when ensemble specifies them", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          status: "started",
          job_id: "fama_ensemble_epochs_123",
          message: "Entrenamiento iniciado",
        }),
      });

      const paramsWithModelEpochs = {
        ...validParams,
        models: [
          { architecture: "ResNet-34d", weight: 0.6, epochs: 35 },
          { architecture: "EfficientNet-B0", weight: 0.4, epochs: 10 },
        ],
      };

      const res = await startTraining(paramsWithModelEpochs);
      expect(res.status).toBe("started");

      const callBody = JSON.parse((global.fetch as any).mock.calls[0][1].body);
      expect(callBody.models[0].epochs).toBe(35);
      expect(callBody.models[1].epochs).toBe(10);
    });

    it("throws ValidationError when model epochs is non-positive or exceeds 1000", async () => {
      const invalidZeroEpochs = {
        ...validParams,
        models: [{ architecture: "ResNet-34d", weight: 1.0, epochs: 0 }],
      };
      await expect(startTraining(invalidZeroEpochs)).rejects.toThrow(ValidationError);

      const invalidExcessiveEpochs = {
        ...validParams,
        models: [{ architecture: "ResNet-34d", weight: 1.0, epochs: 1001 }],
      };
      await expect(startTraining(invalidExcessiveEpochs)).rejects.toThrow(ValidationError);

      // 1000 epochs is allowed
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          job_id: "fama_max_epochs_1000",
          status: "started",
          message: "Training started",
        }),
      });
      const validMaxEpochs = {
        ...validParams,
        models: [{ architecture: "ResNet-34d", weight: 1.0, epochs: 1000 }],
      };
      await expect(startTraining(validMaxEpochs)).resolves.toBeDefined();
    });
  });

  describe("getProgress", () => {
    it("fetches training progress snapshot with metrics and logs", async () => {
      const mockProgress = {
        status: "training",
        job_id: "fama_job_1",
        is_tri_model: true,
        current_model_index: 2,
        total_models: 3,
        current_architecture: "ConvNeXt-Nano",
        epoch: 5,
        total_epochs: 12,
        train_loss: 0.42,
        val_loss: 0.38,
        train_acc: 88.5,
        val_acc: 85.0,
        metrics_history: [
          {
            epoca: 1,
            train_loss: 1.2,
            val_loss: 1.1,
            train_acc: 50.0,
            val_acc: 55.0,
            tiempo_epoca: 1.2,
          },
        ],
        logs: [
          {
            id: "log_1",
            timestamp: "12:00:01",
            level: "INFO",
            message: "Epoch 1 finished",
          },
        ],
        elapsed_seconds: 15.4,
        error_message: null,
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockProgress,
      });

      const progress = await getProgress();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/progress`,
        expect.objectContaining({ method: "GET" })
      );
      expect(progress.status).toBe("training");
      expect(progress.epoch).toBe(5);
      expect(progress.metrics_history).toHaveLength(1);
      expect(progress.logs).toHaveLength(1);
    });

    it("transforms raw string logs into structured log objects", async () => {
      const mockProgressWithLegacyLogs = {
        status: "training",
        epoch: 1,
        total_epochs: 10,
        train_loss: 1.0,
        val_loss: 0.9,
        train_acc: 60.0,
        val_acc: 65.0,
        logs: ["Época 1 finalizada con éxito"],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockProgressWithLegacyLogs,
      });

      const progress = await getProgress();
      expect(progress.logs[0].message).toBe("Época 1 finalizada con éxito");
      expect(progress.logs[0].level).toBe("INFO");
    });
  });

  describe("stopTraining", () => {
    it("requests cooperative training stop", async () => {
      const mockStopResponse = {
        status: "stopping",
        message: "Detención solicitada",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockStopResponse,
      });

      const res = await stopTraining();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/stop`,
        expect.objectContaining({ method: "POST" })
      );
      expect(res.status).toBe("stopping");
    });

    it("throws ApiConnectionError when network fails during stop", async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error("Connection reset"));
      await expect(stopTraining()).rejects.toThrow(ApiConnectionError);
    });
  });

  describe("getHistory", () => {
    it("fetches model history catalog", async () => {
      const mockHistory = {
        history: [
          {
            id: 1,
            architecture: "Super-Ensamble Tri-Modelo",
            epochs: 50,
            accuracy: 86.75,
            loss: 0.4521,
            active: true,
            status: "activo",
            filename: "super_ensemble_calibrated.pt",
            created_at: "2026-09-10T14:30:00Z",
          },
        ],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockHistory,
      });

      const history = await getHistory();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/history`,
        expect.objectContaining({ method: "GET" })
      );
      expect(history).toHaveLength(1);
      expect(history[0].architecture).toBe("Super-Ensamble Tri-Modelo");
      expect(history[0].active).toBe(true);
    });
  });

  describe("activateModel", () => {
    it("activates target model successfully", async () => {
      const mockActivateResponse = {
        success: true,
        active_model_id: 1,
        architecture: "Super-Ensamble Tri-Modelo",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockActivateResponse,
      });

      const res = await activateModel(1);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/training/models/1/activate`,
        expect.objectContaining({ method: "POST" })
      );
      expect(res.success).toBe(true);
      expect(res.active_model_id).toBe(1);
    });

    it("throws ApiConnectionError when activate returns 500", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Server Error",
        json: async () => ({ detail: "Database lock" }),
      });

      await expect(activateModel(99)).rejects.toThrow(ApiConnectionError);
    });
  });
});

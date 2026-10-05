import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  sendFeedback,
  getPendingFeedback,
  approveFeedback,
  rejectFeedback,
  getFeedbackStats,
  ApiConnectionError,
  ValidationError,
  NotFoundError,
} from "../feedbackApi";
import { API_BASE_URL } from "../../api";

describe("feedbackApi (TDD Contract Tests for RF_06 & Semi-Manual Curation)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  // ==========================================================================
  // 1. sendFeedback
  // ==========================================================================
  describe("sendFeedback", () => {
    it("successfully posts validation feedback (correct prediction) and parses 201 response", async () => {
      const mockResponse = {
        id_retroalimentacion: 101,
        id_prediccion: 42,
        id_usuario: 1,
        fue_correcta: true,
        etiqueta_corregida: null,
        procesado: false,
        fecha_retroalimentacion: "2026-09-27T19:30:00Z",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        json: async () => mockResponse,
      });

      const payload = {
        id_prediccion: 42,
        fue_correcta: true,
      };

      const result = await sendFeedback(payload);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/feedback`,
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id_prediccion: 42,
            fue_correcta: true,
            id_usuario: 1,
          }),
        })
      );
      expect(result.id_retroalimentacion).toBe(101);
      expect(result.fue_correcta).toBe(true);
      expect(result.procesado).toBe(false);
    });

    it("successfully posts correction feedback with corrected label and parses response", async () => {
      const mockResponse = {
        id_retroalimentacion: 102,
        id_prediccion: 43,
        id_usuario: 2,
        fue_correcta: false,
        etiqueta_corregida: "Chucao",
        procesado: false,
        fecha_retroalimentacion: "2026-09-27T19:35:00Z",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        json: async () => mockResponse,
      });

      const payload = {
        id_prediccion: 43,
        fue_correcta: false,
        etiqueta_corregida: "Chucao",
        id_usuario: 2,
      };

      const result = await sendFeedback(payload);

      expect(result.id_retroalimentacion).toBe(102);
      expect(result.fue_correcta).toBe(false);
      expect(result.etiqueta_corregida).toBe("Chucao");
    });

    it("throws ValidationError when fue_correcta is false and etiqueta_corregida is missing", async () => {
      await expect(
        sendFeedback({
          id_prediccion: 44,
          fue_correcta: false,
        })
      ).rejects.toThrow(ValidationError);
    });

    it("throws NotFoundError when backend returns 404 for nonexistent prediction", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({
          detail: "Predicción con ID 999 no encontrada en base de datos.",
        }),
      });

      await expect(
        sendFeedback({
          id_prediccion: 999,
          fue_correcta: true,
        })
      ).rejects.toThrow(NotFoundError);
    });

    it("throws ApiConnectionError when backend returns 422 Unprocessable Entity", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        json: async () => ({
          detail: "Validation error in request payload",
        }),
      });

      await expect(
        sendFeedback({
          id_prediccion: 50,
          fue_correcta: true,
        })
      ).rejects.toThrow(ApiConnectionError);
    });

    it("throws ApiConnectionError when fetch throws network error", async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error("Connection refused"));

      await expect(
        sendFeedback({
          id_prediccion: 50,
          fue_correcta: true,
        })
      ).rejects.toThrow(ApiConnectionError);
    });
  });

  // ==========================================================================
  // 2. getPendingFeedback
  // ==========================================================================
  describe("getPendingFeedback", () => {
    it("fetches pending curation items with default limit=50 and parses list", async () => {
      const mockList = [
        {
          id_retroalimentacion: 1,
          id_prediccion: 10,
          ruta_audio_prueba: "data/raw/test/audio_10.wav",
          etiqueta_predicha: "Rayadito",
          confianza: 0.87,
          etiqueta_corregida: "Chucao",
          fecha_retroalimentacion: "2026-09-27T18:00:00Z",
          fue_correcta: false,
          procesado: false,
          id_usuario: 1,
          audio_filename: "audio_10.wav",
          dataset_name: "AvesChilenas",
        },
      ];

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockList,
      });

      const items = await getPendingFeedback();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/feedback/pending?limit=50`,
        expect.objectContaining({ method: "GET" })
      );
      expect(items).toHaveLength(1);
      expect(items[0].id_retroalimentacion).toBe(1);
      expect(items[0].etiqueta_predicha).toBe("Rayadito");
      expect(items[0].etiqueta_corregida).toBe("Chucao");
      expect(items[0].dataset_name).toBe("AvesChilenas");
    });

    it.each([null, undefined])("preserves unknown dataset association (%s) without defaulting", async (dataset_name) => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [{
        id_retroalimentacion: 1, id_prediccion: 10, ruta_audio_prueba: 'old.wav',
        etiqueta_predicha: 'Rayadito', confianza: 0.9, fue_correcta: true, procesado: false,
        ...(dataset_name === undefined ? {} : { dataset_name }),
      }] });
      const [item] = await getPendingFeedback();
      expect(item.dataset_name ?? null).toBeNull();
    });

    it("supports custom limit parameter", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [],
      });

      await getPendingFeedback(15);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/feedback/pending?limit=15`,
        expect.objectContaining({ method: "GET" })
      );
    });

    it("throws ValidationError when response does not match expected schema", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [{ invalid_field: 123 }],
      });

      await expect(getPendingFeedback()).rejects.toThrow(ValidationError);
    });
  });

  // ==========================================================================
  // 3. approveFeedback
  // ==========================================================================
  describe("approveFeedback", () => {
    it("approves by feedback ID only without selecting or overriding a dataset", async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'approved', id_retroalimentacion: 6, destination_path: 'local.wav', clase: 'Rayadito', local_status: 'incorporated', sync_status: 'pending' }) });
      await approveFeedback(6);
      expect(global.fetch).toHaveBeenCalledWith(`${API_BASE_URL}/api/feedback/6/approve`, expect.objectContaining({ method: 'POST' }));
    });
    it("sends POST approval without query and returns confirmation with canonical filename", async () => {
      const mockResponse = {
        status: "approved",
        local_status: "incorporated",
        sync_status: "pending",
        id_retroalimentacion: 5,
        destination_path: "backend/data/raw/AvesChilenas/Chucao/chucao_fb_5.wav",
        clase: "Chucao",
        filename: "chucao_fb_5.wav",
        message: "Audio incorporado exitosamente",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      });

      const result = await approveFeedback(5);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/feedback/5/approve`,
        expect.objectContaining({ method: "POST" })
      );
      expect(result.status).toBe("approved");
      expect(result.destination_path).toContain("AvesChilenas");
      expect(result.filename).toBe("chucao_fb_5.wav");
    });

    it("throws NotFoundError when feedback item does not exist (404)", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({
          detail: "Retroalimentación con ID 999 no encontrada.",
        }),
      });

      await expect(approveFeedback(999)).rejects.toThrow(NotFoundError);
    });
  });

  // ==========================================================================
  // 4. rejectFeedback
  // ==========================================================================
  describe("rejectFeedback", () => {
    it("sends POST reject request and returns rejection confirmation", async () => {
      const mockResponse = {
        status: "rejected",
        id_retroalimentacion: 8,
        message: "Feedback descartado",
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      });

      const result = await rejectFeedback(8);

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/feedback/8/reject`,
        expect.objectContaining({ method: "POST" })
      );
      expect(result.status).toBe("rejected");
    });

    it("throws NotFoundError when feedback item does not exist (404)", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({
          detail: "Retroalimentación con ID 999 no encontrada.",
        }),
      });

      await expect(rejectFeedback(999)).rejects.toThrow(NotFoundError);
    });
  });

  // ==========================================================================
  // 5. getFeedbackStats
  // ==========================================================================
  describe("getFeedbackStats", () => {
    it("fetches consolidated feedback stats and parses schema", async () => {
      const mockStats = {
        total_validated: 120,
        correct_count: 105,
        corrected_count: 15,
        accuracy_rate: 87.5,
        pending_curation_count: 7,
        corrections_breakdown: [
          { etiqueta_corregida: "Chucao", count: 8 },
          { etiqueta_corregida: "Rayadito", count: 7 },
        ],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockStats,
      });

      const stats = await getFeedbackStats();

      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/feedback/stats`,
        expect.objectContaining({ method: "GET" })
      );
      expect(stats.total_validated).toBe(120);
      expect(stats.accuracy_rate).toBe(87.5);
      expect(stats.pending_curation_count).toBe(7);
      expect(stats.corrections_breakdown).toHaveLength(2);
    });

    it("handles zero stats gracefully", async () => {
      const mockZeroStats = {
        total_validated: 0,
        correct_count: 0,
        corrected_count: 0,
        accuracy_rate: 0.0,
        pending_curation_count: 0,
        corrections_breakdown: [],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockZeroStats,
      });

      const stats = await getFeedbackStats();

      expect(stats.total_validated).toBe(0);
      expect(stats.pending_curation_count).toBe(0);
      expect(stats.corrections_breakdown).toEqual([]);
    });

    it("throws ApiConnectionError on network error", async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error("Network down"));

      await expect(getFeedbackStats()).rejects.toThrow(ApiConnectionError);
    });
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, within } from "@testing-library/react";
import IngestionView from "../IngestionView";
import * as feedbackApi from "@/lib/api/feedbackApi";

vi.mock("@/lib/api/feedbackApi", () => ({
  getPendingFeedback: vi.fn(),
  approveFeedback: vi.fn(),
  rejectFeedback: vi.fn(),
  getFeedbackStats: vi.fn(),
  sendFeedback: vi.fn(),
}));

const mockStatus = {
  connected: true,
  bucket: "fama-audio-records-2026",
  total_objects: 120,
  total_bytes: 10485760,
  error: null,
};

const mockDatasets = [
  {
    id: "AvesChilenas",
    name: "AvesChilenas",
    file_count: 45,
    class_count: 15,
    classes: ["Chucao", "Rayadito"],
    total_size_bytes: 25000000,
    last_modified: "2026-09-28T10:00:00Z",
    local_file_count: 45,
    is_synced: true,
  },
];

describe("IngestionView (Human-in-the-Loop MLOps Curation Tray - ADR 0013 / RF_06)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValue([]);
    vi.mocked(feedbackApi.approveFeedback).mockResolvedValue({
      status: "approved",
      id_retroalimentacion: 42,
      destination_path: "datasets/AvesChilenas/Chucao/canto_chucao_01.wav",
      clase: "Chucao",
      filename: "canto_chucao_01.wav",
      message: "Audio incorporado exitosamente al dataset",
    });
    vi.mocked(feedbackApi.rejectFeedback).mockResolvedValue({
      status: "rejected",
      id_retroalimentacion: 42,
      message: "Audio descartado de la cola de curación",
    });

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("/api/ingestion/status")) {
        return {
          ok: true,
          json: async () => mockStatus,
        };
      }
      if (url.includes("/api/ingestion/datasets")) {
        return {
          ok: true,
          json: async () => ({ datasets: mockDatasets }),
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

  it("d) verifies blind direct upload form (#panel-carga-audios or direct input) no longer exists", async () => {
    await act(async () => {
      render(<IngestionView />);
    });

    expect(document.getElementById("panel-carga-audios")).toBeNull();
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByText(/Carga Jerárquica al Data Lake/i)).toBeNull();
    expect(screen.queryByText(/Subir audios a GCS/i)).toBeNull();
  });

  it("a) renders curation section #seccion-curacion-feedback located after datasets table", async () => {
    await act(async () => {
      render(<IngestionView />);
    });

    const curationSection = document.getElementById("seccion-curacion-feedback");
    expect(curationSection).not.toBeNull();

    const datasetsTable = screen.getByRole("table");
    expect(datasetsTable).not.toBeNull();

    // Check DOM position: curationSection follows datasetsTable
    expect(datasetsTable.compareDocumentPosition(curationSection!)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it("b) renders curation-queue-empty indicator when queue is empty and calls onNavigate('predict')", async () => {
    vi.mocked(feedbackApi.getPendingFeedback).mockResolvedValueOnce([]);
    const onNavigateMock = vi.fn();

    await act(async () => {
      render(<IngestionView onNavigate={onNavigateMock} />);
    });

    const emptyBox = screen.getByTestId("curation-queue-empty");
    expect(emptyBox).not.toBeNull();
    expect(emptyBox.getAttribute("role")).toBe("status");
    expect(emptyBox.getAttribute("aria-live")).toBe("polite");

    expect(
      screen.getByText(/Cola de curación vacía \(0 audios pendientes de incorporación\)/i)
    ).toBeDefined();
    expect(
      screen.getByText(
        /Todos los audios clasificados han sido procesados\. Para incorporar nuevas grabaciones con validación de modelo, realiza inferencias en el clasificador acústico\./i
      )
    ).toBeDefined();

    const navButton = screen.getByRole("button", { name: /Ir a Inferencia Acústica/i });
    expect(navButton).toBeDefined();

    await act(async () => {
      fireEvent.click(navButton);
    });

    expect(onNavigateMock).toHaveBeenCalledTimes(1);
    expect(onNavigateMock).toHaveBeenCalledWith("predict");
  });

  it("c) renders pending feedback list and invokes approveFeedback and rejectFeedback", async () => {
    const mockItem1 = {
      id_retroalimentacion: 42,
      id_prediccion: 101,
      id_usuario: 1,
      ruta_audio_prueba: "audio_feedback_42.wav",
      etiqueta_predicha: "Chincol",
      confianza: 0.942,
      etiqueta_corregida: "Chucao",
      fecha_retroalimentacion: "2026-09-28T14:30:00Z",
      fue_correcta: false,
      procesado: false,
      audio_filename: "audio_feedback_42.wav",
    };
    const mockItem2 = {
      id_retroalimentacion: 43,
      id_prediccion: 102,
      id_usuario: 1,
      ruta_audio_prueba: "audio_feedback_43.wav",
      etiqueta_predicha: "Rayadito",
      confianza: 0.88,
      etiqueta_corregida: null,
      fecha_retroalimentacion: "2026-09-28T14:35:00Z",
      fue_correcta: true,
      procesado: false,
      audio_filename: "audio_feedback_43.wav",
    };

    vi.mocked(feedbackApi.getPendingFeedback)
      .mockResolvedValueOnce([mockItem1, mockItem2])
      .mockResolvedValueOnce([mockItem2])
      .mockResolvedValueOnce([]);

    await act(async () => {
      render(<IngestionView />);
    });

    // Empty state must NOT be visible
    expect(screen.queryByTestId("curation-queue-empty")).toBeNull();

    // Pending item data should be rendered
    const curationSection = document.getElementById("seccion-curacion-feedback");
    expect(curationSection).not.toBeNull();
    expect(screen.getByText(/audio_feedback_42\.wav/i)).toBeDefined();
    expect(within(curationSection!).getByText("Chucao")).toBeDefined();
    expect(screen.getByText(/94(\.2)?%/i)).toBeDefined();

    // Check Approve button on first item
    const approveButtons = screen.getAllByRole("button", {
      name: /Aprobar e Incorporar al Dataset/i,
    });
    expect(approveButtons.length).toBe(2);

    await act(async () => {
      fireEvent.click(approveButtons[0]);
    });

    expect(feedbackApi.approveFeedback).toHaveBeenCalledWith(42, expect.anything());

    // After approval refresh, mockItem2 remains
    const rejectButtons = screen.getAllByRole("button", { name: /Descartar/i });
    expect(rejectButtons.length).toBe(1);

    await act(async () => {
      fireEvent.click(rejectButtons[0]);
    });

    expect(feedbackApi.rejectFeedback).toHaveBeenCalledWith(43);
  });

  it("handles GCS disconnected status gracefully and displays local datasets with Local badge", async () => {
    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("/api/ingestion/status")) {
        return {
          ok: true,
          json: async () => ({
            connected: false,
            bucket: "fama-audio-records-2026",
            total_objects: 0,
            total_bytes: 0,
            error: "Google Cloud credentials not found or network unreachable",
          }),
        };
      }
      if (url.includes("/api/ingestion/datasets")) {
        return {
          ok: true,
          json: async () => ({
            datasets: [
              {
                id: "AvesChilenas",
                name: "AvesChilenas",
                file_count: 45,
                class_count: 15,
                classes: ["Chucao", "Rayadito"],
                total_size_bytes: 25000000,
                last_modified: "2026-09-28T10:00:00Z",
                local_file_count: 45,
                is_synced: true,
                source: "local",
                gcs_available: false,
                domain: "bioacoustic",
                domain_label: "Bioacústica Silvestre",
              },
            ],
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    await act(async () => {
      render(<IngestionView />);
    });

    expect(screen.getByText(/GCP: Desconectado/i)).toBeDefined();
    expect(screen.getByText(/Data Lake en modo local/i)).toBeDefined();
    expect(screen.getByText("AvesChilenas")).toBeDefined();
  });
});

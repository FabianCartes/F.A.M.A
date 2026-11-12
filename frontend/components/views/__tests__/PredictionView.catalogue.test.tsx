import { chooseModel, modelOptions } from "../../prediction/__tests__/selectorActions";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionView, { type RegisteredModel } from "../PredictionView";

vi.mock('@/components/auth/SessionBoundary', () => ({ useOptionalWebSession: () => ({ id: 1 }) }));

const bird: RegisteredModel = { dataset_name: 'AvesChilenas', id: "bird-cnn", name: "Aves CNN", description: "Aves", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito"], is_default: true, has_weights: true };
const engine: RegisteredModel = { dataset_name: 'engine_diagnostics', id: "engine-v2", name: "Motor v2", description: "Motor", target_sr: 32000, duration_seconds: 2, classes: ["bad_ignition", "low_oil"], is_default: false, has_weights: true };
const model11: RegisteredModel = { dataset_name: 'AvesChilenas', id: "fama_trained_model_11", name: "Modelo 11", description: "Aves nuevas", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito", "Chincol"], is_default: false, has_weights: true };
const response = (models: RegisteredModel[], defaultId = bird.id, publication_errors: { model_id?: string; code: string; reason?: string }[] = [], catalogueFields: Record<string, unknown> = {}) => new Response(JSON.stringify({ models, total: models.length, default_model_id: defaultId, publication_errors, ...catalogueFields }), { status: 200 });
function deferred() {
  let resolve!: (response: Response) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let catalogue: () => Promise<Response>;
let predict: () => Promise<Response>;
const selection = () => screen.getByRole("combobox", { name: "Modelo:" }) as HTMLButtonElement;
const focus = async () => { await act(async () => { fireEvent(window, new Event("focus")); }); };
const show = async () => { let view!: ReturnType<typeof render>; await act(async () => { view = render(<PredictionView />); }); return view; };
const openDetails = async () => {
  fireEvent.click(screen.getByRole("button", { name: "Ver detalle de evaluación" }));
  return screen.findByRole("dialog", { name: "Detalle de evaluación final" });
};
const provenance = (split: "val" | "test", schema_version: 1 | 2 = 1, sample_count = 4) => ({
  schema_version,
  evaluator_version: "classification-report-v1",
  checkpoint_sha256: "a".repeat(64),
  dataset: "AvesChilenas",
  split,
  manifest_sha256: "b".repeat(64),
  classes: ["Chucao", "Rayadito"],
  predictor_config: { architecture_family: "audio_cnn" },
  preprocessing_config: { target_sr: 22050 },
  aggregation_config: { algorithm: "recording-v1" },
  sample_count,
  code_revision: "167f2df",
});
const completeV1Report = {
  schema_version: 1,
  classes: ["Chucao", "Rayadito"],
  sample_count: 4,
  metrics: { accuracy: 1, precision_macro: 1, recall_macro: 1, f1_macro: 1, f1_weighted: 1, balanced_accuracy: 1 },
  per_class: [
    { label: "Chucao", precision: 1, recall: 1, f1: 1, support: 2, zero_denominator: { precision: false, recall: false, f1: false } },
    { label: "Rayadito", precision: 1, recall: 1, f1: 1, support: 2, zero_denominator: { precision: false, recall: false, f1: false } },
  ],
  support: [2, 2],
  confusion_matrix: [[2, 0], [0, 2]],
  coverage: { absent_classes: [], complete: true },
};
const incompleteV1Report = {
  schema_version: 1,
  classes: ["Chucao", "Rayadito"],
  sample_count: 2,
  metrics: { accuracy: 0.5, precision_macro: null, recall_macro: 0.5, f1_macro: 0.5, f1_weighted: 1, balanced_accuracy: 1 },
  per_class: [
    { label: "Chucao", precision: 0, recall: 0, f1: 0, support: 0, zero_denominator: { precision: true, recall: true, f1: true } },
    { label: "Rayadito", precision: 1, recall: 0.5, f1: 2 / 3, support: 2, zero_denominator: { precision: false, recall: false, f1: false } },
  ],
  support: [0, 2],
  confusion_matrix: [[0, 0], [1, 1]],
  coverage: { absent_classes: ["Chucao"], complete: false },
};
const v2Report = {
  schema_version: 2,
  classes: ["Chucao", "Rayadito"],
  sample_count: 2,
  metrics: { accuracy: 0, precision_macro: 0, recall_macro: 0, f1_macro: 0, f1_weighted: 0, balanced_accuracy: 0 },
  per_class: [
    { label: "Chucao", precision: 0, recall: 0, f1: 0, support: 2, zero_denominator: { precision: true, recall: false, f1: false } },
    { label: "Rayadito", precision: 0, recall: 0, f1: 0, support: 0, zero_denominator: { precision: false, recall: true, f1: false } },
  ],
  support: [2, 0],
  confusion_matrix: [[0, 1, 1], [0, 0, 0]],
  coverage: { absent_classes: ["Rayadito"], complete: false },
  prediction_columns: ["Chucao", "Rayadito", "__rejected__"],
  rejection: { label: "__rejected__", count: 1, rate: 0.5 },
};
const attempt = (id_evaluation: number, status: "pending" | "running" | "completed" | "failed", split: "val" | "test", schema_version: 1 | 2 = 1, sample_count = 4) => ({
  id_evaluation,
  status,
  provenance: provenance(split, schema_version, sample_count),
  created_at: "2025-02-01T10:00:00Z",
  started_at: "2025-02-01T10:01:00Z",
  finished_at: status === "completed" || status === "failed" ? "2025-02-01T10:02:00Z" : null,
});
const completed = (id_evaluation: number, split: "val" | "test", report: Record<string, unknown> = completeV1Report, schema_version: 1 | 2 = 1, sample_count = 4) => ({
  id_evaluation,
  provenance: provenance(split, schema_version, sample_count),
  report,
  created_at: "2025-02-01T10:00:00Z",
  started_at: "2025-02-01T10:01:00Z",
  finished_at: "2025-02-01T10:02:00Z",
});

beforeEach(() => {
  catalogue = async () => response([bird, engine]);
  predict = async () => new Response(JSON.stringify({ filename: "audio.wav", db_id: 201, clase: "Chucao", confianza: 0.9, gcp_upload: true, detalles: { dataset_name: "AvesChilenas" } }));
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/models")) return catalogue();
    if (url.includes("/api/model-info")) return new Response(null, { status: 503 });
    if (url.includes("/api/predict")) return predict();
    throw new Error(`HTTP no previsto: ${url}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Catálogo público de Predicción", () => {
  it("shows the same triad title and full ordered weights on the selected card, with joint metrics only", async () => {
    const triad = {
      ...model11, id: 'fama_trained_model_28', name: 'Birds · Tríada v4',
      architecture: 'ImportedTriad', dataset_name: 'Birds', checkpoint_sha256: 'a'.repeat(64),
      metrics: {
        triad_version: 4, same_components_as_version: 1,
        dataset_id: 'birds-private', dataset_display_name: 'Birds',
        weights: [0.4, 0.3, 0.3], f1_macro: 0.99, accuracy: 0.99,
        components: ['efficientnet_b0', 'convnext_nano', 'resnet34d'].map((architecture, index) => ({
          model_id: index + 1, checkpoint_sha256: String(index + 1).repeat(64),
          imported_source: { profile: { architecture } },
        })),
      },
      evaluations: { test: { latest_attempt: attempt(8, 'completed', 'test', 2, 2),
        latest_completed: completed(8, 'test', v2Report, 2, 2) } },
    } as unknown as RegisteredModel;
    catalogue = async () => response([triad], triad.id, [], { evaluation_catalogue_status: 'available' });
    await show();
    expect(selection().textContent).toContain('Birds · Tríada v4');
    const card = screen.getByRole('region', { name: 'Modelo seleccionado' });
    expect(within(card).getByRole('heading', { name: 'Birds · Tríada v4' })).toBeDefined();
    expect(within(card).getByText('B0 40 · CNX 30 · R34 30')).toBeDefined();
    expect(within(card).getByTitle('Mismos modelos que la v1; solo cambian los pesos')).toBeDefined();
    expect(card.textContent).not.toContain('99.00%');
    expect(card.textContent).not.toContain('99%');
  });

  it("summarizes evaluation details without internal metadata and explains class samples", async () => {
    const evaluated = { ...model11, checkpoint_sha256: "a".repeat(64), evaluations: {
      val: { latest_attempt: attempt(7, "completed", "val", 2, 2), latest_completed: completed(7, "val", v2Report, 2, 2) },
    } } as RegisteredModel;
    catalogue = async () => response([evaluated], evaluated.id, [], { evaluation_catalogue_status: "available" });
    await show();
    expect(screen.queryByRole("region", { name: "Identidad de checkpoints del modelo seleccionado" })).toBeNull();
    const dialog = await openDetails();
    expect(dialog.textContent).not.toMatch(/Schema|SHA-256|Denominador nulo|etiqueta __|checkpoint registrado:|parámetros.*runtime|Soporte por clase:/);
    expect(dialog.textContent).not.toContain("a".repeat(64));
    expect(dialog.textContent).not.toContain("2025-02-01T");
    const latest = within(dialog).getByRole("region", { name: "Último intento Validación (val)" });
    expect(within(latest).getAllByText(/Finalizado:/)).toHaveLength(1);
    expect(latest.textContent).toContain("1 de febrero de 2025");
    expect(latest.textContent).toContain("10:02");
    expect(latest.textContent).toContain("UTC");
    expect(dialog.textContent).toContain("Evaluación finalizada:");
    expect(dialog.textContent).toContain("Rechazos: 1 (50.00%)");
    const table = within(dialog).getByRole("table", { name: "Métricas por clase Validación (val)" });
    expect(within(table).getByRole("columnheader", { name: /Audios evaluados/ })).toBeDefined();
    fireEvent.focus(within(table).getByRole("button", { name: /Ver ayuda:/ }));
    expect(screen.getByRole("tooltip").textContent).toContain("Número de audios reales de cada clase");
    fireEvent.blur(within(table).getByRole("button", { name: /Ver ayuda:/ }));
    // A tap opens it outside the scrollable table, so the container cannot clip it.
    fireEvent.click(within(table).getByRole("button", { name: /Ver ayuda:/ }));
    const tapped = screen.getByRole("tooltip");
    expect(tapped.textContent).toContain("Número de audios reales de cada clase");
    expect(table.parentElement!.contains(tapped)).toBe(false);
    fireEvent.keyDown(document, { key: "Escape" });
    const coverageHelp = within(dialog).getByRole("button", { name: /Ver ayuda: cobertura-/ });
    fireEvent.focus(coverageHelp);
    expect(screen.getByRole("tooltip").textContent).toContain("todas las clases tienen audios");
  });

  it.each([
    ["invalid", "2025-02-01T10:01:00Z", "2025-02-01T10:00:00Z", "Iniciado: 1 de febrero de 2025, 10:01 UTC"],
    [null, null, "2025-02-01T10:00:00Z", "Solicitado: 1 de febrero de 2025, 10:00 UTC"],
    [null, "invalid", "invalid", "Fecha no disponible"],
  ])("uses a clearly labelled valid date when completion=%s", async (finished_at, started_at, created_at, expected) => {
    const evaluated = { ...model11, evaluations: { val: {
      latest_attempt: { ...attempt(7, "running", "val"), finished_at, started_at, created_at },
    } } } as RegisteredModel;
    catalogue = async () => response([evaluated], evaluated.id, [], { evaluation_catalogue_status: "available" });
    await show();
    const dialog = await openDetails();
    const latest = within(dialog).getByRole("region", { name: "Último intento Validación (val)" });
    expect(latest.textContent).toContain(expected);
    expect(latest.querySelectorAll("p")).toHaveLength(1);
    expect(latest.textContent).not.toContain("Invalid Date");
    expect(latest.textContent).not.toContain("2025-02-01T");
  });

  it("gives a long selected model name full width above wrapping metadata badges", async () => {
    const motor = { ...engine, name: "motores · PANNs-CNN14 (v2)", version: 2,
      description: "Inferencia bioacústica con pesos reales entrenados (PANNs-CNN14)" };
    catalogue = async () => response([motor], motor.id);
    await show();
    const heading = screen.getByRole("heading", { name: motor.name });
    const titleBlock = heading.parentElement!;
    const description = within(titleBlock).getByText(motor.description);
    const header = titleBlock.parentElement!;
    const badges = screen.getByText("Versión v2").parentElement!;
    expect(header.classList.contains("flex-col")).toBe(true);
    expect(titleBlock.classList.contains("w-full")).toBe(true);
    expect(titleBlock.classList.contains("min-w-0")).toBe(true);
    expect(heading.classList.contains("break-words")).toBe(true);
    expect(description.parentElement).toBe(titleBlock);
    expect(description.classList.contains("break-words")).toBe(true);
    expect(badges.parentElement).toBe(header);
    expect(badges.classList.contains("flex-wrap")).toBe(true);
    expect(badges.classList.contains("shrink-0")).toBe(false);
    expect(screen.getByText("Última respuesta: Dispositivo no informado")).toBeDefined();
    expect(selection().value).toBe(motor.id);
  });

  it("searches loaded model names without changing selection or requesting inference", async () => {
    await show();
    const requestsBefore = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(selection());
    const search = screen.getByRole("combobox", { name: "Buscar modelo por nombre" });
    fireEvent.change(search, { target: { value: "  mOTOR  " } });
    const options = within(screen.getByRole("listbox", { name: "Modelos disponibles" }));
    expect(options.getAllByRole("option").map(option => option.textContent)).toEqual(["Motor v2"]);
    expect(selection().value).toBe(bird.id);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(requestsBefore);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/predict"))).toBe(false);
    fireEvent.click(options.getByRole("option", { name: "Motor v2" }));
    expect(selection().value).toBe(engine.id);
    expect(screen.queryByRole("listbox", { name: "Modelos disponibles" })).toBeNull();
    expect(document.activeElement).toBe(selection());
  });

  it("shows the training display version without changing the technical selection", async () => {
    const trained = { ...model11, name: "Aves Chilenas · EfficientNet-B0 (v2)", version: 2,
      architecture: "EfficientNet-B0", dataset: "Aves Chilenas" };
    catalogue = async () => response([trained], trained.id);
    let persisted = false;
    const original = global.fetch;
    global.fetch = vi.fn(async (input, options) => {
      if (String(input).includes('/api/inference/history')) return Response.json({
        items: persisted ? [{ id: 201, filename: 'audio.wav', timestamp: '2026-01-01T12:00:00Z',
          clase: 'Chucao', confianza: .9, modelo_id: trained.id }] : [], next_cursor: null,
      });
      return original(input, options);
    });
    const view = await show();
    expect(selection().value).toBe("fama_trained_model_11");
    expect(selection().textContent).toContain(trained.name);
    expect(screen.getByRole("heading", { name: trained.name })).toBeTruthy();
    expect(screen.getByText("Versión v2")).toBeTruthy();
    expect(screen.queryByText("Versión no publicada")).toBeNull();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    predict = async () => {
      persisted = true;
      return Response.json({ filename: "audio.wav", db_id: 201,
        clase: "Chucao", confianza: 0.9, modelo: trained.name, modelo_id: trained.id, gcp_upload: true });
    };
    await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(["audio"], "audio.wav")] } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Ejecutar inferencia/ })); });
    expect(screen.getByText("Modelo ejecutado:").parentElement?.textContent).toContain(trained.name);
    expect(screen.getByRole("row", { name: /audio\.wav/ }).textContent).toContain(trained.name);
    catalogue = async () => response([bird], bird.id);
    await focus();
    expect(screen.getByText("Versión no publicada")).toBeTruthy();
  });

  it("presenta los informes finales val/test del catálogo con versión, muestra y provenance", async () => {
    const evaluatedModel = {
      ...model11,
      evaluations: {
        val: { latest_attempt: attempt(41, "completed", "val"), latest_completed: completed(41, "val") },
        test: { latest_attempt: attempt(42, "completed", "test"), latest_completed: completed(42, "test") },
      },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], model11.id, [], { evaluation_catalogue_status: "available" });

    await show();

    const evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Validación (val)");
    expect(evaluations.textContent).toContain("Test (test)");
    expect(evaluations.textContent).toContain("Informe histórico completado #41");
    expect(evaluations.textContent).toContain("Informe histórico completado #42");
    expect(evaluations.textContent).toContain("Finalizado: 1 de febrero de 2025, 10:02 UTC");
    expect(evaluations.textContent).toContain("Evaluación finalizada: 1 de febrero de 2025, 10:02 UTC");
    expect(evaluations.textContent).toContain("Muestras: 4");
    expect(evaluations.textContent).toContain("Accuracy");
    expect(evaluations.textContent).toContain("Precision macro");
    expect(evaluations.textContent).toContain("Recall macro");
    expect(evaluations.textContent).toContain("F1 macro");
    expect(evaluations.textContent).toContain("F1 ponderado");
    expect(evaluations.textContent).toContain("Balanced accuracy");
    expect(evaluations.textContent).toContain("Cobertura completa");
    expect(evaluations.textContent).not.toContain("classification-report-v1");
    expect(evaluations.textContent).not.toContain("a".repeat(64));
    expect(evaluations.textContent).not.toContain("no acreditan qué parámetros están cargados actualmente en runtime");
    expect(evaluations.textContent).not.toContain("Rechazos:");
  });

  it("muestra solo el par admitido como aplicable y conserva los informes nuevos incompatibles como historia", async () => {
    const evaluatedModel = {
      ...model11,
      checkpoint_sha256: "a".repeat(64),
      evaluations: {
        val: {
          latest_attempt: attempt(142, "failed", "val", 2, 2),
          latest_completed: completed(141, "val", v2Report, 2, 2),
          admitted_completed: completed(131, "val", completeV1Report),
        },
        test: {
          latest_attempt: attempt(144, "completed", "test", 2, 2),
          latest_completed: completed(143, "test", v2Report, 2, 2),
          admitted_completed: completed(132, "test", completeV1Report),
        },
      },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], evaluatedModel.id, [], { evaluation_catalogue_status: "available" });

    await show();

    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    const validation = within(summary).getByRole("row", { name: /^Validación/ });
    expect(validation.textContent).toContain("100.00%");
    expect(validation.textContent).toContain("Par admitido");
    expect(validation.textContent).toBe("Validación100.00%100.00%Par admitido");
    const details = await openDetails();
    expect(details.textContent).toContain("Informe aplicable del par admitido #131");
    expect(details.textContent).toContain("Informe histórico completado #141");
    expect(details.textContent).toContain("Informe aplicable del par admitido #132");
    expect(details.textContent).toContain("Informe histórico completado #143");
    expect(details.textContent).not.toContain("no acredita los parámetros cargados actualmente en runtime");
  });

  it.each([
    ["pending", "Pendiente"],
    ["running", "En curso"],
    ["failed", "Fallido"],
  ] as const)("muestra el estado de último intento %s y conserva el informe previo si falló", async (status, label) => {
    const evaluatedModel = {
      ...model11,
      evaluations: {
        val: {
          latest_attempt: attempt(52, status, "val"),
          latest_completed: status === "failed" ? completed(51, "val") : null,
        },
      },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], model11.id, [], { evaluation_catalogue_status: "available" });

    await show();

    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    const summaryRow = within(summary).getByRole("row", { name: /^Validación/ });
    if (status === "failed") {
      expect(summaryRow.textContent).toContain("100.00%");
      expect(summaryRow.textContent).not.toContain("Fallido");
    } else {
      expect(summaryRow.textContent).toContain("No disponible");
    }
    const evaluations = await openDetails();
    expect(evaluations.textContent).toContain(`Último intento #52: ${label}`);
    if (status === "failed") {
      expect(evaluations.textContent).toContain("Informe histórico completado #51");
      expect(evaluations.textContent).toContain("Último intento #52: Fallido");
      expect(evaluations.textContent).toContain("Muestras: 4");
    } else {
      expect(evaluations.textContent).not.toContain("Informe histórico completado #51");
    }
  });

  it("distingue un estado de intento no reconocido de la ausencia de informes", async () => {
    const evaluatedModel = {
      ...model11,
      evaluations: {
        val: { latest_attempt: { id_evaluation: 95, status: "future_status", created_at: "2025-02-01T10:00:00Z" } },
        test: null,
      },
    } as unknown as RegisteredModel;
    catalogue = async () => response([evaluatedModel], model11.id, [], { evaluation_catalogue_status: "available" });
    await show();

    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(summary.textContent).not.toContain("Catálogo de evaluaciones disponible; no hay informes finales para este modelo.");
    expect(summary.textContent).toContain("Estado no reconocido");
    expect(summary.textContent).not.toContain("Sin métricas publicadas");
    const details = await openDetails();
    expect(details.textContent).toContain("Último intento #95: Estado no reconocido");
    expect(details.textContent).toContain("No hay un informe completado para este split.");
  });

  it("muestra cobertura incompleta y conserva el cero como 0%, sin convertir una métrica nula en cero", async () => {
    const zeroReport = {
      ...incompleteV1Report,
      sample_count: 4,
      metrics: { accuracy: 0, precision_macro: null, recall_macro: 0, f1_macro: 0, f1_weighted: 0, balanced_accuracy: 0 },
      per_class: [
        { label: "Chucao", precision: 0, recall: 0, f1: 0, support: 2, zero_denominator: { precision: false, recall: false, f1: false } },
        { label: "Rayadito", precision: 0, recall: 0, f1: 0, support: 2, zero_denominator: { precision: false, recall: false, f1: false } },
      ],
      support: [2, 2],
      confusion_matrix: [[0, 2], [2, 0]],
      coverage: { absent_classes: [], complete: true },
    };
    const evaluatedModel = {
      ...model11,
      evaluations: { val: { latest_attempt: attempt(61, "completed", "val"), latest_completed: completed(61, "val", zeroReport) } },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], model11.id, [], { evaluation_catalogue_status: "available" });

    await show();

    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    const summaryRow = within(summary).getByRole("row", { name: /^Validación 0\.00% 0\.00% No verificable/ });
    expect(summaryRow.textContent).toContain("Informe histórico; no es aplicable al checkpoint registrado.");
    const evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Muestras: 4");
    expect(evaluations.textContent).toContain("0.00%");
    expect(evaluations.textContent).toContain("Cobertura completa");
    expect(within(evaluations).getByRole("row", { name: "Precision macro No disponible" })).toBeDefined();
  });

  it("presenta schema v2 y sus rechazos sin exigirlos en informes v1", async () => {
    const evaluatedModel = {
      ...model11,
      evaluations: { val: { latest_attempt: attempt(62, "completed", "val", 2, 2), latest_completed: completed(62, "val", v2Report, 2, 2) } },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], model11.id, [], { evaluation_catalogue_status: "available" });

    await show();

    const evaluations = await openDetails();
    expect(evaluations.textContent).not.toContain("Schema del informe:");
    expect(evaluations.textContent).toContain("Rechazos: 1 (50.00%)");
    expect(evaluations.textContent).toContain("Cobertura incompleta · clases ausentes: Rayadito");
  });

  it("distingue catálogo unavailable, disponible vacío y legacy; borra informes obsoletos al recuperar", async () => {
    const withReport = (model: RegisteredModel, id: number) => ({
      ...model,
      evaluations: { val: { latest_attempt: attempt(id, "completed", "val"), latest_completed: completed(id, "val") } },
    }) as RegisteredModel;
    const first = withReport(model11, 71);
    const second = withReport(bird, 70);
    catalogue = async () => response([first, second], first.id, [], { evaluation_catalogue_status: "available" });

    await show();
    let summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    let evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Informe histórico completado #71");
    fireEvent.click(within(evaluations).getByRole("button", { name: "Cerrar detalle" }));
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/api/models"))).toHaveLength(1);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/evaluations"))).toBe(false);

    await chooseModel(bird.name);
    summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(summary.textContent).not.toContain("#71");
    evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Informe histórico completado #70");
    fireEvent.click(within(evaluations).getByRole("button", { name: "Cerrar detalle" }));

    await chooseModel(first.name);
    catalogue = async () => response([first, second], first.id, [], {
      evaluation_catalogue_status: "unavailable",
      evaluation_catalogue_error: "evaluation_records_invalid",
      error_reason: "/private/backend/path",
    });
    await focus();
    summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(summary.textContent).toContain("Catálogo de evaluaciones no disponible");
    expect(summary.textContent).toContain("registros que no se pueden mostrar");
    expect(summary.textContent).not.toContain("#71");
    expect(summary.textContent).not.toContain("/private/backend/path");
    evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Catálogo de evaluaciones no disponible");
    expect(evaluations.textContent).not.toContain("#71");
    expect(evaluations.textContent).not.toContain("/private/backend/path");
    fireEvent.click(within(evaluations).getByRole("button", { name: "Cerrar detalle" }));

    catalogue = async () => response([withReport(model11, 74), second], model11.id, [], { evaluation_catalogue_status: "available" });
    await focus();
    evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Informe histórico completado #74");
    expect(evaluations.textContent).not.toContain("#71");
  });

  it("distingue una respuesta legacy sin el estado del catálogo de evaluaciones vacío disponible", async () => {
    catalogue = async () => response([model11], model11.id, [], { evaluation_catalogue_status: "available" });
    await show();
    let evaluations = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(evaluations.textContent).toContain("Catálogo de evaluaciones disponible; no hay informes finales para este modelo.");

    catalogue = async () => response([model11], model11.id);
    await focus();
    evaluations = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(evaluations.textContent).toContain("respuesta antigua del catálogo");
    expect(evaluations.textContent).not.toContain("no hay informes finales para este modelo");
  });

  it("retira las métricas legacy y concentra el resumen final en la tarjeta del modelo seleccionado", async () => {
    const evaluatedModel = {
      ...model11,
      checkpoint_sha256: "a".repeat(64),
      metrics: { accuracy: 0.5, f1_macro: 0.4, precision_macro: 0.3 },
      evaluations: {
        val: { latest_attempt: attempt(81, "completed", "val"), latest_completed: completed(81, "val") },
        test: { latest_attempt: attempt(82, "completed", "test"), latest_completed: completed(82, "test") },
      },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], evaluatedModel.id, [], { evaluation_catalogue_status: "available" });

    await show();

    expect(screen.queryByText(/Accuracy histórica|F1 histórico|Precision histórica|Evaluación en test set|Rendimiento \/ Métrica/)).toBeNull();
    expect(screen.queryByText("Informes finales por split")).toBeNull();
    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(within(summary).getByRole("row", { name: "Validación 100.00% 100.00% Coincide" })).toBeDefined();
    expect(within(summary).getByRole("row", { name: "Test 100.00% 100.00% Coincide" })).toBeDefined();
    expect(summary.textContent).not.toContain("Solo histórico; coincidir en SHA-256");
    expect(summary.textContent).toContain("checkpoint registrado");
    expect(summary.textContent).not.toContain("50.00%");
    expect(screen.queryByRole("region", { name: "Evaluaciones finales" })).toBeNull();
  });

  it("abre un diálogo accesible con métricas completas, clases, matriz, rechazos sin identificadores internos", async () => {
    const evaluatedModel = {
      ...model11,
      checkpoint_sha256: "a".repeat(64),
      evaluations: {
        val: { latest_attempt: attempt(91, "completed", "val", 2, 2), latest_completed: completed(91, "val", v2Report, 2, 2) },
      },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], evaluatedModel.id, [], { evaluation_catalogue_status: "available" });
    await show();

    const trigger = screen.getByRole("button", { name: "Ver detalle de evaluación" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Detalle de evaluación final" });
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cerrar detalle" }));
    expect(dialog.textContent).toContain("Balanced accuracy");
    expect(dialog.textContent).toContain("Precision macro");
    expect(dialog.textContent).toContain("Recall macro");
    expect(dialog.textContent).toContain("F1 ponderado");
    expect(dialog.textContent).toContain("Chucao");
    expect(dialog.textContent).toContain("Rechazo");
    expect(dialog.textContent).not.toContain("__rejected__");
    expect(dialog.textContent).toContain("Rechazos: 1 (50.00%)");
    expect(dialog.textContent).not.toContain("a".repeat(64));
    expect(within(dialog).getByRole("table", { name: "Matriz de confusión Validación (val)" })).toBeDefined();

    const close = within(dialog).getByRole("button", { name: "Cerrar detalle" });
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it.each([
    ["SHA válido case-insensitive", "A".repeat(64), "a".repeat(64), "Coincide"],
    ["SHA válido distinto", "a".repeat(64), "b".repeat(64), "No coincide"],
    ["hash del informe malformado", "a".repeat(64), "not-a-sha256", "No verificable"],
    ["hash del informe ausente", "a".repeat(64), null, "No verificable"],
    ["hash del modelo ausente", null, "a".repeat(64), "No verificable"],
  ] as const)("clasifica la identidad de checkpoint: %s", async (_case, modelHash, reportHash, expected) => {
    const reportProvenance = provenance("val") as Record<string, unknown>;
    if (reportHash === null) delete reportProvenance.checkpoint_sha256;
    else reportProvenance.checkpoint_sha256 = reportHash;
    const evaluatedModel = {
      ...model11,
      ...(modelHash === null ? {} : { checkpoint_sha256: modelHash }),
      evaluations: {
        val: {
          latest_completed: {
            ...completed(101, "val"),
            provenance: reportProvenance,
          },
        },
      },
    } as RegisteredModel;
    catalogue = async () => response([evaluatedModel], model11.id, [], { evaluation_catalogue_status: "available" });
    await show();

    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    const validation = within(summary).getByRole("row", { name: /^Validación/ });
    expect(within(validation).getByText(expected)).toBeDefined();
    if (expected === "No coincide") {
      expect(validation.textContent).toContain("no es aplicable al checkpoint registrado");
      const details = await openDetails();
      expect(details.textContent).toContain("Informe histórico completado");
      expect(details.textContent).not.toContain("Informe aplicable del par admitido");
    }
  });

  it("cierra y reinicia el detalle al cambiar el modelo, atrapa foco y no consulta ni infiere", async () => {
    const first = { ...model11, evaluations: { val: { latest_attempt: attempt(111, "failed", "val") } } } as RegisteredModel;
    const second = { ...bird, evaluations: { test: { latest_attempt: attempt(112, "pending", "test") } } } as RegisteredModel;
    catalogue = async () => response([first, second], first.id, [], { evaluation_catalogue_status: "available" });
    await show();
    const trigger = screen.getByRole("button", { name: "Ver detalle de evaluación" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Detalle de evaluación final" });
    const close = within(dialog).getByRole("button", { name: "Cerrar detalle" });
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeDefined();
    await chooseModel(second.name);
    expect(screen.queryByRole("dialog")).toBeNull();
    await chooseModel(first.name);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/api/models"))).toHaveLength(1);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/evaluations") || String(url).includes("/api/predict"))).toBe(false);
  });

  it("muestra el historial persistido vacío, sin grabaciones demostrativas", async () => {
    const original = global.fetch;
    global.fetch = vi.fn(async (input, options) => String(input).includes('/api/inference/history')
      ? Response.json({ items: [], next_cursor: null }) : original(input, options));
    await show();
    expect(screen.queryByText("eugralla_paradoxa_mocha_03.wav")).toBeNull();
    expect(screen.getByText("Sin predicciones guardadas para este modelo.")).toBeDefined();
  });
  it("no selecciona un predeterminado sin pesos y lo muestra deshabilitado", async () => {
    const unavailable = { ...bird, id: "missing-bird", name: "Modelo sin pesos", has_weights: false };
    catalogue = async () => response([unavailable, model11, engine], unavailable.id);

    await show();

    expect(selection().value).toBe(model11.id);
    const option = within(modelOptions()).getByRole("option", { name: /Modelo sin pesos.*no disponible/i });
    expect(option.getAttribute("aria-disabled") === "true").toBe(true);
  });

  it.each([false, undefined])("bloquea inferencia cuando ningún modelo confirma pesos (%s)", async hasWeights => {
    catalogue = async () => response([
      { ...bird, has_weights: hasWeights }, { ...engine, has_weights: hasWeights },
    ], bird.id);
    const view = await show();

    expect(selection().value).toBe("");
    expect(selection().textContent).toBe("Sin modelos con pesos disponibles");
    expect(screen.getByRole("status", { name: "Disponibilidad de modelos" }).textContent).toContain("pesos");
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    await act(async () => {
      fireEvent.change(view.container.querySelector('input[type="file"]')!, {
        target: { files: [new File(["audio"], "audio.wav")] },
      });
    });
    // Clicking an unavailable option cannot enable inference.
    await chooseModel(bird.name);
    expect((screen.getByRole("button", { name: /Ejecutar inferencia/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/predict"))).toBe(false);
  });

  it("reemplaza un modelo que pierde pesos por otro disponible del mismo dominio y permite recuperación", async () => {
    await show();
    await chooseModel(engine.name);
    const nextEngine = { ...engine, id: "engine-v3", name: "Motor v3" };
    catalogue = async () => response([bird, { ...engine, has_weights: false }, nextEngine], bird.id);

    await focus();

    expect(selection().value).toBe(nextEngine.id);
    const unavailable = within(modelOptions()).getByRole("option", { name: /Motor v2.*no disponible/i });
    expect(unavailable.getAttribute("aria-disabled") === "true").toBe(true);
    catalogue = async () => response([bird, engine, nextEngine], engine.id);
    await focus();
    expect(selection().value).toBe(nextEngine.id);
    expect(within(modelOptions()).getByRole("option", { name: "Motor v2" }).getAttribute("aria-disabled")).toBe("false");
    await chooseModel(engine.name);
    expect(selection().value).toBe(engine.id);
  });

  it("un catálogo sin pesos recupera una selección solo cuando aparecen pesos confirmados", async () => {
    catalogue = async () => response([{ ...bird, has_weights: false }], bird.id);
    await show();
    expect(selection().value).toBe("");

    catalogue = async () => response([bird, model11], model11.id);
    await focus();

    expect(selection().value).toBe(model11.id);
    expect(screen.queryByRole("status", { name: "Disponibilidad de modelos" })).toBeNull();
  });

  it("muestra publicación parcial sin descartar modelos sanos y limpia el aviso al reintentar", async () => {
    catalogue = async () => response([bird], bird.id, [
      { model_id: model11.id, code: "checkpoint_missing" },
      { code: "checkpoint_invalid" },
      { model_id: "engine-v3", code: "future_code" },
    ]);
    await show();
    expect(selection().value).toBe(bird.id);
    expect(screen.getByRole("status", { name: "Publicación de modelos" }).textContent).toContain("fama_trained_model_11: archivo de pesos ausente");
    expect(screen.getByRole("status", { name: "Publicación de modelos" }).textContent).toContain("Modelo sin identificador: archivo de pesos inválido");
    expect(screen.getByRole("status", { name: "Publicación de modelos" }).textContent).toContain("engine-v3: error de publicación");
    catalogue = async () => response([bird], bird.id, [
      { model_id: "fama_triad_1", code: "triad_component_blocked" },
      { model_id: "fama_triad_2", code: "triad_invalid" },
    ]);
    await focus();
    const triads = screen.getByRole("status", { name: "Publicación de modelos" }).textContent;
    expect(triads).toContain("fama_triad_1: uno de los tres modelos de la tríada no está disponible o no pasó su evaluación");
    expect(triads).toContain("fama_triad_2: los modelos de la tríada no son compatibles entre sí (dataset o clases distintos)");
    catalogue = async () => response([bird, model11]);
    await focus();
    expect(screen.queryByRole("status", { name: "Publicación de modelos" })).toBeNull();
    expect(within(modelOptions()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
  });

  it("conserva el catálogo y la selección frente a HTTP 503 o red caída y permite recuperación", async () => {
    await show();
    await chooseModel(engine.name);
    catalogue = async () => new Response(JSON.stringify({ detail: { errors: [{ code: "database_unavailable" }] } }), { status: 503 });
    await focus();
    expect(screen.getByRole("alert").textContent).toContain("No se pudo actualizar el catálogo de modelos (HTTP 503)");
    expect(selection().value).toBe(engine.id);
    expect(within(modelOptions()).getByRole("option", { name: "Aves CNN" })).toBeDefined();
    catalogue = async () => { throw new Error("/private/backend/path"); };
    await focus();
    expect(screen.getByRole("alert").textContent).not.toContain("/private");
    expect(selection().value).toBe(engine.id);
    catalogue = async () => response([bird, engine, model11]);
    await focus();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(selection().value).toBe(engine.id);
  });

  it("distingue catálogo vacío, errores de publicación y base de datos no disponible", async () => {
    catalogue = async () => response([], "", [{
      model_id: model11.id,
      code: "standard_evaluation_invalid",
      reason: "runtime_configuration_incompatible",
    }]);
    await show();

    const publication = screen.getByRole("status", { name: "Publicación de modelos" });
    expect(publication.textContent).toContain("No hay modelos publicados disponibles");
    expect(publication.textContent).not.toContain("siguen siendo seleccionables");
    expect(publication.textContent).toContain("runtime del predictor incompatible con los informes");

    catalogue = async () => response([], "");
    await focus();
    const empty = screen.getByRole("status", { name: "Disponibilidad de modelos" });
    expect(empty.textContent).toContain("La consulta fue correcta, pero no hay modelos publicados");

    catalogue = async () => new Response(JSON.stringify({ detail: { errors: [{ code: "database_unavailable" }] } }), { status: 503 });
    await focus();
    expect(screen.getByRole("alert").textContent).toContain("la base de datos no está disponible");
    expect(screen.queryByRole("status", { name: "Disponibilidad de modelos" })).toBeNull();
  });

  it("no inventa modelos ni permite ejecutar tras un error inicial o catálogo vacío", async () => {
    catalogue = async () => new Response(null, { status: 503 });
    const view = await show();
    expect(selection().value).toBe("");
    expect(selection().textContent).toBe("Sin modelos disponibles");
    expect(screen.getByRole("alert")).toBeDefined();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(["audio"], "audio.wav")] } }); });
    expect((screen.getByRole("button", { name: /Ejecutar inferencia/ }) as HTMLButtonElement).disabled).toBe(true);
    catalogue = async () => response([], "missing");
    await focus();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(selection().value).toBe("");
    expect((screen.getByRole("button", { name: /Ejecutar inferencia/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("reemplaza una selección retirada dentro del mismo dominio antes de cambiar a aves", async () => {
    await show();
    await chooseModel(engine.name);
    const nextEngine = { ...engine, id: "engine-v3", name: "Motor v3" };
    catalogue = async () => response([bird, nextEngine], bird.id);
    await focus();
    expect(selection().value).toBe(nextEngine.id);
    expect(screen.getByText("Grupo seleccionado: Diagnóstico Acústico de Motores")).toBeDefined();
    catalogue = async () => response([model11], "removed-default");
    await focus();
    expect(selection().value).toBe(model11.id);
    expect(screen.getByText("Grupo seleccionado: Bioacústica de Aves Chilenas")).toBeDefined();
  });

  it.each([engine.id, "not-in-catalogue", ""])("elige solo un predeterminado publicado (%s) al entrar", async defaultId => {
    const ensemble = { ...bird, id: "chilean-birds-ensemble", name: "Ensamble" };
    catalogue = async () => response([bird, ensemble, engine], defaultId);
    await show();
    expect(selection().value).toBe(defaultId === engine.id ? engine.id : bird.id);
  });

  it("conserva una elección hecha mientras el refresco está pendiente", async () => {
    await show();
    const pending = deferred();
    catalogue = () => pending.promise;
    await focus();
    await chooseModel(engine.name);
    await act(async () => { pending.resolve(response([bird, engine, model11], model11.id)); });
    expect(selection().value).toBe(engine.id);
    expect(within(modelOptions()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
  });

  it.each(["success", "failure"])("ignora una respuesta antigua (%s) tras un catálogo nuevo y otra elección", async outcome => {
    await show();
    const old = deferred();
    catalogue = () => old.promise;
    await focus();
    catalogue = async () => response([bird, engine, model11]);
    await focus();
    await chooseModel(model11.name);
    await act(async () => {
      if (outcome === "success") old.resolve(response([bird], bird.id, [{ code: "checkpoint_invalid" }]));
      else old.reject(new Error("HTTP 503"));
    });
    expect(selection().value).toBe(model11.id);
    expect(screen.getByRole("option", { name: "Chincol" })).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status", { name: "Publicación de modelos" })).toBeNull();
  });

  it("refresca al volver visible, pero no al ocultarse, y consulta de nuevo al montar", async () => {
    const view = await show();
    catalogue = async () => response([bird, engine, model11]);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(within(modelOptions()).queryByRole("option", { name: "Modelo 11" })).toBeNull();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(within(modelOptions()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
    view.unmount();
    catalogue = async () => response([model11], model11.id);
    await show();
    expect(selection().value).toBe(model11.id);
    expect(within(modelOptions()).queryByRole("option", { name: "Aves CNN" })).toBeNull();
  });

  it("aborta solicitudes y retira listeners sin errores tardíos después del desmontaje", async () => {
    const pending = deferred();
    catalogue = () => pending.promise;
    const warn = vi.spyOn(console, "warn");
    const view = await show();
    // El conteo HTTP y la señal solo protegen la política acotada de limpieza.
    const requests = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/api/models"));
    const initial = requests().length;
    const signal = requests()[0][1]?.signal;
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await focus();
    await act(async () => { fireEvent(document, new Event("visibilitychange")); pending.reject(new Error("HTTP 503")); });
    expect(requests()).toHaveLength(initial);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it("mantiene el modelo ejecutado y las clases de feedback cuando desaparece durante inferencia", async () => {
    const view = await show();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(["audio"], "audio.wav")] } }); });
    const pending = deferred();
    predict = () => pending.promise;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Ejecutar inferencia/ })); });
    catalogue = async () => response([model11], model11.id);
    await focus();
    expect(selection().value).toBe(model11.id);
    await act(async () => { pending.resolve(new Response(JSON.stringify({ filename: "audio.wav", db_id: 201, modelo: "Aves CNN", clase: "Chucao", confianza: 0.9, gcp_upload: true, detalles: { dataset_name: "AvesChilenas" } }))); });
    expect(screen.getByText("Modelo ejecutado:").parentElement?.textContent).toContain("Aves CNN");
    const feedback = within(screen.getByRole("region", { name: "Validar resultado" }));
    fireEvent.click(feedback.getByRole("button", { name: "Incorrecta" }));
    fireEvent.change(feedback.getByLabelText("Clase correcta"), { target: { value: "Rayadito" } });
    expect(feedback.queryByRole("option", { name: "Chincol" })).toBeNull();
    await focus();
    expect((feedback.getByLabelText("Clase correcta") as HTMLSelectElement).value).toBe("Rayadito");
    expect(screen.getByText("Modelo ejecutado:").parentElement?.textContent).toContain("Aves CNN");
    expect(screen.getByText(/Dataset de inferencia/).parentElement?.textContent).toContain("AvesChilenas");
  });

  it("publica nuevas opciones al recuperar foco sin reemplazar la elección del usuario", async () => {
    await show();
    await chooseModel(engine.name);
    catalogue = async () => response([bird, engine, model11], model11.id);
    await focus();
    expect(within(modelOptions()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
    expect(selection().value).toBe(engine.id);
    await chooseModel(model11.name);
    expect(screen.getByRole("option", { name: "Chincol" })).toBeDefined();
  });
});

// Independent U7 / S4 public UI and simulated HTTP regressions.
describe("U7Independent", () => {
  const calls = (path: string) => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes(path));
  const upload = async (view: ReturnType<typeof render>) => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    await act(async () => { fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [new File(["synthetic"], "synthetic.wav")] },
    }); });
  };

  it.each([false, null, undefined, "true", 1, 0])("requires literal true, rejects %s without HTTP, then recovers", async value => {
    catalogue = async () => response([{ ...bird, has_weights: value } as RegisteredModel], bird.id);
    const view = await show();
    await upload(view);
    const option = within(modelOptions()).getByRole("option", { name: /Aves CNN/ });
    expect(option.getAttribute("aria-disabled")).toBe("true");
    expect(selection().value).toBe("");
    const before = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /Ejecutar inferencia/ }));
    expect(vi.mocked(fetch).mock.calls).toHaveLength(before);
    expect(calls("/api/predict")).toHaveLength(0);
    catalogue = async () => response([bird], bird.id);
    await focus();
    expect(selection().value).toBe(bird.id);
    expect(within(modelOptions()).getByRole("option", { name: "Aves CNN" }).getAttribute("aria-disabled")).toBe("false");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Ejecutar inferencia/ })); });
    expect(calls("/api/predict")).toHaveLength(1);
    expect(String(calls("/api/predict")[0][0])).toContain("model_id=bird-cnn");
    expect((calls("/api/predict")[0][1]?.body as FormData).get("dataset_name")).toBe("AvesChilenas");
  });

  it.each([bird, engine])("replaces $id within its domain despite an opposite-domain default", async original => {
    const opposite = original.id === bird.id ? engine : bird;
    const successor = { ...original, id: "opaque-successor", name: "Successor" };
    catalogue = async () => response([original, opposite], original.id);
    await show();
    catalogue = async () => response([opposite, { ...original, has_weights: false }, successor], opposite.id);
    await focus();
    expect(selection().value).toBe(successor.id);
    catalogue = async () => response([opposite, original, successor], original.id);
    await focus();
    expect(selection().value).toBe(successor.id);
    expect(calls("/api/predict")).toHaveLength(0);
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
  });

  it.each([false, true])("preserves pending result, checkpoint and feedback after catalogue failure=%s", async failed => {
    const requested = { ...bird, id: "bird-ensemble", checkpoint_sha256: "a".repeat(64) };
    catalogue = async () => response([requested, engine], requested.id);
    const pending = deferred();
    predict = () => pending.promise;
    const originalFetch = fetch;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) =>
      String(input).endsWith("/api/feedback")
        ? Response.json({ id_retroalimentacion: 71, id_prediccion: 901, fue_correcta: false, procesado: false })
        : originalFetch(input, options)));
    const view = await show();
    await upload(view);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Ejecutar inferencia/ })); });
    expect(String(calls("/api/predict")[0][0])).toContain("model_id=bird-ensemble");
    expect((calls("/api/predict")[0][1]?.body as FormData).get("dataset_name")).toBe("AvesChilenas");
    await chooseModel(engine.name);
    catalogue = failed ? async () => new Response(null, { status: 503 })
      : async () => response([{ ...engine, checkpoint_sha256: "c".repeat(64) }], engine.id);
    await focus();
    await act(async () => { pending.resolve(Response.json({ filename: "synthetic.wav", db_id: 901,
      modelo_id: requested.id, modelo: "Executed snapshot", clase: "Chucao", confianza: 0, gcp_upload: false,
      modelos_activos: ["Result participant 17%"], modelos_ejecutados: ["Executed predictor"],
      detalles: { dataset_name: "AvesChilenas", loaded_checkpoint_sha256: "b".repeat(64), device: "cpu" } })); });
    const checkpoint = screen.getByRole("region", { name: "Identidad del checkpoint del resultado" });
    expect(checkpoint.textContent).toContain("a".repeat(64));
    expect(checkpoint.textContent).toContain("b".repeat(64));
    expect(checkpoint.textContent).not.toContain("c".repeat(64));
    expect(screen.getByText("Modelo ejecutado:").parentElement?.textContent).toContain("Executed snapshot");
    expect(screen.getByText("✓ Result participant 17%")).toBeDefined();
    expect(screen.getByText("✓ Executed predictor")).toBeDefined();
    const feedback = within(screen.getByRole("region", { name: "Validar resultado" }));
    fireEvent.click(feedback.getByRole("button", { name: "Incorrecta" }));
    expect(feedback.queryByRole("option", { name: "low_oil" })).toBeNull();
    fireEvent.change(feedback.getByLabelText("Clase correcta"), { target: { value: "Rayadito" } });
    await focus();
    await act(async () => { fireEvent.click(feedback.getByRole("button", { name: "Guardar corrección" })); });
    expect(calls("/api/predict")).toHaveLength(1);
    expect(calls("/api/feedback")).toHaveLength(1);
    expect(JSON.parse(String(calls("/api/feedback")[0][1]?.body))).toEqual({
      id_prediccion: 901, fue_correcta: false, etiqueta_corregida: "Rayadito",
    });
  });

  it.each([
    ["legacy_bioacoustic_service", true, "AvesChilenas", true],
    ["other_service", true, "AvesChilenas", false],
    ["legacy_bioacoustic_service", false, "AvesChilenas", false],
    ["legacy_bioacoustic_service", true, "engine_diagnostics", false],
  ])("isolates legacy scope=%s supported=%s domain=%s", async (scope, supported, domain, visible) => {
    const ensemble = { ...bird, id: "bird-ensemble" };
    catalogue = async () => response([ensemble, { ...engine, id: "engine-ensemble" }], ensemble.id);
    const originalFetch = fetch;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) =>
      String(input).includes("/api/model-info") ? Response.json({ state_scope: scope, domain_supported: supported,
        selected_domain: domain, device: "legacy-device", triad_status: [{ name: "Legacy component",
          is_ready: true, is_loaded: false, is_registered: true, weights_available: false, weight: 0.7,
          accuracy: 0, metrics_source: "database_record", recorded_checkpoint: "registered.pt", loaded_checkpoint: null }],
      }) : originalFetch(input, options)));
    await show();
    expect(Boolean(screen.queryByRole("article", { name: "Legacy component" }))).toBe(visible);
    if (visible) {
      const card = within(screen.getByRole("article", { name: "Legacy component" }));
      for (const text of ["Registro BD: Registrado", "Archivo local: Ausente", "No cargado", "Peso cargado: No disponible", "0.0%", "registered.pt"]) {
        expect(card.getByText(text)).toBeDefined();
      }
    }
    await chooseModel(engine.name);
    if (domain !== "engine_diagnostics") expect(screen.queryByRole("article", { name: "Legacy component" })).toBeNull();
    expect(calls("/api/predict")).toHaveLength(0);
    expect(calls("/api/model-info").some(([url]) => String(url).includes("dataset_name=engine_diagnostics"))).toBe(true);
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
  });
});

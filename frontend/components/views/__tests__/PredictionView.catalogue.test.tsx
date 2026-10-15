import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionView, { type RegisteredModel } from "../PredictionView";

const bird: RegisteredModel = { id: "bird-cnn", name: "Aves CNN", description: "Aves", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito"], is_default: true, has_weights: true };
const engine: RegisteredModel = { id: "engine-v2", name: "Motor v2", description: "Motor", target_sr: 32000, duration_seconds: 2, classes: ["bad_ignition", "low_oil"], is_default: false, has_weights: true };
const model11: RegisteredModel = { id: "fama_trained_model_11", name: "Modelo 11", description: "Aves nuevas", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito", "Chincol"], is_default: false, has_weights: true };
const response = (models: RegisteredModel[], defaultId = bird.id, publication_errors: { model_id?: string; code: string; reason?: string }[] = [], catalogueFields: Record<string, unknown> = {}) => new Response(JSON.stringify({ models, total: models.length, default_model_id: defaultId, publication_errors, ...catalogueFields }), { status: 200 });
function deferred() {
  let resolve!: (response: Response) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let catalogue: () => Promise<Response>;
let predict: () => Promise<Response>;
const selection = () => screen.getByRole("combobox", { name: "Modelo:" }) as HTMLSelectElement;
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
    expect(evaluations.textContent).toContain("Inicio: 2025-02-01T10:01:00Z");
    expect(evaluations.textContent).toContain("Informe creado: 2025-02-01T10:00:00Z");
    expect(evaluations.textContent).toContain("Muestras: 4");
    expect(evaluations.textContent).toContain("Accuracy");
    expect(evaluations.textContent).toContain("Precision macro");
    expect(evaluations.textContent).toContain("Recall macro");
    expect(evaluations.textContent).toContain("F1 macro");
    expect(evaluations.textContent).toContain("F1 ponderado");
    expect(evaluations.textContent).toContain("Balanced accuracy");
    expect(evaluations.textContent).toContain("Cobertura completa");
    expect(evaluations.textContent).toContain("classification-report-v1");
    expect(evaluations.textContent).toContain("a".repeat(64));
    expect(evaluations.textContent).toContain("no acreditan qué parámetros están cargados actualmente en runtime");
    expect(evaluations.textContent).not.toContain("Rechazos:");
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
    expect(evaluations.textContent).toContain("Schema del informe: 2");
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

    fireEvent.change(selection(), { target: { value: bird.id } });
    summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(summary.textContent).not.toContain("#71");
    evaluations = await openDetails();
    expect(evaluations.textContent).toContain("Informe histórico completado #70");
    fireEvent.click(within(evaluations).getByRole("button", { name: "Cerrar detalle" }));

    fireEvent.change(selection(), { target: { value: first.id } });
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
    expect(summary.textContent).toContain("checkpoint registrado");
    expect(summary.textContent).not.toContain("50.00%");
    expect(screen.queryByRole("region", { name: "Evaluaciones finales" })).toBeNull();
  });

  it("abre un diálogo accesible con métricas completas, clases, matriz, rechazos y hash legible", async () => {
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
    expect(dialog.textContent).toContain("__rejected__");
    expect(dialog.textContent).toContain("Rechazos: 1 (50.00%)");
    expect(dialog.textContent).toContain("a".repeat(64));
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
      expect(details.textContent).toContain("NO es aplicable al checkpoint registrado");
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
    fireEvent.change(selection(), { target: { value: second.id } });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.change(selection(), { target: { value: first.id } });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/api/models"))).toHaveLength(1);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/evaluations") || String(url).includes("/api/predict"))).toBe(false);
  });

  it("inicia el historial de sesión vacío, sin grabaciones demostrativas", async () => {
    await show();
    expect(screen.queryByText("eugralla_paradoxa_mocha_03.wav")).toBeNull();
    expect(screen.getByText("Sin predicciones en esta sesión.")).toBeDefined();
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
    catalogue = async () => response([bird, model11]);
    await focus();
    expect(screen.queryByRole("status", { name: "Publicación de modelos" })).toBeNull();
    expect(within(selection()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
  });

  it("conserva el catálogo y la selección frente a HTTP 503 o red caída y permite recuperación", async () => {
    await show();
    fireEvent.change(selection(), { target: { value: engine.id } });
    catalogue = async () => new Response(JSON.stringify({ detail: { errors: [{ code: "database_unavailable" }] } }), { status: 503 });
    await focus();
    expect(screen.getByRole("alert").textContent).toContain("No se pudo actualizar el catálogo de modelos (HTTP 503)");
    expect(selection().value).toBe(engine.id);
    expect(within(selection()).getByRole("option", { name: "Aves CNN" })).toBeDefined();
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
    expect(within(selection()).getAllByRole("option").map(o => o.textContent)).toEqual(["Sin modelos disponibles"]);
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
    fireEvent.change(selection(), { target: { value: engine.id } });
    const nextEngine = { ...engine, id: "engine-v3", name: "Motor v3" };
    catalogue = async () => response([bird, nextEngine], bird.id);
    await focus();
    expect(selection().value).toBe(nextEngine.id);
    expect(screen.getByText("Dominio Activo: Diagnóstico Acústico de Motores")).toBeDefined();
    catalogue = async () => response([model11], "removed-default");
    await focus();
    expect(selection().value).toBe(model11.id);
    expect(screen.getByText("Dominio Activo: Bioacústica de Aves Chilenas")).toBeDefined();
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
    fireEvent.change(selection(), { target: { value: engine.id } });
    await act(async () => { pending.resolve(response([bird, engine, model11], model11.id)); });
    expect(selection().value).toBe(engine.id);
    expect(within(selection()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
  });

  it.each(["success", "failure"])("ignora una respuesta antigua (%s) tras un catálogo nuevo y otra elección", async outcome => {
    await show();
    const old = deferred();
    catalogue = () => old.promise;
    await focus();
    catalogue = async () => response([bird, engine, model11]);
    await focus();
    fireEvent.change(selection(), { target: { value: model11.id } });
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
    expect(within(selection()).queryByRole("option", { name: "Modelo 11" })).toBeNull();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(within(selection()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
    view.unmount();
    catalogue = async () => response([model11], model11.id);
    await show();
    expect(selection().value).toBe(model11.id);
    expect(within(selection()).queryByRole("option", { name: "Aves CNN" })).toBeNull();
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
    fireEvent.change(selection(), { target: { value: engine.id } });
    catalogue = async () => response([bird, engine, model11], model11.id);
    await focus();
    expect(within(selection()).getByRole("option", { name: "Modelo 11" })).toBeDefined();
    expect(selection().value).toBe(engine.id);
    fireEvent.change(selection(), { target: { value: model11.id } });
    expect(screen.getByRole("option", { name: "Chincol" })).toBeDefined();
  });
});

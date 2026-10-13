import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionView, { type RegisteredModel } from "../PredictionView";

const registeredA = "a".repeat(64);
const loadedB = "b".repeat(64);
const reportC = "c".repeat(64);
const loadedD = "d".repeat(64);
const registeredE = "e".repeat(64);
const loadedF = "f".repeat(64);
const registeredG = "1".repeat(64);
const loadedH = "2".repeat(64);

const modelA: RegisteredModel = {
  id: "model-a",
  name: "Modelo A",
  description: "Aves",
  target_sr: 22050,
  duration_seconds: 5,
  classes: ["Chucao"],
  is_default: true,
  has_weights: true,
  checkpoint_sha256: registeredA,
  loaded_checkpoint_sha256: loadedB,
  evaluations: {
    val: {
      latest_completed: {
        id_evaluation: 41,
        provenance: { checkpoint_sha256: reportC, split: "val" },
        report: { schema_version: 1, sample_count: 1, metrics: { accuracy: 1 } },
      },
    },
  },
};
const modelB: RegisteredModel = {
  ...modelA,
  id: "model-b",
  name: "Modelo B",
  is_default: false,
  checkpoint_sha256: registeredE,
  loaded_checkpoint_sha256: loadedF,
  evaluations: null,
};
const catalogueResponse = (models: RegisteredModel[]) => Response.json({
  models,
  default_model_id: models[0]?.id,
  evaluation_catalogue_status: "available",
});
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
};

let models: RegisteredModel[];
let predict: () => Promise<Response>;
const selection = () => screen.getByRole("combobox", { name: "Modelo:" }) as HTMLSelectElement;
const catalogueIdentity = () => screen.getByRole("region", { name: "Identidad de checkpoints del modelo seleccionado" });
const resultIdentity = () => screen.getByRole("region", { name: "Identidad del checkpoint del resultado" });
const show = async () => {
  let view!: ReturnType<typeof render>;
  await act(async () => { view = render(<PredictionView />); });
  return view;
};
const startInference = async (view: ReturnType<typeof render>) => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  await act(async () => {
    fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [new File(["audio"], "audio.wav")] },
    });
  });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Ejecutar inferencia/ })); });
};

beforeEach(() => {
  models = [modelA, modelB];
  predict = async () => Response.json({
    filename: "audio.wav",
    db_id: 201,
    clase: "Chucao",
    confianza: 0.9,
    gcp_upload: true,
    detalles: { dataset_name: "AvesChilenas", loaded_checkpoint_sha256: loadedD },
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/models")) return catalogueResponse(models);
    if (url.includes("/api/model-info")) return new Response(null, { status: 503 });
    if (url.includes("/api/predict")) return predict();
    throw new Error(`HTTP no previsto: ${url}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Identidad del checkpoint en Predicción", () => {
  it("distingue checkpoint registrado, instancia cargada e informe de evaluación", async () => {
    await show();

    const current = catalogueIdentity();
    expect(current.textContent).toContain(registeredA);
    expect(current.textContent).toContain(loadedB);
    expect(current.textContent).toContain("No coincide");
    expect(current.textContent).toContain("no acredita continuamente los parámetros en memoria");

    const summary = screen.getByRole("region", { name: "Evaluaciones finales del modelo seleccionado" });
    expect(within(summary).getByRole("row", { name: /^Validación/ }).textContent).toContain("No coincide");
    fireEvent.click(screen.getByRole("button", { name: "Ver detalle de evaluación" }));
    const report = await screen.findByRole("dialog", { name: "Detalle de evaluación final" });
    expect(report.textContent).toContain(reportC);
    expect(report.textContent).toContain("NO es aplicable al checkpoint registrado");
  });

  it("mantiene la identidad cargada en la respuesta original al cambiar modelo y refrescar catálogo", async () => {
    const view = await show();
    const pending = deferred<Response>();
    predict = () => pending.promise;
    await startInference(view);

    fireEvent.change(selection(), { target: { value: modelB.id } });
    const updatedB = { ...modelB, checkpoint_sha256: registeredG, loaded_checkpoint_sha256: loadedH };
    models = [modelA, updatedB];
    await act(async () => {
      pending.resolve(Response.json({
        filename: "audio.wav",
        db_id: 202,
        clase: "Chucao",
        confianza: 0.9,
        gcp_upload: true,
        detalles: { dataset_name: "AvesChilenas", loaded_checkpoint_sha256: loadedD },
      }));
    });
    await act(async () => { fireEvent(window, new Event("focus")); });

    const result = resultIdentity();
    expect(result.textContent).toContain(loadedD);
    expect(result.textContent).toContain(registeredA);
    expect(result.textContent).toContain("No coincide");
    expect(result.textContent).not.toContain(loadedF);
    const current = catalogueIdentity();
    expect(current.textContent).toContain(registeredG);
    expect(current.textContent).toContain(loadedH);
    expect(within(result).queryByText(registeredG)).toBeNull();
  });

  it("identifica una coincidencia válida entre registro e instancia cargada", async () => {
    models = [{ ...modelA, loaded_checkpoint_sha256: registeredA }];
    predict = async () => Response.json({
      filename: "matching.wav",
      db_id: 204,
      clase: "Chucao",
      confianza: 0.9,
      gcp_upload: false,
      detalles: { dataset_name: "AvesChilenas", loaded_checkpoint_sha256: registeredA },
    });
    const view = await show();

    expect(catalogueIdentity().textContent).toContain("Coincide");
    await startInference(view);
    const result = await screen.findByRole("region", { name: "Identidad del checkpoint del resultado" });
    expect(result.textContent).toContain("Coincide");
  });

  it.each([
    ["ausente", undefined],
    ["nulo", null],
    ["malformado", "not-a-sha256"],
  ] as const)("no atribuye identidad ni coincidencia cuando el hash opcional está %s", async (_case, invalidHash) => {
    const modelWithoutIdentity = { ...modelA } as RegisteredModel;
    if (invalidHash === undefined) delete modelWithoutIdentity.loaded_checkpoint_sha256;
    else modelWithoutIdentity.loaded_checkpoint_sha256 = invalidHash;
    models = [modelWithoutIdentity];
    predict = async () => Response.json({
      filename: "legacy.wav",
      db_id: 203,
      clase: "Chucao",
      confianza: 0.8,
      gcp_upload: false,
      ...(invalidHash === undefined
        ? {}
        : { detalles: { dataset_name: "AvesChilenas", loaded_checkpoint_sha256: invalidHash } }),
    });
    const view = await show();
    await startInference(view);
    await screen.findByRole("region", { name: "Identidad del checkpoint del resultado" });

    expect(catalogueIdentity().textContent).toContain("No disponible");
    expect(catalogueIdentity().textContent).toContain("No verificable");
    expect(resultIdentity().textContent).toContain("No disponible");
    expect(resultIdentity().textContent).toContain("No verificable");
    expect(resultIdentity().textContent).not.toContain("Coincide");
  });
});

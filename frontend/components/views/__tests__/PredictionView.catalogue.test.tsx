import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionView, { type RegisteredModel } from "../PredictionView";

const bird: RegisteredModel = { id: "bird-cnn", name: "Aves CNN", description: "Aves", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito"], is_default: true, has_weights: true };
const engine: RegisteredModel = { id: "engine-v2", name: "Motor v2", description: "Motor", target_sr: 32000, duration_seconds: 2, classes: ["bad_ignition", "low_oil"], is_default: false, has_weights: true };
const model11: RegisteredModel = { id: "fama_trained_model_11", name: "Modelo 11", description: "Aves nuevas", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito", "Chincol"], is_default: false, has_weights: true };
const response = (models: RegisteredModel[], defaultId = bird.id, publication_errors: { model_id?: string; code: string }[] = []) => new Response(JSON.stringify({ models, total: models.length, default_model_id: defaultId, publication_errors }), { status: 200 });
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
    await act(async () => { pending.resolve(new Response(JSON.stringify({ filename: "audio.wav", db_id: 201, clase: "Chucao", confianza: 0.9, gcp_upload: true, detalles: { dataset_name: "AvesChilenas" } }))); });
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

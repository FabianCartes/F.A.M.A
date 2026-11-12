import { chooseModel } from "../../prediction/__tests__/selectorActions";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionView, { type RegisteredModel } from "../PredictionView";

vi.mock('@/components/auth/SessionBoundary', () => ({ useOptionalWebSession: () => ({ id: 1 }) }));

const bird: RegisteredModel = { dataset_name: 'AvesChilenas', id: "bird-cnn", name: "Aves CNN", description: "Aves", target_sr: 22050, duration_seconds: 5, classes: ["Chucao", "Rayadito"], is_default: true, has_weights: true };
const triad = (id: number, version: number): RegisteredModel => ({
  dataset_name: 'AvesChilenas', id: `fama_triad_${id}`, name: `Tríada ${id}`, description: "Tres componentes", target_sr: 22050,
  duration_seconds: 5, classes: ["Chucao", "Rayadito"], is_default: false, has_weights: true, version,
});
const composition = (id: number, version: number, weights: number[], latest = true) => ({
  id, model_id: `fama_triad_${id}`, dataset_id: 3, partition_version: "p1", job_id: "job-1", version,
  previous_id: version > 1 ? id - 1 : null, latest, active: false,
  components: [11, 12, 13].map((m, i) => ({ id_modelo: m, catalogue_id: `fama_trained_model_${m}`, weight: weights[i] })),
  author_id: 1, created_at: "2026-11-11T10:00:00Z",
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const catalogueOf = (models: RegisteredModel[]) => json({ models, total: models.length, default_model_id: "bird-cnn", publication_errors: [] });

let models: RegisteredModel[];
let transport: ReturnType<typeof vi.fn>;
const calls = () => transport.mock.calls.map(([url, init]) => ({ url: String(url), init: init as RequestInit | undefined }));
const show = async () => { await act(async () => { render(<PredictionView />); }); };

beforeEach(() => {
  models = [bird, triad(7, 1)];
  transport = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/models")) return catalogueOf(models);
    if (url.includes("/api/model-info")) return new Response(null, { status: 503 });
    if (url.endsWith("/api/triad-compositions/7")) return json(composition(7, 1, [0.5, 0.3, 0.2]));
    if (url.endsWith("/api/triad-compositions/8")) return json(composition(8, 2, [0.6, 0.3, 0.1]));
    if (url.includes("/api/inference/history")) return json({ items: [], next_cursor: null });
    throw new Error(`HTTP no previsto: ${url}`);
  });
  vi.stubGlobal("fetch", transport);
});
afterEach(() => {
  expect(calls().some(c => c.url.includes("private_only"))).toBe(false);
  cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();
});

describe("Tríada estándar en Predicción", () => {
  it("muestra la composición como un solo modelo con sus tres pesos fijos de entrenamiento", async () => {
    await show();
    await chooseModel("Tríada 7");
    const panel = await screen.findByRole("region", { name: "Composición de la tríada" });
    await waitFor(() => expect(within(panel).getByText("50 %")).toBeDefined());
    expect(within(panel).getByText("30 %")).toBeDefined();
    expect(within(panel).getByText("20 %")).toBeDefined();
    expect(calls().some(c => c.url.endsWith("/api/triad-compositions/7"))).toBe(true);
    expect(screen.queryByRole("option", { name: /fama_trained_model_1[123]/ })).toBeNull();
  });

  it("no permite revisar los pesos después del entrenamiento", async () => {
    await show();
    await chooseModel("Tríada 7");
    const panel = await screen.findByRole("region", { name: "Composición de la tríada" });
    await waitFor(() => expect(within(panel).getByText("50 %")).toBeDefined());
    expect(within(panel).queryByRole("spinbutton")).toBeNull();
    expect(within(panel).queryByRole("textbox")).toBeNull();
    expect(within(panel).queryByRole("button")).toBeNull();
    expect(within(panel).getByText(/fijados en el entrenamiento/)).toBeDefined();
    expect(calls().some(c => c.url.endsWith("/weights"))).toBe(false);
  });

  it("no muestra el panel para un modelo individual", async () => {
    await show();
    await screen.findByRole("combobox", { name: "Modelo:" });
    expect(screen.queryByRole("region", { name: "Composición de la tríada" })).toBeNull();
    expect(calls().some(c => c.url.includes("/api/triad-compositions"))).toBe(false);
  });

});

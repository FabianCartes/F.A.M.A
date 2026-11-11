import { chooseModel } from "../../prediction/__tests__/selectorActions";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionView, { type RegisteredModel } from "../PredictionView";
import { triadWeightsFromPercents } from "@/components/training/TriadComponentsEditor";

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
let revise: (body: { weights: number[] }) => Response;
let transport: ReturnType<typeof vi.fn>;
const calls = () => transport.mock.calls.map(([url, init]) => ({ url: String(url), init: init as RequestInit | undefined }));
const show = async () => { await act(async () => { render(<PredictionView />); }); };
const selection = () => screen.getByRole("combobox", { name: "Modelo:" });

beforeEach(() => {
  models = [bird, triad(7, 1)];
  revise = () => json(composition(8, 2, [0.6, 0.3, 0.1]), 201);
  transport = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/models")) return catalogueOf(models);
    if (url.includes("/api/model-info")) return new Response(null, { status: 503 });
    if (url.endsWith("/api/triad-compositions/7")) return json(composition(7, 1, [0.5, 0.3, 0.2]));
    if (url.endsWith("/api/triad-compositions/8")) return json(composition(8, 2, [0.6, 0.3, 0.1]));
    if (url.endsWith("/api/triad-compositions/7/weights")) return revise(JSON.parse(String(init?.body)));
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
  it("muestra la composición como un solo modelo con sus tres componentes y pesos", async () => {
    await show();
    await chooseModel("Tríada 7");
    const panel = await screen.findByRole("region", { name: "Composición de la tríada" });
    await waitFor(() => expect(within(panel).getAllByText(/fama_trained_model_1[123]/)).toHaveLength(3));
    expect((within(panel).getByLabelText("Porcentaje del componente 1") as HTMLInputElement).value).toBe("50");
    expect((within(panel).getByLabelText("Porcentaje del componente 2") as HTMLInputElement).value).toBe("30");
    expect((within(panel).getByLabelText("Porcentaje del componente 3") as HTMLInputElement).value).toBe("20");
    expect(calls().some(c => c.url.endsWith("/api/triad-compositions/7"))).toBe(true);
    expect(screen.queryByRole("option", { name: /fama_trained_model_1[123]/ })).toBeNull();
  });

  it("no muestra el panel para un modelo individual", async () => {
    await show();
    await screen.findByRole("combobox", { name: "Modelo:" });
    expect(screen.queryByRole("region", { name: "Composición de la tríada" })).toBeNull();
    expect(calls().some(c => c.url.includes("/api/triad-compositions"))).toBe(false);
  });

  it("revisa los pesos con el endpoint estándar y selecciona la nueva versión", async () => {
    await show();
    await chooseModel("Tríada 7");
    const panel = await screen.findByRole("region", { name: "Composición de la tríada" });
    await waitFor(() => expect((within(panel).getByLabelText("Porcentaje del componente 1") as HTMLInputElement).value).toBe("50"));
    [60, 30, 10].forEach((value, i) => fireEvent.change(within(panel).getByLabelText(`Porcentaje del componente ${i + 1}`), { target: { value: String(value) } }));
    models = [bird, triad(8, 2)];
    await act(async () => { fireEvent.click(within(panel).getByRole("button", { name: "Guardar nueva versión de pesos" })); });
    const post = calls().find(c => c.url.endsWith("/api/triad-compositions/7/weights"))!;
    expect(post.init?.method).toBe("POST");
    expect(JSON.parse(String(post.init?.body))).toEqual({ weights: triadWeightsFromPercents([60, 30, 10]).weights });
    await waitFor(() => expect(selection().textContent).toContain("Tríada 8"));
    expect(calls().some(c => c.url.endsWith("/api/triad-compositions/8"))).toBe(true);
  });

  it.each([[422, "Pesos inválidos"], [409, "La versión ya no es la última"]])("muestra el error %i sin cambiar la selección", async (status, detail) => {
    revise = () => json({ detail }, status);
    await show();
    await chooseModel("Tríada 7");
    const panel = await screen.findByRole("region", { name: "Composición de la tríada" });
    await waitFor(() => expect((within(panel).getByLabelText("Porcentaje del componente 1") as HTMLInputElement).value).toBe("50"));
    fireEvent.change(within(panel).getByLabelText("Porcentaje del componente 1"), { target: { value: "40" } });
    fireEvent.change(within(panel).getByLabelText("Porcentaje del componente 3"), { target: { value: "30" } });
    await act(async () => { fireEvent.click(within(panel).getByRole("button", { name: "Guardar nueva versión de pesos" })); });
    expect((await within(panel).findByRole("alert")).textContent).toContain(detail);
    expect(selection().textContent).toContain("Tríada 7");
  });

  it("no envía la revisión cuando el total no es exactamente 100 %", async () => {
    await show();
    await chooseModel("Tríada 7");
    const panel = await screen.findByRole("region", { name: "Composición de la tríada" });
    await waitFor(() => expect((within(panel).getByLabelText("Porcentaje del componente 1") as HTMLInputElement).value).toBe("50"));
    fireEvent.change(within(panel).getByLabelText("Porcentaje del componente 1"), { target: { value: "55" } });
    expect((within(panel).getByRole("button", { name: "Guardar nueva versión de pesos" }) as HTMLButtonElement).disabled).toBe(true);
    expect(calls().some(c => c.url.endsWith("/weights"))).toBe(false);
  });
});

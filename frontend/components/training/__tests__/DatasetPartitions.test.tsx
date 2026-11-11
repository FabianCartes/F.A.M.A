import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetPartitions from "../DatasetPartitions";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("reserves test recordings and keeps legacy 80/20 versions visible as history", async () => {
  const calls: RequestInit[] = [];
  const version = "b".repeat(64);
  const preview = {format:2,version,counts:{train:6,val:2,test:2},warnings:[],entries:[],excluded:[]};
  vi.stubGlobal("fetch", vi.fn(async (_url, options?: RequestInit) => {
    calls.push(options ?? {});
    return {ok:true,status:200,json:async () => options?.method === "POST" ? preview : {
      versions:[{format:1,version:"a".repeat(64),counts:{train:8,val:2},warnings:[]}]}};
  }));
  const select = vi.fn();
  render(<DatasetPartitions dataset="Sample" selected="" busy={false} onSelect={select} />);
  const legacy = await screen.findByRole("option",{name:/Histórica 80\/20/});
  expect((legacy as HTMLOptionElement).disabled).toBe(true);
  expect(screen.getByLabelText("Prueba (%)")).toBeDefined();
  fireEvent.click(screen.getByRole("button",{name:"Previsualizar reparto"}));
  expect(await screen.findByText("6 para entrenamiento · 2 para validación · 2 para prueba")).toBeDefined();
  expect(JSON.parse(String(calls.find(call=>call.method === "POST")?.body))).toEqual({validation_percent:20,test_percent:20,seed:42});
  fireEvent.click(screen.getByRole("button",{name:"Guardar versión y seleccionarla"}));
  await waitFor(() => expect(select).toHaveBeenCalledWith(version));
});


it("opens with the dataset and names versions by number and date without their hash", async () => {
  const newer = { format: 2, version: "c".repeat(64), counts: { train: 6, val: 2, test: 2 }, warnings: [],
    created_at: "2026-11-11T18:00:00Z", policy: { validation_percent: 20, test_percent: 20, seed: 42 } };
  const older = { format: 2, version: "d".repeat(64), counts: { train: 5, val: 2, test: 2 }, warnings: [],
    created_at: "2026-11-10T18:00:00Z", policy: { validation_percent: 20, test_percent: 20, seed: 7 } };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ versions: [newer, older] }) })));
  render(<DatasetPartitions dataset="Sample" selected={newer.version} busy={false} onSelect={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /particiones/ })).toBeNull();
  const option = await screen.findByRole("option", { name: /^Versión 2 · 6 entrenamiento \/ 2 validación \/ 2 prueba/ });
  expect(option.textContent).toContain(new Date(newer.created_at).toLocaleString("es-CL"));
  expect(screen.getByRole("option", { name: /^Versión 1 · 5 entrenamiento/ })).toBeDefined();
  const section = screen.getByRole("region", { name: "Particiones de entrenamiento" });
  expect(section.textContent).toContain("Versión seleccionada: Versión 2");
  expect(section.textContent).not.toMatch(/[0-9a-f]{12}/);
});

const reviewBody = { total: 10, classes: { Canastero: 5, Chucao: 5 },
  not_local: { count: 1, files: ["Chucao/4.wav"] }, duplicates: { count: 1, groups: [["Canastero/5.wav", "Canastero/6.wav"]] },
  small_classes: [{ clase: "Canastero", count: 5 }, { clase: "Chucao", count: 5 }],
  window_seconds: 5, short_audios: { count: 2, threshold_seconds: 2.5, files: ["Canastero/7.wav", "Canastero/8.wav"] },
  long_audios: { count: 3, files: ["Chucao/0.wav", "Chucao/1.wav", "Chucao/2.wav"] },
  class_median_seconds: { Canastero: 3.85, Chucao: 10.5 }, duration_imbalance: true, unknown_durations: 0 };

function partitionsTransport(versions: unknown[], calls: { url: string; body?: unknown }[] = []) {
  return vi.fn(async (input: string, options?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (url.includes("/review")) return { ok: true, status: 200, json: async () => reviewBody };
    if (url.endsWith("/preview")) return { ok: true, status: 200, json: async () => ({ format: 2, version: "f".repeat(64),
      counts: { train: 8, val: 2, test: 2 }, warnings: [], entries: [], excluded: [] }) };
    return { ok: true, status: 200, json: async () => ({ versions }) };
  });
}

it("warns that the selected version is behind and creates an updated version with its policy", async () => {
  const stale = { format: 2, version: "c".repeat(64), counts: { train: 6, val: 2, test: 2 }, warnings: [],
    created_at: "2026-11-11T18:00:00Z", policy: { validation_percent: 25, test_percent: 15, seed: 7 }, freshness: { new: 12, changed: 1 } };
  const calls: { url: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", partitionsTransport([stale], calls));
  render(<DatasetPartitions dataset="Sample" selected={stale.version} busy={false} onSelect={vi.fn()} />);
  expect(await screen.findByText("Hay 12 audios nuevos desde esta versión.")).toBeDefined();
  expect(screen.getByText("1 audio de esta versión cambió o ya no está disponible.")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Crear versión actualizada" }));
  expect(await screen.findByText(/Versión actualizada de Versión 1/)).toBeDefined();
  const preview = calls.find(call => call.url.endsWith("/preview"));
  expect(preview?.body).toEqual({ validation_percent: 25, test_percent: 15, seed: 7, base_version: stale.version });
  expect((screen.getByLabelText("Semilla del reparto") as HTMLInputElement).value).toBe("7");
  fireEvent.click(screen.getByRole("button", { name: "Guardar versión y seleccionarla" }));
  await waitFor(() => expect(calls.filter(call => call.body && !call.url.endsWith("/preview")).at(-1)?.body).toMatchObject({
    base_version: stale.version, preview_version: "f".repeat(64) }));
});

it("does not warn for a version that is up to date", async () => {
  const current = { format: 2, version: "c".repeat(64), counts: { train: 6, val: 2, test: 2 }, warnings: [],
    policy: { validation_percent: 20, test_percent: 20, seed: 42 }, freshness: { new: 0, changed: 0 } };
  vi.stubGlobal("fetch", partitionsTransport([current]));
  render(<DatasetPartitions dataset="Sample" selected={current.version} busy={false} onSelect={vi.fn()} />);
  await screen.findByRole("option", { name: /^Versión 1/ });
  expect(screen.queryByText(/audios? nuevos? desde esta versión/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Crear versión actualizada" })).toBeNull();
});

it("summarizes the dataset review before partitioning", async () => {
  vi.stubGlobal("fetch", partitionsTransport([]));
  render(<DatasetPartitions dataset="Sample" selected="" busy={false} onSelect={vi.fn()} />);
  const review = within(await screen.findByRole("region", { name: "Revisión del dataset" }));
  expect(review.getByText("10 audios registrados en 2 clases.")).toBeDefined();
  expect(review.getByText("1 audio no está descargado en este equipo.")).toBeDefined();
  expect(review.getByText("1 grupo de audios duplicados.")).toBeDefined();
  expect(review.getByText("Clases con pocos audios (menos de 10): Canastero (5), Chucao (5).")).toBeDefined();
  expect(review.getByText("2 audios duran menos de 2,5 s (la mitad de la ventana de 5 s) y se completarán con silencio.")).toBeDefined();
  expect(review.getByText("3 audios duran más de 5 s; se usa su tramo más activo.")).toBeDefined();
  expect(review.getByText("Las clases tienen duraciones muy distintas (Canastero 3,85 s, Chucao 10,5 s); el modelo podría aprender la duración en vez del sonido.")).toBeDefined();
  expect(review.queryByText(/atípica/)).toBeNull();
  expect(review.queryByText(/\.wav/)).toBeNull();
  expect(screen.getByRole("region", { name: "Revisión del dataset" }).querySelector("details")).toBeNull();
});

it("asks the review for the training analysis window", async () => {
  const calls: { url: string }[] = [];
  vi.stubGlobal("fetch", partitionsTransport([], calls));
  render(<DatasetPartitions dataset="Sample" selected="" busy={false} onSelect={vi.fn()} windowSeconds={8} />);
  await screen.findByRole("region", { name: "Revisión del dataset" });
  expect(calls.some(call => call.url.endsWith("/partitions/review?window_seconds=8"))).toBe(true);
});

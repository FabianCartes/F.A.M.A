import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import TrainingView from "../TrainingView";

const model = (id: number, name: string, dataset: string, architecture = "AudioCNN") => ({
  id, name, architecture, dataset, dataset_name: dataset, version: 1, epochs: 1, accuracy: 80, loss: 0.1,
  active: false, status: "entrenado", filename: `${id}.pt`,
  hyperparameters: { learning_rate: 0.001, batch_size: 8, optimizer: "AdamW", loss_type: "Focal", ensemble_weight: 0.1 },
  audio_specs: { target_sr: 16000, duration_seconds: 2, n_mels: 80, n_fft: 512, hop_length: 128, fmin: 0, fmax: 7000 },
});
const history = [
  model(1, "Clasificador Pájaros", "Aves pequeño"),
  model(2, "Diagnóstico motor", "engine_diagnostics", "PANNs"),
  model(3, "Miembro A", "Aves triada"), model(4, "Miembro B", "Aves triada"), model(5, "Miembro C", "Aves triada"),
];
const compositions = [{ id: 9, version: 1, job_id: "job", name: "Super-Ensamble Aves", components: [
  { id_modelo: 3, weight: 0.4 }, { id_modelo: 4, weight: 0.3 }, { id_modelo: 5, weight: 0.3 },
] }];

async function setup() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/checkpoints/sync-status")) return new Response(JSON.stringify({ models: [] }));
    if (url.includes("/partitions")) return new Response(JSON.stringify({ versions: [] }));
    return { ok: true, json: async () => url.includes("/history") ? { history, compositions }
      : url.includes("/datasets") ? { datasets: [] } : url.includes("/progress") ? { status: "idle", logs: [] } : {} };
  }));
  await act(async () => { render(<TrainingView />); });
  await screen.findByRole("row", { name: /Clasificador Pájaros/ });
}
const search = (text: string) => fireEvent.change(screen.getByRole("searchbox", { name: "Buscar en el historial" }), { target: { value: text } });
const rows = () => screen.getAllByRole("row").slice(1).map(row => row.textContent ?? "");
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("filtra por nombre sin distinguir mayúsculas ni tildes", async () => {
  await setup();
  search("PAJAROS");
  expect(rows()).toHaveLength(1);
  expect(rows()[0]).toMatch(/Clasificador Pájaros/);
});

it("filtra por dataset y por arquitectura", async () => {
  await setup();
  search("engine");
  expect(rows()).toEqual([expect.stringMatching(/Diagnóstico motor/)]);
  search("panns");
  expect(rows()).toEqual([expect.stringMatching(/Diagnóstico motor/)]);
});

it("muestra el ensamble completo cuando coincide su nombre o uno de sus miembros", async () => {
  await setup();
  search("super-ensamble");
  expect(rows()).toEqual([expect.stringMatching(/Miembro A.*Miembro B.*Miembro C/)]);
  search("miembro b");
  expect(rows()).toEqual([expect.stringMatching(/Miembro A.*Miembro B.*Miembro C/)]);
});

it("avisa cuando nada coincide y restaura la lista al limpiar la búsqueda", async () => {
  await setup();
  search("  inexistente ");
  expect(screen.queryAllByRole("row").slice(1)).toHaveLength(0);
  expect(screen.getByText("Ningún modelo coincide con «inexistente».")).toBeDefined();
  search("");
  expect(rows()).toHaveLength(3);
});

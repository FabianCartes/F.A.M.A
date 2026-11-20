import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";

const session = vi.hoisted(() => ({ user: null as null | { id: number; rol: "administrador" | "investigador" } }));
vi.mock("@/components/auth/SessionBoundary", () => ({ useOptionalWebSession: () => session.user }));

import TrainingView from "../TrainingView";

const member = (id: number, active = false) => ({
  id, name: `Miembro ${id}`, architecture: ["Alpha", "Beta", "Gamma", "Delta"][id - 1], dataset: "Aves",
  epochs: 1, accuracy: 80, loss: 0.1, active, status: "entrenado", filename: `${id}.pt`,
  hyperparameters: { learning_rate: 0.001, batch_size: 8, optimizer: "AdamW", loss_type: "Focal", ensemble_weight: 0.1 },
  audio_specs: { target_sr: 16000, duration_seconds: 2, n_mels: 80, n_fft: 512, hop_length: 128, fmin: 0, fmax: 7000 },
});
const triad = (active: boolean) => ({ id: 5, version: 1, job_id: "job-a", active, components: [
  { id_modelo: 1, weight: 0.5 }, { id_modelo: 2, weight: 0.3 }, { id_modelo: 3, weight: 0.2 },
] });

let history = { history: [member(1), member(2), member(3), { ...member(4), name: "Individual" }], compositions: [triad(false)] };
let activation: () => Response = () => new Response(JSON.stringify({ success: true }));

async function setup(rol: "administrador" | "investigador" | null) {
  session.user = rol ? { id: 1, rol } : null;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST" && url.includes("/activate")) return activation();
    if (url.includes("/checkpoints/sync-status")) return new Response(JSON.stringify({ models: [] }));
    if (url.includes("/partitions")) return new Response(JSON.stringify({ versions: [] }));
    return { ok: true, json: async () => url.includes("/history") ? history
      : url.includes("/datasets") ? { datasets: [] } : url.includes("/progress") ? { status: "idle", logs: [] } : {} };
  }));
  await act(async () => { render(<TrainingView />); });
}

const posts = () => vi.mocked(fetch).mock.calls
  .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST").map(([url]) => String(url));

afterEach(() => {
  cleanup(); vi.unstubAllGlobals();
  history = { history: [member(1), member(2), member(3), { ...member(4), name: "Individual" }], compositions: [triad(false)] };
  activation = () => new Response(JSON.stringify({ success: true }));
});

it("el administrador activa un modelo individual como predeterminado y recarga el historial", async () => {
  await setup("administrador");
  const row = await screen.findByRole("row", { name: /Individual/ });
  history = { ...history, history: [member(1), member(2), member(3), { ...member(4, true), name: "Individual" }] };
  await act(async () => { fireEvent.click(within(row).getByRole("button", { name: "Activar como predeterminado" })); });
  expect(posts()).toEqual(["/api/training/models/4/activate"]);
  const updated = await screen.findByRole("row", { name: /Individual/ });
  expect(within(updated).getByText("Predeterminado")).toBeDefined();
  expect(within(updated).queryByRole("button", { name: "Activar como predeterminado" })).toBeNull();
});

it("el administrador activa la tríada con su propio endpoint", async () => {
  await setup("administrador");
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  await act(async () => { fireEvent.click(within(row).getByRole("button", { name: "Activar como predeterminado" })); });
  expect(posts()).toEqual(["/api/triad-compositions/5/activate"]);
});

it("muestra el motivo cuando el backend rechaza la activación", async () => {
  activation = () => new Response(JSON.stringify({ success: false, error: "Los modelos importados no pueden activarse globalmente." }));
  await setup("administrador");
  const row = await screen.findByRole("row", { name: /Individual/ });
  await act(async () => { fireEvent.click(within(row).getByRole("button", { name: "Activar como predeterminado" })); });
  expect(within(row).getByRole("alert").textContent).toContain("Los modelos importados no pueden activarse globalmente.");
});

it("el investigador ve cuál es el predeterminado pero no puede cambiarlo", async () => {
  history = { ...history, compositions: [triad(true)] };
  await setup("investigador");
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  expect(within(row).getByText("Predeterminado")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Activar como predeterminado" })).toBeNull();
});

import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import TrainingView from "../TrainingView";

const models = [1, 2, 3].map((id) => ({
  id, name: `Miembro ${id}`, architecture: ["Alpha", "Beta", "Gamma"][id - 1],
  dataset: "Datos", epochs: id, accuracy: 70 + id, loss: id / 10,
  active: false, status: "entrenado", filename: `${id}.pt`,
  hyperparameters: { learning_rate: 0.001, batch_size: 8, optimizer: "AdamW", loss_type: "Focal", ensemble_weight: 0.1 },
  audio_specs: { target_sr: 16000, duration_seconds: 2, n_mels: 80, n_fft: 512, hop_length: 128, fmin: 0, fmax: 7000 },
}));
const composition = { id: 5, version: 2, job_id: "job-a", components: [
  { id_modelo: 1, weight: 0.5 }, { id_modelo: 2, weight: 0.3 }, { id_modelo: 3, weight: 0.2 },
] };

async function setup(history: object[], compositions?: object[]) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/checkpoints/sync-status")) return new Response(JSON.stringify({ models: [] }));
    if (url.includes("/models/2/checkpoint/sync")) return new Response(JSON.stringify({ model_id: 2, filename: "2.pt", sha256: "a".repeat(64), size_bytes: 2, local: "valid", cloud: "available", generation: "1", transfer_verified: true, action: "uploaded" }));
    return { ok: true, json: async () => url.includes("/history") ? { history, compositions }
      : url.includes("/datasets") ? { datasets: [] } : url.includes("/progress") ? { status: "idle", logs: [] } : {} };
  }));
  await act(async () => { render(<TrainingView />); });
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("prioriza el dataset visual agrupado y usa el canónico si falta", async () => {
  const visual = models.map(m => ({ ...m, dataset: "Visual", dataset_name: "canonical" }));
  const fallback = models.map(m => ({ ...m, id: m.id + 3, name: `Otro ${m.id}`, dataset: "", dataset_name: "respaldo" }));
  const standalone = { ...models[0], id: 7, name: "Individual", dataset: "Visual individual", dataset_name: "canónico individual" };
  await setup([...visual, ...fallback, standalone], [composition, {
    ...composition, id: 6, job_id: "job-b", components: composition.components.map(c => ({ ...c, id_modelo: c.id_modelo + 3 })),
  }]);
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  expect(within(row).getByText("Visual")).toBeDefined();
  expect(within(row).queryByText("canonical")).toBeNull();
  expect(within(screen.getByRole("row", { name: /Otro 1.*Otro 2.*Otro 3/ })).getByText("respaldo")).toBeDefined();
  expect(within(screen.getByRole("row", { name: /Individual/ })).getByText("canónico individual")).toBeDefined();
});

it("identifica la ficha conjunta con la versión de composición y conserva la versión individual", async () => {
  const members = models.map(m => ({ ...m, version: 9, dataset_name: "canonical", dataset: "Visual" }));
  const standalone = { ...members[0], id: 7, name: "Individual", version: 8 };
  await setup([...members, standalone], [composition]);
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  fireEvent.click(within(row).getByRole("button", { name: "Ficha Técnica" }));
  let sheet = within(screen.getByTestId("modal-ficha-tecnica"));
  expect(sheet.getByText("v2")).toBeDefined();
  expect(sheet.queryByText("v9")).toBeNull();
  fireEvent.click(sheet.getByText("Cerrar"));
  fireEvent.click(within(screen.getByRole("row", { name: /Individual/ })).getByRole("button", { name: "Ficha Técnica" }));
  sheet = within(screen.getByTestId("modal-ficha-tecnica"));
  expect(sheet.getByText("v8")).toBeDefined();
});

it("agrupa miembros explícitos y no inventa una evaluación conjunta", async () => {
  await setup(models, [composition]);
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  expect(within(row).getByText("Sin evaluación conjunta")).toBeDefined();
  expect(screen.getAllByRole("row")).toHaveLength(2);
  expect(within(row).queryByRole("button", { name: /Activar/ })).toBeNull();
});

it("mantiene trabajos distintos y deja visibles grupos incompletos o inválidos", async () => {
  const more = models.map(m => ({ ...m, id: m.id + 3, name: `Otro ${m.id}` }));
  const orphan = { ...models[0], id: 7, name: "Huérfano" };
  await setup([...models, ...more, orphan], [composition,
    { ...composition, id: 6, job_id: "job-b", components: composition.components.map(c => ({ ...c, id_modelo: c.id_modelo + 3 })) },
    { ...composition, id: 7, job_id: "job-c", components: [{ id_modelo: 7, weight: 0.5 }, { id_modelo: 8, weight: 0.3 }, { id_modelo: 9, weight: 0.2 }] },
  ]);
  expect(await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ })).toBeDefined();
  expect(screen.getByRole("row", { name: /Otro 1.*Otro 2.*Otro 3/ })).toBeDefined();
  expect(screen.getByRole("row", { name: /Huérfano/ })).toBeDefined();
});

it("muestra detalles individuales, pesos actuales y sincroniza cada checkpoint desde la ficha conjunta", async () => {
  await setup(models, [composition]);
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  fireEvent.click(within(row).getByRole("button", { name: "Ficha Técnica" }));
  const sheet = within(screen.getByTestId("modal-ficha-tecnica"));
  for (const [arch, weight, filename] of [["Alpha", "0.5", "1.pt"], ["Beta", "0.3", "2.pt"], ["Gamma", "0.2", "3.pt"]]) {
    const section = sheet.getByRole("heading", { name: `${arch} · métricas individuales` }).closest("section")!;
    expect(within(section).getByText(weight)).toBeDefined();
    expect(within(section).getByText(filename)).toBeDefined();
    expect(within(section).getByText("16000 Hz")).toBeDefined();
    expect(within(section).getByText("AdamW")).toBeDefined();
    expect(within(section).getByText("Pérdida (Loss):")).toBeDefined();
  }
  const beta = sheet.getByRole("heading", { name: "Beta · métricas individuales" }).closest("section")!;
  fireEvent.click(within(beta).getByRole("button", { name: "Sincronizar en GCS" }));
  expect(await screen.findByRole("dialog", { name: "Checkpoint sincronizado" })).toBeDefined();
  expect(vi.mocked(global.fetch).mock.calls.some(([url, options]) => String(url).includes("/models/2/checkpoint/sync") && options?.method === "POST")).toBe(true);
});

it("actualiza los grupos al recargar el historial", async () => {
  await setup(models);
  expect(await screen.findByRole("row", { name: /Miembro 1/ })).toBeDefined();
  const previous = vi.mocked(global.fetch).getMockImplementation()!;
  vi.mocked(global.fetch).mockImplementation(async (input, options) => String(input).includes("/history")
    ? { ok: true, json: async () => ({ history: models, compositions: [composition] }) } as Response
    : previous(input, options));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  expect(await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ })).toBeDefined();
});

it("conserva modelos individuales sin metadatos y con pesos inválidos", async () => {
  await setup(models, [{ ...composition, components: composition.components.map(c => ({ ...c, weight: 0 })) }]);
  expect(await screen.findByRole("row", { name: /Miembro 1/ })).toBeDefined();
  expect(screen.getByRole("row", { name: /Miembro 2/ })).toBeDefined();
  expect(screen.getByRole("row", { name: /Miembro 3/ })).toBeDefined();
  expect(screen.queryByText("Sin evaluación conjunta")).toBeNull();
});

const completed = (accuracy: number) => ({ status: "completed", sample_count: 40, rejection_rate: 0.05, error_reason: null,
  metrics: { accuracy, f1_macro: 0.8, balanced_accuracy: 0.81, precision_macro: 0.8, recall_macro: 0.81, f1_weighted: 0.8 } });

it("muestra la exactitud conjunta de validación en la fila y val/test diferenciados en la ficha", async () => {
  await setup(models, [{ ...composition, evaluation: { val: completed(0.8375), test: completed(0.9) } }]);
  const row = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  expect(within(row).getByText("83.75%")).toBeDefined();
  expect(within(row).queryByText("Sin evaluación conjunta")).toBeNull();
  fireEvent.click(within(row).getByRole("button", { name: "Ficha Técnica" }));
  const joint = within(within(screen.getByTestId("modal-ficha-tecnica")).getByRole("region", { name: "Evaluación conjunta" }));
  expect(joint.getByText("Validación")).toBeDefined();
  expect(joint.getByText("Prueba")).toBeDefined();
  expect(joint.getByText("83.75%")).toBeDefined();
  expect(joint.getByText("90.00%")).toBeDefined();
  expect(joint.getAllByText("40 grabaciones")).toHaveLength(2);
});

it("distingue pendiente, fallo y ausencia sin inventar precisión", async () => {
  const more = models.map(m => ({ ...m, id: m.id + 3, name: `Otro ${m.id}` }));
  await setup([...models, ...more], [
    { ...composition, evaluation: { val: { status: "running", sample_count: 40, metrics: null, rejection_rate: null, error_reason: null }, test: null } },
    { ...composition, id: 6, job_id: "job-b", components: composition.components.map(c => ({ ...c, id_modelo: c.id_modelo + 3 })),
      evaluation: { val: { status: "failed", sample_count: 40, metrics: null, rejection_rate: null, error_reason: "Checkpoint cambió durante inferencia" },
        test: { status: "completed", sample_count: 40, metrics: { accuracy: "alta" }, rejection_rate: 0, error_reason: null } } },
  ]);
  const pending = await screen.findByRole("row", { name: /Miembro 1.*Miembro 2.*Miembro 3/ });
  expect(within(pending).getByText("Evaluación conjunta pendiente")).toBeDefined();
  const failed = screen.getByRole("row", { name: /Otro 1.*Otro 2.*Otro 3/ });
  expect(within(failed).getByText("Evaluación conjunta fallida")).toBeDefined();
  fireEvent.click(within(failed).getByRole("button", { name: "Ficha Técnica" }));
  const joint = within(within(screen.getByTestId("modal-ficha-tecnica")).getByRole("region", { name: "Evaluación conjunta" }));
  expect(joint.getByText("Checkpoint cambió durante inferencia")).toBeDefined();
  expect(joint.getByText("Sin informe válido")).toBeDefined();
  expect(joint.queryByText(/%/)).toBeNull();
});

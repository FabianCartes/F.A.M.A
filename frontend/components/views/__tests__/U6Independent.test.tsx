import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DashboardView from "../DashboardView";
import IngestionView from "../IngestionView";

// S1/S4: public UI and HTTP boundary only; no internal component mocks.
const response = (data: unknown, status = 200) => ({ ok: status === 200, status, json: async () => data });
const stats = () => ({
 kpis: { accuracy: 0, loss: 0, total_datasets: 0, total_audios: 0, total_predictions: 0,
 avg_confidence: 0, latest_model_name: "Recorded zero model", metrics_source: "database" },
 training_curves: [], recent_activity: [],
 super_ensemble: { ready: null, active_mode: "unknown", models: [] },
 system_health: { database: "operational", storage: "not_checked", inference_engine: "not_checked", device: "unknown" },
 domain_champions: { bioacoustic: { title: "Historical bird experiment", architecture: "ReferenceNet",
 accuracy: 91.25, macro_f1: 88, classes_count: 7, source: "historical_reference" } },
});
const dataset = { id: "AvesChilenas", name: "AvesChilenas", classes: ["bird"], file_count: 1,
 total_size_bytes: 12, last_modified: null, local_file_count: 0, is_synced: false, source: "gcs", gcs_available:true, gcs_file_count:1 };
let currentStats: ReturnType<typeof stats>;
let datasets: typeof dataset[];
let failedRefresh: boolean;
let syncStatus: number;
let syncData: unknown;
let calls: { url: string; method: string; body: unknown }[];
beforeEach(() => {
 currentStats = stats(); datasets = [dataset]; failedRefresh = false; syncStatus = 200;
 syncData = {}; calls = [];
 vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
  const url = String(input), method = init?.method ?? "GET";
  calls.push({ url, method, body: init?.body });
  if (url.endsWith("/api/dashboard/stats")) return response(currentStats, failedRefresh ? 503 : 200);
  if (url.endsWith("/api/training/hardware")) return response({}, 503);
  if (url.endsWith("/api/ingestion/status")) return response({ connected: false, bucket: "synthetic", total_objects: 0, total_bytes: 0 });
  if (url.endsWith("/api/ingestion/datasets")) return response({ datasets });
  if (url.endsWith("/api/ingestion/sync")) return response(syncData, syncStatus);
  if (url.endsWith("/api/ingestion/imports/access")) return response({ development_mode: false });
  if (url.includes("/feedback")) return response([]);
  throw new Error(`Unexpected simulated request: ${url}`);
 }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("S1/S4 preserved shared consumer seams", () => {
 it("preserves dashboard quick-navigation callback values", async () => {
  const navigate = vi.fn(); render(<DashboardView onNavigate={navigate} />);
  await screen.findByText("0.00%");
  fireEvent.click(screen.getByRole("button", { name: /Ingesta de Datos/ }));
  fireEvent.click(screen.getByRole("button", { name: /Ajuste y ejecución de la tríada/ }));
  fireEvent.click(screen.getByRole("button", { name: /Inferencia Bioacústica/ }));
  expect(navigate.mock.calls).toEqual([["ingesta"], ["entrenamiento"], ["prediccion"]]);
 });
 it("keeps ZIP controls operable and session-gated without submitting data", async () => {
  render(<IngestionView />); await screen.findAllByText("AvesChilenas");
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  let dialog = await screen.findByRole("dialog");
  await within(dialog).findByText(/Inicia sesión en F.A.M.A./i);
  fireEvent.click(within(dialog).getByRole("button", { name: /Cerrar importación/ }));
  fireEvent.click(screen.getByRole("button", { name: "Descargar versión como ZIP" }));
  dialog = await screen.findByRole("dialog");
  await within(dialog).findByText(/Inicia sesión en F.A.M.A./i);
  fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar exportación" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
 });
 it("preserves ingestion empty-queue navigation callback", async () => {
  datasets = []; const navigate = vi.fn(); render(<IngestionView onNavigate={navigate} />);
  const buttons = await screen.findAllByRole("button", { name: "Ir a Inferencia Acústica" });
  for (const button of buttons) fireEvent.click(button);
  expect(navigate.mock.calls.length).toBeGreaterThan(0);
  expect(navigate.mock.calls.every(c => c[0] === "predict")).toBe(true);
 });
 it("keeps measured zero metrics visible", async () => {
  render(<DashboardView onNavigate={vi.fn()} />);
  expect(await screen.findByText("0.00%")).toBeDefined();
  expect(screen.getByText("0.0000")).toBeDefined();
 });
});
describe("S1/S4 truthful dashboard observations", () => {
 it("does not turn missing metrics into measured zero", async () => {
  Object.assign(currentStats.kpis, { accuracy: null, loss: null, total_audios: null, total_predictions: null });
  render(<DashboardView onNavigate={vi.fn()} />);
  await screen.findByText("Recorded zero model");
  const metrics = screen.getByRole("region", { name: "Métricas registradas" });
  expect(within(metrics).getAllByText("No disponible").length).toBeGreaterThanOrEqual(4);
  expect(within(metrics).queryByText("0.00%")).toBeNull();
 });
 it("separates historical results from current availability", async () => {
  render(<DashboardView onNavigate={vi.fn()} />);
  const history = await screen.findByRole("article", { name: "Referencia bioacoustic" });
  expect(within(history).getByText("91.25%")).toBeDefined();
  expect(within(history).getByText(/no acredita disponibilidad actual/)).toBeDefined();
  expect(screen.getByText("Estado no comprobado")).toBeDefined();
 });
 it("retains the last reading but marks failed refresh as unavailable", async () => {
  render(<DashboardView onNavigate={vi.fn()} />); await screen.findByText("Recorded zero model");
  failedRefresh = true;
  fireEvent.click(screen.getByTitle("Actualizar métricas en tiempo real"));
  expect(await screen.findByText("Datos actuales del dashboard no disponibles; se conserva la última lectura.")).toBeDefined();
  expect(screen.getByText("Recorded zero model")).toBeDefined();
  expect(screen.getByText(/BD no confirmada/)).toBeDefined();
 });
});
describe("S1/S4 per-stage persistence completion", () => {
 it.each([
  ["confirmed", true, 0, 0, "completed", "completada"],
  ["database rejected", false, 0, 0, "completed", "parcial"],
  ["database unknown", undefined, 0, 0, "completed", "parcial"],
  ["preprocessing rejected", true, 1, 0, "completed", "parcial"],
  ["download rejected", true, 0, 1, "completed", "parcial"],
  ["top-level failure", true, 0, 0, "failed", "fallida"],
 ] as const)("reports %s without overstating success", async (_label, persisted, prepFailed, downloadFailed, status, expected) => {
  syncData = { status, total_downloaded: 1, total_skipped: 0, total_failed: downloadFailed, total_preprocessed: 0,
   results: [{ dataset: dataset.id, downloaded: 1, skipped: 0, failed: downloadFailed, preprocessed: 0,
    db_persisted: persisted, preprocess_info: { failed: prepFailed } }] };
  render(<IngestionView />); await screen.findAllByText("AvesChilenas");
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  fireEvent.click(screen.getByRole("button", { name: "Descargar desde GCS" }));
  const exact = `Sincronización ${expected}: 1 archivo(s) descargados, 0 omitidos, 0 tensores procesados, ${downloadFailed} errores de descarga.`;
  expect(await screen.findByText(exact)).toBeDefined();
  const request = calls.find(c => c.url.endsWith("/api/ingestion/sync"));
  expect(request?.method).toBe("POST");
  expect(JSON.parse(String(request?.body))).toEqual({ datasets: [dataset.id], preprocess: false });
  await waitFor(() => expect(screen.getByRole("button", { name: "Descargar desde GCS" }).hasAttribute("disabled")).toBe(false));
 });
 it("preserves HTTP error text without a completed success", async () => {
  syncStatus = 503; render(<IngestionView />); await screen.findAllByText("AvesChilenas");
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  fireEvent.click(screen.getByRole("button", { name: "Descargar desde GCS" }));
  expect(await screen.findByText("Fallo en el proceso de sincronización: Error en el servidor: HTTP 503")).toBeDefined();
  expect(screen.queryByText(/^Sincronización completada:/)).toBeNull();
 });
});

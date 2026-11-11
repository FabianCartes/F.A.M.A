import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import FeedbackSyncPanel from "@/components/feedback/FeedbackSyncPanel";
import IngestionView from "../IngestionView";
import * as feedbackApi from "@/lib/api/feedbackApi";

vi.mock("@/lib/api/feedbackApi", () => ({ getPendingFeedback: vi.fn(async () => []), getFeedbackSync: vi.fn(),
  approveFeedback: vi.fn(), rejectFeedback: vi.fn(), getFeedbackStats: vi.fn(), sendFeedback: vi.fn() }));

const record = (sync_status: "pending" | "synced") => ({ id_retroalimentacion: 1, id_prediccion: 1,
  dataset_name: "gatos y perros", storage_class: "cat", class_label: "cat", local_status: "incorporated" as const,
  sync_status, attempts: sync_status === "synced" ? 1 : 0, error_code: null, db_persisted: true });
const listings = () => vi.mocked(global.fetch).mock.calls.filter(([url]) =>
  new URL(String(url), "http://localhost").pathname === "/api/ingestion/datasets").length;

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  global.fetch = vi.fn(async input => {
    const path = new URL(String(input), "http://localhost").pathname;
    const body = path === "/api/ingestion/datasets" ? { datasets: [] } : { connected: true };
    return { ok: true, status: 200, json: async () => body } as Response;
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });

it("polls pending cloud copies and refreshes the dataset inventory once a copy is synced", async () => {
  vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValueOnce([record("pending")]).mockResolvedValue([record("synced")]);
  await act(async () => { render(<IngestionView />); });
  await act(async () => { await vi.advanceTimersByTimeAsync(100); });
  const before = listings();
  expect(vi.mocked(feedbackApi.getFeedbackSync)).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(vi.mocked(feedbackApi.getFeedbackSync)).toHaveBeenCalledTimes(2);
  expect(listings()).toBe(before + 1);
  await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(vi.mocked(feedbackApi.getFeedbackSync)).toHaveBeenCalledTimes(2);
  expect(listings()).toBe(before + 1);
});

it("does not poll when every cloud copy is already synced", async () => {
  vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([record("synced")]);
  await act(async () => { render(<IngestionView />); });
  await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(vi.mocked(feedbackApi.getFeedbackSync)).toHaveBeenCalledTimes(1);
});

it("names who proposed and who incorporated each audio, abbreviating when it is the same person", async () => {
  vi.mocked(feedbackApi.getFeedbackSync).mockResolvedValue([
    { ...record("synced"), id_retroalimentacion: 3, proposed_by: 2, incorporated_by: 2,
      proposed_by_name: "Kevin Cárdenas", incorporated_by_name: "Kevin Cárdenas" },
    { ...record("synced"), id_retroalimentacion: 2, proposed_by: 3, incorporated_by: 2,
      proposed_by_name: "Ana", incorporated_by_name: "Kevin Cárdenas" },
    { ...record("synced"), id_retroalimentacion: 1, proposed_by: 3, incorporated_by: null,
      proposed_by_name: "Ana", incorporated_by_name: null },
  ]);
  await act(async () => { render(<FeedbackSyncPanel refreshKey={0} />); });
  expect(await screen.findByText("Propuesto e incorporado por Kevin Cárdenas")).toBeDefined();
  expect(screen.getByText("Propuesto por Ana · Incorporado por Kevin Cárdenas")).toBeDefined();
  expect(screen.getByText("Propuesto por Ana · Incorporado por autor sin registrar")).toBeDefined();
  expect(screen.queryByText(/cuenta #/)).toBeNull();
});

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
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

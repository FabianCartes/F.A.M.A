import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import IngestionView from "../IngestionView";

const panel = vi.hoisted(() => ({ props: {} as { onPublishingChange?: (name: string | null) => void; onCatalogChange?: () => void } }));
vi.mock("@/components/ingestion/DatasetImportPanel", () => ({
  default: (props: typeof panel.props) => { panel.props = props; return null; },
}));
vi.mock("@/lib/api/feedbackApi", () => ({ getPendingFeedback: vi.fn(async () => []), getFeedbackSync: vi.fn(async () => []),
  approveFeedback: vi.fn(), rejectFeedback: vi.fn(), getFeedbackStats: vi.fn(), sendFeedback: vi.fn() }));

const aves = { id: "Aves", name: "Aves", file_count: 2, classes: ["birds"], total_size_bytes: 10, last_modified: null,
  local_file_count: 0, source: "gcs", gcs_available: true, gcs_file_count: 2, gcs_size_bytes: 10 };
const legacy = { ...aves, id: "Legacy", name: "Legacy", gcs_file_count: 9, file_count: 9 };
let counts: { name: string; file_count: number }[] = [];
let listing: unknown[] = [];
const calls = () => vi.mocked(global.fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost").pathname);

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  counts = [{ name: "Aves", file_count: 5 }, { name: "Legacy", file_count: 0 }];
  listing = [aves, legacy];
  global.fetch = vi.fn(async input => {
    const path = new URL(String(input), "http://localhost").pathname;
    const body = path === "/api/ingestion/datasets/counts" ? { datasets: counts }
      : path === "/api/ingestion/datasets" ? { datasets: listing } : { connected: true };
    return { ok: true, status: 200, json: async () => body } as Response;
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

const cell = (name: string) => within(screen.getByRole("row", { name: new RegExp(name) }));

it("polls lightweight counts only for the publishing dataset and refreshes the full inventory when it ends", async () => {
  await act(async () => { render(<IngestionView />); });
  expect(calls()).not.toContain("/api/ingestion/datasets/counts");
  await act(async () => { panel.props.onPublishingChange?.("Aves"); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(cell("Aves").getByText("5 audios")).toBeDefined();
  expect(cell("Legacy").getByText("9 audios")).toBeDefined();
  counts = [{ name: "Aves", file_count: 8 }];
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(cell("Aves").getByText("8 audios")).toBeDefined();
  const full = calls().filter(path => path === "/api/ingestion/datasets").length;
  listing = [{ ...aves, gcs_file_count: 8, file_count: 8 }, legacy];
  await act(async () => { panel.props.onPublishingChange?.(null); panel.props.onCatalogChange?.(); });
  const polled = calls().filter(path => path === "/api/ingestion/datasets/counts").length;
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(calls().filter(path => path === "/api/ingestion/datasets/counts")).toHaveLength(polled);
  expect(calls().filter(path => path === "/api/ingestion/datasets").length).toBeGreaterThan(full);
});

it("adds a row for a dataset that is not listed yet while it publishes", async () => {
  listing = [legacy];
  await act(async () => { render(<IngestionView />); });
  await act(async () => { panel.props.onPublishingChange?.("Aves"); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(cell("Aves").getByText("5 audios")).toBeDefined();
});

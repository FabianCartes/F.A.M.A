import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([false, true])("preserves server truth on recovery and polling failure; transport=%s", async transport => {
  const base = "/api/ingestion/imports";
  const execution = { id: "work", import_id: "source", kind: "preview", status: transport ? "running" : "failed",
    stage: transport ? "validating" : "failed", progress: 1, result: {},
    error: transport ? null : { code: "execution_failed" }, status_url: base + "/source/jobs/work" };
  const source = { id: "source", archive_name: "failed.zip", status: transport ? "validating" : "cancelled",
    sync_status: "pending", dataset_id: null, added_count: 0, preview_token: "a".repeat(64),
    error: transport ? null : "execution_failed", execution,
    preview: { auto_import: true, root: "", file_count: 0, class_count: 0, error_count: 0,
      warning_count: 0, total_size_bytes: 0, synced_count: 0 } };
  const writes: string[] = [];
  const page = (key: string, items: unknown[]) => Response.json({ [key]: items, total: items.length,
    next_cursor: null, snapshot: source.preview_token });
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (options?.method === "POST") writes.push(path);
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path === base) return page("imports", [source]);
    if (path === execution.status_url) throw new Error("Synthetic lost response");
    if (path.endsWith("/files")) return page("files", []);
    if (path.endsWith("/issues")) return page("issues", []);
    throw new Error(`Unexpected ${path}`);
  }));
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const start = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole("button", { name: /failed.zip —/ }));
  if (transport) {
    await screen.findByText("Synthetic lost response");
    expect(screen.getByText(/Validando los audios…|Trabajo en ejecución: validating/)).toBeDefined();
    expect(screen.queryByText(/quedó cancelada/)).toBeNull();
  } else {
    await screen.findByText(/La importación falló y quedó cancelada/);
    expect(screen.queryByRole("button", { name: "Reintentar trabajo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancelar importación" })).toBeNull();
    expect(screen.queryByText(/La sincronización no está completa/)).toBeNull();
  }
  expect(writes).toEqual([]);
});

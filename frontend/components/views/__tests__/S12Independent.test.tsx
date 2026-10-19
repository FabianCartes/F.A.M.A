import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const B = "/api/ingestion/imports";
const limits = { received_bytes: 1024, expanded_bytes: 4096, entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 };
const preview = { root: "", file_count: 1, class_count: 1, error_count: 0, warning_count: 1, total_size_bytes: 204, synced_count: 0, new_count: 1 };
const page = (key: string, rows: unknown[]) => Response.json({ [key]: rows, total: rows.length, next_cursor: null, snapshot: "a".repeat(64) });

it.each([undefined, false, true])("remount preserves explicit authorization %s without creating work", async auto_import => {
  const writes: string[] = [];
  const source = { id: "history", status: "ready", sync_status: "pending", dataset_id: null, added_count: 0, preview_token: "a".repeat(64), preview: { ...preview, auto_import }, error: null, execution: null };
  const reads: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (options?.method && options.method !== "GET") { writes.push(path); throw new Error("Unexpected write"); }
    reads.push(path);
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json(limits);
    if (path === B) return page("imports", [source]);
    if (path.endsWith("/files")) return page("files", []);
    if (path.endsWith("/classes")) return page("classes", ["bird"]);
    if (path.endsWith("/issues")) return page("issues", []);
    throw new Error("Unexpected read " + path);
  }));
  async function inspect() {
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    const dialog = within(screen.getByRole("dialog"));
    const open = dialog.getByRole("button", { name: "Importar dataset" });
    await waitFor(() => expect((open as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(open);
    fireEvent.click(await screen.findByRole("button", { name: /history —/ }));
    await screen.findByText(/Clases propuestas: 1/);
    expect(Boolean(screen.queryByRole("button", { name: "Confirmar importación local" }))).toBe(auto_import !== true);
    expect(screen.queryByRole("button", { name: "Sincronizar con GCS" })).toBeNull();
    expect(screen.queryByText(/Importada localmente/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Actualizar importaciones" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Actualizar importaciones" }) as HTMLButtonElement).disabled).toBe(false));
  }
  const first = render(<DatasetImportPanel />);
  await inspect();
  first.unmount();
  render(<DatasetImportPanel />);
  await inspect();
  expect(reads.filter(path => path === B).length).toBeGreaterThanOrEqual(4);
  expect(writes).toEqual([]);
});

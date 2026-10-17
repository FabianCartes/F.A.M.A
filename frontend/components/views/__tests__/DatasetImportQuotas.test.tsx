import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const quota = { current_bytes: 100, current_files: 1, new_bytes: 200, new_files: 2,
  projected_bytes: 300, projected_files: 3, limit_bytes: 300, limit_files: 3 };

async function openReview(capacity: typeof quota = quota, status = "ready", errorCount = 0) {
  const writes: string[] = [];
  const job = { id: "quota-review", status, sync_status: "pending", dataset_id: null,
    added_count: 0, preview_token: "a".repeat(64), error: null,
    preview: { root: "", file_count: 3, class_count: 1, error_count: errorCount, warning_count: 0,
      total_size_bytes: 300, synced_count: 0, new_count: 2, quota: capacity } };
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") writes.push(input);
    if (input.endsWith("/access")) return Response.json({ development_mode: true });
    if (input.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4,
      dataset_bytes: 300, dataset_entries: 3 });
    const page = (key: string, items: unknown[], snapshot: string) => Response.json({
      [key]: items, total: items.length, next_cursor: null, snapshot });
    if (input.endsWith("/datasets")) return page("datasets", [], "catalog");
    if (input.endsWith("/imports")) return page("imports", [job], "history");
    if (input.endsWith("/files")) return page("files", [], job.preview_token);
    if (input.endsWith("/classes")) return page("classes", ["birds"], job.preview_token);
    if (input.endsWith("/issues")) return page("issues", errorCount ? [{ id: "quota", severity: "error",
      path: "", code: "dataset_size_limit", action: "Reduce el contenido nuevo." }] : [], job.preview_token);
    throw new Error("Unexpected request: " + input);
  }));
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const dialog = await screen.findByRole("dialog", { name: "Importar dataset" });
  const start = within(dialog).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole("button", { name: /quota-review —/ }));
  await screen.findByText("archivos: 0");
  await screen.findByText("clases: 1");
  await screen.findByText(`incidencias: ${errorCount ? 1 : 0}`);
  return writes;
}

it("shows bounded unique dataset capacity and permits the exact boundary without automatic writes", async () => {
  const writes = await openReview();
  expect(await screen.findByText("Bytes únicos: actuales 100 + nuevos 200 = proyectados 300 / límite 300.")).toBeDefined();
  expect(screen.getByText("Archivos únicos: actuales 1 + nuevos 2 = proyectados 3 / límite 3.")).toBeDefined();
  expect((screen.getByRole("button", { name: "Confirmar importación local" }) as HTMLButtonElement).disabled).toBe(false);
  expect(writes).toEqual([]);
});

it.each(["bytes", "files"] as const)("blocks confirmation when projected %s exceed the reviewed limit", async dimension => {
  const capacity = { ...quota, [`projected_${dimension}`]: 301 };
  const writes = await openReview(capacity);
  const confirm = screen.getByRole("button", { name: "Confirmar importación local" }) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  fireEvent.click(confirm);
  expect(writes).toEqual([]);
});

it("shows structured quota issues without offering confirmation for a correction preview", async () => {
  const writes = await openReview({ ...quota, projected_bytes: 301 }, "needs_correction", 1);
  expect(await screen.findByText(/dataset_size_limit/)).toBeDefined();
  expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
  expect(writes).toEqual([]);
});

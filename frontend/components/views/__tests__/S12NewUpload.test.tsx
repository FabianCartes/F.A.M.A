import { File } from "node:buffer";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const B = "/api/ingestion/imports";
const limits = { received_bytes: 1024, expanded_bytes: 4096, entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 };
const preview = { root: "", file_count: 1, class_count: 1, error_count: 0, warning_count: 1, total_size_bytes: 204, synced_count: 0, new_count: 1 };
const page = (key: string, rows: unknown[]) => Response.json({ [key]: rows, total: rows.length, next_cursor: null, snapshot: "a".repeat(64) });

it.each([false, true])("new upload authorizes only local publication; rejected=%s", async rejected => {
  vi.stubGlobal("crypto", webcrypto);
  const writes: { path: string; body: unknown }[] = [];
  const source = { id: "new", status: "receiving", sync_status: "pending", dataset_id: null, added_count: 0, preview_token: "a".repeat(64), preview: { ...preview, auto_import: true }, error: null, execution: null };
  const job = { id: "work", import_id: "new", kind: "preview", status: "succeeded", stage: "succeeded", progress: 100, result: {}, error: null, status_url: B + "/new/jobs/work" };
  let finished = false;
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (options?.method) writes.push({ path, body: options.method === "POST" && options.body ? JSON.parse(String(options.body)) : undefined });
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json(limits);
    if (path === B) return options?.method ? Response.json(source) : page("imports", []);
    if (path.endsWith("/receipt")) return Response.json({ import_id: "new", name: "synthetic.zip", size_bytes: 3, received_bytes: 0, reserved_bytes: 4099, chunk_bytes: 16 * 1024 ** 2, status: "receiving" });
    if (path.endsWith("/chunks/0") || path.endsWith("/finalize")) return Response.json({ import_id: "new", name: "synthetic.zip", size_bytes: 3, received_bytes: 3, reserved_bytes: 4099, chunk_bytes: 16 * 1024 ** 2, status: path.endsWith("/finalize") ? "sealed" : "receiving" });
    if (path.endsWith("/preview")) return Response.json({ ...job, status: "queued", stage: "queued", progress: 0 }, { status: 202 });
    if (path === job.status_url) { finished = true; return Response.json(job); }
    if (path === B + "/new") return Response.json(finished ? { ...source, status: rejected ? "needs_correction" : "imported", added_count: rejected ? 0 : 1, preview: { ...source.preview, error_count: rejected ? 1 : 0 }, execution: job } : source);
    if (path.endsWith("/files")) return page("files", []);
    if (path.endsWith("/classes")) return page("classes", ["bird"]);
    if (path.endsWith("/issues")) return page("issues", rejected ? [{ id: "issue", path: "bird/nested/", code: "class_folders_required", severity: "error", action: "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas." }] : []);
    throw new Error("Unexpected request " + path);
  }));
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const open = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" });
  await waitFor(() => expect((open as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(open);
  fireEvent.change(screen.getByLabelText("Nombre del dataset"), { target: { value: "New" } });
  fireEvent.change(screen.getByLabelText("Archivo ZIP"), { target: { files: [new File(["abc"], "synthetic.zip")] } });
  fireEvent.click(screen.getByRole("button", { name: "Importar ZIP" }));
  await screen.findByText(rejected ? /ZIP rechazado/ : /Importada localmente: 1 archivo/);
  if (rejected) await screen.findByText(/Organiza el ZIP como clase/);
  expect(writes.filter(w => w.path === B)).toHaveLength(1);
  expect(writes.find(w => w.path === B)?.body).toMatchObject({ auto_import: true, layout: "class_folders", target_id: null });
  expect(writes.filter(w => /\/(confirm|sync|cancel)$/.test(w.path))).toEqual([]);
  expect(writes.filter(w => w.path.endsWith("/preview"))).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
});

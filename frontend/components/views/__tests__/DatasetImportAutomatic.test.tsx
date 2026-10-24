import { File } from "node:buffer";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const base = "/api/ingestion/imports";
const limits = { received_bytes: 1024, expanded_bytes: 4096, entries: 10, depth: 12, path_bytes: 240,
  audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 };
const preview = { auto_import: true, root: "", file_count: 1, class_count: 1, error_count: 0,
  warning_count: 1, total_size_bytes: 100, synced_count: 0, new_count: 1 };
const execution = { id: "exec", import_id: "source", kind: "preview", status: "running", stage: "verifying",
  progress: 1, result: {}, error: null, status_url: `${base}/source/jobs/exec` };
const source = { id: "source", status: "ready", sync_status: "pending", dataset_id: null, added_count: 0,
  preview_token: "a".repeat(64), preview, error: null, execution };
const page = (key: string, rows: unknown[]) => Response.json({ [key]: rows, total: rows.length,
  next_cursor: null, snapshot: source.preview_token });

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const start = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(start);
}

it("authorizes automatic import once and polls the same job through hidden publication without confirm or sync", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const writes: { path: string; body?: Record<string, unknown> }[] = [];
  let complete!: (response: Response) => void;
  let published = false;
  const finished = { ...execution, status: "succeeded", stage: "succeeded", progress: 100,
    result: { dataset_id: "dataset", added_count: 1 } };
  const fetcher = vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (options?.method) writes.push({ path, body: options.method === "POST" && options.body
      ? JSON.parse(String(options.body)) : undefined });
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json(limits);
    if (path === base) return options?.method ? Response.json({ ...source, status: "receiving", execution: null }) : page("imports", []);
    if (path.endsWith("/receipt")) return Response.json({ import_id: source.id, name: "birds.zip", size_bytes: 3,
      received_bytes: 0, reserved_bytes: 4099, chunk_bytes: 16 * 1024 ** 2, status: "receiving" });
    if (path.endsWith("/chunks/0") || path.endsWith("/finalize")) return Response.json({ import_id: source.id,
      name: "birds.zip", size_bytes: 3, received_bytes: 3, reserved_bytes: 4099, chunk_bytes: 16 * 1024 ** 2,
      status: path.endsWith("/finalize") ? "sealed" : "receiving" });
    if (path === base + "/source") return Response.json(published
      ? { ...source, status: "imported", dataset_id: "dataset", added_count: 1, execution: finished }
      : { ...source, status: "validating", execution: null });
    if (path.endsWith("/preview")) return Response.json(execution, { status: 202 });
    if (path === execution.status_url) return new Promise<Response>(resolve => { complete = resolve; });
    if (path.endsWith("/files")) return page("files", []);
    if (path.endsWith("/classes")) return page("classes", ["bird"]);
    if (path.endsWith("/issues")) return page("issues", []);
    throw new Error(`Unexpected ${options?.method || "GET"} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<DatasetImportPanel />);
  expect(writes).toEqual([]);
  await open();
  expect(writes).toEqual([]);
  fireEvent.change(screen.getByLabelText("Nombre del dataset"), { target: { value: "Birds" } });
  fireEvent.change(screen.getByLabelText("Archivo ZIP"), { target: { files: [new File(["zip"], "birds.zip")] } });
  fireEvent.click(screen.getByRole("button", { name: /^(Importar|Validar) ZIP$/ }));
  await waitFor(() => expect(complete).toBeTypeOf("function"));
  expect(writes.find(write => write.path === base)?.body).toMatchObject({ auto_import: true, layout: "class_folders", target_id: null });
  expect(screen.getByText(/se importará automáticamente solo si supera la validación/)).toBeDefined();
  expect(screen.getByRole("button", { name: "Importar ZIP" })).toBeDefined();
  expect(screen.queryByText(/Importada localmente/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cerrar importación" }));
  await act(async () => { published = true; complete(Response.json(finished)); });
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/source"))).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  await screen.findByText(/Importada localmente: 1 archivo/);
  expect(screen.getByText(/Advertencias: 1/)).toBeDefined();
  expect(screen.getByRole("button", { name: "Sincronizar con GCS" })).toBeDefined();
  expect(writes.filter(write => write.path.endsWith("/preview"))).toHaveLength(1);
  expect(writes.filter(write => /\/(confirm|sync|cancel)$/.test(write.path))).toEqual([]);
});

it.each(["ready", "committing", "needs_correction"])("recovers automatic %s with inert reads and no second confirmation", async status => {
  const issue = { id: "issue", path: "bird/session/a.wav", code: "class_folders_required", severity: "error",
    action: "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas." };
  const automatic = { ...source, status, execution: { ...execution,
    status: status === "needs_correction" ? "succeeded" : "failed",
    error: status === "needs_correction" ? null : { code: "execution_failed" } },
    preview: { ...preview, error_count: status === "needs_correction" ? 1 : 0 } };
  const legacy = { ...source, id: "legacy", execution: null, preview: { ...preview, auto_import: undefined } };
  const writes: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (options?.method) writes.push(path);
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json(limits);
    if (path === base) return page("imports", [automatic, legacy]);
    if (path === execution.status_url + "/retry") return Response.json({ ...execution, id: "retry", status: "queued",
      status_url: `${base}/source/jobs/retry` }, { status: 202 });
    if (path === `${base}/source/jobs/retry`) return Response.json({ ...execution, id: "retry", status: "succeeded" });
    if (path === `${base}/source`) return Response.json({ ...source, status: "imported", dataset_id: "dataset", added_count: 1,
      execution: { ...execution, id: "retry", status: "succeeded" } });
    if (path.endsWith("/files")) return page("files", []);
    if (path.endsWith("/classes")) return page("classes", ["bird"]);
    if (path.endsWith("/issues")) return page("issues", status === "needs_correction" ? [issue] : []);
    throw new Error(`Unexpected ${path}`);
  }));
  const first = render(<DatasetImportPanel />);
  await open();
  fireEvent.click(screen.getByRole("button", { name: /source —/ }));
  expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
  expect(screen.queryByText(/Importada localmente/)).toBeNull();
  if (status === "needs_correction") {
    await screen.findByText(new RegExp(issue.action));
    expect(screen.getByText(/ZIP rechazado/)).toBeDefined();
    expect(screen.queryByText(/Trabajo completado/)).toBeNull();
  } else expect(screen.getByRole("button", { name: "Reintentar trabajo" })).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Actualizar importaciones" }));
  await waitFor(() => expect((screen.getByRole("button", { name: "Actualizar importaciones" }) as HTMLButtonElement).disabled).toBe(false));
  expect(writes).toEqual([]);
  first.unmount();
  render(<DatasetImportPanel />);
  await open();
  fireEvent.click(screen.getByRole("button", { name: /source —/ }));
  expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /legacy —/ }));
  expect(screen.getByRole("button", { name: "Confirmar importación local" })).toBeDefined();
  expect(writes).toEqual([]);
  if (status === "committing") {
    fireEvent.click(screen.getByRole("button", { name: /source —/ }));
    fireEvent.click(screen.getByRole("button", { name: "Reintentar trabajo" }));
    await screen.findByText(/Importada localmente: 1 archivo/);
    expect(writes).toEqual([execution.status_url + "/retry"]);
  }
});

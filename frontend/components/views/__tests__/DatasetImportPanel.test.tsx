import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";
import { durableFetch } from "./datasetImportTransport";
import { File } from "node:buffer";
import { webcrypto } from "node:crypto";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function openImport() {
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const dialog = await screen.findByRole("dialog", { name: "Importar dataset" });
  const start = within(dialog).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  return dialog;
}

const counts = { file_count: 0, class_count: 1, error_count: 0, warning_count: 0, total_size_bytes: 0, synced_count: 0 };
const collectionResponse = (key: string, items: unknown[], snapshot: string) =>
  Response.json({ [key]: items, total: items.length, next_cursor: null, snapshot });
function reviewResponse(input: string, snapshot: string, files: unknown[] = [], issues: unknown[] = []) {
  if (input.endsWith("/files")) return collectionResponse("files", files, snapshot);
  if (input.endsWith("/classes")) return collectionResponse("classes", ["birds"], snapshot);
  if (input.endsWith("/issues")) return collectionResponse("issues", issues, snapshot);
  return null;
}

describe("private dataset import", () => {
  it("recovers the historical root without an editable field and preserves local success on cloud error", async () => {
    const base = "/api/ingestion/imports";
    const writes: { path: string; body: unknown }[] = [];
    const preview = { root: "wrap", ...counts };
    const ready = { id: "independent", status: "ready", sync_status: "pending", dataset_id: null,
      added_count: 0, preview_token: "q".repeat(64), preview, error: null };
    let snapshot = ready.preview_token;
    vi.stubGlobal("fetch", durableFetch(async (input: string, options?: RequestInit) => {
      const page = reviewResponse(input, snapshot);
      if (page) return page;
      const url = new URL(input, "http://synthetic.test").pathname;
      if (url === base + "/access") return Response.json({ development_mode: true });
      expect(new Headers(options?.headers).get("Authorization")).toBeNull();
      if (url === base + "/limits") return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
        entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
        validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
      if (url === base + "/datasets") return collectionResponse("datasets", [], "catalog");
      if (url === base) return collectionResponse("imports", [ready], "history");
      const body: unknown = JSON.parse(String(options?.body));
      writes.push({ path: url, body });
      if (url.endsWith("/preview")) {
        snapshot = "r".repeat(64);
        expect(body).toMatchObject({ root: "wrap" });
        return Response.json({ ...ready, preview: { ...preview, root: "wrap" }, preview_token: "r".repeat(64) });
      }
      if (url.endsWith("/confirm")) {
        expect(body).toMatchObject({ preview_token: "r".repeat(64) });
        return Response.json({ ...ready, status: "imported", dataset_id: "private", added_count: 1 });
      }
      if (url.endsWith("/sync")) return Response.json({ ...ready, status: "imported", dataset_id: "private",
        added_count: 1, sync_status: "error", error: "sync_failed_or_integrity_conflict" });
      throw new Error("Unexpected request: " + url);
    }));
    render(<DatasetImportPanel />);
    expect(writes).toEqual([]);
    await openImport();
    fireEvent.click(await screen.findByRole("button", { name: /independent —/ }));
    expect(screen.queryByLabelText("Raíz de clases dentro del ZIP")).toBeNull();
    const confirmButton = screen.getByRole("button", { name: "Confirmar importación local" }) as HTMLButtonElement;
    expect(confirmButton.disabled).toBe(false);
    expect(writes).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Confirmar importación local" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar importación local" }));
    await screen.findByText(/Importada localmente: 1 archivo/);
    expect(writes.map(w => w.path)).toEqual([base + "/independent/preview", base + "/independent/confirm"]);
    fireEvent.click(screen.getByRole("button", { name: "Sincronizar con GCS" }));
    await screen.findByText("Sincronización: error");
    expect(screen.getByText(/Importada localmente: 1 archivo/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Reanudar sincronización con GCS" })).toBeDefined();
    expect(writes.filter(w => w.path.endsWith("/sync"))).toHaveLength(1);
  });

  it("explains format in a modal without an embedded login before exposing a file picker", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ development_mode: false })));
    render(<DatasetImportPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    expect(screen.getByText(/Una carpeta por clase/)).toBeDefined();
    expect(screen.getByText(/sin carpeta contenedora ni subcarpetas/)).toBeDefined();
    expect(screen.getByText("chucao/audio_01.wav colilarga/audio_01.wav")).toBeDefined();
    expect(screen.getByText(/no inicia preparación ni entrenamiento/)).toBeDefined();
    expect(screen.getByText(/al menos un WAV válido y único/i)).toBeDefined();
    expect(screen.queryByLabelText("Archivo ZIP")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Importar dataset" })).toBeDefined();
    expect(screen.queryByLabelText("Correo")).toBeNull();
    expect(screen.queryByLabelText("Contraseña")).toBeNull();
    expect(screen.queryByRole("button", { name: /Iniciar sesión|Cerrar sesión/ })).toBeNull();
    await screen.findByText(/La vista de acceso está pendiente/);
    expect((within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("imports automatically without login in local mode and only syncs on explicit action", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const calls: string[] = [];
    const files = [{ id: "audio", relative_path: "birds/a.wav", original_path: "birds/a.wav", class_name: "birds",
      sha256: "a".repeat(64), size_bytes: 100, duplicate: false, existing: false }];
    const preview = { auto_import: true, root: "", ...counts, file_count: 1, new_count: 1, duplicate_count: 0, duplicate_collection: false };
    const job = { id: "job1", status: "ready", sync_status: "pending", dataset_id: null, added_count: 0,
      preview_token: "p".repeat(64), preview, error: null };
    vi.stubGlobal("fetch", durableFetch(async (input: string, options?: RequestInit) => {
      calls.push(`${options?.method || "GET"} ${input}`);
      const page = reviewResponse(input, job.preview_token, files);
      if (page) return page;
      if (input.endsWith("/access")) return Response.json({ development_mode: true });
      expect(new Headers(options?.headers).get("Authorization")).toBeNull();
      if (input.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096, entries: 10,
        depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
      if (input.endsWith("/datasets")) return collectionResponse("datasets", [{
        id: "existing", name: "Existing birds", file_count: 2, revision: 1,
      }], "catalog");
      if (input.endsWith("/imports") && !options?.method) return collectionResponse("imports", [], "history");
      if (input.endsWith("/imports")) {
        expect(JSON.parse(String(options?.body))).toMatchObject({
          name: "Birds", description: "New collection", target_id: null, layout: "class_folders", auto_import: true,
        });
        return Response.json({ ...job, status: "receiving" });
      }
      if (input.endsWith("/receipt")) return Response.json({ import_id: "job1", name: "birds.zip", size_bytes: 3,
        received_bytes: 0, reserved_bytes: 4099, chunk_bytes: 16 * 1024 ** 2, status: "receiving" });
      if (input.endsWith("/receipt/chunks/0") || input.endsWith("/receipt/finalize")) return Response.json({
        import_id: "job1", name: "birds.zip", size_bytes: 3, received_bytes: 3, reserved_bytes: 4099,
        chunk_bytes: 16 * 1024 ** 2, status: input.endsWith("/finalize") ? "sealed" : "receiving" });
      if (input.endsWith("/job1")) return Response.json({ ...job, status: "validating" });
      if (input.endsWith("/preview")) {
        expect(JSON.parse(String(options?.body))).toMatchObject({ root: "" });
        return Response.json({ ...job, status: "imported", added_count: 1, dataset_id: "d1" });
      }
      if (input.endsWith("/confirm")) return Response.json({ ...job, status: "imported", added_count: 1, dataset_id: "d1" });
      if (input.endsWith("/sync")) return Response.json({ ...job, status: "imported", added_count: 1, sync_status: "synced", dataset_id: "d1" });
      throw new Error(`Unexpected request: ${input}`);
    }));
    render(<DatasetImportPanel />);
    await openImport();
    await screen.findByLabelText("Archivo ZIP");
    expect(screen.queryByLabelText("Destino")).toBeNull();
    expect(screen.queryByLabelText("Raíz de clases dentro del ZIP")).toBeNull();
    expect(screen.queryByRole("option", { name: "Crear dataset privado" })).toBeNull();
    expect(screen.queryByRole("button", { name: /página de destinos/ })).toBeNull();
    expect(screen.queryByLabelText("Dataset para exportar")).toBeNull();
    expect(screen.queryByRole("button", { name: "Descargar versión como ZIP" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Archivo ZIP"), { target: { files: [new File(["zip"], "birds.zip", { type: "application/zip" })] } });
    expect((screen.getByRole("button", { name: "Importar ZIP" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Nombre del dataset"), { target: { value: "Birds" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "New collection" } });
    expect((screen.getByRole("button", { name: "Importar ZIP" }) as HTMLButtonElement).disabled).toBe(false);
    // Closing only hides the window; the selected archive and form survive.
    fireEvent.click(screen.getByTestId("dataset-import-backdrop"));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    expect((screen.getByLabelText("Nombre del dataset") as HTMLInputElement).value).toBe("Birds");
    expect(screen.getByText("Archivo seleccionado: birds.zip")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Importar ZIP" }));
    await screen.findByText("birds/a.wav → birds");
    expect(calls.some(call => call.includes("/sync"))).toBe(false);
    expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
    await screen.findByText(/Importada localmente: 1 archivo/);
    expect(calls.some(call => call.includes("/sync"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Sincronizar con GCS" }));
    await waitFor(() => expect(screen.getByText("Sincronización: sincronizada")).toBeDefined());
  });

  it("keeps confirmation unavailable on validation errors and recovers a pending journal", async () => {
    const issue = { id: "issue", severity: "error", path: "birds/broken.wav", code: "invalid_wav", action: "Sustituye el WAV dañado." };
    const job = { id: "pending", status: "committing", sync_status: "pending", dataset_id: "d1", added_count: 0,
      preview_token: "p".repeat(64), preview: { root: "aves", ...counts }, error: null };
    vi.stubGlobal("fetch", durableFetch(async (input: string, options?: RequestInit) => {
      const page = reviewResponse(input, job.preview_token, [], input.includes("/invalid/") ? [issue] : []);
      if (page) return page;
      if (input.endsWith("/access")) return Response.json({ development_mode: true });
      if (input.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096, entries: 10,
        depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
      if (input.endsWith("/datasets")) return collectionResponse("datasets", [], "catalog");
      if (input.endsWith("/imports")) return collectionResponse("imports", [job,
        { ...job, id: "invalid", status: "needs_correction", preview: { ...job.preview, error_count: 1 } }], "history");
      if (input.endsWith("/confirm")) {
        expect(JSON.parse(String(options?.body))).toMatchObject({ preview_token: job.preview_token });
        return Response.json({ ...job, status: "imported", added_count: 1 });
      }
      throw new Error(`Unexpected: ${input}`);
    }));
    render(<DatasetImportPanel />);
    await openImport();
    fireEvent.click(await screen.findByRole("button", { name: /invalid —/ }));
    expect((await screen.findByRole("alert")).textContent).toContain(issue.action);
    expect(screen.queryByRole("button", { name: "Confirmar importación local" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /pending —/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar importación local" }));
    await screen.findByText(/Importada localmente: 1 archivo/);
  });

  it("closes on backdrop, Escape and close button, not inside clicks, and restores focus", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ development_mode: false })));
    render(<DatasetImportPanel />);
    const trigger = screen.getByRole("button", { name: "Importar dataset" });
    const previousOverflow = document.body.style.overflow;
    for (const close of ["backdrop", "escape", "button"]) {
      trigger.focus();
      fireEvent.click(trigger);
      const dialog = screen.getByRole("dialog", { name: "Importar dataset" });
      const closeButton = within(dialog).getByRole("button", { name: "Cerrar importación" });
      expect(document.activeElement).toBe(closeButton);
      expect(document.body.style.overflow).toBe("hidden");
      expect(dialog.classList.contains("text-xs")).toBe(true);
      fireEvent.click(within(dialog).getByText(/Una carpeta por clase/));
      expect(screen.getByRole("dialog")).toBe(dialog);
      if (close === "backdrop") fireEvent.click(screen.getByTestId("dataset-import-backdrop"));
      if (close === "escape") fireEvent.keyDown(document, { key: "Escape" });
      if (close === "button") fireEvent.click(closeButton);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(trigger);
      expect(document.body.style.overflow).toBe(previousOverflow);
    }
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
  });

  it("uses an existing session supplied by the dedicated access view without a local login", async () => {
    const configured = { received_bytes: 1024, expanded_bytes: 4096, entries: 10, depth: 12, path_bytes: 240,
      audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 };
    vi.stubGlobal("fetch", durableFetch(async (input: string, options?: RequestInit) => {
      expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer supplied-session");
      if (input.endsWith("/access")) return Response.json({ development_mode: false });
      if (input.endsWith("/limits")) return Response.json(configured);
      if (input.endsWith("/datasets")) return collectionResponse("datasets", [], "catalog");
      return collectionResponse("imports", [], "history");
    }));
    render(<DatasetImportPanel sessionToken="supplied-session" />);
    await openImport();
    expect(screen.getByLabelText("Archivo ZIP")).toBeDefined();
    expect(screen.queryByLabelText("Contraseña")).toBeNull();
  });

  it("keeps failure actionable and never exposes an import form when access discovery fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Modo local no permitido" }, { status: 503 })));
    render(<DatasetImportPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    expect((await screen.findByRole("alert")).textContent).toContain("503: Modo local no permitido");
    expect(screen.queryByLabelText("Archivo ZIP")).toBeNull();
    expect(screen.getByRole("button", { name: "Reintentar conexión" })).toBeDefined();
  });

  it("contains keyboard focus and restores background interactivity after closing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ development_mode: false })));
    const { container } = render(<><button>Background action</button><DatasetImportPanel /></>);
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    await screen.findByText(/La vista de acceso está pendiente/);
    const close = screen.getByRole("button", { name: "Cerrar importación" });
    expect(container.hasAttribute("inert")).toBe(true);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    screen.getByRole("button", { name: "Background action" }).focus();
    expect(document.activeElement).toBe(close);
    fireEvent.click(close);
    expect(container.hasAttribute("inert")).toBe(false);
    screen.getByRole("button", { name: "Background action" }).focus();
    expect(document.activeElement?.textContent).toBe("Background action");
  });

  it("continues an in-flight confirmation while hidden without sending cancel or a duplicate write", async () => {
    const job = { id: "working", status: "ready", sync_status: "pending", dataset_id: null, added_count: 0,
      preview_token: "p".repeat(64), preview: { root: "", ...counts }, error: null };
    const writes: string[] = [];
    let complete!: (response: Response) => void;
    vi.stubGlobal("fetch", durableFetch(async (input: string, options?: RequestInit) => {
      const page = reviewResponse(input, job.preview_token);
      if (page) return page;
      if (options?.method === "POST") {
        writes.push(input);
        return new Promise<Response>(resolve => { complete = resolve; });
      }
      if (input.endsWith("/access")) return Response.json({ development_mode: true });
      if (input.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096, entries: 10,
        depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
      if (input.endsWith("/datasets")) return collectionResponse("datasets", [], "catalog");
      return collectionResponse("imports", [job], "history");
    }));
    render(<DatasetImportPanel />);
    await openImport();
    fireEvent.click(screen.getByRole("button", { name: /working —/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar importación local" }));
    expect(screen.getByText("Admitiendo confirmación local…")).toBeDefined();
    fireEvent.click(screen.getByTestId("dataset-import-backdrop"));
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => { complete(Response.json({ ...job, status: "imported", dataset_id: "local", added_count: 1 })); });
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    expect(screen.getByText(/Importada localmente: 1 archivo/)).toBeDefined();
    expect(writes).toHaveLength(1);
    expect(writes[0].endsWith("/working/confirm")).toBe(true);
  });
});

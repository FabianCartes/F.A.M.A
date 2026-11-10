import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetExportDialog from "@/components/ingestion/DatasetExportDialog";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("paginates the catalogue, retries a later page and exports its dataset without losing the hidden job", async () => {
  const base = "/api/ingestion/imports";
  const cursor = "next/page+=";
  const writes: string[] = [];
  let failNext = true;
  const job = { id: "later-job", dataset_id: "later", revision: 3, status: "queued", progress: 0,
    size_bytes: null, sha256: null, expires_at: 9999999999, error: null };
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(input, "http://synthetic.test");
    if (options?.method === "POST") {
      writes.push(url.pathname);
      expect(url.pathname).toBe(`${base}/datasets/later/revisions/3/exports`);
      return Response.json(job);
    }
    if (url.pathname.endsWith("/access")) return Response.json({ development_mode: true });
    if (url.pathname === `${base}/datasets`) {
      const next = url.searchParams.get("cursor");
      if (next) {
        expect(next).toBe(cursor);
        if (failNext) { failNext = false; return Response.json({ detail: "Página no disponible" }, { status: 503 }); }
      }
      return Response.json({ datasets: [next ? { id: "later", name: "Later birds", file_count: 1, revision: 3 }
        : { id: "first", name: "First birds", file_count: 1, revision: 1 }], total: 2,
        next_cursor: next ? null : cursor, snapshot: "catalog" });
    }
    if (url.pathname.endsWith("/exports/later-job")) return Response.json({ ...job, status: "succeeded", progress: 100 });
    throw new Error(`Unexpected request: ${input}`);
  }));
  render(<DatasetExportDialog />);
  const trigger = screen.getByRole("button", { name: "Descargar versión como ZIP" });
  fireEvent.click(trigger);
  await screen.findByRole("option", { name: "First birds" });
  fireEvent.click(screen.getByRole("button", { name: "Siguiente página de datasets" }));
  expect((await screen.findByRole("alert")).textContent).toContain("503: Página no disponible");
  fireEvent.click(screen.getByRole("button", { name: "Reintentar conexión" }));
  await screen.findByRole("option", { name: "Later birds" });
  expect(screen.queryByRole("option", { name: "First birds" })).toBeNull();
  expect((screen.getByRole("button", { name: "Siguiente página de datasets" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Dataset para exportar"), { target: { value: "later" } });
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Descargar versión como ZIP" }));
  await screen.findByText(/Exportación completa/);
  fireEvent.click(screen.getByRole("button", { name: "Cerrar exportación" }));
  fireEvent.click(trigger);
  await screen.findByText(/Exportación completa/);
  expect((screen.getByLabelText("Dataset para exportar") as HTMLSelectElement).value).toBe("later");
  expect(writes).toEqual([`${base}/datasets/later/revisions/3/exports`]);
});

it("offers a native direct download only after export completion, and renews without fetching ZIP bytes", async () => {
  const base = "/api/ingestion/imports";
  const job = { id: "export-id", dataset_id: "dataset", revision: 2, status: "queued", progress: 0,
    status_url: `${base}/exports/export-id`, size_bytes: null, sha256: null, expires_at: 9999999999, error: null };
  const native = "https://downloads.example.test/api/ingestion/imports/exports/export-id/download?ticket=opaque";
  const calls: string[] = [];
  let settle!: (response: Response) => void;
  const page = (key: string, rows: unknown[]) => Response.json({ [key]: rows, total: rows.length, next_cursor: null, snapshot: "catalog" });
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "https://ui.example.test").pathname;
    calls.push(path);
    expect(input).not.toContain("downloads.example.test");
    if (path.endsWith("/access")) return Response.json({ development_mode: false });
    if (path.endsWith("/datasets")) return page("datasets", [{ id: "dataset", name: "Birds", file_count: 1, revision: 2 }]);
    if (path === `${base}/datasets/dataset/exports`) return Response.json({ exports: [] });
    if (path.endsWith("/revisions/2/exports")) {
      expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer synthetic-session");
      return Response.json(job, { status: 202 });
    }
    if (path === job.status_url) return new Promise<Response>(resolve => { settle = resolve; });
    if (path.endsWith("/sessions")) return Response.json({ url: native, expires_at: 9999999999 });
    throw new Error(`Unexpected ${path}`);
  }));
  const blob = vi.fn(() => { throw new Error("Blob is forbidden for exports"); });
  vi.stubGlobal("URL", class extends URL { static createObjectURL = blob; });
  render(<DatasetExportDialog sessionToken="synthetic-session" />);
  expect(calls).toEqual([]);
  const trigger = screen.getByRole("button", { name: "Descargar versión como ZIP" });
  fireEvent.click(trigger);
  const dialog = within(screen.getByRole("dialog", { name: "Descargar versión como ZIP" }));
  await screen.findByLabelText("Dataset para exportar");
  expect(screen.queryByLabelText("Archivo ZIP")).toBeNull();
  fireEvent.change(screen.getByLabelText("Dataset para exportar"), { target: { value: "dataset" } });
  fireEvent.click(dialog.getByRole("button", { name: "Descargar versión como ZIP" }));
  await screen.findByText(/Exportación admitida/);
  expect(screen.queryByRole("link", { name: "Descargar ZIP exportado" })).toBeNull();
  await waitFor(() => expect(settle).toBeDefined());
  fireEvent.click(dialog.getByRole("button", { name: "Cerrar exportación" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await act(async () => settle(Response.json({ ...job, status: "succeeded", progress: 100, size_bytes: 123, sha256: "a".repeat(64) })));
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("button", { name: "Preparar descarga" }));
  const link = await screen.findByRole("link", { name: "Descargar ZIP exportado" });
  expect(link.getAttribute("href")).toBe(native);
  expect(link.getAttribute("referrerpolicy")).toBe("no-referrer");
  fireEvent.click(screen.getByRole("button", { name: "Renovar descarga" }));
  await waitFor(() => expect(calls.filter(path => path.endsWith("/sessions"))).toHaveLength(2));
  expect(blob).not.toHaveBeenCalled();
  expect(calls.some(path => path.endsWith("/limits") || path === base)).toBe(false);
});

it("supports modal keyboard focus and close controls without admitting an export", async () => {
  const fetch = vi.fn(async (input: string, options?: RequestInit) => {
    expect(options?.method).toBeUndefined();
    return input.endsWith("/access") ? Response.json({ development_mode: true })
      : Response.json({ datasets: [], total: 0, next_cursor: null, snapshot: "catalog" });
  });
  vi.stubGlobal("fetch", fetch);
  const { unmount } = render(<DatasetExportDialog />);
  const trigger = screen.getByRole("button", { name: "Descargar versión como ZIP" });
  const originalOverflow = document.body.style.overflow;
  for (const method of ["escape", "backdrop", "button"]) {
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Descargar versión como ZIP" });
    const close = within(dialog).getByRole("button", { name: "Cerrar exportación" });
    expect(document.activeElement).toBe(close);
    expect(document.body.style.overflow).toBe("hidden");
    await screen.findByLabelText("Dataset para exportar");
    fireEvent.click(within(dialog).getByText(/Descarga una versión sincronizada/));
    expect(screen.getByRole("dialog")).toBe(dialog);
    const last = within(dialog).getByRole("button", { name: "Recuperar exportaciones" });
    // With no dataset selected, the last enabled control is the revision input.
    expect((last as HTMLButtonElement).disabled).toBe(true);
    const revision = within(dialog).getByLabelText("Revisión para exportar");
    revision.focus();
    fireEvent.keyDown(revision, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(revision);
    if (method === "escape") fireEvent.keyDown(dialog, { key: "Escape" });
    if (method === "backdrop") fireEvent.click(screen.getByTestId("dataset-export-backdrop"));
    if (method === "button") fireEvent.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe(originalOverflow);
    expect(trigger.closest("[inert]")).toBeNull();
  }
  expect(fetch.mock.calls.every(([, options]) => !(options as RequestInit | undefined)?.method)).toBe(true);
  fireEvent.click(trigger);
  unmount();
  expect(document.body.style.overflow).toBe(originalOverflow);
});

it("keeps session requirements and retries catalogue failures without starting imports", async () => {
  const fetch = vi.fn(async () => Response.json({ development_mode: false }));
  vi.stubGlobal("fetch", fetch);
  const { unmount } = render(<DatasetExportDialog />);
  fireEvent.click(screen.getByRole("button", { name: "Descargar versión como ZIP" }));
  await screen.findByText(/Inicia sesión en F.A.M.A./);
  expect(screen.queryByLabelText("Dataset para exportar")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  unmount();

  let failed = false;
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    if (input.endsWith("/access")) return Response.json({ development_mode: true });
    if (!failed) { failed = true; return Response.json({ detail: "Catálogo no disponible" }, { status: 503 }); }
    return Response.json({ datasets: [], total: 0, next_cursor: null, snapshot: "catalog" });
  }));
  render(<DatasetExportDialog />);
  fireEvent.click(screen.getByRole("button", { name: "Descargar versión como ZIP" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Reintentar conexión" }));
  await screen.findByLabelText("Dataset para exportar");
  expect(screen.queryByRole("alert")).toBeNull();
});

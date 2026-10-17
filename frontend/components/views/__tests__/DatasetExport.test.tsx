import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path.endsWith("/datasets")) return page("datasets", [{ id: "dataset", name: "Birds", file_count: 1, revision: 2 }]);
    if (path === base) return page("imports", []);
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
  render(<DatasetImportPanel sessionToken="synthetic-session" />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const start = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" });
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.change(screen.getByLabelText("Dataset para exportar"), { target: { value: "dataset" } });
  fireEvent.click(screen.getByRole("button", { name: "Exportar revisión" }));
  await screen.findByText(/Exportación admitida/);
  expect(screen.queryByRole("link", { name: "Descargar ZIP exportado" })).toBeNull();
  await waitFor(() => expect(settle).toBeDefined());
  await act(async () => settle(Response.json({ ...job, status: "succeeded", progress: 100, size_bytes: 123, sha256: "a".repeat(64) })));
  fireEvent.click(await screen.findByRole("button", { name: "Preparar descarga" }));
  const link = await screen.findByRole("link", { name: "Descargar ZIP exportado" });
  expect(link.getAttribute("href")).toBe(native);
  expect(link.getAttribute("referrerpolicy")).toBe("no-referrer");
  fireEvent.click(screen.getByRole("button", { name: "Renovar descarga" }));
  await waitFor(() => expect(calls.filter(path => path.endsWith("/sessions"))).toHaveLength(2));
  expect(blob).not.toHaveBeenCalled();
});

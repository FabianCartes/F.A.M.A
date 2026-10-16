import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("replaces review pages instead of accumulating rows and preserves the reviewed token", async () => {
  const base = "/api/ingestion/imports";
  const job = { id: "paged", status: "ready", sync_status: "pending", dataset_id: null, added_count: 0,
    preview_token: "a".repeat(64), error: null, preview: { root: "", file_count: 51, class_count: 1,
      error_count: 0, warning_count: 0, total_size_bytes: 5100, synced_count: 0, new_count: 51 } };
  const files = Array.from({ length: 50 }, (_, i) => ({ id: String(i), original_path: `birds/${i}.wav`,
    relative_path: `birds/${i}.wav`, class_name: "birds", sha256: String(i), size_bytes: 100, duplicate: false }));
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(input, "http://synthetic.test");
    const path = url.pathname;
    const page = (key: string, items: unknown[], total = items.length, next_cursor: string | null = null) =>
      Response.json({ [key]: items, total, next_cursor, snapshot: job.preview_token });
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096, entries: 100,
      depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60,
      free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path === base + "/datasets") return page("datasets", []);
    if (path === base) return page("imports", [job]);
    if (path.endsWith("/classes")) return page("classes", ["birds"]);
    if (path.endsWith("/issues")) return page("issues", []);
    if (path.endsWith("/files")) return url.searchParams.has("cursor")
      ? page("files", [{ ...files[0], id: "50", original_path: "birds/final.wav" }], 51)
      : page("files", files, 51, "second");
    if (path.endsWith("/confirm")) {
      expect(JSON.parse(String(options?.body))).toEqual({ preview_token: job.preview_token });
      return Response.json({ ...job, status: "imported", added_count: 51 });
    }
    throw new Error(`Unexpected ${input}`);
  }));
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const start = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole("button", { name: /paged —/ }));
  await screen.findByText("birds/0.wav → birds");
  fireEvent.click(screen.getByRole("button", { name: "Siguiente página de archivos" }));
  await screen.findByText(/birds\/final.wav/);
  expect(screen.queryByText("birds/0.wav → birds")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Anterior página de archivos" }));
  await screen.findByText("birds/0.wav → birds");
  expect(screen.queryByText(/birds\/final.wav/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Confirmar importación local" }));
  await screen.findByText(/Importada localmente: 51/);
});

it("ignores a delayed page from a previous job and keeps confirmation explicit", async () => {
  const base = "/api/ingestion/imports";
  const job = (id: string) => ({ id, status: "ready", sync_status: "pending", dataset_id: null, added_count: 0,
    preview_token: id.repeat(64), error: null, preview: { root: "", file_count: 1, class_count: 1,
      error_count: 0, warning_count: 0, total_size_bytes: 100, synced_count: 0, new_count: 1 } });
  const jobs = [job("a"), job("b")];
  let resolveOld!: (response: Response) => void;
  const old = new Promise<Response>(resolve => { resolveOld = resolve; });
  const file = (id: string) => ({ id, original_path: `birds/${id}.wav`, relative_path: `birds/${id}.wav`,
    class_name: "birds", sha256: id, size_bytes: 100, duplicate: false });
  const page = (key: string, items: unknown[], snapshot: string | null = null) =>
    Response.json({ [key]: items, total: items.length, next_cursor: null, snapshot });
  const fetcher = vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096, entries: 100,
      depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600, validation_seconds: 60,
      free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path === base) return page("imports", jobs);
    if (path === base + "/datasets") return page("datasets", []);
    const current = path.includes("/a/") ? jobs[0] : jobs[1];
    if (path.endsWith("/files")) return current.id === "a" ? old : page("files", [file("current")], current.preview_token);
    if (path.endsWith("/classes")) return page("classes", ["birds"], current.preview_token);
    if (path.endsWith("/issues")) return page("issues", [], current.preview_token);
    if (path.endsWith("/confirm")) {
      expect(JSON.parse(String(options?.body))).toEqual({ preview_token: jobs[1].preview_token });
      return Response.json({ ...jobs[1], status: "imported", added_count: 1 });
    }
    throw new Error(`Unexpected ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<DatasetImportPanel sessionToken="synthetic" />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const start = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole("button", { name: /a —/ }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith("/a/files"))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: /b —/ }));
  await screen.findByText("birds/current.wav → birds");
  await act(async () => { resolveOld(page("files", [file("old")], jobs[0].preview_token)); await old; });
  await waitFor(() => expect(screen.queryByText("birds/old.wav → birds")).toBeNull());
  expect(fetcher.mock.calls.some(([url]) => url.endsWith("/sync") || url.endsWith("/confirm"))).toBe(false);
  fireEvent.change(screen.getByRole("textbox", { name: "Raíz de clases dentro del ZIP" }), { target: { value: "changed" } });
  expect((screen.getByRole("button", { name: "Confirmar importación local" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "Raíz de clases dentro del ZIP" }), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Confirmar importación local" }));
  await screen.findByText(/Importada localmente: 1/);
  expect(fetcher.mock.calls.some(([url]) => url.endsWith("/sync"))).toBe(false);
});

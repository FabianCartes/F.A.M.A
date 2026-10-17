import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("restores a durable job after remount and never treats admission as final success", async () => {
  const base = "/api/ingestion/imports";
  const execution = { id: "execution", import_id: "source", kind: "confirm", status: "running",
    stage: "verifying", progress: 20, result: {}, error: null, status_url: `${base}/source/jobs/execution` };
  const source = { id: "source", status: "ready", sync_status: "pending", dataset_id: null, added_count: 0,
    preview_token: "a".repeat(64), error: null, execution,
    preview: { root: "", file_count: 1, class_count: 1, error_count: 0, warning_count: 0,
      total_size_bytes: 100, synced_count: 0, new_count: 1 } };
  const posts: string[] = [];
  let resolveStatus!: (value: Response) => void;
  const page = (key: string, items: unknown[]) => Response.json({ [key]: items, total: items.length,
    next_cursor: null, snapshot: source.preview_token });
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    if (options?.method === "POST") posts.push(path);
    if (path.endsWith("/access")) return Response.json({ development_mode: true });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path === base) return page("imports", [source]);
    if (path.endsWith("/datasets")) return page("datasets", []);
    if (path === execution.status_url) return new Promise<Response>(resolve => { resolveStatus = resolve; });
    if (path === base + "/source") return Response.json({ ...source, status: "imported", dataset_id: "dataset",
      added_count: 1, execution: { ...execution, status: "succeeded", stage: "succeeded", progress: 100 } });
    if (path.endsWith("/files")) return page("files", []);
    if (path.endsWith("/classes")) return page("classes", ["birds"]);
    if (path.endsWith("/issues")) return page("issues", []);
    throw new Error(`Unexpected ${path}`);
  }));
  async function recover() {
    fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
    const start = within(screen.getByRole("dialog")).getByRole("button", { name: "Importar dataset" });
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(start);
    fireEvent.click(await screen.findByRole("button", { name: /source —/ }));
    await screen.findByText(/Trabajo en ejecución/);
    expect(screen.queryByText(/Importada localmente/)).toBeNull();
    expect((screen.getByRole("button", { name: "Confirmar importación local" }) as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(resolveStatus).toBeDefined());
  }
  const first = render(<DatasetImportPanel />);
  await recover();
  first.unmount();
  resolveStatus = undefined as unknown as typeof resolveStatus;
  render(<DatasetImportPanel />);
  await recover();
  await act(async () => { resolveStatus(Response.json({ ...execution, status: "succeeded", progress: 100 })); });
  await screen.findByText(/Importada localmente: 1/);
  expect(posts).toEqual([]);
});

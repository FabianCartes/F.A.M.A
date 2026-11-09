import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import RejectedImportReason from "@/components/ingestion/RejectedImportReason";
import type { ImportJob } from "@/lib/api/datasetImports";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const job: ImportJob = { id: "rejected", status: "cancelled", sync_status: "pending", dataset_id: null, added_count: 0, error: "validation_failed", preview_token: "snapshot", preview: { file_count: 5, class_count: 2, error_count: 2, warning_count: 1, total_size_bytes: 100, synced_count: 0 } };
const issue = (action: string, severity = "error") => ({ id: action, code: "technical_code", path: "private/path.wav", severity, action });
const page = (issues: unknown[], next_cursor: string | null = null, snapshot = "snapshot") => Response.json({ issues, next_cursor, snapshot, total: 3 });

it("shows all human error reasons across pages, without warnings or technical pagination", async () => {
  const fetch = vi.fn(async (url: string) => url.includes("cursor=") ? page([issue("Corrige el audio dañado."), issue("Primera razón.")]) : page([issue("Primera razón."), issue("Advertencia oculta", "warning")], "next"));
  vi.stubGlobal("fetch", fetch);
  render(<RejectedImportReason job={job} token="synthetic" />);
  await screen.findByText("Corrige el audio dañado.");
  expect(screen.getAllByText("Primera razón.")).toHaveLength(1);
  expect(screen.queryByText(/Advertencia oculta|technical_code|private\/path/)).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each(["transport", "snapshot", "loop"])("offers a plain retry for %s failures", async failure => {
  let retry = false;
  const fetch = vi.fn(async () => {
    if (retry) return page([issue("Corrige el audio dañado.")]);
    if (failure === "transport") return Response.json({}, { status: 503 });
    if (failure === "snapshot") return page([issue("No mostrar")], null, "changed");
    return page([issue("No mostrar")], "repeat");
  });
  vi.stubGlobal("fetch", fetch);
  render(<RejectedImportReason job={job} token="synthetic" />);
  await screen.findByRole("alert");
  expect(screen.queryByText("No mostrar")).toBeNull();
  expect(fetch.mock.calls.length).toBeLessThanOrEqual(2);
  retry = true;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await screen.findByText("Corrige el audio dañado.");
});

it("does not invent a reason when only warnings are available", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => page([issue("Solo advertencia", "warning")])));
  render(<RejectedImportReason job={job} token="synthetic" />);
  await screen.findByText(/No hay una razón del rechazo disponible/);
  expect(screen.queryByText("Solo advertencia")).toBeNull();
});

it("aborts obsolete requests without displaying another identity's reasons", async () => {
  let finish!: (response: Response) => void;
  let signal: AbortSignal | null | undefined;
  vi.stubGlobal("fetch", vi.fn((_: string, options: RequestInit) => {
    const authorization = new Headers(options.headers).get("Authorization");
    if (authorization === "Bearer old") { signal = options.signal; return new Promise<Response>(resolve => { finish = resolve; }); }
    return Promise.resolve(page([issue("Razón de la identidad actual.")]));
  }));
  const view = render(<RejectedImportReason key="old" job={job} token="old" />);
  view.rerender(<RejectedImportReason key="new" job={job} token="new" />);
  await screen.findByText("Razón de la identidad actual.");
  finish(page([issue("Razón obsoleta.")], "another"));
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("Razón obsoleta.")).toBeNull();
});

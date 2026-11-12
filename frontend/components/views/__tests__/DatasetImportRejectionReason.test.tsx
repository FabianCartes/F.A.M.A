import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import RejectedImportReason from "@/components/ingestion/RejectedImportReason";
import type { ImportJob } from "@/lib/api/datasetImports";
import SessionBoundary from "@/components/auth/SessionBoundary";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const job: ImportJob = { id: "rejected", status: "cancelled", dataset_id: null, added_count: 0, error: "validation_failed", preview_token: "snapshot", preview: { file_count: 5, class_count: 2, error_count: 2, warning_count: 1, total_size_bytes: 100 } };
const issue = (action: string, severity = "error") => ({ id: action, code: "technical_code", path: "private/path.wav", severity, action });
const page = (issues: unknown[], next_cursor: string | null = null, snapshot = "snapshot") => Response.json({ issues, next_cursor, snapshot, total: 3 });

it("shows all human error reasons across pages, without warnings or technical pagination", async () => {
  const fetch = vi.fn(async (url: string) => url.includes("cursor=") ? page([issue("Corrige el audio dañado."), issue("Primera razón.")]) : page([issue("Primera razón."), issue("Advertencia oculta", "warning")], "next"));
  vi.stubGlobal("fetch", fetch);
  render(<RejectedImportReason job={job} />);
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
  render(<RejectedImportReason job={job} />);
  await screen.findByRole("alert");
  expect(screen.queryByText("No mostrar")).toBeNull();
  expect(fetch.mock.calls.length).toBeLessThanOrEqual(2);
  retry = true;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await screen.findByText("Corrige el audio dañado.");
});

it("does not invent a reason when only warnings are available", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => page([issue("Solo advertencia", "warning")])));
  render(<RejectedImportReason job={job} />);
  await screen.findByText(/No hay una razón del rechazo disponible/);
  expect(screen.queryByText("Solo advertencia")).toBeNull();
});

it("aborts obsolete requests without displaying another identity's reasons", async () => {
  let finish!: (response: Response) => void;
  let signal: AbortSignal | null | undefined;
  let owner = 1;
  vi.stubGlobal("fetch", vi.fn((url: string, options: RequestInit) => {
    expect(new Headers(options.headers).has("Authorization")).toBe(false);
    expect(options.credentials).toBe("same-origin");
    if (url.endsWith("/auth/me")) return Promise.resolve(Response.json({ id: owner, nombre_completo: "Propietario", email: "owner@example.test", rol: "investigador", activo: true }));
    if (owner === 1) { signal = options.signal; return new Promise<Response>(resolve => { finish = resolve; }); }
    return Promise.resolve(page([issue("Razón de la identidad actual.")]));
  }));
  render(<SessionBoundary><RejectedImportReason job={job} /></SessionBoundary>);
  await screen.findByText("Consultando la razón del rechazo…");
  // Loading can render before the effect starts the request we intend to abort.
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  expect(signal?.aborted).toBe(false);
  owner = 2;
  await act(async () => { fireEvent.focus(window); });
  await screen.findByText("Razón de la identidad actual.");
  await act(async () => { finish(page([issue("Razón obsoleta.")], "another")); });
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("Razón obsoleta.")).toBeNull();
});

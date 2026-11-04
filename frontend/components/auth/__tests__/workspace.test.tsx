import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import SessionBoundary, { useOptionalWebSession } from "../SessionBoundary";
import { importRequest } from "@/lib/api/datasetImports";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
const user = { id: 1, email: "one@example.test", nombre_completo: "Owner one", rol: "investigador", activo: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function PrivateState() {
  const owner = useOptionalWebSession();
  const [text, setText] = useState("");
  return <><p>Legacy stays available</p>{owner && <label>Private draft<input aria-label="Private draft" value={text} onChange={event => setText(event.target.value)} /></label>}</>;
}

it("clears private state on imported HTTP 401 without blocking legacy", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => path.endsWith("/me") ? Response.json(user) : Response.json({}, { status: 401 })));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  fireEvent.change(screen.getByLabelText("Private draft"), { target: { value: "private cached data" } });
  await act(async () => { await importRequest("", "/api/ingestion/imports/datasets").catch(() => undefined); });
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  expect(screen.getByText("Legacy stays available")).toBeDefined();
  expect(screen.getByRole("link", { name: "Iniciar sesión" })).toBeDefined();
});

it("clears a previous user's draft when the cookie identity changes on focus", async () => {
  let identity = user;
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(identity)));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  fireEvent.change(screen.getByLabelText("Private draft"), { target: { value: "owner one private draft" } });
  identity = { ...user, id: 2, nombre_completo: "Owner two" };
  fireEvent.focus(window);
  await screen.findByText("Owner two");
  expect((screen.getByLabelText("Private draft") as HTMLInputElement).value).toBe("");
});

it("keeps private state closed when server logout fails and allows a confirmed retry", async () => {
  let revoked = false;
  let retry = false;
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.endsWith("/logout")) {
      if (!retry) return Response.json({}, { status: 503 });
      revoked = true;
      return new Response(null, { status: 204 });
    }
    return revoked ? Response.json({}, { status: 401 }) : Response.json(user);
  }));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  fireEvent.focus(window);
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  retry = true;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar cierre de sesión" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(revoked).toBe(true);
});


it("ignores a stale unauthorized response after confirming a different cookie identity", async () => {
  let identity = user;
  let rejectOld: (response: Response) => void = () => undefined;
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.endsWith("/me")) return Response.json(identity);
    return new Promise<Response>(resolve => { rejectOld = resolve; });
  }));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  const oldRequest = importRequest("", "/api/ingestion/imports/datasets").catch(() => undefined);
  identity = { ...user, id: 2, nombre_completo: "New confirmed identity" };
  fireEvent.focus(window);
  await screen.findByText(identity.nombre_completo);
  await act(async () => { rejectOld(Response.json({}, { status: 401 })); await oldRequest; });
  expect(screen.getByText(identity.nombre_completo)).toBeDefined();
  expect(screen.getByLabelText("Private draft")).toBeDefined();
});

it("closes private state when imported training polling reports unauthorized", async () => {
  const { getProgress } = await import("@/lib/api/trainingApi");
  vi.stubGlobal("fetch", vi.fn(async (path: string) => path.endsWith("/me") ? Response.json(user) : Response.json({}, { status: 401 })));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  await act(async () => { await getProgress().catch(() => undefined); });
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  expect(screen.getByText("Legacy stays available")).toBeDefined();
});

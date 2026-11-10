import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import SessionBoundary, { useOptionalWebSession } from "../SessionBoundary";
import { importRequest } from "@/lib/api/datasetImports";
import SidebarSession from "@/components/SidebarSession";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
const user = { id: 1, email: "one@example.test", nombre_completo: "Owner one", rol: "investigador", activo: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

function PrivateState() {
  const owner = useOptionalWebSession();
  const [text, setText] = useState("");
  return <><SidebarSession isCollapsed={false} onToggleCollapsed={() => {}} /><p>Workspace content</p>{owner && <label>Private draft<input aria-label="Private draft" value={text} onChange={event => setText(event.target.value)} /></label>}</>;
}

it("presents a single logout control inside the existing sidebar session", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(user)));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  const sidebarSession = await screen.findByRole("region", { name: "Sesión actual" });
  expect(within(sidebarSession).getByText(user.nombre_completo)).toBeDefined();
  expect(within(sidebarSession).getByRole("button", { name: "Cerrar sesión" })).toBeDefined();
  expect(screen.getAllByRole("button", { name: "Cerrar sesión" })).toHaveLength(1);
});

it("keeps logout pending despite a late private 401, then retains recovery on failure", async () => {
  let finishPrivate!: (response: Response) => void;
  let finishLogout!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.endsWith("/me")) return Response.json(user);
    return new Promise<Response>(resolve => {
      if (path.endsWith("/logout")) finishLogout = resolve; else finishPrivate = resolve;
    });
  }));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  const pending = importRequest("/api/ingestion/imports/datasets").catch(() => undefined);
  fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  await act(async () => { finishPrivate(Response.json({}, { status: 401 })); await pending; });
  expect(screen.getByRole("status").textContent).toBe("Cerrando sesión…");
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(navigation.replace).not.toHaveBeenCalled();
  await act(async () => { finishLogout(Response.json({}, { status: 503 })); });
  expect(screen.getByRole("button", { name: "Reintentar cierre de sesión" })).toBeDefined();
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(navigation.replace).not.toHaveBeenCalled();
});

it("hides the workspace before redirecting on imported HTTP 401", async () => {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => path.endsWith("/me") ? Response.json(user) : Response.json({}, { status: 401 })));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  fireEvent.change(screen.getByLabelText("Private draft"), { target: { value: "private cached data" } });
  await act(async () => { await importRequest("/api/ingestion/imports/datasets").catch(() => undefined); });
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(navigation.replace).toHaveBeenCalledWith("/login");
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

it.each(["http", "network"])("keeps a failed %s session check on the access surface until a successful retry", async (failure) => {
  let healthy = false;
  vi.stubGlobal("fetch", vi.fn(async () => {
    if (healthy) return Response.json(user);
    if (failure === "network") throw new TypeError("Synthetic network failure");
    return Response.json({}, { status: 503 });
  }));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(screen.getByRole("region", { name: "Acceso a F.A.M.A." })).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
  expect(screen.queryByText(/legacy/i)).toBeNull();
  healthy = true;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar comprobación" }));
  await screen.findByText(user.nombre_completo);
  expect(screen.getByText("Workspace content")).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
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
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(navigation.replace).not.toHaveBeenCalled();
  expect(screen.getByRole("region", { name: "Acceso a F.A.M.A." })).toBeDefined();
  fireEvent.focus(window);
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  retry = true;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar cierre de sesión" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(revoked).toBe(true);
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
});


it("preserves failed logout recovery when a pending private request later returns 401", async () => {
  let finishPrivate!: (response: Response) => void;
  let retry = false;
  let revoked = false;
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path.endsWith("/logout")) {
      if (!retry) return Response.json({}, { status: 503 });
      revoked = true;
      return new Response(null, { status: 204 });
    }
    if (path.endsWith("/me")) return revoked ? Response.json({}, { status: 401 }) : Response.json(user);
    return new Promise<Response>(resolve => { finishPrivate = resolve; });
  }));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  const pending = importRequest("/api/ingestion/imports/datasets").catch(() => undefined);
  fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  const warning = (await screen.findByRole("alert")).textContent;
  await act(async () => { finishPrivate(Response.json({}, { status: 401 })); await pending; });
  expect(screen.getByRole("alert").textContent).toBe(warning);
  expect(screen.getByRole("button", { name: "Reintentar cierre de sesión" })).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
  await act(async () => { fireEvent.focus(window); });
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(screen.getByRole("alert").textContent).toBe(warning);
  expect(navigation.replace).not.toHaveBeenCalled();
  retry = true;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar cierre de sesión" }));
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  expect(revoked).toBe(true);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText("Workspace content")).toBeNull();
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
  const oldRequest = importRequest("/api/ingestion/imports/datasets").catch(() => undefined);
  identity = { ...user, id: 2, nombre_completo: "New confirmed identity" };
  fireEvent.focus(window);
  await screen.findByText(identity.nombre_completo);
  await act(async () => { rejectOld(Response.json({}, { status: 401 })); await oldRequest; });
  expect(screen.getByText(identity.nombre_completo)).toBeDefined();
  expect(screen.getByLabelText("Private draft")).toBeDefined();
});

it("does not restore an invalidated owner from a late session revalidation", async () => {
  let refreshing = false;
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (!path.endsWith("/me")) return Response.json({}, { status: 401 });
    return refreshing ? new Promise<Response>(resolve => { finish = resolve; }) : Response.json(user);
  }));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  refreshing = true;
  await act(async () => { fireEvent.focus(window); });
  await act(async () => { await importRequest("/api/ingestion/imports/datasets").catch(() => undefined); });
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(navigation.replace).toHaveBeenCalledWith("/login");
  await act(async () => { finish(Response.json(user)); });
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(screen.queryByText(user.nombre_completo)).toBeNull();
});

it("closes private state when imported training polling reports unauthorized", async () => {
  const { getProgress } = await import("@/lib/api/trainingApi");
  vi.stubGlobal("fetch", vi.fn(async (path: string) => path.endsWith("/me") ? Response.json(user) : Response.json({}, { status: 401 })));
  render(<SessionBoundary><PrivateState /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  await act(async () => { await getProgress().catch(() => undefined); });
  expect(screen.queryByLabelText("Private draft")).toBeNull();
  expect(screen.queryByText("Workspace content")).toBeNull();
  expect(navigation.replace).toHaveBeenCalledWith("/login");
});

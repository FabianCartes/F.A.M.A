import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ResetPage from "@/app/reset-password/page";

const token = "a".repeat(43);
beforeEach(() => {
  window.history.replaceState(null, "", `/reset-password#token=${token}`);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

it("takes the capability out of the URL and resets without storing it or logging in", async () => {
  const storage = vi.spyOn(Storage.prototype, "setItem");
  const request = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", request);
  const view = render(<ResetPage />);
  fireEvent.change(await screen.findByLabelText("Nueva contraseña"), { target: { value: "RecoveredPassword2026!" } });
  expect(window.location.hash).toBe("");
  expect(view.container.innerHTML).not.toContain(token);
  fireEvent.change(screen.getByLabelText("Confirmar contraseña"), { target: { value: "RecoveredPassword2026!" } });
  fireEvent.click(screen.getByRole("button", { name: "Actualizar contraseña" }));
  expect(await screen.findByText(/Contraseña actualizada/)).toBeDefined();
  expect(request).toHaveBeenCalledTimes(1);
  expect(request.mock.calls[0][0]).toBe("/api/auth/reset-password");
  expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({ token, new_password: "RecoveredPassword2026!" });
  expect(storage).not.toHaveBeenCalled();
});

it("does not send mismatched passwords", async () => {
  const request = vi.fn(); vi.stubGlobal("fetch", request);
  render(<ResetPage />);
  fireEvent.change(await screen.findByLabelText("Nueva contraseña"), { target: { value: "RecoveredPassword2026!" } });
  fireEvent.change(screen.getByLabelText("Confirmar contraseña"), { target: { value: "DifferentPassword2026!" } });
  fireEvent.click(screen.getByRole("button", { name: "Actualizar contraseña" }));
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(request).not.toHaveBeenCalled();
});

it("rejects missing capabilities without inventing a recovery request", async () => {
  window.history.replaceState(null, "", "/reset-password");
  const request = vi.fn(); vi.stubGlobal("fetch", request);
  render(<ResetPage />);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/inválido|incompleto/i));
  expect(request).not.toHaveBeenCalled();
});

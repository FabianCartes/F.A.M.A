import { beforeEach, expect, it, vi } from "vitest";
import { render, waitFor, fireEvent, act } from "@testing-library/react";
import AuthSurface from "../AuthSurface";

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

it("mounts the requested decorative canvas and retains the usable form if WebGL is unavailable", async () => {
  const view = render(<AuthSurface><h1>Acceso</h1><input aria-label="Correo" /></AuthSurface>);
  await waitFor(() => expect(view.container.querySelector("canvas")).not.toBeNull());
  expect(view.container.querySelector("canvas")?.getAttribute("aria-hidden")).toBe("true");
  expect(view.getByLabelText("Correo")).toBeDefined();
});

it("does not request a graphics context when reduced motion is preferred", () => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const view = render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  expect(view.container.querySelector("canvas")).toBeNull();
  expect(HTMLCanvasElement.prototype.getContext).not.toHaveBeenCalled();
});

function graphics(compileFailure = false) {
  const resources: Record<string, object[]> = {};
  const deleted: Record<string, object[]> = {};
  const methods: Record<string, ReturnType<typeof vi.fn>> = {};
  for (const kind of ["Shader", "Program", "Buffer", "VertexArray", "Texture", "Framebuffer"]) {
    resources[kind] = []; deleted[kind] = [];
    methods[`create${kind}`] = vi.fn(() => { const resource = {}; resources[kind].push(resource); return resource; });
    methods[`delete${kind}`] = vi.fn((resource: object) => deleted[kind].push(resource));
  }
  methods.getShaderParameter = vi.fn(() => !compileFailure);
  methods.getProgramParameter = vi.fn(() => true);
  methods.getExtension = vi.fn(() => null);
  const gl = new Proxy(methods, { get(target, property: string) {
    if (/^[A-Z_0-9]+$/.test(property)) return 1;
    return target[property] ?? (target[property] = vi.fn());
  } });
  const frames = new Map<number, FrameRequestCallback>();
  let next = 0;
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => { frames.set(++next, callback); return next; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => frames.delete(id)));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  vi.mocked(HTMLCanvasElement.prototype.getContext).mockImplementation(((kind: string) => kind === "webgl2" ? gl : null) as typeof HTMLCanvasElement.prototype.getContext);
  return { resources, deleted, frames, gl };
}

it("releases allocated graphics resources and pending frames when the access surface unmounts", () => {
  const gpu = graphics();
  const view = render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  expect(gpu.frames.size).toBeGreaterThan(0);
  view.unmount();
  expect(gpu.frames.size).toBe(0);
  for (const kind of Object.keys(gpu.resources)) expect(new Set(gpu.deleted[kind])).toEqual(new Set(gpu.resources[kind]));
});

it("stops the renderer and returns to the static background after context loss", () => {
  const gpu = graphics();
  const view = render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  fireEvent(view.container.querySelector("canvas")!, new Event("webglcontextlost", { cancelable: true }));
  expect(gpu.frames.size).toBe(0);
  for (const kind of Object.keys(gpu.resources)) expect(new Set(gpu.deleted[kind])).toEqual(new Set(gpu.resources[kind]));
});

it("does not leak shaders or programs if shader compilation fails", () => {
  const gpu = graphics(true);
  render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  for (const kind of Object.keys(gpu.resources)) expect(new Set(gpu.deleted[kind])).toEqual(new Set(gpu.resources[kind]));
  expect(gpu.frames.size).toBe(0);
});

it("lets the user pause the background and releases its graphics context resources", () => {
  const gpu = graphics();
  const view = render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  fireEvent.click(view.getByRole("button", { name: "Pausar animación" }));
  expect(view.container.querySelector("canvas")).toBeNull();
  expect(gpu.frames.size).toBe(0);
});

it("keeps the form usable if the browser refuses creation of a WebGL context", () => {
  graphics();
  vi.mocked(HTMLCanvasElement.prototype.getContext).mockImplementation(() => { throw new Error("Context denied"); });
  const view = render(<AuthSurface><h1>Acceso</h1><input aria-label="Correo" /></AuthSurface>);
  expect(view.getByLabelText("Correo")).toBeDefined();
});

it("falls back without leaking partial allocations when a graphics buffer cannot be created", () => {
  const gpu = graphics();
  gpu.gl.createBuffer.mockReturnValueOnce(null);
  const view = render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  expect(view.container.querySelector(".sliced-waves-container")?.getAttribute("data-webgl")).not.toBe("active");
  expect(gpu.frames.size).toBe(0);
  for (const kind of Object.keys(gpu.resources)) expect(new Set(gpu.deleted[kind])).toEqual(new Set(gpu.resources[kind]));
});

it("retains a usable fallback on browsers without the required resize observer", () => {
  graphics(); vi.stubGlobal("ResizeObserver", undefined);
  const view = render(<AuthSurface><h1>Acceso</h1><input aria-label="Correo" /></AuthSurface>);
  expect(view.getByLabelText("Correo")).toBeDefined();
});

it("releases the renderer when the user switches to reduced motion while the page is open", () => {
  const gpu = graphics();
  let notify = () => {};
  const media = { matches: false, addEventListener: vi.fn((_, listener) => { notify = listener; }), removeEventListener: vi.fn() };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  const view = render(<AuthSurface><h1>Acceso</h1></AuthSurface>);
  act(() => { media.matches = true; notify(); });
  expect(view.container.querySelector("canvas")).toBeNull();
  expect(gpu.frames.size).toBe(0);
});

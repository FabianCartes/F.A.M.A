import { File } from "node:buffer";
import { createHash, webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

const base = "/api/ingestion/imports";
const digest = (value: string) => createHash("sha256").update(value).digest("hex");
const data = "0123456789abcdefXYZ";
const mismatch = "01234567BAD!cdefXYZ";
const original = { id: "own", status: "receiving", sync_status: "pending", dataset_id: null,
  added_count: 0, preview_token: null, error: null,
  preview: { root: "", file_count: 0, class_count: 0, error_count: 0, warning_count: 0, total_size_bytes: 0, synced_count: 0 } };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// Independent protocol fixture: server bytes and public responses, not client internals.
function server(mode = "ok", prefix = 16) {
  let bytes = data.slice(0, prefix), sealed = false, preview = false, failed = false;
  const calls: string[] = [];
  const stateHash = () => digest(JSON.stringify({ bytes, sealed, preview }));
  const receipt = () => ({ import_id: "own", name: "own.zip", size_bytes: 19, received_bytes: bytes.length,
    reserved_bytes: 80, chunk_bytes: 4, status: sealed ? "sealed" : "receiving" });
  const records = () => Array.from({ length: Math.ceil(bytes.length / 4) }, (_, index) => ({ index,
    offset_bytes: index * 4, length_bytes: Math.min(4, bytes.length - index * 4),
    sha256: digest(data.slice(index * 4, index * 4 + 4)) }));
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
    const url = new URL(input, "http://test.invalid"), path = url.pathname;
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer own-session");
    calls.push(`${options?.method || "GET"} ${path}${url.search}`);
    if (path.endsWith("/access")) return Response.json({ development_mode: false });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 19, expanded_bytes: 80, entries: 10,
      depth: 4, path_bytes: 100, audio_bytes: 40, audio_seconds: 10, validation_seconds: 10,
      free_bytes: 1, ttl_seconds: 100, concurrent_imports: 1 });
    if (path.endsWith("/datasets")) return Response.json({ datasets: [], total: 0, next_cursor: null, snapshot: "a" });
    if (path === base) return Response.json({ imports: [original], total: 1, next_cursor: null, snapshot: "b" });
    if (path.endsWith("/receipt")) return Response.json(receipt());
    if (path.endsWith("/receipt/chunks")) {
      const second = url.searchParams.has("cursor");
      const accepted = records();
      let rows = accepted.slice(second ? 2 : 0, second ? accepted.length : 2);
      if (mode === "order" && second) rows = [...rows].reverse();
      if (mode === "duplicate" && second) rows = [accepted[1], accepted[2]];
      if (mode === "empty" && second) rows = [];
      return Response.json({ chunks: rows, total: accepted.length,
        snapshot: mode === "snapshot" && second ? bytes.length + 4 : bytes.length,
        next_cursor: !second && accepted.length > 2 && mode !== "incomplete" ? "page+2" : null });
    }
    const chunk = path.match(/receipt\/chunks\/(\d+)$/);
    if (chunk) {
      const text = await (options?.body as Blob).text(), headers = new Headers(options?.headers);
      expect(Number(headers.get("X-Chunk-Offset"))).toBe(bytes.length);
      expect(Number(chunk[1]) * 4).toBe(bytes.length);
      expect(headers.get("X-Chunk-SHA256")).toBe(digest(text));
      expect(text.length).toBeLessThanOrEqual(4);
      bytes += text;
      if (mode === "lostchunk" && !failed) { failed = true; throw new Error("Own lost chunk reply"); }
      return Response.json(mode === "ack" ? { ...receipt(), received_bytes: bytes.length - text.length } : receipt());
    }
    if (path.endsWith("/finalize")) {
      expect(bytes).toBe(data);
      if (mode === "finalfail" && !failed) {
        failed = true;
        return Response.json({ detail: "Own finalize refused" }, { status: 409 });
      }
      sealed = true;
      if (mode === "lostfinal" && !failed) { failed = true; throw new Error("Own lost final reply"); }
      return Response.json(receipt());
    }
    if (path.endsWith("/preview")) {
      expect(sealed).toBe(true);
      preview = true;
      return Response.json({ id: "exec", import_id: "own", kind: "preview", status: "queued", stage: "queued",
        progress: 100, result: {}, error: null, status_url: `${base}/own/jobs/exec` });
    }
    if (path.endsWith("/jobs/exec")) return Response.json({ id: "exec", import_id: "own", kind: "preview",
      status: "succeeded", stage: "done", progress: 100, result: {}, error: null, status_url: `${base}/own/jobs/exec` });
    if (path.endsWith("/cancel")) return Response.json({ ...original, status: "cancelled" });
    if (path === `${base}/own`) return Response.json({ ...original, status: preview ? "ready" : sealed ? "validating" : "receiving" });
    throw new Error(`Unplanned ${path}`);
  }));
  return { calls, stateHash, bytes: () => bytes };
}

async function select(contents = data) {
  render(<DatasetImportPanel sessionToken="own-session" />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const dialog = await screen.findByRole("dialog");
  const start = within(dialog).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  fireEvent.click(screen.getByRole("button", { name: /own —/ }));
  const file = new File([contents], "own.zip", { type: "application/zip" });
  const slices = vi.spyOn(file, "slice"), whole = vi.spyOn(file, "arrayBuffer");
  fireEvent.change(screen.getByLabelText("Archivo ZIP"), { target: { files: [file] } });
  return { slices, whole };
}
function validate() { fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" })); }
async function ready() { await screen.findByText("Importación own: lista para confirmar"); }

it.each([
  ["changed", "El archivo seleccionado no coincide con el prefijo aceptado. Selecciona el ZIP original o cancela la importación."],
  ["snapshot", "El prefijo de recepción cambió o está incompleto. Consulta su estado y reintenta."],
  ["empty", "El prefijo de recepción cambió o está incompleto. Consulta su estado y reintenta."],
  ["incomplete", "El registro del prefijo está incompleto."],
  ["order", "El registro del prefijo no es coherente."],
  ["duplicate", "El registro del prefijo no es coherente."],
])("rejects %s without changing server bytes or admitting preview", async (mode, error) => {
  const receipt = server(mode), before = receipt.stateHash();
  const file = await select(mode === "changed" ? mismatch : data);
  validate();
  expect((await screen.findByRole("alert")).textContent).toBe(error);
  expect(receipt.stateHash()).toBe(before);
  expect(file.whole).not.toHaveBeenCalled();
  expect(receipt.calls.filter(call => call.startsWith("PUT") || /finalize|preview|archive/.test(call))).toEqual([]);
  expect((screen.getByRole("button", { name: "Cancelar importación" }) as HTMLButtonElement).disabled).toBe(false);
  expect((screen.getByRole("button", { name: "Validar ZIP" }) as HTMLButtonElement).disabled).toBe(false);
});

it("verifies four prefix chunks over two pages before the short final suffix", async () => {
  const receipt = server(), file = await select();
  validate();
  await ready();
  expect(file.whole).not.toHaveBeenCalled();
  expect(file.slices.mock.calls).toEqual([[0, 4], [4, 8], [8, 12], [12, 16], [16, 19]]);
  expect(receipt.calls.filter(call => /receipt/.test(call))).toEqual([
    `POST ${base}/own/receipt`, `GET ${base}/own/receipt/chunks`, `GET ${base}/own/receipt/chunks?cursor=page%2B2`,
    `PUT ${base}/own/receipt/chunks/4`, `POST ${base}/own/receipt/finalize`]);
  expect(receipt.bytes()).toBe(data);
});

it.each(["lostchunk", "lostfinal", "finalfail"])("recovers %s without retransmitting acknowledged chunks", async mode => {
  const receipt = server(mode, 0);
  await select();
  validate();
  const error = (await screen.findByRole("alert")).textContent;
  expect(error).toBe(mode === "lostchunk" ? "Own lost chunk reply" : mode === "lostfinal" ? "Own lost final reply" : "409: Own finalize refused");
  expect(receipt.calls.some(call => call.endsWith("/preview"))).toBe(false);
  if (mode === "lostchunk") expect(screen.getByText(/Bytes reconocidos por el servidor: 0 de 19/)).toBeDefined();
  validate();
  await ready();
  expect(receipt.calls.filter(call => call.startsWith("PUT"))).toHaveLength(5);
  expect(receipt.calls.filter(call => call.endsWith("/preview"))).toHaveLength(1);
});

it("rejects an inconsistent PUT acknowledgement before finalizing or validating", async () => {
  const receipt = server("ack", 0);
  await select();
  validate();
  expect((await screen.findByRole("alert")).textContent).toBe("La confirmación del fragmento no coincide. Consulta la recepción antes de reintentar.");
  expect(receipt.calls.filter(call => call.startsWith("PUT"))).toHaveLength(1);
  expect(receipt.calls.some(call => /finalize|preview|archive/.test(call))).toBe(false);
});

it("clears the selected file and progress when resetting a failed receipt", async () => {
  server("snapshot");
  await select();
  validate();
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Nueva importación" }));
  expect(screen.queryByText(/Archivo seleccionado/)).toBeNull();
  expect(screen.queryByText(/Bytes reconocidos/)).toBeNull();
  expect((screen.getByRole("button", { name: "Validar ZIP" }) as HTMLButtonElement).disabled).toBe(true);
});

it("keeps one PUT in flight, reports only acknowledged bytes, and clears history selection", async () => {
  const receipt = server("ok", 0), normal = vi.mocked(fetch).getMockImplementation()!;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  vi.mocked(fetch).mockImplementation(async (input, options) => {
    if (String(input).endsWith("/chunks/0")) await gate;
    return normal(input, options);
  });
  const file = await select();
  validate();
  await waitFor(() => expect(file.slices).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/Bytes reconocidos por el servidor: 0 de 19/)).toBeDefined();
  expect(receipt.calls.filter(call => call.startsWith("PUT"))).toEqual([]);
  release();
  await ready();
  fireEvent.click(screen.getByRole("button", { name: /own —/ }));
  expect(screen.queryByText(/Archivo seleccionado/)).toBeNull();
  expect(screen.queryByText(/Bytes reconocidos/)).toBeNull();
  const before = receipt.stateHash();
  validate();
  expect((await screen.findByRole("alert")).textContent).toBe("Selecciona el ZIP original para reintentar la recepción.");
  expect(receipt.stateHash()).toBe(before);
});

it.each([["wrong.txt", 19], ["big.zip", 20]])("rejects %s before any receipt mutation", async (name, size) => {
  const receipt = server();
  await select();
  const before = receipt.stateHash();
  fireEvent.change(screen.getByLabelText("Archivo ZIP"), { target: { files: [new File(["x".repeat(size)], name)] } });
  expect((await screen.findByRole("alert")).textContent).toBe("Selecciona un ZIP dentro del límite recibido.");
  validate();
  expect((await screen.findByRole("alert")).textContent).toBe("Selecciona el ZIP original para reintentar la recepción.");
  expect(receipt.stateHash()).toBe(before);
  expect(receipt.calls.some(call => call.includes("/receipt"))).toBe(false);
});

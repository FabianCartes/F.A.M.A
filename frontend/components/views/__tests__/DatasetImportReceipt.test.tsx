import { File as BrowserFile } from "node:buffer";
import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";
import { durableFetch } from "./datasetImportTransport";

const base = "/api/ingestion/imports";
const source = { id: "resume", status: "receiving", sync_status: "pending", dataset_id: null,
  added_count: 0, preview_token: null, error: null,
  preview: { file_count: 0, class_count: 0, error_count: 0, warning_count: 0, total_size_bytes: 0, synced_count: 0 } };
const hash = (value: string) => createHash("sha256").update(value).digest("hex");
const chunks = ["aaaa", "bbbb", "cccc", "dd"];
const records = chunks.map((value, index) => ({ index, offset_bytes: index * 4,
  length_bytes: value.length, sha256: hash(value) }));

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function transport(prefix = 0, history = true) {
  let received = prefix, sealed = false;
  const writes: string[] = [];
  const pages: string[] = [];
  const receipt = () => ({ import_id: source.id, name: "birds.zip", size_bytes: 14,
    received_bytes: received, reserved_bytes: 100, chunk_bytes: 4, status: sealed ? "sealed" : "receiving" });
  const fetcher = durableFetch(async (input, options) => {
    const url = new URL(input, "http://synthetic.test");
    const path = url.pathname;
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer session");
    if (options?.method) writes.push(`${options.method} ${path}`);
    if (path.endsWith("/access")) return Response.json({ development_mode: false });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (path.endsWith("/datasets")) return Response.json({ datasets: [], total: 0, next_cursor: null, snapshot: "c" });
    if (path === base) return options?.method ? Response.json(source) : Response.json({ imports: history ? [source] : [], total: history ? 1 : 0, next_cursor: null, snapshot: "h" });
    if (path.endsWith("/receipt")) return Response.json(receipt());
    if (path.endsWith("/receipt/chunks")) {
      pages.push(url.search);
      const second = url.searchParams.has("cursor");
      const accepted = records.filter(record => record.offset_bytes < received);
      return Response.json({ chunks: accepted.slice(second ? 2 : 0, second ? 4 : 2), total: accepted.length,
        snapshot: received, next_cursor: !second && accepted.length > 2 ? "page+two" : null });
    }
    const match = path.match(/\/receipt\/chunks\/(\d+)$/);
    if (match) {
      const index = Number(match[1]);
      const headers = new Headers(options?.headers);
      expect(headers.get("Content-Type")).toBe("application/octet-stream");
      expect(headers.get("X-Chunk-Offset")).toBe(String(index * 4));
      expect(headers.get("X-Chunk-SHA256")).toBe(records[index].sha256);
      expect(await (options?.body as Blob).text()).toBe(chunks[index]);
      expect(index * 4).toBe(received);
      received += chunks[index].length;
      return Response.json(receipt());
    }
    if (path.endsWith("/receipt/finalize")) { expect(received).toBe(14); sealed = true; return Response.json(receipt()); }
    if (path === `${base}/resume`) return Response.json({ ...source, status: sealed ? "validating" : "receiving" });
    if (path.endsWith("/preview")) return Response.json({ ...source, status: "ready" });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { writes, pages, fetcher };
}

async function open(history = true, contents = chunks.join("")) {
  render(<DatasetImportPanel sessionToken="session" />);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const dialog = await screen.findByRole("dialog");
  const start = within(dialog).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  if (history) fireEvent.click(screen.getByRole("button", { name: /resume —/ }));
  else fireEvent.change(screen.getByLabelText("Nombre del dataset"), { target: { value: "Birds" } });
  const file = new BrowserFile([contents], "birds.zip", { type: "application/zip" });
  const slices = vi.spyOn(file, "slice");
  const wholeRead = vi.spyOn(file, "arrayBuffer");
  fireEvent.change(screen.getByLabelText("Archivo ZIP"), { target: { files: [file] } });
  return { slices, wholeRead };
}

it("uploads sequential bounded slices, acknowledges bytes, seals then separately admits preview", async () => {
  const { writes } = transport(0, false);
  const { slices, wholeRead } = await open(false);
  fireEvent.click(screen.getByRole("button", { name: "Importar ZIP" }));
  await screen.findByText("Importación resume: lista para confirmar");
  expect(writes).toEqual([`POST ${base}`, `POST ${base}/resume/receipt`,
    ...[0, 1, 2, 3].map(index => `PUT ${base}/resume/receipt/chunks/${index}`),
    `POST ${base}/resume/receipt/finalize`, `POST ${base}/resume/preview`]);
  expect(slices.mock.calls.map(([start, end]) => [start, end])).toEqual([[0, 4], [4, 8], [8, 12], [12, 14]]);
  expect(wholeRead).not.toHaveBeenCalled();
  expect(screen.getByText(/Bytes reconocidos por el servidor: 14 de 14/)).toBeDefined();
});

it("rejects a changed middle chunk despite identical name, size and endpoints, without appending or finalizing", async () => {
  const { writes } = transport(12);
  const { slices, wholeRead } = await open(true, "aaaaXXXXccccdd");
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  expect((await screen.findByRole("alert")).textContent).toContain("no coincide con el prefijo aceptado");
  expect(writes.filter(path => /\/chunks\/|\/finalize|\/preview|\/archive/.test(path))).toEqual([]);
  expect(slices.mock.calls.map(([start, end]) => [start, end])).toEqual([[0, 4], [4, 8]]);
  expect(wholeRead).not.toHaveBeenCalled();
});

it("checks every prefix page before uploading the suffix, and displays verification while a read is pending", async () => {
  const { writes, pages, fetcher } = transport(12);
  const { slices } = await open();
  const normal = fetcher.getMockImplementation()!;
  let release!: () => void;
  fetcher.mockImplementation(async (input, options) => {
    if (input.includes("cursor=")) await new Promise<void>(resolve => { release = resolve; });
    return normal(input, options);
  });
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await screen.findByText(/Verificando archivo para reanudar: 8 de 12/);
  expect(writes.filter(path => path.startsWith("PUT"))).toEqual([]);
  await act(async () => release());
  await screen.findByText("Importación resume: lista para confirmar");
  expect(pages).toEqual(["", "?cursor=page%2Btwo"]);
  expect(writes.filter(path => path.startsWith("PUT"))).toEqual([`PUT ${base}/resume/receipt/chunks/3`]);
  expect(slices.mock.calls.map(([start, end]) => [start, end])).toEqual([[0, 4], [4, 8], [8, 12], [12, 14]]);
});

it("recovers a lost chunk acknowledgement from server state, without counting it locally or uploading it again", async () => {
  const { writes, fetcher } = transport();
  const normal = fetcher.getMockImplementation()!;
  let lose = true;
  fetcher.mockImplementation(async (input, options) => {
    const response = await normal(input, options);
    if (input.endsWith("/chunks/0") && lose) { lose = false; throw new Error("Connection lost after durable append"); }
    return response;
  });
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await screen.findByRole("alert");
  expect(screen.getByText(/Bytes reconocidos por el servidor: 0 de 14/)).toBeDefined();
  expect(writes.some(path => /\/finalize|\/preview/.test(path))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await screen.findByText("Importación resume: lista para confirmar");
  expect(writes.filter(path => path.startsWith("PUT"))).toEqual([0, 1, 2, 3].map(index => `PUT ${base}/resume/receipt/chunks/${index}`));
});

it("rejects incomplete or changing hash pages without a write to the ZIP or admission", async () => {
  const { writes, fetcher } = transport(12);
  const normal = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input, options) => input.endsWith("/receipt/chunks")
    ? Response.json({ chunks: records.slice(0, 2), total: 3, snapshot: 8, next_cursor: null }) : normal(input, options));
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await screen.findByRole("alert");
  expect(writes.filter(path => /\/chunks\/|\/finalize|\/preview|\/archive/.test(path))).toEqual([]);
});

it("does not report unacknowledged progress or admit preview when receipt admission fails", async () => {
  const { writes, fetcher } = transport();
  const normal = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input, options) => input.endsWith("/receipt")
    ? Response.json({ detail: "Presupuesto temporal agotado" }, { status: 429 }) : normal(input, options));
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  expect((await screen.findByRole("alert")).textContent).toContain("429: Presupuesto temporal agotado");
  expect(writes).toEqual([]);
  expect(screen.queryByText(/Bytes reconocidos/)).toBeNull();
});

it("requires file reselection after choosing an import from history, rather than reusing another selection", async () => {
  transport(12);
  await open();
  fireEvent.click(screen.getByRole("button", { name: /resume —/ }));
  expect(screen.queryByText("Archivo seleccionado: birds.zip")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Selecciona el ZIP original");
});

it("reverifies the complete archive after a lost finalization reply, without resending chunks or premature preview", async () => {
  const { writes, fetcher } = transport();
  const normal = fetcher.getMockImplementation()!;
  let lose = true;
  fetcher.mockImplementation(async (input, options) => {
    const response = await normal(input, options);
    if (input.endsWith("/receipt/finalize") && lose) { lose = false; throw new Error("Lost sealed reply"); }
    return response;
  });
  const { slices } = await open();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await screen.findByRole("alert");
  expect(writes.some(path => path.endsWith("/preview"))).toBe(false);
  slices.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await screen.findByText("Importación resume: lista para confirmar");
  expect(slices.mock.calls.map(([start, end]) => [start, end])).toEqual([[0, 4], [4, 8], [8, 12], [12, 14]]);
  expect(writes.filter(path => path.startsWith("PUT"))).toHaveLength(4);
  expect(writes.filter(path => path.endsWith("/preview"))).toHaveLength(1);
});

it("keeps chunks sequential and does not display bytes as acknowledged before the PUT resolves", async () => {
  const { writes, fetcher } = transport();
  const normal = fetcher.getMockImplementation()!;
  let release!: () => void;
  fetcher.mockImplementation(async (input, options) => {
    if (input.endsWith("/chunks/0")) await new Promise<void>(resolve => { release = resolve; });
    return normal(input, options);
  });
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Validar ZIP" }));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  expect(screen.getByText(/Bytes reconocidos por el servidor: 0 de 14/)).toBeDefined();
  expect(writes.filter(path => path.startsWith("PUT"))).toEqual([]);
  fireEvent.click(screen.getByTestId("dataset-import-backdrop"));
  await act(async () => release());
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  await screen.findByText("Importación resume: lista para confirmar");
  expect(writes.filter(path => path.endsWith("/preview"))).toHaveLength(1);
});

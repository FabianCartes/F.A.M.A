import { z } from "zod";
import { importBase, importRequest, jsonRequest } from "./datasetImports";

const bytes = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
export const receiptSchema = z.object({
  import_id: z.string(), name: z.string(), size_bytes: bytes.positive(),
  received_bytes: bytes, reserved_bytes: bytes, chunk_bytes: bytes.positive().max(2 ** 31 - 1),
  status: z.enum(["receiving", "sealed", "cancelled"]),
}).refine(row => row.received_bytes <= row.size_bytes &&
  (row.received_bytes === row.size_bytes || row.received_bytes % row.chunk_bytes === 0),
{ message: "El prefijo de recepción no es válido." });
export type ImportReceipt = z.infer<typeof receiptSchema>;
export type ReceiptProgress = { receipt: ImportReceipt; phase: "verifying" | "uploading" | "sealing" | "sealed"; verified: number };
const chunkPageSchema = z.object({
  chunks: z.array(z.object({ index: bytes, offset_bytes: bytes, length_bytes: bytes.positive(),
    sha256: z.string().regex(/^[0-9a-f]{64}$/) })).max(200),
  total: bytes, snapshot: bytes, next_cursor: z.string().min(1).nullable(),
});

async function sha256(blob: Blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

/** The server receipt, never a browser counter, is the resume authority. */
export async function uploadImportReceipt(token: string, importId: string, file: File,
  progress: (value: ReceiptProgress) => void) {
  if (!crypto.subtle) throw new Error("La recepción requiere un contexto seguro con SHA-256 disponible.");
  const endpoint = `${importBase}/${importId}/receipt`;
  const response = await importRequest(token, endpoint, jsonRequest({ name: file.name, size_bytes: file.size }));
  let receipt = receiptSchema.parse(await response.json());
  if (receipt.import_id !== importId || receipt.name !== file.name || receipt.size_bytes !== file.size || receipt.status === "cancelled") {
    throw new Error("El archivo no corresponde a la recepción seleccionada.");
  }
  // Verify every accepted chunk, one slice and one bounded hash page at a time.
  // A changing prefix invalidates the traversal; never append on partial proof.
  let verified = 0, index = 0;
  let cursor: string | null = null;
  if (receipt.received_bytes > 0) {
    progress({ receipt, phase: "verifying", verified });
    do {
      const response = await importRequest(token, `${endpoint}/chunks${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
      const page = chunkPageSchema.parse(await response.json());
      if (page.snapshot !== receipt.received_bytes || page.total !== Math.ceil(receipt.received_bytes / receipt.chunk_bytes) || !page.chunks.length) {
        throw new Error("El prefijo de recepción cambió o está incompleto. Consulta su estado y reintenta.");
      }
      for (const record of page.chunks) {
        const length = Math.min(receipt.chunk_bytes, file.size - verified);
        if (record.index !== index || record.offset_bytes !== verified || record.length_bytes !== length ||
            verified + length > receipt.received_bytes) throw new Error("El registro del prefijo no es coherente.");
        if (await sha256(file.slice(verified, verified + length)) !== record.sha256) {
          throw new Error("El archivo seleccionado no coincide con el prefijo aceptado. Selecciona el ZIP original o cancela la importación.");
        }
        verified += length;
        index += 1;
        progress({ receipt, phase: "verifying", verified });
      }
      cursor = page.next_cursor;
      if (cursor && verified >= receipt.received_bytes) throw new Error("La página del prefijo no es coherente.");
    } while (cursor);
    if (verified !== receipt.received_bytes) throw new Error("El registro del prefijo está incompleto.");
  }
  progress({ receipt, phase: "uploading", verified: 0 });
  for (let offset = receipt.received_bytes; offset < file.size;) {
    const end = Math.min(offset + receipt.chunk_bytes, file.size);
    const chunk = file.slice(offset, end);
    const digest = await sha256(chunk);
    const response = await importRequest(token, `${endpoint}/chunks/${offset / receipt.chunk_bytes}`, {
      method: "PUT", headers: { "Content-Type": "application/octet-stream",
        "X-Chunk-Offset": String(offset), "X-Chunk-SHA256": digest }, body: chunk,
    });
    const next = receiptSchema.parse(await response.json());
    if (next.import_id !== importId || next.size_bytes !== receipt.size_bytes ||
        next.chunk_bytes !== receipt.chunk_bytes || next.received_bytes !== end || next.status !== "receiving") {
      throw new Error("La confirmación del fragmento no coincide. Consulta la recepción antes de reintentar.");
    }
    receipt = next;
    offset = end;
    progress({ receipt, phase: "uploading", verified: 0 });
  }
  progress({ receipt, phase: "sealing", verified: 0 });
  const finalized = receiptSchema.parse(await (await importRequest(token, `${endpoint}/finalize`, jsonRequest({}))).json());
  if (finalized.import_id !== importId || finalized.size_bytes !== file.size ||
      finalized.received_bytes !== file.size || finalized.status !== "sealed") throw new Error("No se confirmó la recepción completa.");
  progress({ receipt: finalized, phase: "sealed", verified });
}

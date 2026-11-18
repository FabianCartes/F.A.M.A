import { afterEach, describe, expect, it, vi } from "vitest";
import { approveFeedback, getFeedbackSync } from "../feedbackApi";

const record = { id_retroalimentacion: 7, id_prediccion: 12, dataset_name: "AvesChilenas", storage_class: "rayadito", class_label: "Rayadito", local_status: "incorporated", sync_status: "pending", attempts: 1, error_code: "upload_failed" };
const approval = { status: "approved", id_retroalimentacion: 7, destination_path: "local.wav", clase: "Rayadito", filename: "feedback_7.wav", local_status: "incorporated", sync_status: "pending" };
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });
function respond(data: unknown) { global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => data }); }

describe("accepted local and cloud acknowledgement contract", () => {
  it("reads recent records with default limit and abort support without mutations", async () => {
    respond([record]);
    const controller = new AbortController();
    expect(await getFeedbackSync(undefined, controller.signal)).toEqual([record]);
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/api/feedback/sync?limit=50'), {
      method: 'GET', signal: controller.signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    });
  });
  it("requests a later page only when an offset is given", async () => {
    respond([record]);
    await getFeedbackSync(21, undefined, 20);
    expect(global.fetch).toHaveBeenCalledWith(expect.stringMatching(/\/api\/feedback\/sync\?limit=21&offset=20$/), expect.anything());
    await expect(getFeedbackSync(20, undefined, -1)).rejects.toThrow("El desplazamiento debe ser un entero no negativo");
  });
  it("retains the real approval milestones, including replay acknowledgement", async () => {
    respond(approval);
    expect(await approveFeedback(7)).toMatchObject({ local_status: "incorporated", sync_status: "pending" });
    respond({ ...approval, sync_status: "synced" });
    expect((await approveFeedback(7)).sync_status).toBe("synced");
  });
});

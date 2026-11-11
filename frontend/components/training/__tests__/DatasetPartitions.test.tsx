import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import DatasetPartitions from "../DatasetPartitions";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("reserves test recordings and keeps legacy 80/20 versions visible as history", async () => {
  const calls: RequestInit[] = [];
  const version = "b".repeat(64);
  const preview = {format:2,version,counts:{train:6,val:2,test:2},warnings:[],entries:[],excluded:[]};
  vi.stubGlobal("fetch", vi.fn(async (_url, options?: RequestInit) => {
    calls.push(options ?? {});
    return {ok:true,status:200,json:async () => options?.method === "POST" ? preview : {
      versions:[{format:1,version:"a".repeat(64),counts:{train:8,val:2},warnings:[]}]}};
  }));
  const select = vi.fn();
  render(<DatasetPartitions dataset="Sample" selected="" busy={false} onSelect={select} />);
  const legacy = await screen.findByRole("option",{name:/Histórica 80\/20/});
  expect((legacy as HTMLOptionElement).disabled).toBe(true);
  expect(screen.getByLabelText("Prueba (%)")).toBeDefined();
  fireEvent.click(screen.getByRole("button",{name:"Previsualizar reparto"}));
  expect(await screen.findByText("6 para entrenamiento · 2 para validación · 2 para prueba")).toBeDefined();
  expect(JSON.parse(String(calls.find(call=>call.method === "POST")?.body))).toEqual({validation_percent:20,test_percent:20,seed:42});
  fireEvent.click(screen.getByRole("button",{name:"Guardar versión y seleccionarla"}));
  await waitFor(() => expect(select).toHaveBeenCalledWith(version));
});


it("opens with the dataset and names versions by number and date without their hash", async () => {
  const newer = { format: 2, version: "c".repeat(64), counts: { train: 6, val: 2, test: 2 }, warnings: [],
    created_at: "2026-11-11T18:00:00Z", policy: { validation_percent: 20, test_percent: 20, seed: 42 } };
  const older = { format: 2, version: "d".repeat(64), counts: { train: 5, val: 2, test: 2 }, warnings: [],
    created_at: "2026-11-10T18:00:00Z", policy: { validation_percent: 20, test_percent: 20, seed: 7 } };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ versions: [newer, older] }) })));
  render(<DatasetPartitions dataset="Sample" selected={newer.version} busy={false} onSelect={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /particiones/ })).toBeNull();
  const option = await screen.findByRole("option", { name: /^Versión 2 · 6 entrenamiento \/ 2 validación \/ 2 prueba/ });
  expect(option.textContent).toContain(new Date(newer.created_at).toLocaleString("es-CL"));
  expect(screen.getByRole("option", { name: /^Versión 1 · 5 entrenamiento/ })).toBeDefined();
  const section = screen.getByRole("region", { name: "Particiones de entrenamiento" });
  expect(section.textContent).toContain("Versión seleccionada: Versión 2");
  expect(section.textContent).not.toMatch(/[0-9a-f]{12}/);
});

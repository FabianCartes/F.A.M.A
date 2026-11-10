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
  fireEvent.click(screen.getByRole("button",{name:"Gestionar particiones"}));
  const legacy = await screen.findByRole("option",{name:/Histórica 80\/20/});
  expect((legacy as HTMLOptionElement).disabled).toBe(true);
  expect(screen.getByLabelText("Prueba (%)")).toBeDefined();
  fireEvent.click(screen.getByRole("button",{name:"Previsualizar reparto"}));
  expect(await screen.findByText("6 para entrenamiento · 2 para validación · 2 para prueba")).toBeDefined();
  expect(JSON.parse(String(calls.find(call=>call.method === "POST")?.body))).toEqual({validation_percent:20,test_percent:20,seed:42});
  fireEvent.click(screen.getByRole("button",{name:"Guardar versión y seleccionarla"}));
  await waitFor(() => expect(select).toHaveBeenCalledWith(version));
});

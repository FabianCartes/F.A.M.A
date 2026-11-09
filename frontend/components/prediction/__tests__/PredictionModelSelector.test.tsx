import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PredictionModelSelector from "../PredictionModelSelector";

const models = [
  { id: "first", name: "Modelo", has_weights: true },
  { id: "second", name: "Modelo", has_weights: true },
];
afterEach(cleanup);

it("highlights the hovered option without selecting it and keeps duplicate names distinct", () => {
  const onChange = vi.fn();
  render(<PredictionModelSelector models={models} value="first" onChange={onChange} />);
  const trigger = screen.getByRole("combobox", { name: "Modelo:" });
  fireEvent.click(trigger);
  const options = screen.getAllByRole("option", { name: "Modelo" });
  fireEvent.mouseEnter(options[1]);
  expect(options[1].classList.contains("bg-[#23252e]")).toBe(true);
  expect(screen.getByRole("combobox", { name: "Buscar modelo por nombre" }).getAttribute("aria-activedescendant")).toBe(options[1].id);
  expect(options[0].getAttribute("aria-selected")).toBe("true");
  expect(options[1].getAttribute("aria-selected")).toBe("false");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.click(options[1]);
  expect(onChange).toHaveBeenCalledExactlyOnceWith("second");
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it.each([false, undefined])("opens by keyboard, skips unavailable weights=%s and never selects them", hasWeights => {
  const onChange = vi.fn();
  render(<PredictionModelSelector models={[models[0], { id: "missing", name: "Sin pesos", has_weights: hasWeights }, models[1]]} value="first" onChange={onChange} />);
  const trigger = screen.getByRole("combobox", { name: "Modelo:" });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  const search = screen.getByRole("combobox", { name: "Buscar modelo por nombre" });
  const options = screen.getAllByRole("option");
  expect(document.activeElement).toBe(search);
  expect(search.getAttribute("aria-activedescendant")).toBe(options[0].id);
  fireEvent.keyDown(search, { key: "ArrowUp" });
  expect(search.getAttribute("aria-activedescendant")).toBe(options[2].id);
  fireEvent.keyDown(search, { key: "ArrowDown" });
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(search.getAttribute("aria-activedescendant")).toBe(options[2].id);
  expect(options[1].getAttribute("aria-disabled")).toBe("true");
  fireEvent.mouseEnter(options[1]);
  fireEvent.click(options[1]);
  fireEvent.keyDown(search, { key: "Enter" });
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getByRole("listbox")).toBeDefined();
  fireEvent.keyDown(search, { key: "ArrowDown" });
  fireEvent.keyDown(search, { key: "Enter" });
  expect(onChange).toHaveBeenCalledExactlyOnceWith("second");
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it.each(["Escape", "blur", "trigger"])("closes on %s, clears a fruitless query and keeps selection", method => {
  const onChange = vi.fn();
  render(<><PredictionModelSelector models={models} value="first" onChange={onChange} /><button>Fuera</button></>);
  const trigger = screen.getByRole("combobox", { name: "Modelo:" });
  fireEvent.click(trigger);
  const search = screen.getByRole("combobox", { name: "Buscar modelo por nombre" });
  fireEvent.change(search, { target: { value: "sin coincidencias" } });
  expect(screen.getByRole("status").textContent).toBe("No hay modelos que coincidan con la búsqueda.");
  expect(screen.queryByRole("option")).toBeNull();
  fireEvent.keyDown(search, { key: "ArrowDown" });
  fireEvent.keyDown(search, { key: "Enter" });
  expect(onChange).not.toHaveBeenCalled();
  if (method === "Escape") fireEvent.keyDown(search, { key: "Escape" });
  else if (method === "blur") {
    const outside = screen.getByRole("button", { name: "Fuera" });
    fireEvent.blur(search, { relatedTarget: outside });
    outside.focus();
    expect(document.activeElement).toBe(outside);
  } else fireEvent.click(trigger);
  expect(screen.queryByRole("listbox")).toBeNull();
  expect((trigger as HTMLButtonElement).value).toBe("first");
  if (method === "Escape") expect(document.activeElement).toBe(trigger);
  fireEvent.click(trigger);
  expect((screen.getByRole("combobox", { name: "Buscar modelo por nombre" }) as HTMLInputElement).value).toBe("");
  expect(screen.getAllByRole("option")).toHaveLength(2);
  expect(onChange).not.toHaveBeenCalled();
});

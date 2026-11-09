import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import PredictionModelSelector from "../PredictionModelSelector";

const models = [
  { id: "first", name: "Modelo", has_weights: true },
  { id: "second", name: "Modelo", has_weights: true },
];
afterEach(cleanup);

it("shows ordered compact triad weights without renumbering the persisted title or changing the selected ID", () => {
  const onChange = vi.fn();
  const triad = {
    id: "fama_trained_model_28", name: "Birds · Tríada v4", has_weights: true,
    architecture: "ImportedTriad", dataset_name: "Birds",
    metrics: {
      weights: [0.4, 0.3, 0.3],
      components: ["EfficientNet-B0", "ConvNeXt-Nano", "ResNet-34d"].map((architecture, index) => ({
        model_id: index + 1, checkpoint_sha256: String(index + 1).repeat(64),
        imported_source: { profile: { architecture } },
      })),
    },
  };
  render(<PredictionModelSelector models={[triad]} value={triad.id} onChange={onChange} />);
  const trigger = screen.getByRole("combobox", { name: "Modelo:" });
  expect(trigger.textContent).toContain("Birds · Tríada v4");
  fireEvent.click(trigger);
  const option = screen.getByRole("option");
  expect(within(option).getByText("B0 40 · CNX 30 · R34 30")).toBeDefined();
  expect(option.textContent).toContain("Birds · Tríada v4");
  expect(option.textContent).not.toContain("v1");
  fireEvent.click(option);
  expect(onChange).toHaveBeenCalledExactlyOnceWith("fama_trained_model_28");
});

it("groups triads by persisted dataset identity and orders each group newest first without renumbering", () => {
  const triad = (id: string, dataset: string, version: number) => ({
    id, name: `${dataset} · Tríada v${version}`, has_weights: true, architecture: "ImportedTriad",
    metrics: { dataset_id: dataset, dataset_display_name: dataset, triad_version: version },
  });
  render(<PredictionModelSelector models={[
    triad("birds-old", "Birds", 1), triad("machines", "Machines", 2),
    triad("birds-new", "Birds", 4),
  ]} value="birds-old" onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("combobox", { name: "Modelo:" }));
  const birds = screen.getByRole("group", { name: "Birds" });
  expect(within(birds).getAllByRole("option").map(option => option.textContent)).toEqual([
    "Birds · Tríada v4", "Birds · Tríada v1",
  ]);
  expect(within(screen.getByRole("group", { name: "Machines" })).getByRole("option").textContent)
    .toBe("Machines · Tríada v2");
  fireEvent.change(screen.getByRole("combobox", { name: "Buscar modelo por nombre" }), { target: { value: "v4" } });
  expect(screen.getAllByRole("option")).toHaveLength(1);
  expect(screen.getByRole("option").textContent).toBe("Birds · Tríada v4");
});

it.each([undefined, 1, 3])("shows a weight-only tooltip only for a proven earlier version (%s)", reference => {
  const triad = {
    id: "triad", name: "Birds · Tríada v4", has_weights: true, architecture: "ImportedTriad",
    metrics: { triad_version: 4, same_components_as_version: reference },
  };
  render(<PredictionModelSelector models={[triad]} value="triad" onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("combobox", { name: "Modelo:" }));
  if (reference === undefined) {
    expect(screen.queryByTitle(/Mismos modelos que la v/)).toBeNull();
  } else {
    expect(screen.getByTitle(`Mismos modelos que la v${reference}; solo cambian los pesos`)).toBeDefined();
  }
});

it.each([0, 4, 5, Number.NaN])("does not invent a weight-only reference for invalid version %s", reference => {
  const triad = { id: "triad", name: "Birds · Tríada v4", has_weights: true, architecture: "ImportedTriad",
    metrics: { triad_version: 4, same_components_as_version: reference } };
  render(<PredictionModelSelector models={[triad]} value="triad" onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("combobox", { name: "Modelo:" }));
  expect(screen.queryByTitle(/Mismos modelos que la v/)).toBeNull();
});

it("does not fabricate architecture badges from incomplete component metadata", () => {
  const triad = { id: "triad", name: "Tríada importada", has_weights: true, architecture: "ImportedTriad",
    metrics: { weights: [0.4, 0.3, 0.3], components: [{}, {}, {}] } };
  render(<PredictionModelSelector models={[triad]} value="triad" onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("combobox", { name: "Modelo:" }));
  expect(screen.getByRole("option").textContent).toBe("Tríada importada");
  expect(screen.queryByText(/B0|CNX|R34/)).toBeNull();
});

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

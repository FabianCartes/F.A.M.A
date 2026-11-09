import { act, fireEvent, screen, within } from "@testing-library/react";

export const modelOptions = () => {
  const trigger = screen.getByRole("combobox", { name: "Modelo:" });
  if (trigger.getAttribute("aria-expanded") !== "true") fireEvent.click(trigger);
  return screen.getByRole("listbox", { name: "Modelos disponibles" });
};

export const chooseModel = async (name: string) => {
  const option = within(modelOptions()).getByRole("option", {
    name: accessibleName => accessibleName === name || accessibleName === `${name} (no disponible)`,
  });
  await act(async () => { fireEvent.click(option); });
};

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect, vi } from "vitest";
import RootLayout, { metadata, viewport } from "../layout";

// next/font/local is a build-time boundary: Vitest simulates generated classes;
// real Next.js builds validate the loader configuration and font binaries.
vi.mock("next/font/local", () => ({
  default: vi
    .fn()
    .mockReturnValueOnce({
      variable: "font-montserrat",
      className: "",
      style: {},
    })
    .mockReturnValueOnce({
      variable: "font-open-sans",
      className: "",
      style: {},
    }),
}));

describe("RootLayout public metadata contract (App Router head)", () => {
  it("renders its children in the Spanish document with both font classes", () => {
    const markup = renderToStaticMarkup(
      RootLayout({
        children: createElement(
          "main",
          null,
          "Sonidos: ñandú, acción, pingüino, ¿sí? ¡Claro!",
        ),
      }),
    );

    expect(markup).toContain(
      '<html lang="es" class="font-montserrat font-open-sans dark">',
    );
    expect(markup).toContain("Sonidos: ñandú, acción, pingüino, ¿sí? ¡Claro!");
    expect(markup).toContain(
      'class="min-h-screen bg-gray-950 text-white antialiased"',
    );
  });

  it("declares the document title for the platform", () => {
    expect(metadata.title).toBe("F.A.M.A. | Clasificación Bioacústica");
  });

  it("maps the viewport to the device width instead of a fixed desktop canvas", () => {
    expect(viewport.width).toBe("device-width");
  });

  it("keeps the initial scale at 1 so mobile users are not zoomed", () => {
    expect(viewport.initialScale).toBe(1);
  });

  it("covers the safe area on notched devices via viewport-fit", () => {
    expect(viewport.viewportFit).toBe("cover");
  });

  it("paints the browser chrome with the platform background color", () => {
    expect(viewport.themeColor).toBe("#030712");
  });
});

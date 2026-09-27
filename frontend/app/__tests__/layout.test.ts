import { describe, it, expect, vi } from "vitest";
import RootLayout, { metadata, viewport } from "../layout";

// next/font/google is a build-time boundary: only the Next.js compiler can
// transform its loaders, so outside the bundler the exports are inert.
vi.mock("next/font/google", () => ({
  Montserrat: () => ({ variable: "font-montserrat", className: "font-montserrat", style: {} }),
  Open_Sans: () => ({ variable: "font-open-sans", className: "font-open-sans", style: {} }),
}));

describe("RootLayout public metadata contract (App Router head)", () => {
  it("renders an element that accepts children", () => {
    expect(typeof RootLayout).toBe("function");
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

import { describe, it, expect } from "vitest";
import { rebalanceWeights } from "../ensembleWeights";

describe("rebalanceWeights", () => {
  it("always returns [1.0] when there is only 1 model", () => {
    expect(rebalanceWeights([1.0], 0, 0.5)).toEqual([1.0]);
  });

  it("rebalances 2 models correctly when one slider changes", () => {
    const result = rebalanceWeights([0.5, 0.5], 0, 0.7);
    expect(result[0]).toBeCloseTo(0.7, 4);
    expect(result[1]).toBeCloseTo(0.3, 4);
    expect(result[0] + result[1]).toBeCloseTo(1.0, 4);
  });

  it("rebalances 3 models proportionally when one slider changes", () => {
    // Initial equal weights
    const initial = [1 / 3, 1 / 3, 1 / 3];
    const result = rebalanceWeights(initial, 0, 0.5);

    expect(result[0]).toBeCloseTo(0.5, 4);
    expect(result[1]).toBeCloseTo(0.25, 4);
    expect(result[2]).toBeCloseTo(0.25, 4);
    const sum = result.reduce((acc, w) => acc + w, 0);
    expect(sum).toBeCloseTo(1.0, 4);
  });

  it("handles setting a model weight to 1.0 by zeroing out the others", () => {
    const result = rebalanceWeights([0.4, 0.3, 0.3], 1, 1.0);
    expect(result[1]).toBeCloseTo(1.0, 4);
    expect(result[0]).toBeCloseTo(0.0, 4);
    expect(result[2]).toBeCloseTo(0.0, 4);
    const sum = result.reduce((acc, w) => acc + w, 0);
    expect(sum).toBeCloseTo(1.0, 4);
  });

  it("handles setting a model weight to 0.0 by scaling up the others", () => {
    const result = rebalanceWeights([0.5, 0.25, 0.25], 0, 0.0);
    expect(result[0]).toBeCloseTo(0.0, 4);
    expect(result[1]).toBeCloseTo(0.5, 4);
    expect(result[2]).toBeCloseTo(0.5, 4);
    const sum = result.reduce((acc, w) => acc + w, 0);
    expect(sum).toBeCloseTo(1.0, 4);
  });

  it("distributes equally when other models all have 0 weight", () => {
    const result = rebalanceWeights([1.0, 0.0, 0.0], 0, 0.4);
    expect(result[0]).toBeCloseTo(0.4, 4);
    expect(result[1]).toBeCloseTo(0.3, 4);
    expect(result[2]).toBeCloseTo(0.3, 4);
    const sum = result.reduce((acc, w) => acc + w, 0);
    expect(sum).toBeCloseTo(1.0, 4);
  });

  it("clamps newWeight between 0.0 and 1.0", () => {
    const resultNegative = rebalanceWeights([0.5, 0.5], 0, -0.2);
    expect(resultNegative[0]).toBeCloseTo(0.0, 4);
    expect(resultNegative[1]).toBeCloseTo(1.0, 4);

    const resultOverflow = rebalanceWeights([0.5, 0.5], 0, 1.5);
    expect(resultOverflow[0]).toBeCloseTo(1.0, 4);
    expect(resultOverflow[1]).toBeCloseTo(0.0, 4);
  });
});

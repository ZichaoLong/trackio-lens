import { describe, expect, it } from "vitest";
import { readoutAt, readoutSteps } from "./chartReadout.js";

describe("original observation readout", () => {
  const rows = [
    { run: "a", step: 0, loss: 0, data_type: "original" },
    { run: "b", step: 0, loss: null, data_type: "original" },
    { run: "a", step: 1, loss: 4, data_type: "original" },
    { run: "b", step: 1, loss: 2, data_type: "original" },
    { run: "a", step: 0, loss: 999, data_type: "smoothed" },
  ];
  it("preserves zero, missing values and source measurements", () => {
    const original = structuredClone(rows);
    expect(readoutSteps(rows, "step")).toEqual([0, 1]);
    expect(readoutAt(rows, "step", "loss", 0).map(row => row.value)).toEqual([0, null]);
    expect(readoutAt(rows, "step", "loss", 1).map(row => row.value)).toEqual([4, 2]);
    expect(rows).toEqual(original);
  });
});

import { describe, expect, it } from "vitest";
import { formatCaseName, formatMeters, formatNewton } from "./format";

describe("format helpers", () => {
  it("formats Newton values using kN for engineering scanability", () => {
    expect(formatNewton(87500)).toBe("87.50 kN");
    expect(formatNewton(312.345)).toBe("312.35 N");
  });

  it("formats distances with stable precision", () => {
    expect(formatMeters(12.345)).toBe("12.35 m");
    expect(formatMeters(null)).toBe("—");
  });

  it("turns case ids into compact labels", () => {
    expect(formatCaseName("power_current_speed_1p50")).toBe("500kV电力缆｜流速1.50 m/s");
    expect(formatCaseName("la_accel_200m")).toBe("LA 信号缆｜加速铺设 200 m");
    expect(formatCaseName("la_dynamic_accel_current_1p50")).toBe("LA｜加速时程，流速1.50 m/s");
  });
});

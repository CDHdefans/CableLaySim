import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultPlots } from "./ResultPlots";
import type { RunCaseResponse } from "./types";

describe("ResultPlots", () => {
  it("uses engineering axis ranges from backend plot data without comparison scaling", () => {
    const { container } = render(<ResultPlots result={resultWithBackendPlotData()} />);

    const topTensionChart = container.querySelector("svg.result-chart");

    expect(topTensionChart).not.toBeNull();
    expect(topTensionChart?.textContent).toContain("0");
    expect(topTensionChart?.textContent).toContain("10");
    expect(topTensionChart?.textContent).toContain("20");
    expect(topTensionChart?.textContent).toContain("30");
    expect(topTensionChart?.textContent).toContain("40");
    expect(topTensionChart?.textContent).not.toContain("-2.40");
    expect(topTensionChart?.textContent).not.toContain("32.4");
  });
});

function resultWithBackendPlotData(): RunCaseResponse {
  return {
    case_name: "operator_input",
    summary: {
      top_tension_initial_n: 12000,
      top_tension_min_n: 11000,
      top_tension_final_n: 40000,
      suspended_length_m: 180.5,
      layback_m: 42.25,
    },
    artifacts: {
      summary_csv: "custom/operator_input/summary.csv",
      profile_csv: "custom/operator_input/profile.csv",
      profile_svg: "custom/operator_input/profile.svg",
    },
    plot_data: {
      profile: [
        profilePoint(0, 0, 0, 0, 40000),
        profilePoint(1, 4, 12, 50, 22000),
        profilePoint(2, 16, 34, 100, 1500),
      ],
      time_history: {
        source: "quasi_static_reference",
        label: "后端返回时程",
        points: [
          { time_s: 0, top_tension_n: 12000, tdp_x_m: 16, tdp_y_m: 34 },
          { time_s: 15, top_tension_n: 11000, tdp_x_m: 16, tdp_y_m: 34 },
          { time_s: 30, top_tension_n: 40000, tdp_x_m: 16, tdp_y_m: 34 },
        ],
      },
    },
  };
}

function profilePoint(index: number, x: number, y: number, z: number, tension: number) {
  return {
    index,
    arc_m: index * 50,
    x_m: x,
    y_m: y,
    z_m: z,
    theta_rad: 1.2,
    psi_rad: 0.5,
    tangent_x: 0.2,
    tangent_y: 0.1,
    tangent_z: 0.9,
    current_x_mps: 1.5,
    current_y_mps: 0,
    current_z_mps: 0,
    drag_x_n_per_m: 100,
    drag_y_n_per_m: 0,
    drag_z_n_per_m: 0,
    tension_n: tension,
  };
}

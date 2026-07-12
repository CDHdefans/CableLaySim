import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SimulationResultView } from "./SimulationResultView";
import type { RunTimeHistoryResponse } from "./types";

describe("SimulationResultView", () => {
  it("updates the cable tension distribution when the 3D timeline changes", () => {
    const { container } = render(<SimulationResultView apiBase="http://127.0.0.1:8765" result={result} />);
    const line = () => container.querySelector(".tension-distribution-line")?.getAttribute("points");

    const initialLine = line();
    expect(initialLine).toBeTruthy();
    expect(screen.getByText("当前帧 0.0 s")).toBeInTheDocument();
    expect(screen.getByText("当前船速")).toBeInTheDocument();
    expect(screen.getByText("0.80 m/s")).toBeInTheDocument();
    expect(screen.getByText("当前放缆")).toBeInTheDocument();
    expect(screen.getByText("0.90 m/s")).toBeInTheDocument();
    expect(screen.getByText("当前犁速")).toBeInTheDocument();
    expect(screen.getByText("0.75 m/s")).toBeInTheDocument();
    expect(screen.getByText("风险与可信度")).toBeInTheDocument();
    expect(screen.getByText("边界张力已传入相邻段")).toBeInTheDocument();
    expect(screen.getByText("Rmin 原始值")).toBeInTheDocument();
    expect(screen.getByText("2.30 m")).toBeInTheDocument();
    expect(screen.getByText("0.050-0.200 s")).toBeInTheDocument();
    expect(screen.getByText("min 3.50 m / mean 4.20 m")).toBeInTheDocument();
    expect(screen.getByText("10-12 次/步 / 单次上限 100")).toBeInTheDocument();
    expect(screen.getByText("9.00e-11 m")).toBeInTheDocument();
    const trends = screen.getByLabelText("动态时程趋势");
    const topTrend = within(trends).getByLabelText("顶张力趋势");
    const ploughTrend = within(trends).getByLabelText("犁入口张力趋势");
    const suspendedTrend = within(trends).getByLabelText("悬垂长度趋势");
    expect(within(trends).getByText("顶张力")).toBeInTheDocument();
    expect(within(trends).getByText("犁入口张力")).toBeInTheDocument();
    expect(within(trends).getByText("悬垂长度")).toBeInTheDocument();
    expect(within(trends).getByText("当前游标 0.0 s")).toBeInTheDocument();
    expect(within(topTrend).getByText("0.90 kN")).toBeInTheDocument();
    expect(within(ploughTrend).getByText("0.12 kN")).toBeInTheDocument();
    expect(within(suspendedTrend).getByText("95.00 m")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("时间轴"), { target: { value: "1" } });

    expect(screen.getByText("当前帧 10.0 s")).toBeInTheDocument();
    expect(screen.getByText("1.20 m/s")).toBeInTheDocument();
    expect(screen.getByText("1.10 m/s")).toBeInTheDocument();
    expect(within(trends).getByText("当前游标 10.0 s")).toBeInTheDocument();
    expect(within(topTrend).getByText("0.12 kN")).toBeInTheDocument();
    expect(within(ploughTrend).getByText("0.90 kN")).toBeInTheDocument();
    expect(within(suspendedTrend).getByText("98.00 m")).toBeInTheDocument();
    expect(line()).toBeTruthy();
    expect(line()).not.toEqual(initialLine);
  });

  it("interpolates trend values when the frame time falls between time-history samples", () => {
    const baseFrames = result.plot_data.frames!;
    const midFrameResult: RunTimeHistoryResponse = {
      ...result,
      plot_data: {
        ...result.plot_data,
        frames: {
          source: baseFrames.source,
          label: baseFrames.label,
          items: [
            baseFrames.items[0],
            {
              ...baseFrames.items[0],
              time_s: 5,
              vessel_y_m: 4,
              plough_y_m: -51,
            },
            baseFrames.items[1],
          ],
        },
      },
    };

    render(<SimulationResultView apiBase="http://127.0.0.1:8765" result={midFrameResult} />);
    fireEvent.change(screen.getByLabelText("时间轴"), { target: { value: "1" } });

    const trends = screen.getByLabelText("动态时程趋势");
    expect(within(trends).getByText("当前游标 5.0 s")).toBeInTheDocument();
    expect(within(within(trends).getByLabelText("顶张力趋势")).getByText("0.51 kN")).toBeInTheDocument();
    expect(within(within(trends).getByLabelText("犁入口张力趋势")).getByText("0.51 kN")).toBeInTheDocument();
    expect(within(within(trends).getByLabelText("悬垂长度趋势")).getByText("96.50 m")).toBeInTheDocument();
  });

  it("shows an empty trend state when optional time-history fields are missing", () => {
    const sparseResult: RunTimeHistoryResponse = {
      ...result,
      plot_data: {
        ...result.plot_data,
        time_history: {
          ...result.plot_data.time_history,
          points: result.plot_data.time_history.points.map((point) => ({
            time_s: point.time_s,
            top_tension_n: point.top_tension_n,
            tdp_x_m: point.tdp_x_m,
            tdp_y_m: point.tdp_y_m,
            iterations: point.iterations,
          })),
        },
      },
    };

    render(<SimulationResultView apiBase="http://127.0.0.1:8765" result={sparseResult} />);

    const trends = screen.getByLabelText("动态时程趋势");
    expect(within(within(trends).getByLabelText("顶张力趋势")).getByText("0.90 kN")).toBeInTheDocument();
    expect(within(within(trends).getByLabelText("犁入口张力趋势")).getByText("暂无可绘制时程。")).toBeInTheDocument();
    expect(within(within(trends).getByLabelText("悬垂长度趋势")).getByText("暂无可绘制时程。")).toBeInTheDocument();
  });
});

const result: RunTimeHistoryResponse = {
  case_name: "timeline-sync",
  summary: {
    diameter_m: 0.0264,
    weight_air_n_per_m: 16.09,
    submerged_weight_n_per_m: 10.59,
    tangential_drag_coefficient: 0.01,
    normal_drag_coefficient: 2.12,
    axial_stiffness_n: 1e9,
    current_speed_mps: 0.35,
    current_direction_deg: 90,
    speed_change: "steady",
    initial_speed_mps: 0.8,
    final_speed_mps: 1.2,
    payout_initial_speed_mps: 0.9,
    payout_final_speed_mps: 1.1,
    length_boundary_source: "known_plough_trajectory",
    duration_s: 10,
    total_duration_s: 10,
    water_depth_m: 80,
    element_count: 3,
    touchdown_tension_n: 200,
    evidence_level: "known plough trajectory endpoint model with XPBD length constraints and segment tension output",
    initial_tension_n: 900,
    extreme_tension_n: 900,
    steady_tension_n: 900,
    plough_speed_mps: 0.75,
    plough_inlet_tension_final_n: 120,
    plough_boundary_tension_final_n: 200,
    plough_adjacent_segment_tension_final_n: 196,
    plough_tension_status: "carried",
    minimum_bend_radius_min_m: 12,
    minimum_bend_radius_limit_m: 10,
    minimum_bend_radius_margin_m: 2,
    minimum_bend_radius_status: "ok",
    minimum_bend_radius_time_s: 10,
    minimum_bend_radius_node_index: 1,
    minimum_bend_radius_near_seabed: false,
    minimum_bend_radius_raw_m: 2.3,
    minimum_bend_radius_raw_time_s: 10,
    minimum_bend_radius_raw_node_index: 2,
    minimum_bend_radius_raw_near_seabed: true,
    integration_time_step_min_s: 0.05,
    integration_time_step_max_s: 0.2,
    spatial_step_min_m: 3.5,
    spatial_step_mean_m: 4.2,
    xpbd_iterations_per_step: 12,
    xpbd_iterations_per_step_min: 10,
    xpbd_iterations_per_step_max: 12,
    xpbd_iteration_limit_per_solve: 100,
    axial_constraint_residual_max_m: 9e-11,
  },
  artifacts: {
    time_summary_csv: "time_histories/timeline-sync/time_summary.csv",
    time_history_csv: "time_histories/timeline-sync/time_history.csv",
    time_history_svg: "time_histories/timeline-sync/time_history.svg",
  },
  plot_data: {
    time_history: {
      source: "la_dynamic_xpbd_node_state",
      label: "动态张力时程",
      points: [
        {
          time_s: 0,
          top_tension_n: 900,
          tdp_x_m: 0,
          tdp_y_m: -55,
          suspended_length_m: 95,
          iterations: 10,
          plough_inlet_tension_n: 120,
        },
        {
          time_s: 10,
          top_tension_n: 120,
          tdp_x_m: 0,
          tdp_y_m: -47,
          suspended_length_m: 98,
          iterations: 20,
          plough_inlet_tension_n: 900,
        },
      ],
    },
    frames: {
      source: "la_dynamic_xpbd_frames",
      label: "动态三维帧",
      items: [
        {
          time_s: 0,
          boundary: "known_plough_trajectory",
          segment_tensions_n: [900, 500],
          vessel_x_m: 0,
          vessel_y_m: 0,
          vessel_z_m: 0,
          plough_x_m: 0,
          plough_y_m: -55,
          plough_z_m: 78,
          points: [
            { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 900 },
            { index: 1, x_m: 0, y_m: -25, z_m: 40, tension_n: 500 },
            { index: 2, x_m: 0, y_m: -55, z_m: 78, tension_n: 120 },
          ],
        },
        {
          time_s: 10,
          boundary: "known_plough_trajectory",
          segment_tensions_n: [120, 640],
          vessel_x_m: 0,
          vessel_y_m: 8,
          vessel_z_m: 0,
          plough_x_m: 0,
          plough_y_m: -47,
          plough_z_m: 78,
          points: [
            { index: 0, x_m: 0, y_m: 8, z_m: 0, tension_n: 120 },
            { index: 1, x_m: 0, y_m: -18, z_m: 42, tension_n: 640 },
            { index: 2, x_m: 0, y_m: -47, z_m: 78, tension_n: 900 },
          ],
        },
      ],
    },
  },
};

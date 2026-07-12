import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  advanceRealtimeSession,
  buildFileUrl,
  createRealtimeSession,
  deleteRealtimeSession,
  getRealtimeSession,
  getCases,
  getTimeHistoryCases,
  groupCases,
  runCase,
  runCustomCase,
  runTimeHistory,
} from "./api";
import type { CableCase, CustomCaseRequest } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API adapters", () => {
  it("supports the realtime session lifecycle", async () => {
    const packet = {
      sequence: 0,
      time_s: 0,
      observed_at_unix_s: 100,
      quality: "valid" as const,
      vessel: { x_m: 0, y_m: 0, z_m: 0, velocity_x_mps: 0.8, velocity_y_mps: 0, velocity_z_mps: 0 },
      plough: { x_m: -55, y_m: 0, z_m: 80, velocity_x_mps: 0.8, velocity_y_mps: 0, velocity_z_mps: 0 },
      payout_speed_mps: 0.8,
      plough_exit_speed_mps: 0.8,
      current_velocity_x_mps: 0,
      current_velocity_y_mps: 0.35,
    };
    const response = {
      session_id: "session/one",
      sequence: 0,
      time_s: 0,
      compute_wall_s: 0.01,
      realtime_factor: null,
      input_age_s: 0,
      input_status: "valid",
      tensions: { top_tension_n: 1000, plough_inlet_tension_n: 300, plough_boundary_tension_n: 290 },
      contact: { tdp_x_m: -20, tdp_y_m: 0, tdp_arc_length_m: 60, free_span_material_length_m: 60, seabed_contact_length_m: 0, seabed_normal_reaction_n: 0 },
      integration: { time_step_min_s: 0.01, time_step_max_s: 0.01, axial_constraint_residual_max_m: 0.001 },
      frame: { time_s: 0, points: [] },
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => response });
    vi.stubGlobal("fetch", fetchMock);
    const request = { ...minimalTimeHistoryInputs(), initial_packet: packet };

    await expect(createRealtimeSession(request, "http://api.test")).resolves.toEqual(response);
    await expect(advanceRealtimeSession("session/one", { ...packet, sequence: 1, time_s: 1 }, "http://api.test")).resolves.toEqual(response);
    await expect(getRealtimeSession("session/one", "http://api.test")).resolves.toEqual(response);
    await expect(deleteRealtimeSession("session/one", "http://api.test")).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://api.test/api/realtime-sessions/session%2Fone/samples", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://api.test/api/realtime-sessions/session%2Fone");
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://api.test/api/realtime-sessions/session%2Fone", { method: "DELETE" });
  });
  it("builds backend file URLs without stripping artifact folders", () => {
    expect(buildFileUrl("ha_accel_200m/profile.svg", "http://127.0.0.1:8000")).toBe(
      "http://127.0.0.1:8000/api/files/ha_accel_200m/profile.svg",
    );
  });

  it("loads cases from the backend", async () => {
    const cases: CableCase[] = [
      {
        name: "la_accel_200m",
        label: "LA 信号缆｜加速铺设 200 m",
        description: "轻型电缆加速例子",
        group: "LA",
        example: true,
        display_order: 10,
        suggested_output_dir: "custom/la-accel-200m",
          inputs: {
            cable: "LA",
            solver_model: "generic",
            diameter_m: 0.0264,
            weight_air_n_per_m: 16.09,
            submerged_weight_n_per_m: 10.59,
            hydrodynamic_constant: 0.6173,
            tangential_drag_coefficient: 0.01,
            normal_drag_coefficient: 2.12,
            total_length_m: 350,
            axial_stiffness_n: 1e9,
            max_water_depth_m: null,
            max_allowable_tension_n: null,
            min_bending_radius_m: null,
            initial_speed_mps: 0.5,
            final_speed_mps: 1.5,
            duration_s: 30,
            water_depth_m: 200,
            touchdown_tension_n: 0,
            current_u_mps: 0,
            current_v_mps: 0,
            vessel_speed_mps: null,
            payout_speed_mps: null,
            current_surface_mps: null,
          current_bottom_mps: null,
          current_direction_deg: null,
        },
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ cases }),
      }),
    );

    await expect(getCases("http://api.test")).resolves.toEqual(cases);
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/cases");
  });

  it("raises structured API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ error: "unknown_case", message: "Unknown case: missing" }),
      }),
    );

    await expect(runCase({ case_name: "missing", points: 17 }, "http://api.test")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "unknown_case",
      message: "Unknown case: missing",
    } satisfies Partial<ApiError>);
  });

  it("posts user-entered values to the custom calculation endpoint", async () => {
    const request: CustomCaseRequest = {
      ...minimalInputs("CUSTOM"),
      case_name: "custom_demo",
      points: 31,
      diameter_m: 0.05,
      water_depth_m: 120,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          case_name: "custom_demo",
          summary: {
            top_tension_initial_n: 1,
            top_tension_min_n: 1,
            top_tension_final_n: 1,
            suspended_length_m: 1,
            layback_m: 1,
          },
          artifacts: {
            summary_csv: "custom/custom_demo/summary.csv",
            profile_csv: "custom/custom_demo/profile.csv",
            profile_svg: "custom/custom_demo/profile.svg",
          },
        }),
      }),
    );

    await expect(runCustomCase(request, "http://api.test")).resolves.toMatchObject({
      case_name: "custom_demo",
    });
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/run-custom-case", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  });

  it("loads dynamic time-history cases from the backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          cases: [
            {
              name: "la_dynamic_accel_current_1p50",
              label: "LA｜加速时程，流速1.50 m/s",
              description: "多单元角运动时程",
              group: "LA dynamic",
              example: true,
              display_order: 10,
              suggested_output_dir: "time_histories/la-accel-current-1p50",
              inputs: {
                case_name: "la_dynamic_accel_current_1p50",
                current_speed_mps: 1.5,
                speed_change: "accel",
                initial_speed_mps: 0.5,
                final_speed_mps: 1.5,
                duration_s: 30,
                total_duration_s: 360,
                water_depth_m: 100,
                element_count: 32,
                current_direction_deg: 90,
                touchdown_tension_n: 0,
              },
            },
          ],
        }),
      }),
    );

    await expect(getTimeHistoryCases("http://api.test")).resolves.toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/time-history-cases");
  });

  it("posts named dynamic cases to the time-history endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          case_name: "la_dynamic_accel_current_1p50",
          summary: {
            current_speed_mps: 1.5,
            current_direction_deg: 90,
            speed_change: "accel",
            initial_speed_mps: 0.5,
            final_speed_mps: 1.5,
            payout_initial_speed_mps: 0.5,
            payout_final_speed_mps: 1.5,
            length_boundary_source: "xpbd_node_dynamics_contact_remesh",
            duration_s: 30,
            total_duration_s: 360,
            water_depth_m: 100,
            element_count: 32,
            touchdown_tension_n: 0,
            evidence_level:
              "node-coordinate XPBD dynamic laying with payout insertion, contact/friction, bottom remeshing, and XPBD/load-recursive segment tension diagnostics",
            initial_tension_n: 1164,
            extreme_tension_n: 1083,
            steady_tension_n: 1101,
          },
          artifacts: {
            time_summary_csv: "time_histories/la_dynamic_accel_current_1p50/time_summary.csv",
            time_history_csv: "time_histories/la_dynamic_accel_current_1p50/time_history.csv",
            time_history_svg: "time_histories/la_dynamic_accel_current_1p50/time_history.svg",
          },
          plot_data: {
            time_history: {
              source: "la_dynamic_xpbd_node_state",
              label: "动态张力时程",
              points: [{ time_s: 0, top_tension_n: 1164, tdp_x_m: 12, tdp_y_m: 95 }],
            },
          },
        }),
      }),
    );

    await expect(runTimeHistory({ case_name: "la_dynamic_accel_current_1p50", points: 31 }, "http://api.test")).resolves.toMatchObject({
      plot_data: {
        time_history: {
          source: "la_dynamic_xpbd_node_state",
        },
      },
    });
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/run-time-history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_name: "la_dynamic_accel_current_1p50", points: 31 }),
    });
  });

  it("posts full operator dynamic inputs to the time-history endpoint", async () => {
    const request = {
      case_name: "LA｜加速时程，流速1.25 m/s",
      points: 9,
      output_dir: "time_histories/la-operator-check",
      diameter_m: 0.0264,
      weight_air_n_per_m: 16.09,
      submerged_weight_n_per_m: 10.59,
      tangential_drag_coefficient: 0.01,
      normal_drag_coefficient: 2.12,
      axial_stiffness_n: 1e9,
      current_speed_mps: 1.25,
      current_direction_deg: 60,
      speed_change: "accel" as const,
      initial_speed_mps: 0.4,
      final_speed_mps: 1.1,
      duration_s: 20,
      total_duration_s: 80,
      water_depth_m: 90,
      element_count: 8,
      touchdown_tension_n: 100,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          case_name: request.case_name,
          summary: {
            diameter_m: 0.0264,
            weight_air_n_per_m: 16.09,
            submerged_weight_n_per_m: 10.59,
            tangential_drag_coefficient: 0.01,
            normal_drag_coefficient: 2.12,
            axial_stiffness_n: 1e9,
            current_speed_mps: 1.25,
            current_direction_deg: 60,
            speed_change: "accel",
            initial_speed_mps: 0.4,
            final_speed_mps: 1.1,
            payout_initial_speed_mps: 0.4,
            payout_final_speed_mps: 1.1,
            length_boundary_source: "xpbd_node_dynamics_contact_remesh",
            duration_s: 20,
            total_duration_s: 80,
            water_depth_m: 90,
            element_count: 8,
            touchdown_tension_n: 100,
            evidence_level:
              "node-coordinate XPBD dynamic laying with payout insertion, contact/friction, bottom remeshing, and XPBD/load-recursive segment tension diagnostics",
            initial_tension_n: 900,
            extreme_tension_n: 850,
            steady_tension_n: 870,
          },
          artifacts: {
            time_summary_csv: "time_histories/la-operator-check/time_summary.csv",
            time_history_csv: "time_histories/la-operator-check/time_history.csv",
            time_history_svg: "time_histories/la-operator-check/time_history.svg",
          },
          plot_data: {
            time_history: {
              source: "la_dynamic_xpbd_node_state",
              label: "动态张力时程",
              points: [{ time_s: 0, top_tension_n: 900, tdp_x_m: 12, tdp_y_m: 95 }],
            },
          },
        }),
      }),
    );

    await expect(runTimeHistory(request, "http://api.test")).resolves.toMatchObject({
      case_name: request.case_name,
      summary: { current_speed_mps: 1.25, water_depth_m: 90 },
    });
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/run-time-history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  });

  it("groups cases for the operator browser", () => {
    const grouped = groupCases([
      exampleCase("power_current_speed_0p50", "500kV", "500kV 电力缆｜流速 0.50 m/s", false, 5),
      exampleCase("power_current_speed_1p50", "500kV", "500kV 电力缆｜流速 1.50 m/s", true, 30),
      exampleCase("la_accel_200m", "LA", "LA 信号缆｜加速铺设 200 m", true, 10),
      exampleCase("ha_decel_200m", "HA", "HA 信号缆｜减速铺设 200 m", true, 20),
    ]);

    expect(grouped.map((group) => group.label)).toEqual(["LA", "HA", "500kV"]);
    expect(grouped[0].cases[0].name).toBe("la_accel_200m");
    expect(grouped[2].cases.map((item) => item.name)).toEqual(["power_current_speed_1p50"]);
  });
});

function exampleCase(name: string, group: string, label: string, example: boolean, displayOrder: number): CableCase {
  return {
    name,
    label,
    description: `${label}说明`,
    group,
    example,
    display_order: displayOrder,
    suggested_output_dir: `custom/${name.replace(/_/g, "-")}`,
    inputs: minimalInputs(group === "500kV" ? "POWER_500KV" : group),
  };
}

function minimalInputs(cable: string): CableCase["inputs"] {
  return {
    cable,
    solver_model: cable === "POWER_500KV" ? "power_500kv" : "generic",
    diameter_m: 0,
    weight_air_n_per_m: 0,
    submerged_weight_n_per_m: 0,
    hydrodynamic_constant: 0,
    tangential_drag_coefficient: 0,
    normal_drag_coefficient: 0,
    total_length_m: 0,
    axial_stiffness_n: 1e9,
    max_water_depth_m: null,
    max_allowable_tension_n: null,
    min_bending_radius_m: null,
    initial_speed_mps: 0,
    final_speed_mps: 0,
    duration_s: 0,
    water_depth_m: 0,
    touchdown_tension_n: 0,
    current_u_mps: 0,
    current_v_mps: 0,
    vessel_speed_mps: null,
    payout_speed_mps: null,
    current_surface_mps: null,
    current_bottom_mps: null,
    current_direction_deg: null,
  };
}

function minimalTimeHistoryInputs() {
  return {
    case_name: "realtime_baseline",
    diameter_m: 0.0264,
    weight_air_n_per_m: 16.09,
    submerged_weight_n_per_m: 10.59,
    tangential_drag_coefficient: 0.01,
    normal_drag_coefficient: 2.12,
    axial_stiffness_n: 1e9,
    current_speed_mps: 0.35,
    current_direction_deg: 90,
    speed_change: "steady" as const,
    initial_speed_mps: 0.8,
    final_speed_mps: 0.8,
    payout_initial_speed_mps: 0.8,
    payout_final_speed_mps: 0.8,
    length_boundary_source: "known_plough_trajectory",
    duration_s: 3600,
    total_duration_s: 3600,
    water_depth_m: 80,
    element_count: 24,
    touchdown_tension_n: 0,
    vessel_initial_x_m: 0,
    vessel_initial_y_m: 0,
    vessel_heading_deg: 0,
    plough_initial_x_m: -55,
    plough_initial_y_m: 0,
    plough_initial_z_m: 80,
    plough_speed_mps: 0.8,
    plough_exit_speed_mps: 0.8,
    plough_heading_deg: 0,
  };
}

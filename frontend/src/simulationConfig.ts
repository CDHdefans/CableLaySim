import type { DynamicTimeHistoryForm, TimeHistoryCase } from "./types";

export type ConsoleModule = "parameters" | "simulation" | "tension";
export type SpeedChange = "steady" | "accel" | "decel";

// 默认连接本机后端；部署或联调其他地址时可通过 VITE_API_BASE_URL 覆盖。
export const DEFAULT_DYNAMIC_FORM: DynamicTimeHistoryForm = {
  case_name: "常规基准",
  points: 361,
  output_dir: "time_histories/plough-straight-baseline",
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
  final_speed_mps: 0.8,
  payout_initial_speed_mps: 0.88,
  payout_final_speed_mps: 0.88,
  length_boundary_source: "known_plough_trajectory",
  duration_s: 360,
  total_duration_s: 360,
  water_depth_m: 80,
  element_count: 24,
  touchdown_tension_n: 200,
  vessel_initial_x_m: 0,
  vessel_initial_y_m: 0,
  vessel_heading_deg: 0,
  plough_initial_x_m: -55,
  plough_initial_y_m: 0,
  plough_initial_z_m: 80,
  plough_speed_mps: 0.75,
  plough_heading_deg: 0,
  initial_suspended_length_m: 100,
  vessel_motion_segments: [
    {
      duration_s: 360,
      start_speed_mps: 0.8,
      end_speed_mps: 0.8,
      heading_deg: 0,
      start_velocity_x_mps: 0.8,
      start_velocity_y_mps: 0,
      end_velocity_x_mps: 0.8,
      end_velocity_y_mps: 0,
    },
  ],
  plough_motion_segments: [
    {
      duration_s: 360,
      start_speed_mps: 0.75,
      end_speed_mps: 0.75,
      heading_deg: 0,
      start_velocity_x_mps: 0.75,
      start_velocity_y_mps: 0,
      end_velocity_x_mps: 0.75,
      end_velocity_y_mps: 0,
    },
  ],
  payout_speed_segments: [
    { duration_s: 360, start_speed_mps: 0.88, end_speed_mps: 0.88 },
  ],
  min_bending_radius_m: null,
};

export const SPEED_CHANGE_OPTIONS: { value: SpeedChange; label: string }[] = [
  { value: "steady", label: "匀速" },
  { value: "accel", label: "加速" },
  { value: "decel", label: "减速" },
];

export function groupTimeHistoryCases(cases: TimeHistoryCase[]): { label: string; cases: TimeHistoryCase[] }[] {
  const groups = new Map<string, TimeHistoryCase[]>();
  cases.forEach((item) => {
    const existing = groups.get(item.group) ?? [];
    existing.push(item);
    groups.set(item.group, existing);
  });
  return Array.from(groups.entries()).map(([label, groupCases]) => ({ label, cases: groupCases }));
}

export function labelForTimeHistoryCase(caseName: string, timeHistoryCases: TimeHistoryCase[]): string {
  return timeHistoryCases.find((item) => item.name === caseName)?.label ?? caseName;
}

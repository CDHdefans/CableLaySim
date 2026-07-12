import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, { isCurrentRealtimeRequest, realtimeScheduleDelayMs } from "./App";
import type { CableCase, TimeHistoryCase } from "./types";

const apiMock = vi.hoisted(() => {
  class MockApiError extends Error {
    readonly status: number;
    readonly code: string;

    constructor(status: number, code: string, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
    }
  }

  return {
    ApiError: MockApiError,
    advanceRealtimeSession: vi.fn(),
    DEFAULT_API_BASE: "http://api.test",
    buildFileUrl: vi.fn((path: string) => `http://files.test/${path}`),
    createRealtimeSession: vi.fn(),
    deleteRealtimeSession: vi.fn(),
    getRealtimeSession: vi.fn(),
    getCases: vi.fn(),
    getHealth: vi.fn(),
    getTimeHistoryCases: vi.fn(),
    groupCases: vi.fn(),
    runCustomCase: vi.fn(),
    runTimeHistory: vi.fn(),
  };
});

vi.mock("./api", () => apiMock);

const staticCases: CableCase[] = [
  {
    name: "power_current_speed_1p50",
    label: "500kV｜水深100 m、流速1.50 m/s",
    description: "旧静态剖面算例，不应出现在当前仿真平台入口。",
    group: "500kV",
    example: true,
    display_order: 30,
    suggested_output_dir: "custom/500kv-standard-current-1p50",
    inputs: {
      cable: "500kV 电力缆",
      solver_model: "power_500kv",
      diameter_m: 0.139,
      weight_air_n_per_m: 470.4,
      submerged_weight_n_per_m: 313.6,
      hydrodynamic_constant: 0,
      tangential_drag_coefficient: 0,
      normal_drag_coefficient: 1,
      total_length_m: 160,
      axial_stiffness_n: 1e9,
      max_water_depth_m: 100,
      max_allowable_tension_n: 87500,
      min_bending_radius_m: 5,
      initial_speed_mps: 0.5,
      final_speed_mps: 0.5,
      duration_s: 0,
      water_depth_m: 100,
      touchdown_tension_n: 1500,
      current_u_mps: 0,
      current_v_mps: 0,
      vessel_speed_mps: 0.5,
      payout_speed_mps: 0.5,
      current_surface_mps: 1.5,
      current_bottom_mps: 0.5,
      current_direction_deg: 90,
    },
  },
];

const timeHistoryCases: TimeHistoryCase[] = [
  routeScenario({
    name: "plough_straight_baseline_6min",
    label: "常规基准",
    description: "船、放缆和埋设犁稳定同步前进，用作其他对比的基准。",
    display_order: 10,
    suggested_output_dir: "time_histories/plough-straight-baseline",
  }),
  routeScenario({
    name: "plough_straight_low_speed_6min",
    label: "低速铺埋",
    description: "只降低船速、放缆速度和犁速，观察悬垂形态和张力变化。",
    display_order: 20,
    suggested_output_dir: "time_histories/plough-straight-low-speed",
    initial_speed_mps: 0.6,
    final_speed_mps: 0.6,
    payout_initial_speed_mps: 0.66,
    payout_final_speed_mps: 0.66,
    plough_speed_mps: 0.55,
  }),
  routeScenario({
    name: "plough_straight_high_speed_6min",
    label: "高速铺埋",
    description: "只提高船速、放缆速度和犁速，观察速度敏感性。",
    display_order: 30,
    suggested_output_dir: "time_histories/plough-straight-high-speed",
    initial_speed_mps: 1,
    final_speed_mps: 1,
    payout_initial_speed_mps: 1.1,
    payout_final_speed_mps: 1.1,
    plough_speed_mps: 0.95,
  }),
  routeScenario({
    name: "plough_straight_low_tdp_tension_6min",
    label: "低触地张力",
    description: "只降低触地点张力，观察入口张力、TDP 和悬垂形态变化。",
    display_order: 40,
    suggested_output_dir: "time_histories/plough-straight-low-tdp-tension",
    touchdown_tension_n: 100,
  }),
  routeScenario({
    name: "plough_straight_high_tdp_tension_6min",
    label: "高触地张力",
    description: "只提高触地点张力，观察张力分布和悬垂形态变化。",
    display_order: 50,
    suggested_output_dir: "time_histories/plough-straight-high-tdp-tension",
    touchdown_tension_n: 400,
  }),
  routeScenario({
    name: "plough_cross_current_0p50_90deg_6min",
    label: "横流0.50 m/s",
    description: "固定铺埋速度，施加垂向来流，观察侧偏和张力分布。",
    group: "横流偏载",
    display_order: 110,
    suggested_output_dir: "time_histories/plough-cross-current-0p50-90deg",
    current_speed_mps: 0.5,
  }),
  routeScenario({
    name: "plough_cross_current_0p95_90deg_6min",
    label: "横流0.95 m/s",
    description: "只提高横向海流速度，对比流速大小的影响。",
    group: "横流偏载",
    display_order: 120,
    suggested_output_dir: "time_histories/plough-cross-current-0p95-90deg",
    current_speed_mps: 0.95,
  }),
  routeScenario({
    name: "plough_cross_current_0p95_60deg_6min",
    label: "来流60°",
    description: "保持流速不变，将来流方向改为 60°。",
    group: "横流偏载",
    display_order: 130,
    suggested_output_dir: "time_histories/plough-cross-current-0p95-60deg",
    current_speed_mps: 0.95,
    current_direction_deg: 60,
  }),
  routeScenario({
    name: "plough_cross_current_0p95_30deg_6min",
    label: "来流30°",
    description: "保持流速不变，将来流方向改为 30°。",
    group: "横流偏载",
    display_order: 140,
    suggested_output_dir: "time_histories/plough-cross-current-0p95-30deg",
    current_speed_mps: 0.95,
    current_direction_deg: 30,
  }),
  routeScenario({
    name: "plough_cross_current_0p95_0deg_6min",
    label: "来流0°",
    description: "保持流速不变，将来流方向改为顺铺埋方向。",
    group: "横流偏载",
    display_order: 150,
    suggested_output_dir: "time_histories/plough-cross-current-0p95-0deg",
    current_speed_mps: 0.95,
    current_direction_deg: 0,
  }),
  routeScenario({
    name: "plough_decel_mild_6min",
    label: "温和减速",
    description: "船端、放缆和犁端同步减速，观察顶张力峰值和回落。",
    group: "控速减速",
    display_order: 210,
    suggested_output_dir: "time_histories/plough-decel-mild",
    speed_change: "decel",
    initial_speed_mps: 0.9,
    final_speed_mps: 0.7,
    payout_initial_speed_mps: 0.98,
    payout_final_speed_mps: 0.78,
    duration_s: 90,
    plough_speed_mps: 0.65,
  }),
  routeScenario({
    name: "plough_decel_strong_6min",
    label: "强减速",
    description: "提高减速幅度，检查动态峰值和 TDP 迁移。",
    group: "控速减速",
    display_order: 220,
    suggested_output_dir: "time_histories/plough-decel-strong",
    speed_change: "decel",
    initial_speed_mps: 1.1,
    final_speed_mps: 0.55,
    payout_initial_speed_mps: 1.18,
    payout_final_speed_mps: 0.65,
    duration_s: 90,
    plough_speed_mps: 0.55,
  }),
  routeScenario({
    name: "plough_decel_long_6min",
    label: "长历时减速",
    description: "用更长减速历时释放加速度冲击，观察峰值是否降低。",
    group: "控速减速",
    display_order: 230,
    suggested_output_dir: "time_histories/plough-decel-long",
    speed_change: "decel",
    initial_speed_mps: 0.9,
    final_speed_mps: 0.6,
    payout_initial_speed_mps: 0.98,
    payout_final_speed_mps: 0.7,
    duration_s: 180,
    plough_speed_mps: 0.6,
  }),
  routeScenario({
    name: "plough_payout_matched_6min",
    label: "同步放缆",
    description: "放缆速度与犁速相同，用作放缆偏差基准。",
    group: "放缆偏快",
    display_order: 310,
    suggested_output_dir: "time_histories/plough-payout-matched",
    payout_initial_speed_mps: 0.8,
    payout_final_speed_mps: 0.8,
    plough_speed_mps: 0.8,
  }),
  routeScenario({
    name: "plough_payout_fast_1p10_6min",
    label: "放缆快10%",
    description: "放缆速度略高于犁速，观察悬垂段增长。",
    group: "放缆偏快",
    display_order: 320,
    suggested_output_dir: "time_histories/plough-payout-fast-1p10",
    payout_initial_speed_mps: 0.88,
    payout_final_speed_mps: 0.88,
    plough_speed_mps: 0.8,
  }),
  routeScenario({
    name: "plough_payout_fast_1p25_6min",
    label: "放缆快25%",
    description: "进一步提高放缆速度，检查入口张力和形态变化。",
    group: "放缆偏快",
    display_order: 330,
    suggested_output_dir: "time_histories/plough-payout-fast-1p25",
    payout_initial_speed_mps: 1,
    payout_final_speed_mps: 1,
    plough_speed_mps: 0.8,
  }),
  routeScenario({
    name: "plough_material_la_6min",
    label: "LA 信号缆",
    description: "同一船端和犁端轨迹下采用 LA 信号缆参数，作为缆型对比基准。",
    group: "信号缆与电力缆",
    display_order: 410,
    suggested_output_dir: "time_histories/plough-material-la",
  }),
  routeScenario({
    name: "plough_material_ha_6min",
    label: "HA 信号缆",
    description: "只把缆型参数改为 HA 信号缆，观察单位重、直径和阻力系数改变后的张力与形态。",
    group: "信号缆与电力缆",
    display_order: 420,
    suggested_output_dir: "time_histories/plough-material-ha",
    diameter_m: 0.0332,
    weight_air_n_per_m: 25.8,
    submerged_weight_n_per_m: 17.8,
  }),
  routeScenario({
    name: "plough_material_power_500kv_6min",
    label: "500 kV 电力缆",
    description: "只把缆型参数改为 500 kV 电力缆，观察重型电力缆在同一运动边界下的张力与形态。",
    group: "信号缆与电力缆",
    display_order: 430,
    suggested_output_dir: "time_histories/plough-material-power-500kv",
    diameter_m: 0.139,
    weight_air_n_per_m: 470.4,
    submerged_weight_n_per_m: 313.6,
    min_bending_radius_m: 5,
  }),
  {
    name: "la_dynamic_accel_current_1p50",
    label: "LA｜旧动态复现例子",
    description: "旧论文复现动态入口，不应出现在当前仿真平台入口。",
    group: "动态时程",
    example: true,
    display_order: 10,
    suggested_output_dir: "time_histories/la-accel-current-1p50",
    inputs: {
      case_name: "la_dynamic_accel_current_1p50",
      diameter_m: 0.0264,
      weight_air_n_per_m: 16.09,
      submerged_weight_n_per_m: 10.59,
      tangential_drag_coefficient: 0.01,
      normal_drag_coefficient: 2.12,
      axial_stiffness_n: 1e9,
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
    },
  },
];

function routeScenario(
  overrides: Partial<TimeHistoryCase["inputs"]> &
    Pick<TimeHistoryCase, "name" | "label" | "description" | "display_order" | "suggested_output_dir"> &
    Partial<Pick<TimeHistoryCase, "group">>,
): TimeHistoryCase {
  return {
    name: overrides.name,
    label: overrides.label,
    description: overrides.description,
    group: overrides.group ?? "常规直线铺埋",
    example: true,
    display_order: overrides.display_order,
    suggested_output_dir: overrides.suggested_output_dir,
    inputs: {
      case_name: overrides.name,
      diameter_m: overrides.diameter_m ?? 0.0264,
      weight_air_n_per_m: overrides.weight_air_n_per_m ?? 16.09,
      submerged_weight_n_per_m: overrides.submerged_weight_n_per_m ?? 10.59,
      tangential_drag_coefficient: overrides.tangential_drag_coefficient ?? 0.01,
      normal_drag_coefficient: overrides.normal_drag_coefficient ?? 2.12,
      axial_stiffness_n: overrides.axial_stiffness_n ?? 1e9,
      current_speed_mps: overrides.current_speed_mps ?? 0.35,
      current_direction_deg: overrides.current_direction_deg ?? 90,
      speed_change: overrides.speed_change ?? "steady",
      initial_speed_mps: overrides.initial_speed_mps ?? 0.8,
      final_speed_mps: overrides.final_speed_mps ?? 0.8,
      payout_initial_speed_mps: overrides.payout_initial_speed_mps ?? 0.88,
      payout_final_speed_mps: overrides.payout_final_speed_mps ?? 0.88,
      length_boundary_source: "known_plough_trajectory",
      duration_s: overrides.duration_s ?? 360,
      total_duration_s: 360,
      water_depth_m: overrides.water_depth_m ?? 80,
      element_count: overrides.element_count ?? 24,
      touchdown_tension_n: overrides.touchdown_tension_n ?? 200,
      vessel_initial_x_m: 0,
      vessel_initial_y_m: 0,
      vessel_heading_deg: 0,
      plough_initial_x_m: -55,
      plough_initial_y_m: 0,
      plough_initial_z_m: overrides.plough_initial_z_m ?? overrides.water_depth_m ?? 80,
      plough_speed_mps: overrides.plough_speed_mps ?? 0.75,
      plough_heading_deg: 0,
      min_bending_radius_m: overrides.min_bending_radius_m ?? null,
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getHealth.mockResolvedValue({
    status: "ok",
    service: "cable-tension-backend",
    output_root: "E:/project/backend/output",
  });
  apiMock.getCases.mockResolvedValue(staticCases);
  apiMock.getTimeHistoryCases.mockResolvedValue(timeHistoryCases);
});

describe("App", () => {
  it("schedules packets against absolute 5 s deadlines", () => {
    expect(realtimeScheduleDelayMs(1_000, 1, 1_000)).toBe(5_000);
    expect(realtimeScheduleDelayMs(1_000, 2, 6_300)).toBe(4_700);
    expect(realtimeScheduleDelayMs(1_000, 2, 12_000)).toBe(0);
  });

  it("does not let a stale request generation own a replacement session", () => {
    expect(isCurrentRealtimeRequest(1, 2, "old", "new")).toBe(false);
    expect(isCurrentRealtimeRequest(2, 2, "old", "new")).toBe(false);
    expect(isCurrentRealtimeRequest(2, 2, "new", "new")).toBe(true);
  });
  it("starts and stops one persistent 5 s realtime session", async () => {
    apiMock.createRealtimeSession.mockResolvedValue(realtimeFramePayload());
    apiMock.deleteRealtimeSession.mockResolvedValue(undefined);
    render(<App />);
    await screen.findByText("后端在线");

    fireEvent.click(screen.getByRole("button", { name: "5 s 准实时" }));
    fireEvent.click(screen.getByRole("button", { name: "启动实时会话" }));

    await waitFor(() => expect(apiMock.createRealtimeSession).toHaveBeenCalledTimes(1));
    expect(apiMock.createRealtimeSession).toHaveBeenCalledWith(
      expect.objectContaining({
        case_name: "常规基准",
        max_sensor_gap_s: 5.5,
        max_data_age_s: 6,
        initial_packet: expect.objectContaining({
          sequence: 0,
          time_s: 0,
          quality: "valid",
          payout_speed_mps: 0.88,
          plough_exit_speed_mps: 0.75,
        }),
      }),
      "http://api.test",
    );
    await expect(screen.findByLabelText("准实时计算结果")).resolves.toBeInTheDocument();
    expect(screen.getByText("船端张力")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "停止会话" }));
    await waitFor(() => expect(apiMock.deleteRealtimeSession).toHaveBeenCalledWith("session-1", "http://api.test"));
    expect(screen.getByRole("button", { name: "会话已停止" })).toBeDisabled();
  });

  it("loads the simulation console with a left parameter panel and current route scenarios", async () => {
    render(<App />);

    expect(screen.getByText("CableLaySim")).toBeInTheDocument();
    expect(screen.getByText("铺缆船仿真分析系统")).toBeInTheDocument();
    await expect(screen.findByText("后端在线")).resolves.toBeInTheDocument();

    expect(apiMock.getCases).not.toHaveBeenCalled();
    expect(apiMock.groupCases).not.toHaveBeenCalled();
    expect(screen.queryByText(/500kV/)).not.toBeInTheDocument();
    expect(screen.queryByText("LA｜旧动态复现例子")).not.toBeInTheDocument();
    expect(screen.queryByText("三维剖面计算")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("计算模型")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "运行计算" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "输入卡片" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "输出卡片" })).not.toBeInTheDocument();

    const consoleRail = screen.getByLabelText("仿真控制台");
    expect(within(consoleRail).getByRole("button", { name: "仿真参数设置" })).toHaveAttribute("aria-pressed", "true");
    expect(within(consoleRail).queryByLabelText("计算名称")).not.toBeInTheDocument();
    expect(within(consoleRail).queryByLabelText("均匀海流速度 m/s")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仿真视图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "缆线张力" })).toBeDisabled();
    expect(screen.getByLabelText("参数设置界面")).toBeInTheDocument();
    expect(screen.getByLabelText("仿真参数设置")).toBeInTheDocument();
    expect(screen.getByText("工况模板")).toBeInTheDocument();
    expect(screen.getByText("1 类 / 14 组")).toBeInTheDocument();
    expect(screen.getByText("材料选择")).toBeInTheDocument();
    expect(screen.getByText("3 类")).toBeInTheDocument();
    expect(screen.queryByText(/填入时程参数/)).not.toBeInTheDocument();
    const exampleRail = screen.getByLabelText("工况模板");
    const materialRail = screen.getByLabelText("材料选择");
    expect(within(exampleRail).queryByText("材料参数")).not.toBeInTheDocument();
    expect(within(exampleRail).getByText("环境/运动参数")).toBeInTheDocument();
    expect(within(materialRail).getByText("缆型/材料参数")).toBeInTheDocument();
    expect(within(exampleRail).queryByRole("heading", { name: "常规直线铺埋" })).not.toBeInTheDocument();
    expect(within(exampleRail).queryByRole("heading", { name: "横流偏载" })).not.toBeInTheDocument();
    expect(within(exampleRail).queryByRole("heading", { name: "控速减速" })).not.toBeInTheDocument();
    expect(within(exampleRail).queryByRole("table", { name: "工况参数对比" })).not.toBeInTheDocument();
    expect(screen.queryByText("工况参数对比")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /常规基准/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /低速铺埋/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /触地张力/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /强横流偏载/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /斜向来流/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /小角度来流/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /强减速/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /明显放缆偏快/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /顺向来流/ })).toBeInTheDocument();
    expect(within(materialRail).getByRole("button", { name: /LA 信号缆/ })).toBeInTheDocument();
    expect(within(materialRail).getByRole("button", { name: /HA 信号缆/ })).toBeInTheDocument();
    expect(within(materialRail).getByRole("button", { name: /电力缆/ })).toBeInTheDocument();
    expect(within(exampleRail).queryByRole("button", { name: /LA 信号缆/ })).not.toBeInTheDocument();
    expect(within(exampleRail).queryByRole("button", { name: /HA 信号缆/ })).not.toBeInTheDocument();
    expect(within(exampleRail).queryByRole("button", { name: /电力缆/ })).not.toBeInTheDocument();
    within(exampleRail)
      .getAllByRole("button")
      .forEach((button) => {
        expect(button.textContent).not.toMatch(/\d+(?:\.\d+)?\s*(?:m\/s|N|deg|°|%|kV)/i);
      });
    within(materialRail)
      .getAllByRole("button")
      .forEach((button) => {
        expect(button.textContent).not.toMatch(/\d+(?:\.\d+)?\s*(?:m\/s|N|deg|°|%|kV)/i);
      });
    expect(within(exampleRail).queryByText("来流方向")).not.toBeInTheDocument();
    expect(within(exampleRail).queryByText("90 -> 60 deg")).not.toBeInTheDocument();
    expect(within(exampleRail).queryByText("90 -> 30 deg")).not.toBeInTheDocument();
    expect(within(exampleRail).queryByText("90 -> 0 deg")).not.toBeInTheDocument();
    expect(within(exampleRail).queryByText("200 -> 400 N")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行仿真" })).toBeInTheDocument();
    expect(screen.getByLabelText("计算名称")).toHaveValue("常规基准");
    expect(screen.getByLabelText("计算时长 s")).toHaveValue(360);
    expect(screen.getByLabelText("输出帧数（不改变内部积分步长）")).toHaveValue(361);
    expect(screen.getByLabelText("缆线离散单元数")).toHaveValue(24);
    expect(screen.getByLabelText("匀速段 1时长 s")).toHaveValue(360);
    expect(screen.queryByText("第2段")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("触地点张力 N")).not.toBeInTheDocument();
    expect(screen.getByLabelText("缆径 m")).toHaveValue(0.0264);
    expect(screen.getByLabelText("水中单位重 N/m")).toHaveValue(10.59);
    expect(screen.getByLabelText("法向阻力系数 Cn")).toHaveValue(2.12);
    expect(screen.getByLabelText("轴向刚度 EA N")).toHaveValue(1000000000);
    expect(screen.getByLabelText("船端初始作业坐标 Y m")).toHaveValue(0);
    expect(screen.getByLabelText("犁入口初始作业坐标 X m")).toHaveValue(-55);
    expect(screen.getByLabelText("犁入口初始作业坐标 Y m")).toHaveValue(0);
    expect(screen.getByLabelText("犁入口速度第1段段首纵向速度 uX m/s")).toHaveValue(0.75);
  });

  it("keeps material selection separate from environment templates", async () => {
    render(<App />);

    await screen.findByText("后端在线");
    const materialRail = screen.getByLabelText("材料选择");

    fireEvent.click(within(materialRail).getByRole("button", { name: /HA 信号缆/ }));
    expect(screen.getByLabelText("计算名称")).toHaveValue("常规基准");
    expect(screen.getByLabelText("缆径 m")).toHaveValue(0.0332);
    expect(screen.getByLabelText("空气中单位重 N/m")).toHaveValue(25.8);
    expect(screen.getByLabelText("水中单位重 N/m")).toHaveValue(17.8);
    expect(screen.getByLabelText("均匀海流速度 m/s")).toHaveValue(0.35);
    expect(screen.getByLabelText("犁入口速度第1段段首纵向速度 uX m/s")).toHaveValue(0.75);

    fireEvent.click(screen.getByRole("button", { name: /斜向来流/ }));
    expect(screen.getByLabelText("计算名称")).toHaveValue("来流60°");
    expect(screen.getByLabelText("均匀海流速度 m/s")).toHaveValue(0.95);
    expect(screen.getByLabelText("海流去向角 deg（0=作业纵向+X）")).toHaveValue(60);
    expect(screen.getByLabelText("缆径 m")).toHaveValue(0.0332);
    expect(screen.getByLabelText("空气中单位重 N/m")).toHaveValue(25.8);
    expect(screen.getByLabelText("水中单位重 N/m")).toHaveValue(17.8);
  });

  it("uses one steady stage for baseline and two synchronized stages only for ramp-and-hold cases", async () => {
    render(<App />);
    await screen.findByText("后端在线");

    expect(screen.getByLabelText("匀速段 1时长 s")).toHaveValue(360);
    expect(screen.queryByLabelText("匀速段 2时长 s")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /强减速/ }));
    expect(screen.getByLabelText("变速段 1时长 s")).toHaveValue(90);
    expect(screen.getByLabelText("匀速段 2时长 s")).toHaveValue(270);

    fireEvent.change(screen.getByLabelText("计算时长 s"), { target: { value: "480" } });
    expect(screen.getByLabelText("变速段 1时长 s")).toHaveValue(90);
    expect(screen.getByLabelText("匀速段 2时长 s")).toHaveValue(270);

    fireEvent.change(screen.getByLabelText("计算时长 s"), { target: { value: "60" } });
    expect(screen.getByLabelText("计算时长 s")).toHaveValue(60);
    expect(screen.getByLabelText("变速段 1时长 s")).toHaveValue(90);
    expect(screen.getByLabelText("匀速段 2时长 s")).toHaveValue(270);
    expect(screen.getByText("计算至本段 60.0 s")).toBeInTheDocument();
    expect(screen.getByText("本次不计算")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("变速段 1时长 s"), { target: { value: "120" } });
    expect(screen.getByLabelText("变速段 1时长 s")).toHaveValue(120);
    expect(screen.getByLabelText("船端导缆点速度第1段段首纵向速度 uX m/s")).toBeInTheDocument();
    expect(screen.getByLabelText("犁入口速度第1段段首纵向速度 uX m/s")).toBeInTheDocument();
    expect(screen.getByLabelText("放缆第1段段首速度 qf m/s")).toBeInTheDocument();
  });

  it("uses visible measured longitudinal and transverse velocities to run the known-plough dynamic solver", async () => {
    apiMock.runTimeHistory.mockResolvedValue(knownPloughTimeHistoryPayload());
    render(<App />);

    await screen.findByText("后端在线");
    fireEvent.change(screen.getByLabelText("输出帧数（不改变内部积分步长）"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("缆径 m"), { target: { value: "0.04" } });
    fireEvent.change(screen.getByLabelText("水中单位重 N/m"), { target: { value: "18.5" } });
    fireEvent.change(screen.getByLabelText("均匀海流速度 m/s"), { target: { value: "0.55" } });
    fireEvent.change(screen.getByLabelText("计算时长 s"), { target: { value: "480" } });
    fireEvent.change(screen.getByLabelText("船端导缆点速度第1段段末纵向速度 uX m/s"), { target: { value: "1.2" } });
    fireEvent.change(screen.getByLabelText("船端导缆点速度第1段段末横向速度 vY m/s"), { target: { value: "1.2" } });
    fireEvent.change(screen.getByLabelText("犁入口速度第1段段末纵向速度 uX m/s"), { target: { value: "0.82" } });
    fireEvent.change(screen.getByLabelText("犁入口速度第1段段末横向速度 vY m/s"), { target: { value: "0.82" } });
    fireEvent.change(screen.getByLabelText("放缆第1段段末速度 qf m/s"), { target: { value: "1.25" } });
    fireEvent.change(screen.getByLabelText("犁出口材料速度 q_p m/s（实测，可选）"), { target: { value: "0.52" } });
    fireEvent.click(screen.getByRole("button", { name: "运行仿真" }));

    await waitFor(() => expect(apiMock.runTimeHistory).toHaveBeenCalledTimes(1));
    expect(apiMock.runCustomCase).not.toHaveBeenCalled();
    expect(apiMock.runTimeHistory).toHaveBeenCalledWith(
      expect.objectContaining({
        case_name: "常规基准",
        points: 9,
        diameter_m: 0.04,
        weight_air_n_per_m: 16.09,
        submerged_weight_n_per_m: 18.5,
        tangential_drag_coefficient: 0.01,
        normal_drag_coefficient: 2.12,
        axial_stiffness_n: 1e9,
        current_speed_mps: 0.55,
        speed_change: "accel",
        initial_speed_mps: 0.8,
        final_speed_mps: 1.697056274847714,
        payout_initial_speed_mps: 0.88,
        payout_final_speed_mps: 1.25,
        length_boundary_source: "known_plough_trajectory",
        duration_s: 360,
        total_duration_s: 480,
        element_count: 24,
        plough_initial_x_m: -55,
        plough_initial_y_m: 0,
        plough_initial_z_m: 80,
        vessel_heading_deg: 0,
        plough_speed_mps: 1.159655121145938,
        plough_heading_deg: 0,
        plough_exit_speed_mps: 0.52,
        vessel_motion_segments: [
          {
            duration_s: 360,
            start_speed_mps: 0.8,
            end_speed_mps: 1.697056274847714,
            heading_deg: 0,
            start_velocity_x_mps: 0.8,
            start_velocity_y_mps: 0,
            end_velocity_x_mps: 1.2,
            end_velocity_y_mps: 1.2,
          },
        ],
        plough_motion_segments: [
          {
            duration_s: 360,
            start_speed_mps: 0.75,
            end_speed_mps: 1.159655121145938,
            heading_deg: 0,
            start_velocity_x_mps: 0.75,
            start_velocity_y_mps: 0,
            end_velocity_x_mps: 0.82,
            end_velocity_y_mps: 0.82,
          },
        ],
        payout_speed_segments: [
          { duration_s: 360, start_speed_mps: 0.88, end_speed_mps: 1.25 },
        ],
      }),
      "http://api.test",
    );
  });

  it("fills the cross-current route case from examples", async () => {
    render(<App />);

    await screen.findByText("后端在线");
    fireEvent.click(screen.getByRole("button", { name: /斜向来流/ }));

    expect(screen.getByLabelText("计算名称")).toHaveValue("来流60°");
    expect(screen.getByLabelText("均匀海流速度 m/s")).toHaveValue(0.95);
    expect(screen.getByLabelText("海流去向角 deg（0=作业纵向+X）")).toHaveValue(60);
    expect(screen.getByLabelText("计算时长 s")).toHaveValue(360);
    expect(screen.getByLabelText("缆线离散单元数")).toHaveValue(24);
    expect(screen.getByLabelText("犁入口速度第1段段首纵向速度 uX m/s")).toHaveValue(0.75);
  });

  it("runs from the parameter panel, opens the simulation view, and exposes only cable tension analysis", async () => {
    apiMock.runTimeHistory.mockResolvedValue(knownPloughTimeHistoryPayload());
    render(<App />);

    await screen.findByText("后端在线");
    expect(screen.getByRole("button", { name: "仿真参数设置" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("均匀海流速度 m/s")).toBeInTheDocument();
    expect(screen.queryByText("三维仿真运动")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "运行仿真" }));

    await expect(screen.findByRole("button", { name: "仿真视图" })).resolves.toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("三维仿真运动")).toBeInTheDocument();
    expect(screen.queryByLabelText("均匀海流速度 m/s")).not.toBeInTheDocument();
    expect(screen.getByText("铺缆船")).toBeInTheDocument();
    expect(screen.getByText("埋设犁")).toBeInTheDocument();
    expect(screen.getByText("犁端运动轨迹")).toBeInTheDocument();
    expect(screen.getByText("犁出口材料速度 0.55 m/s（无滑移推定）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "缆线张力" })).not.toBeDisabled();
    expect(screen.getByLabelText("缆线张力分析")).toBeInTheDocument();
    expect(screen.getAllByText("犁入口张力").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("0.95 kN")).toBeInTheDocument();
    expect(screen.getByText("最小弯曲半径")).toBeInTheDocument();
    expect(screen.getAllByText("12.40 m").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("弯曲半径裕度")).toBeInTheDocument();
    expect(screen.getByText("+2.40 m")).toBeInTheDocument();
    expect(screen.getByText("弯曲状态")).toBeInTheDocument();
    expect(screen.getByText("当前口径未低于限值")).toBeInTheDocument();
    expect(screen.getByText("风险与可信度")).toBeInTheDocument();
    expect(screen.getByText("边界张力已传入相邻段")).toBeInTheDocument();
    expect(screen.getByText("Rmin 原始值")).toBeInTheDocument();
    expect(screen.getByText("2.10 m")).toBeInTheDocument();
    expect(screen.getByText("0.050-0.200 s")).toBeInTheDocument();
    expect(screen.getByText("已知埋设犁轨迹")).toBeInTheDocument();
    expect(screen.getByText("每段张力随时间输出")).toBeInTheDocument();
    expect(screen.getByText("时程 CSV")).toBeInTheDocument();
    expect(screen.queryByText("受力分析")).not.toBeInTheDocument();
    expect(screen.queryByText("位置轨迹")).not.toBeInTheDocument();
    expect(screen.queryByText("环境数据")).not.toBeInTheDocument();
    expect(screen.queryByText("报告导出")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "仿真参数设置" }));
    expect(screen.getByRole("button", { name: "仿真参数设置" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("均匀海流速度 m/s")).toBeInTheDocument();
    expect(screen.queryByText("三维仿真运动")).not.toBeInTheDocument();
  });

  it("shows dynamic run errors without clearing typed inputs", async () => {
    apiMock.runTimeHistory.mockRejectedValue(new apiMock.ApiError(400, "invalid_input", "犁端速度分量无效"));
    render(<App />);

    await screen.findByText("后端在线");
    fireEvent.change(screen.getByLabelText("犁入口速度第1段段首纵向速度 uX m/s"), { target: { value: "-1" } });
    fireEvent.click(screen.getByRole("button", { name: "运行仿真" }));

    await expect(screen.findByText("犁端速度分量无效")).resolves.toBeInTheDocument();
    expect(screen.getByLabelText("犁入口速度第1段段首纵向速度 uX m/s")).toHaveValue(-1);
    expect(screen.getByRole("button", { name: "仿真参数设置" })).toHaveAttribute("aria-pressed", "true");
  });

  it("requires measured q_p when the plough command is not longitudinal +X", async () => {
    render(<App />);

    await screen.findByText("后端在线");
    fireEvent.change(screen.getByLabelText("犁入口速度第1段段首横向速度 vY m/s"), { target: { value: "0.2" } });

    expect(screen.getByText("犁出口材料速度 需要实测 q_p")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("犁出口材料速度 q_p m/s（实测，可选）"), { target: { value: "0.52" } });
    expect(screen.getByText("犁出口材料速度 0.52 m/s（实测）")).toBeInTheDocument();
  });
});

function realtimeFramePayload() {
  return {
    session_id: "session-1",
    sequence: 0,
    time_s: 0,
    compute_wall_s: 0.02,
    realtime_factor: null,
    input_age_s: 0,
    input_status: "valid",
    tensions: { top_tension_n: 1019, plough_inlet_tension_n: 316, plough_boundary_tension_n: 310 },
    contact: {
      tdp_x_m: -20,
      tdp_y_m: 0,
      tdp_arc_length_m: 60,
      free_span_material_length_m: 60,
      seabed_contact_length_m: 0,
      seabed_normal_reaction_n: 0,
    },
    integration: { time_step_min_s: 0.01, time_step_max_s: 0.01, axial_constraint_residual_max_m: 0.001 },
    frame: {
      time_s: 0,
      boundary: "known_plough_trajectory",
      vessel_x_m: 0,
      vessel_y_m: 0,
      vessel_z_m: 0,
      plough_x_m: -55,
      plough_y_m: 0,
      plough_z_m: 80,
      points: [
        { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 1019 },
        { index: 1, x_m: -55, y_m: 0, z_m: 80, tension_n: 316 },
      ],
    },
  };
}

function knownPloughTimeHistoryPayload() {
  return {
    case_name: "known_plough_boundary_demo",
    summary: {
      current_speed_mps: 0.4,
      current_direction_deg: 90,
      diameter_m: 0.0264,
      weight_air_n_per_m: 16.09,
      submerged_weight_n_per_m: 10.59,
      tangential_drag_coefficient: 0.01,
      normal_drag_coefficient: 2.12,
      axial_stiffness_n: 1e9,
      speed_change: "accel",
      initial_speed_mps: 0.8,
      final_speed_mps: 1.0,
      duration_s: 10,
      total_duration_s: 20,
      water_depth_m: 80,
      element_count: 10,
      touchdown_tension_n: 200,
      payout_initial_speed_mps: 1.05,
      payout_final_speed_mps: 1.15,
      length_boundary_source: "known_plough_trajectory",
      evidence_level:
        "known plough trajectory endpoint model with XPBD length constraints and segment tension output",
      initial_tension_n: 1180,
      extreme_tension_n: 1110,
      steady_tension_n: 1140,
      plough_speed_mps: 0.8,
      plough_exit_speed_mps: 0.55,
      plough_exit_speed_source: "no_slip_inferred",
      plough_inlet_tension_final_n: 950,
      plough_boundary_tension_final_n: 200,
      plough_adjacent_segment_tension_final_n: 196,
      plough_tension_status: "carried",
      minimum_bend_radius_min_m: 12.4,
      minimum_bend_radius_limit_m: 10,
      minimum_bend_radius_margin_m: 2.4,
      minimum_bend_radius_status: "ok",
      minimum_bend_radius_time_s: 20,
      minimum_bend_radius_node_index: 1,
      minimum_bend_radius_near_seabed: false,
      minimum_bend_radius_raw_m: 2.1,
      minimum_bend_radius_raw_time_s: 20,
      minimum_bend_radius_raw_node_index: 2,
      minimum_bend_radius_raw_near_seabed: true,
      integration_time_step_min_s: 0.05,
      integration_time_step_max_s: 0.2,
      spatial_step_min_m: 3.4,
      spatial_step_mean_m: 4.1,
      xpbd_iterations_per_step: 12,
    },
    artifacts: {
      time_summary_csv: "time_histories/known-plough-boundary/time_summary.csv",
      time_history_csv: "time_histories/known-plough-boundary/time_history.csv",
      time_history_svg: "time_histories/known-plough-boundary/time_history.svg",
    },
    plot_data: {
      time_history: {
        source: "la_dynamic_xpbd_node_state",
        label: "动态张力时程",
        points: [
          {
            time_s: 0,
            top_tension_n: 1180,
            tdp_x_m: 0,
            tdp_y_m: -55,
            suspended_length_m: 98,
            iterations: 10,
            plough_x_m: 0,
            plough_y_m: -55,
            plough_z_m: 78,
            plough_inlet_tension_n: 920,
            plough_entry_angle_deg: 25.1,
            minimum_bend_radius_m: 12.4,
          },
          {
            time_s: 20,
            top_tension_n: 1140,
            tdp_x_m: 0,
            tdp_y_m: -39,
            suspended_length_m: 103,
            iterations: 200,
            plough_x_m: 0,
            plough_y_m: -39,
            plough_z_m: 78,
            plough_inlet_tension_n: 950,
            plough_entry_angle_deg: 23.5,
            minimum_bend_radius_m: 14.2,
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
            segment_tensions_n: [1180, 920],
            vessel_x_m: 0,
            vessel_y_m: 0,
            vessel_z_m: 0,
            plough_x_m: 0,
            plough_y_m: -55,
            plough_z_m: 78,
            minimum_bend_radius_m: 12.4,
            points: [
              { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 1180 },
              { index: 1, x_m: 0, y_m: -25, z_m: 40, tension_n: 1050 },
              { index: 2, x_m: 0, y_m: -55, z_m: 78, tension_n: 920 },
            ],
          },
          {
            time_s: 20,
            boundary: "known_plough_trajectory",
            segment_tensions_n: [1140, 950],
            vessel_x_m: 0,
            vessel_y_m: 19,
            vessel_z_m: 0,
            plough_x_m: 0,
            plough_y_m: -39,
            plough_z_m: 78,
            minimum_bend_radius_m: 14.2,
            points: [
              { index: 0, x_m: 0, y_m: 19, z_m: 0, tension_n: 1140 },
              { index: 1, x_m: 0, y_m: -12, z_m: 42, tension_n: 1030 },
              { index: 2, x_m: 0, y_m: -39, z_m: 78, tension_n: 950 },
            ],
          },
        ],
      },
    },
  };
}

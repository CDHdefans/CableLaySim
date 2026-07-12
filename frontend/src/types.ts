export type SolverModel = "power_500kv" | "generic";
export type CalculationMode = "profile" | "dynamic";

export interface CableInputs {
  cable: string;
  solver_model: SolverModel;
  diameter_m: number;
  weight_air_n_per_m: number;
  submerged_weight_n_per_m: number;
  hydrodynamic_constant: number;
  tangential_drag_coefficient: number;
  normal_drag_coefficient: number;
  total_length_m: number;
  axial_stiffness_n: number;
  max_water_depth_m: number | null;
  max_allowable_tension_n: number | null;
  min_bending_radius_m: number | null;
  initial_speed_mps: number;
  final_speed_mps: number;
  duration_s: number;
  water_depth_m: number;
  touchdown_tension_n: number;
  current_u_mps: number;
  current_v_mps: number;
  vessel_speed_mps: number | null;
  payout_speed_mps: number | null;
  current_surface_mps: number | null;
  current_bottom_mps: number | null;
  current_direction_deg: number | null;
}

export interface CableCase {
  name: string;
  label: string;
  description: string;
  group: string;
  example: boolean;
  display_order?: number;
  suggested_output_dir: string;
  inputs: CableInputs;
}

export interface TimeHistoryCaseInputs {
  case_name: string;
  diameter_m: number;
  weight_air_n_per_m: number;
  submerged_weight_n_per_m: number;
  tangential_drag_coefficient: number;
  normal_drag_coefficient: number;
  axial_stiffness_n: number;
  current_speed_mps: number;
  current_direction_deg: number;
  speed_change: "steady" | "accel" | "decel";
  initial_speed_mps: number;
  final_speed_mps: number;
  payout_initial_speed_mps?: number | null;
  payout_final_speed_mps?: number | null;
  length_boundary_source?: string;
  duration_s: number;
  total_duration_s: number;
  water_depth_m: number;
  element_count: number;
  touchdown_tension_n: number;
  vessel_initial_x_m?: number;
  vessel_initial_y_m?: number;
  vessel_heading_deg?: number;
  plough_initial_x_m?: number | null;
  plough_initial_y_m?: number | null;
  plough_initial_z_m?: number | null;
  plough_speed_mps?: number | null;
  plough_exit_speed_mps?: number | null;
  plough_heading_deg?: number | null;
  initial_suspended_length_m?: number | null;
  min_bending_radius_m?: number | null;
  vessel_motion_segments?: MotionSegmentInput[];
  plough_motion_segments?: MotionSegmentInput[];
  vessel_motion_samples?: MotionSampleInput[];
  plough_motion_samples?: MotionSampleInput[];
  payout_speed_segments?: SpeedSegmentInput[];
}

export interface MotionSegmentInput {
  duration_s: number;
  start_speed_mps: number;
  end_speed_mps: number;
  heading_deg: number;
  start_velocity_x_mps?: number;
  start_velocity_y_mps?: number;
  end_velocity_x_mps?: number;
  end_velocity_y_mps?: number;
}

export interface SpeedSegmentInput {
  duration_s: number;
  start_speed_mps: number;
  end_speed_mps: number;
}

export interface MotionSampleInput {
  time_s: number;
  x_m: number;
  y_m: number;
  z_m?: number | null;
  velocity_x_mps?: number | null;
  velocity_y_mps?: number | null;
  velocity_z_mps?: number | null;
}

export interface TimeHistoryCase {
  name: string;
  label: string;
  description: string;
  group: string;
  example: boolean;
  display_order?: number;
  suggested_output_dir: string;
  inputs: TimeHistoryCaseInputs;
}

export interface GroupedCases {
  label: string;
  cases: CableCase[];
}

export interface RunCaseRequest {
  case_name: string;
  points: number;
  output_dir?: string;
}

export interface CustomCaseRequest extends CableInputs {
  case_name: string;
  points: number;
  output_dir?: string;
}

export interface RunCaseSummary {
  top_tension_initial_n: number;
  top_tension_min_n: number;
  top_tension_final_n: number;
  suspended_length_m: number;
  layback_m: number;
}

export interface ProfilePlotPoint {
  index: number;
  arc_m: number;
  x_m: number;
  y_m: number;
  z_m: number;
  theta_rad: number;
  psi_rad: number;
  tangent_x: number;
  tangent_y: number;
  tangent_z: number;
  current_x_mps: number;
  current_y_mps: number;
  current_z_mps: number;
  drag_x_n_per_m: number;
  drag_y_n_per_m: number;
  drag_z_n_per_m: number;
  tension_n: number;
}

export interface TimeHistoryPlotPoint {
  time_s: number;
  top_tension_n: number;
  tdp_x_m: number;
  tdp_y_m: number;
  suspended_length_m?: number;
  material_suspended_length_m?: number;
  geometric_length_deficit_m?: number;
  tdp_arc_length_m?: number;
  free_span_material_length_m?: number;
  seabed_contact_length_m?: number;
  seabed_normal_reaction_n?: number;
  iterations?: number;
  plough_x_m?: number;
  plough_y_m?: number;
  plough_z_m?: number;
  plough_inlet_tension_n?: number;
  plough_entry_angle_deg?: number;
  minimum_bend_radius_m?: number;
}

export interface TimeHistoryPlotData {
  source: string;
  label: string;
  points: TimeHistoryPlotPoint[];
}

export interface DynamicFramePoint {
  index: number;
  x_m: number;
  y_m: number;
  z_m: number;
  tension_n: number;
}

export interface DynamicFrame {
  time_s: number;
  points: DynamicFramePoint[];
  segment_tensions_n?: number[];
  boundary?: string;
  vessel_x_m?: number;
  vessel_y_m?: number;
  vessel_z_m?: number;
  plough_x_m?: number;
  plough_y_m?: number;
  plough_z_m?: number;
  minimum_bend_radius_m?: number;
}

export interface DynamicFramePlotData {
  source: string;
  label: string;
  items: DynamicFrame[];
}

export interface RunCasePlotData {
  profile: ProfilePlotPoint[];
  time_history: TimeHistoryPlotData;
}

export interface RunCaseResponse {
  case_name: string;
  summary: RunCaseSummary;
  artifacts: {
    summary_csv: string;
    profile_csv: string;
    profile_svg: string;
  };
  plot_data?: RunCasePlotData;
}

export interface NamedTimeHistoryRequest {
  case_name: string;
  points: number;
  output_dir?: string;
  current_speed_mps?: never;
  current_direction_deg?: never;
  speed_change?: never;
  initial_speed_mps?: never;
  final_speed_mps?: never;
  payout_initial_speed_mps?: never;
  payout_final_speed_mps?: never;
  length_boundary_source?: never;
  duration_s?: never;
  total_duration_s?: never;
  water_depth_m?: never;
  element_count?: never;
  touchdown_tension_n?: never;
  diameter_m?: never;
  weight_air_n_per_m?: never;
  submerged_weight_n_per_m?: never;
  tangential_drag_coefficient?: never;
  normal_drag_coefficient?: never;
  axial_stiffness_n?: never;
  vessel_initial_x_m?: never;
  vessel_initial_y_m?: never;
  vessel_heading_deg?: never;
  plough_initial_x_m?: never;
  plough_initial_y_m?: never;
  plough_initial_z_m?: never;
  plough_speed_mps?: never;
  plough_exit_speed_mps?: never;
  plough_heading_deg?: never;
  initial_suspended_length_m?: never;
  min_bending_radius_m?: never;
  vessel_motion_segments?: never;
  plough_motion_segments?: never;
  vessel_motion_samples?: never;
  plough_motion_samples?: never;
  payout_speed_segments?: never;
}

export interface OperatorTimeHistoryRequest extends TimeHistoryCaseInputs {
  points: number;
  output_dir?: string;
}

export interface DynamicTimeHistoryForm extends OperatorTimeHistoryRequest {}

export type RunTimeHistoryRequest = NamedTimeHistoryRequest | OperatorTimeHistoryRequest;

export interface RunTimeHistorySummary {
  diameter_m: number;
  weight_air_n_per_m: number;
  submerged_weight_n_per_m: number;
  tangential_drag_coefficient: number;
  normal_drag_coefficient: number;
  axial_stiffness_n: number;
  current_speed_mps: number;
  current_direction_deg: number;
  speed_change: "steady" | "accel" | "decel";
  initial_speed_mps: number;
  final_speed_mps: number;
  payout_initial_speed_mps?: number | null;
  payout_final_speed_mps?: number | null;
  length_boundary_source: string;
  initial_suspended_length_m?: number | null;
  duration_s: number;
  total_duration_s: number;
  water_depth_m: number;
  element_count: number;
  touchdown_tension_n: number;
  evidence_level: string;
  initial_tension_n: number;
  extreme_tension_n: number;
  steady_tension_n: number;
  plough_speed_mps?: number | null;
  plough_exit_speed_mps?: number | null;
  plough_exit_speed_source?: "measured" | "no_slip_inferred" | "not_applicable";
  plough_inlet_tension_final_n?: number | null;
  plough_boundary_tension_final_n?: number | null;
  plough_adjacent_segment_tension_final_n?: number | null;
  plough_tension_status?: string | null;
  minimum_bend_radius_min_m?: number | null;
  minimum_bend_radius_limit_m?: number | null;
  minimum_bend_radius_margin_m?: number | null;
  minimum_bend_radius_status?: "ok" | "below_limit" | "not_available" | "not_configured";
  minimum_bend_radius_time_s?: number | null;
  minimum_bend_radius_node_index?: number | null;
  minimum_bend_radius_left_segment_m?: number | null;
  minimum_bend_radius_right_segment_m?: number | null;
  minimum_bend_radius_turn_angle_deg?: number | null;
  minimum_bend_radius_node_depth_m?: number | null;
  minimum_bend_radius_near_seabed?: boolean | null;
  minimum_bend_radius_excluded_tail_nodes?: number | null;
  minimum_bend_radius_raw_m?: number | null;
  minimum_bend_radius_raw_time_s?: number | null;
  minimum_bend_radius_raw_node_index?: number | null;
  minimum_bend_radius_raw_left_segment_m?: number | null;
  minimum_bend_radius_raw_right_segment_m?: number | null;
  minimum_bend_radius_raw_turn_angle_deg?: number | null;
  minimum_bend_radius_raw_node_depth_m?: number | null;
  minimum_bend_radius_raw_near_seabed?: boolean | null;
  integration_time_step_max_s?: number | null;
  integration_time_step_min_s?: number | null;
  spatial_step_mean_m?: number | null;
  spatial_step_min_m?: number | null;
  xpbd_iterations_per_step?: number | null;
  xpbd_iterations_per_step_min?: number | null;
  xpbd_iterations_per_step_max?: number | null;
  xpbd_iteration_limit_per_solve?: number | null;
  axial_constraint_residual_max_m?: number | null;
  geometric_length_deficit_max_m?: number | null;
  geometric_length_deficit_final_m?: number | null;
  vessel_motion_segments?: MotionSegmentInput[];
  plough_motion_segments?: MotionSegmentInput[];
  vessel_motion_samples?: MotionSampleInput[];
  plough_motion_samples?: MotionSampleInput[];
  payout_speed_segments?: SpeedSegmentInput[];
}

export interface RunTimeHistoryResponse {
  case_name: string;
  summary: RunTimeHistorySummary;
  artifacts: {
    time_summary_csv: string;
    time_history_csv: string;
    time_history_svg: string;
  };
  plot_data: {
    time_history: TimeHistoryPlotData;
    frames?: DynamicFramePlotData;
  };
}

export interface RealtimeEndpointSample {
  x_m: number;
  y_m: number;
  z_m: number;
  velocity_x_mps: number;
  velocity_y_mps: number;
  velocity_z_mps: number;
}

export interface RealtimeSensorPacket {
  sequence: number;
  time_s: number;
  observed_at_unix_s: number;
  quality: "valid" | "invalid";
  vessel: RealtimeEndpointSample;
  plough: RealtimeEndpointSample;
  payout_speed_mps: number;
  plough_exit_speed_mps: number;
  current_velocity_x_mps: number;
  current_velocity_y_mps: number;
}

export interface CreateRealtimeSessionRequest extends TimeHistoryCaseInputs {
  max_sensor_gap_s?: number;
  max_data_age_s?: number;
  initial_packet: RealtimeSensorPacket;
}

export interface RealtimeFrameResponse {
  session_id: string;
  sequence: number;
  time_s: number;
  compute_wall_s: number;
  realtime_factor: number | null;
  input_age_s: number;
  input_status: string;
  tensions: {
    top_tension_n: number;
    plough_inlet_tension_n: number;
    plough_boundary_tension_n: number;
  };
  contact: {
    tdp_x_m: number;
    tdp_y_m: number;
    tdp_arc_length_m: number;
    free_span_material_length_m: number;
    seabed_contact_length_m: number;
    seabed_normal_reaction_n: number;
  };
  integration: {
    time_step_min_s: number | null;
    time_step_max_s: number | null;
    axial_constraint_residual_max_m: number | null;
  };
  frame: DynamicFrame;
}

export interface ReproductionMetadata {
  available: boolean;
  root: string;
  inputs: string[];
  tables: string[];
  figures: string[];
  cases: string[];
  time_histories: string[];
  case_count?: number;
}

export interface HealthResponse {
  status: string;
  service: string;
  output_root: string;
}

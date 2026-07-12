"""Transparent LA dynamic time-history diagnostics.

The dynamic reproduction keeps Table 4-1 outside the solver: paper values are
diagnostics, not fitted targets. The default LA path uses a multi-element
finite-difference inclination/azimuth iteration driven by the cable inputs,
vessel speed change, gravity, and drag balance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .cases import get_cable
from .parameters import CableParameters


_SEAWATER_DENSITY_KG_M3 = 1025.0
_GRAVITY_MPS2 = 9.8
_MIN_SPEED_MPS = 1.0e-12
_ROUTE_LONGITUDINAL_TOLERANCE = 1.0e-9
_CYLINDER_ADDED_MASS_COEFFICIENT = 1.0
_DEFAULT_DYNAMIC_CABLE = get_cable("LA")


@dataclass(frozen=True)
class MotionSegment:
    """One prescribed planar motion command segment.

    ``heading_deg`` is a speed-vector azimuth fallback in the operation-track
    frame: 0 deg is the longitudinal/surge-aligned ``+X`` direction and 90 deg
    is the transverse/sway-aligned ``+Y`` direction. It is not a vessel gyro
    heading. Direct measured fairlead/plough velocity components take
    precedence when all four component fields are provided.
    Speed changes linearly within the segment and position is integrated over time.
    """

    duration_s: float
    start_speed_mps: float
    end_speed_mps: float
    heading_deg: float
    start_velocity_x_mps: float | None = None
    start_velocity_y_mps: float | None = None
    end_velocity_x_mps: float | None = None
    end_velocity_y_mps: float | None = None


@dataclass(frozen=True)
class MotionSample:
    """One measured endpoint motion sample in the operation-track frame.

    ``x_m``/``y_m`` are measured fairlead or plough-inlet positions after
    conversion from ship-body/navigation coordinates. Optional velocity
    components are measured or filtered endpoint velocities in the same frame.
    """

    time_s: float
    x_m: float
    y_m: float
    z_m: float | None = None
    velocity_x_mps: float | None = None
    velocity_y_mps: float | None = None
    velocity_z_mps: float | None = None


@dataclass(frozen=True)
class SpeedSegment:
    """One prescribed scalar speed command segment."""

    duration_s: float
    start_speed_mps: float
    end_speed_mps: float


@dataclass(frozen=True)
class ScalarSample:
    """One synchronized scalar input sample."""

    time_s: float
    value: float


@dataclass(frozen=True)
class CurrentSample:
    """One synchronized horizontal water-velocity sample in the work frame."""

    time_s: float
    velocity_x_mps: float
    velocity_y_mps: float


@dataclass(frozen=True)
class TimeHistoryPoint:
    """One sample in a top-tension time history."""

    time_s: float
    top_tension_n: float
    tdp_x_m: float
    tdp_y_m: float
    suspended_length_m: float
    iterations: int
    plough_x_m: float | None = None
    plough_y_m: float | None = None
    plough_z_m: float | None = None
    plough_inlet_tension_n: float | None = None
    plough_boundary_tension_n: float | None = None
    plough_adjacent_segment_tension_n: float | None = None
    plough_entry_angle_deg: float | None = None
    minimum_bend_radius_m: float | None = None
    minimum_bend_radius_node_index: int | None = None
    minimum_bend_radius_left_segment_m: float | None = None
    minimum_bend_radius_right_segment_m: float | None = None
    minimum_bend_radius_turn_angle_deg: float | None = None
    minimum_bend_radius_node_depth_m: float | None = None
    minimum_bend_radius_near_seabed: bool | None = None
    minimum_bend_radius_excluded_tail_nodes: int | None = None
    minimum_bend_radius_raw_m: float | None = None
    minimum_bend_radius_raw_node_index: int | None = None
    minimum_bend_radius_raw_left_segment_m: float | None = None
    minimum_bend_radius_raw_right_segment_m: float | None = None
    minimum_bend_radius_raw_turn_angle_deg: float | None = None
    minimum_bend_radius_raw_node_depth_m: float | None = None
    minimum_bend_radius_raw_near_seabed: bool | None = None
    material_suspended_length_m: float | None = None
    geometric_length_deficit_m: float | None = None
    tdp_arc_length_m: float | None = None
    free_span_material_length_m: float | None = None
    seabed_contact_length_m: float | None = None
    seabed_normal_reaction_n: float | None = None


@dataclass(frozen=True)
class TimeHistoryFramePoint:
    """One cable node in a dynamic 3D frame.

    Coordinates use the vessel/top node as the origin and positive ``z_m`` as
    downward water depth.
    """

    index: int
    x_m: float
    y_m: float
    z_m: float
    tension_n: float


@dataclass(frozen=True)
class TimeHistoryFrame:
    """One sampled 3D cable shape from the dynamic angle state."""

    time_s: float
    points: list[TimeHistoryFramePoint]
    segment_tensions_n: tuple[float, ...] = ()
    boundary: str = "free_laying"
    vessel_x_m: float | None = None
    vessel_y_m: float | None = None
    vessel_z_m: float | None = None
    plough_x_m: float | None = None
    plough_y_m: float | None = None
    plough_z_m: float | None = None
    minimum_bend_radius_m: float | None = None
    minimum_bend_radius_node_index: int | None = None
    minimum_bend_radius_left_segment_m: float | None = None
    minimum_bend_radius_right_segment_m: float | None = None
    minimum_bend_radius_turn_angle_deg: float | None = None
    minimum_bend_radius_node_depth_m: float | None = None
    minimum_bend_radius_near_seabed: bool | None = None
    minimum_bend_radius_excluded_tail_nodes: int | None = None
    minimum_bend_radius_raw_m: float | None = None
    minimum_bend_radius_raw_node_index: int | None = None
    minimum_bend_radius_raw_left_segment_m: float | None = None
    minimum_bend_radius_raw_right_segment_m: float | None = None
    minimum_bend_radius_raw_turn_angle_deg: float | None = None
    minimum_bend_radius_raw_node_depth_m: float | None = None
    minimum_bend_radius_raw_near_seabed: bool | None = None


@dataclass(frozen=True)
class DynamicCaseInput:
    """Inputs for one LA time-history diagnostic case."""

    case_name: str
    current_speed_mps: float
    speed_change: str
    initial_speed_mps: float
    final_speed_mps: float
    duration_s: float
    water_depth_m: float
    diameter_m: float = _DEFAULT_DYNAMIC_CABLE.diameter_m
    weight_air_n_per_m: float = _DEFAULT_DYNAMIC_CABLE.weight_air_n_per_m
    submerged_weight_n_per_m: float = _DEFAULT_DYNAMIC_CABLE.submerged_weight_n_per_m
    tangential_drag_coefficient: float = _DEFAULT_DYNAMIC_CABLE.tangential_drag_coefficient
    normal_drag_coefficient: float = _DEFAULT_DYNAMIC_CABLE.normal_drag_coefficient
    axial_stiffness_n: float = _DEFAULT_DYNAMIC_CABLE.axial_stiffness_n
    element_count: int = 32
    total_duration_s: float = 360.0
    current_direction_deg: float = 90.0
    touchdown_tension_n: float = 0.0
    payout_initial_speed_mps: float | None = None
    payout_final_speed_mps: float | None = None
    length_boundary_source: str = "straight_line_sensitivity"
    vessel_initial_x_m: float = 0.0
    vessel_initial_y_m: float = 0.0
    vessel_heading_deg: float = 0.0
    plough_initial_x_m: float | None = None
    plough_initial_y_m: float | None = None
    plough_initial_z_m: float | None = None
    plough_speed_mps: float | None = None
    plough_exit_speed_mps: float | None = None
    plough_heading_deg: float | None = None
    initial_suspended_length_m: float | None = None
    min_bending_radius_m: float | None = None
    vessel_motion_segments: tuple[MotionSegment, ...] = ()
    plough_motion_segments: tuple[MotionSegment, ...] = ()
    vessel_motion_samples: tuple[MotionSample, ...] = ()
    plough_motion_samples: tuple[MotionSample, ...] = ()
    payout_speed_segments: tuple[SpeedSegment, ...] = ()
    payout_speed_samples: tuple[ScalarSample, ...] = ()
    plough_exit_speed_samples: tuple[ScalarSample, ...] = ()
    current_samples: tuple[CurrentSample, ...] = ()


@dataclass(frozen=True)
class TimeHistoryResult:
    """Scalar summary and sampled time-history output."""

    case_name: str
    diameter_m: float
    weight_air_n_per_m: float
    submerged_weight_n_per_m: float
    tangential_drag_coefficient: float
    normal_drag_coefficient: float
    axial_stiffness_n: float
    current_speed_mps: float
    current_direction_deg: float
    speed_change: str
    initial_speed_mps: float
    final_speed_mps: float
    duration_s: float
    total_duration_s: float
    water_depth_m: float
    element_count: int
    touchdown_tension_n: float
    payout_initial_speed_mps: float
    payout_final_speed_mps: float
    length_boundary_source: str
    initial_suspended_length_m: float | None
    evidence_level: str
    initial_tension_n: float
    extreme_tension_n: float
    steady_tension_n: float
    history: list[TimeHistoryPoint]
    frames: list[TimeHistoryFrame]
    plough_speed_mps: float | None = None
    plough_exit_speed_mps: float | None = None
    plough_exit_speed_source: str = "not_applicable"
    plough_inlet_tension_final_n: float | None = None
    plough_boundary_tension_final_n: float | None = None
    plough_adjacent_segment_tension_final_n: float | None = None
    plough_tension_status: str = "not_applicable"
    minimum_bend_radius_min_m: float | None = None
    minimum_bend_radius_limit_m: float | None = None
    minimum_bend_radius_margin_m: float | None = None
    minimum_bend_radius_status: str = "not_configured"
    minimum_bend_radius_time_s: float | None = None
    minimum_bend_radius_node_index: int | None = None
    minimum_bend_radius_left_segment_m: float | None = None
    minimum_bend_radius_right_segment_m: float | None = None
    minimum_bend_radius_turn_angle_deg: float | None = None
    minimum_bend_radius_node_depth_m: float | None = None
    minimum_bend_radius_near_seabed: bool | None = None
    minimum_bend_radius_excluded_tail_nodes: int | None = None
    minimum_bend_radius_raw_m: float | None = None
    minimum_bend_radius_raw_time_s: float | None = None
    minimum_bend_radius_raw_node_index: int | None = None
    minimum_bend_radius_raw_left_segment_m: float | None = None
    minimum_bend_radius_raw_right_segment_m: float | None = None
    minimum_bend_radius_raw_turn_angle_deg: float | None = None
    minimum_bend_radius_raw_node_depth_m: float | None = None
    minimum_bend_radius_raw_near_seabed: bool | None = None
    integration_time_step_max_s: float | None = None
    integration_time_step_min_s: float | None = None
    spatial_step_mean_m: float | None = None
    spatial_step_min_m: float | None = None
    xpbd_iterations_per_step: int | None = None
    xpbd_iterations_per_step_min: int | None = None
    xpbd_iterations_per_step_max: int | None = None
    xpbd_iteration_limit_per_solve: int | None = None
    axial_constraint_residual_max_m: float | None = None
    geometric_length_deficit_max_m: float | None = None
    geometric_length_deficit_final_m: float | None = None
    vessel_motion_segments: tuple[MotionSegment, ...] = ()
    plough_motion_segments: tuple[MotionSegment, ...] = ()
    vessel_motion_samples: tuple[MotionSample, ...] = ()
    plough_motion_samples: tuple[MotionSample, ...] = ()
    payout_speed_segments: tuple[SpeedSegment, ...] = ()


@dataclass(frozen=True)
class _StraightLineState:
    theta_rad: float
    psi_rad: float
    suspended_length_m: float
    top_tension_n: float
    tdp_x_m: float
    tdp_y_m: float


@dataclass(frozen=True)
class _AngleState:
    angles_rad: tuple[float, ...]
    psis_rad: tuple[float, ...]
    angular_rates_radps: tuple[float, ...]
    azimuth_rates_radps: tuple[float, ...]
    suspended_length_m: float = 0.0


@dataclass(frozen=True)
class _AngleSample:
    time_s: float
    tension_n: float
    tdp_x_m: float
    tdp_y_m: float
    suspended_length_m: float
    angles_rad: tuple[float, ...]
    psis_rad: tuple[float, ...]
    tensions_n: tuple[float, ...]
    integration_steps: int


def _known_plough_case(case_name: str, **overrides: object) -> DynamicCaseInput:
    values: dict[str, object] = {
        "case_name": case_name,
        "current_speed_mps": 0.35,
        "current_direction_deg": 90.0,
        "speed_change": "steady",
        "initial_speed_mps": 0.80,
        "final_speed_mps": 0.80,
        "payout_initial_speed_mps": 0.88,
        "payout_final_speed_mps": 0.88,
        "length_boundary_source": "known_plough_trajectory",
        "duration_s": 360.0,
        "total_duration_s": 360.0,
        "water_depth_m": 80.0,
        "element_count": 24,
        "touchdown_tension_n": 200.0,
        "vessel_initial_x_m": 0.0,
        "vessel_initial_y_m": 0.0,
        "vessel_heading_deg": 0.0,
        "plough_initial_x_m": -55.0,
        "plough_initial_y_m": 0.0,
        "plough_initial_z_m": 80.0,
        "plough_speed_mps": 0.75,
        "plough_heading_deg": 0.0,
    }
    values.update(overrides)
    if values.get("initial_suspended_length_m") is None:
        vessel = (float(values["vessel_initial_x_m"]), float(values["vessel_initial_y_m"]), 0.0)
        plough = (
            float(values["plough_initial_x_m"]),
            float(values["plough_initial_y_m"]),
            float(values["plough_initial_z_m"]),
        )
        values["initial_suspended_length_m"] = 1.03 * math.dist(vessel, plough)
    return DynamicCaseInput(**values)  # type: ignore[arg-type]


def _known_plough_material_case(case_name: str, cable_name: str, **overrides: object) -> DynamicCaseInput:
    cable = get_cable(cable_name)
    values: dict[str, object] = {
        "diameter_m": cable.diameter_m,
        "weight_air_n_per_m": cable.weight_air_n_per_m,
        "submerged_weight_n_per_m": cable.submerged_weight_n_per_m,
        "tangential_drag_coefficient": cable.tangential_drag_coefficient,
        "normal_drag_coefficient": cable.normal_drag_coefficient,
        "axial_stiffness_n": cable.axial_stiffness_n,
        "min_bending_radius_m": cable.min_bending_radius_m,
    }
    values.update(overrides)
    return _known_plough_case(case_name, **values)


_DYNAMIC_CASES = {
    "la_dynamic_accel_current_1p00": DynamicCaseInput(
        case_name="la_dynamic_accel_current_1p00",
        current_speed_mps=1.00,
        speed_change="accel",
        initial_speed_mps=0.5,
        final_speed_mps=1.5,
        duration_s=30.0,
        water_depth_m=100.0,
    ),
    "la_dynamic_accel_current_1p50": DynamicCaseInput(
        case_name="la_dynamic_accel_current_1p50",
        current_speed_mps=1.50,
        speed_change="accel",
        initial_speed_mps=0.5,
        final_speed_mps=1.5,
        duration_s=30.0,
        water_depth_m=100.0,
    ),
    "la_dynamic_decel_current_1p00": DynamicCaseInput(
        case_name="la_dynamic_decel_current_1p00",
        current_speed_mps=1.00,
        speed_change="decel",
        initial_speed_mps=1.5,
        final_speed_mps=0.5,
        duration_s=30.0,
        water_depth_m=100.0,
    ),
    "la_dynamic_decel_current_1p50": DynamicCaseInput(
        case_name="la_dynamic_decel_current_1p50",
        current_speed_mps=1.50,
        speed_change="decel",
        initial_speed_mps=1.5,
        final_speed_mps=0.5,
        duration_s=30.0,
        water_depth_m=100.0,
    ),
    "plough_straight_baseline_6min": _known_plough_case("plough_straight_baseline_6min"),
    "plough_straight_low_speed_6min": _known_plough_case(
        "plough_straight_low_speed_6min",
        initial_speed_mps=0.60,
        final_speed_mps=0.60,
        payout_initial_speed_mps=0.66,
        payout_final_speed_mps=0.66,
        plough_speed_mps=0.55,
    ),
    "plough_straight_high_speed_6min": _known_plough_case(
        "plough_straight_high_speed_6min",
        initial_speed_mps=1.00,
        final_speed_mps=1.00,
        payout_initial_speed_mps=1.10,
        payout_final_speed_mps=1.10,
        plough_speed_mps=0.95,
    ),
    "plough_straight_low_tdp_tension_6min": _known_plough_case(
        "plough_straight_low_tdp_tension_6min",
        touchdown_tension_n=100.0,
    ),
    "plough_straight_high_tdp_tension_6min": _known_plough_case(
        "plough_straight_high_tdp_tension_6min",
        touchdown_tension_n=400.0,
    ),
    "plough_cross_current_0p50_90deg_6min": _known_plough_case(
        "plough_cross_current_0p50_90deg_6min",
        current_speed_mps=0.50,
        current_direction_deg=90.0,
    ),
    "plough_cross_current_0p95_90deg_6min": _known_plough_case(
        "plough_cross_current_0p95_90deg_6min",
        current_speed_mps=0.95,
        current_direction_deg=90.0,
    ),
    "plough_cross_current_0p95_60deg_6min": _known_plough_case(
        "plough_cross_current_0p95_60deg_6min",
        current_speed_mps=0.95,
        current_direction_deg=60.0,
    ),
    "plough_cross_current_0p95_30deg_6min": _known_plough_case(
        "plough_cross_current_0p95_30deg_6min",
        current_speed_mps=0.95,
        current_direction_deg=30.0,
    ),
    "plough_cross_current_0p95_0deg_6min": _known_plough_case(
        "plough_cross_current_0p95_0deg_6min",
        current_speed_mps=0.95,
        current_direction_deg=0.0,
    ),
    "plough_decel_mild_6min": _known_plough_case(
        "plough_decel_mild_6min",
        speed_change="decel",
        initial_speed_mps=0.90,
        final_speed_mps=0.70,
        payout_initial_speed_mps=0.98,
        payout_final_speed_mps=0.78,
        duration_s=90.0,
        plough_speed_mps=0.65,
    ),
    "plough_decel_strong_6min": _known_plough_case(
        "plough_decel_strong_6min",
        speed_change="decel",
        initial_speed_mps=1.10,
        final_speed_mps=0.55,
        payout_initial_speed_mps=1.18,
        payout_final_speed_mps=0.65,
        duration_s=90.0,
        plough_speed_mps=0.55,
    ),
    "plough_decel_long_6min": _known_plough_case(
        "plough_decel_long_6min",
        speed_change="decel",
        initial_speed_mps=0.90,
        final_speed_mps=0.60,
        payout_initial_speed_mps=0.98,
        payout_final_speed_mps=0.70,
        duration_s=180.0,
        plough_speed_mps=0.60,
    ),
    "plough_payout_matched_6min": _known_plough_case(
        "plough_payout_matched_6min",
        payout_initial_speed_mps=0.80,
        payout_final_speed_mps=0.80,
        plough_speed_mps=0.80,
    ),
    "plough_payout_fast_1p10_6min": _known_plough_case(
        "plough_payout_fast_1p10_6min",
        payout_initial_speed_mps=0.88,
        payout_final_speed_mps=0.88,
        plough_speed_mps=0.80,
    ),
    "plough_payout_fast_1p25_6min": _known_plough_case(
        "plough_payout_fast_1p25_6min",
        payout_initial_speed_mps=1.00,
        payout_final_speed_mps=1.00,
        plough_speed_mps=0.80,
    ),
    "plough_material_la_6min": _known_plough_material_case("plough_material_la_6min", "LA"),
    "plough_material_ha_6min": _known_plough_material_case("plough_material_ha_6min", "HA"),
    "plough_material_power_500kv_6min": _known_plough_material_case(
        "plough_material_power_500kv_6min",
        "POWER_500KV",
    ),
}

CONSTRUCTION_TIME_HISTORY_CASES: tuple[str, ...] = (
    "plough_straight_baseline_6min",
    "plough_straight_low_speed_6min",
    "plough_straight_high_speed_6min",
    "plough_straight_low_tdp_tension_6min",
    "plough_straight_high_tdp_tension_6min",
    "plough_cross_current_0p50_90deg_6min",
    "plough_cross_current_0p95_90deg_6min",
    "plough_cross_current_0p95_60deg_6min",
    "plough_cross_current_0p95_30deg_6min",
    "plough_cross_current_0p95_0deg_6min",
    "plough_decel_mild_6min",
    "plough_decel_strong_6min",
    "plough_decel_long_6min",
    "plough_payout_matched_6min",
    "plough_payout_fast_1p10_6min",
    "plough_payout_fast_1p25_6min",
    "plough_material_la_6min",
    "plough_material_ha_6min",
    "plough_material_power_500kv_6min",
)


def list_time_history_cases() -> list[str]:
    """Return all named LA time-history cases."""

    return sorted(_DYNAMIC_CASES)


def get_time_history_case(case_name: str) -> DynamicCaseInput:
    """Return one named LA time-history input case."""

    if case_name not in _DYNAMIC_CASES:
        raise KeyError(f"unknown time-history case: {case_name}")
    return _DYNAMIC_CASES[case_name]


def cable_parameters_from_dynamic_case(case: DynamicCaseInput) -> CableParameters:
    """Build the material parameter set used by the dynamic solver."""

    return CableParameters(
        name="DYNAMIC_INPUT",
        diameter_m=case.diameter_m,
        weight_air_n_per_m=case.weight_air_n_per_m,
        submerged_weight_n_per_m=case.submerged_weight_n_per_m,
        hydrodynamic_constant=_DEFAULT_DYNAMIC_CABLE.hydrodynamic_constant,
        tangential_drag_coefficient=case.tangential_drag_coefficient,
        normal_drag_coefficient=case.normal_drag_coefficient,
        total_length_m=_DEFAULT_DYNAMIC_CABLE.total_length_m,
        axial_stiffness_n=case.axial_stiffness_n,
        min_bending_radius_m=case.min_bending_radius_m,
    )


def solve_time_history(case_name: str, *, points: int = 361) -> TimeHistoryResult:
    """Solve a LA time-history case with finite-difference angle motion."""

    return solve_time_history_input(get_time_history_case(case_name), points=points)


def solve_time_history_input(case: DynamicCaseInput, *, points: int = 361) -> TimeHistoryResult:
    """Solve one LA time-history input with finite-difference angle motion."""

    if points < 3:
        raise ValueError("points must be at least 3")
    _validate_dynamic_case(case)
    return _solve_finite_difference_angle_time_history(case, points=points)


def _validate_dynamic_case(
    case: DynamicCaseInput,
    *,
    allowed_length_boundary_sources: set[str] | None = None,
) -> None:
    allowed_sources = allowed_length_boundary_sources or {"straight_line_sensitivity"}
    if case.speed_change not in {"steady", "accel", "decel"}:
        raise ValueError("speed_change must be steady, accel, or decel")
    if case.length_boundary_source not in allowed_sources:
        allowed = " or ".join(sorted(allowed_sources))
        raise ValueError(f"length_boundary_source must be {allowed}")
    if not 0.0 <= case.vessel_heading_deg <= 360.0:
        raise ValueError("vessel_heading_deg must be between 0 and 360")
    if case.length_boundary_source == "known_plough_trajectory":
        _validate_motion_samples("vessel_motion_samples", case.vessel_motion_samples)
        _validate_motion_samples("plough_motion_samples", case.plough_motion_samples, water_depth_m=case.water_depth_m)
        if not case.plough_motion_samples:
            for name, value in (
                ("plough_initial_x_m", case.plough_initial_x_m),
                ("plough_initial_y_m", case.plough_initial_y_m),
                ("plough_initial_z_m", case.plough_initial_z_m),
            ):
                if value is None:
                    raise ValueError(f"{name} is required for known_plough_trajectory")
        if not case.plough_motion_segments and not case.plough_motion_samples:
            for name, value in (
                ("plough_speed_mps", case.plough_speed_mps),
                ("plough_heading_deg", case.plough_heading_deg),
            ):
                if value is None:
                    raise ValueError(
                        f"{name} is required for known_plough_trajectory when plough_motion_segments is not provided"
                    )
        if case.plough_speed_mps is not None and case.plough_speed_mps < 0.0:
            raise ValueError("plough_speed_mps must be greater than or equal to 0")
        if case.plough_exit_speed_mps is not None and case.plough_exit_speed_mps < 0.0:
            raise ValueError("plough_exit_speed_mps must be greater than or equal to 0")
        if case.plough_exit_speed_mps is None and not allows_no_slip_inferred_plough_exit(
            plough_motion_segments=case.plough_motion_segments,
            plough_motion_samples=case.plough_motion_samples,
            plough_heading_deg=case.plough_heading_deg,
        ):
            raise ValueError(
                "plough_exit_speed_mps is required unless plough motion is a verified straight +X no-slip fallback"
            )
        if case.plough_heading_deg is not None and not 0.0 <= case.plough_heading_deg <= 360.0:
            raise ValueError("plough_heading_deg must be between 0 and 360")
        if case.initial_suspended_length_m is None:
            raise ValueError("initial_suspended_length_m is required for known_plough_trajectory")
        if case.initial_suspended_length_m <= 0.0:
            raise ValueError("initial_suspended_length_m must be greater than 0")
        if (
            case.plough_initial_z_m is not None
            and (case.plough_initial_z_m < 0.0 or case.plough_initial_z_m > case.water_depth_m)
        ):
            raise ValueError("plough_initial_z_m must be between 0 and water_depth_m")
        _validate_motion_segments("vessel_motion_segments", case.vessel_motion_segments)
        _validate_motion_segments("plough_motion_segments", case.plough_motion_segments)
        _validate_speed_segments("payout_speed_segments", case.payout_speed_segments)
    if case.element_count < 2:
        raise ValueError("element_count must be at least 2")
    for name, value in (
        ("current_speed_mps", case.current_speed_mps),
        ("initial_speed_mps", case.initial_speed_mps),
        ("final_speed_mps", case.final_speed_mps),
        ("duration_s", case.duration_s),
        ("touchdown_tension_n", case.touchdown_tension_n),
    ):
        if value < 0.0:
            raise ValueError(f"{name} must be greater than or equal to 0")
    for name, value in (
        ("payout_initial_speed_mps", case.payout_initial_speed_mps),
        ("payout_final_speed_mps", case.payout_final_speed_mps),
    ):
        if value is not None and value < 0.0:
            raise ValueError(f"{name} must be greater than or equal to 0")
    if case.min_bending_radius_m is not None and case.min_bending_radius_m <= 0.0:
        raise ValueError("min_bending_radius_m must be greater than 0")
    for name, value in (
        ("diameter_m", case.diameter_m),
        ("weight_air_n_per_m", case.weight_air_n_per_m),
        ("submerged_weight_n_per_m", case.submerged_weight_n_per_m),
        ("axial_stiffness_n", case.axial_stiffness_n),
    ):
        if value <= 0.0:
            raise ValueError(f"{name} must be greater than 0")
    for name, value in (
        ("tangential_drag_coefficient", case.tangential_drag_coefficient),
        ("normal_drag_coefficient", case.normal_drag_coefficient),
    ):
        if value < 0.0:
            raise ValueError(f"{name} must be greater than or equal to 0")
    for name, value in (
        ("total_duration_s", case.total_duration_s),
        ("water_depth_m", case.water_depth_m),
    ):
        if value <= 0.0:
            raise ValueError(f"{name} must be greater than 0")
    if not 0.0 <= case.current_direction_deg <= 360.0:
        raise ValueError("current_direction_deg must be between 0 and 360")
    if case.duration_s > case.total_duration_s:
        raise ValueError("duration_s must be less than or equal to total_duration_s")
    if case.duration_s <= 0.0:
        raise ValueError("duration_s must be greater than 0 for dynamic speed-change cases")
    if case.speed_change == "accel" and case.final_speed_mps <= case.initial_speed_mps:
        raise ValueError("final_speed_mps must be greater than initial_speed_mps when speed_change is accel")
    if case.speed_change == "decel" and case.final_speed_mps >= case.initial_speed_mps:
        raise ValueError("final_speed_mps must be less than initial_speed_mps when speed_change is decel")
    if case.speed_change == "steady" and not math.isclose(case.final_speed_mps, case.initial_speed_mps):
        raise ValueError("final_speed_mps must equal initial_speed_mps when speed_change is steady")


def _validate_motion_segments(name: str, segments: tuple[MotionSegment, ...]) -> None:
    for index, segment in enumerate(segments):
        if segment.duration_s <= 0.0:
            raise ValueError(f"{name}[{index}].duration_s must be greater than 0")
        if segment.start_speed_mps < 0.0 or segment.end_speed_mps < 0.0:
            raise ValueError(f"{name}[{index}] speeds must be greater than or equal to 0")
        if not 0.0 <= segment.heading_deg <= 360.0:
            raise ValueError(f"{name}[{index}].heading_deg must be between 0 and 360")


def _validate_motion_samples(
    name: str,
    samples: tuple[MotionSample, ...],
    *,
    water_depth_m: float | None = None,
) -> None:
    previous_time: float | None = None
    for index, sample in enumerate(samples):
        if sample.time_s < 0.0:
            raise ValueError(f"{name}[{index}].time_s must be greater than or equal to 0")
        if previous_time is not None and sample.time_s <= previous_time:
            raise ValueError(f"{name}[{index}].time_s must be strictly increasing")
        if index == 0 and not math.isclose(sample.time_s, 0.0, abs_tol=1.0e-9):
            raise ValueError(f"{name}[0].time_s must be 0")
        previous_time = sample.time_s
        if sample.z_m is not None and water_depth_m is not None and (sample.z_m < 0.0 or sample.z_m > water_depth_m):
            raise ValueError(f"{name}[{index}].z_m must be between 0 and water_depth_m")


def _validate_speed_segments(name: str, segments: tuple[SpeedSegment, ...]) -> None:
    for index, segment in enumerate(segments):
        if segment.duration_s <= 0.0:
            raise ValueError(f"{name}[{index}].duration_s must be greater than 0")
        if segment.start_speed_mps < 0.0 or segment.end_speed_mps < 0.0:
            raise ValueError(f"{name}[{index}] speeds must be greater than or equal to 0")


def allows_no_slip_inferred_plough_exit(
    *,
    plough_motion_segments: tuple[MotionSegment, ...],
    plough_motion_samples: tuple[MotionSample, ...],
    plough_heading_deg: float | None,
) -> bool:
    """Allow a no-slip material-flow fallback only for prescribed straight +X motion."""

    if plough_motion_samples:
        return False
    if plough_motion_segments:
        return all(_motion_segment_is_positive_x(segment) for segment in plough_motion_segments)
    return plough_heading_deg is not None and _is_positive_x_heading(plough_heading_deg)


def _motion_segment_is_positive_x(segment: MotionSegment) -> bool:
    components = (
        segment.start_velocity_x_mps,
        segment.start_velocity_y_mps,
        segment.end_velocity_x_mps,
        segment.end_velocity_y_mps,
    )
    if all(component is not None for component in components):
        start_x, start_y, end_x, end_y = components
        assert start_x is not None and start_y is not None and end_x is not None and end_y is not None
        return (
            start_x >= -_ROUTE_LONGITUDINAL_TOLERANCE
            and end_x >= -_ROUTE_LONGITUDINAL_TOLERANCE
            and abs(start_y) <= _ROUTE_LONGITUDINAL_TOLERANCE
            and abs(end_y) <= _ROUTE_LONGITUDINAL_TOLERANCE
        )
    return _is_positive_x_heading(segment.heading_deg)


def _is_positive_x_heading(heading_deg: float) -> bool:
    return math.isclose(heading_deg % 360.0, 0.0, abs_tol=_ROUTE_LONGITUDINAL_TOLERANCE)


def _solve_finite_difference_angle_time_history(
    case: DynamicCaseInput,
    *,
    points: int,
) -> TimeHistoryResult:
    sample_times = _sample_times(case, points)
    angle_samples = _integrate_angle_motion(case, sample_times)
    history = [_point_at_time(sample) for sample in angle_samples]
    frames = [_frame_at_time(sample) for sample in angle_samples]
    tensions = [point.top_tension_n for point in history]

    return TimeHistoryResult(
        case_name=case.case_name,
        diameter_m=case.diameter_m,
        weight_air_n_per_m=case.weight_air_n_per_m,
        submerged_weight_n_per_m=case.submerged_weight_n_per_m,
        tangential_drag_coefficient=case.tangential_drag_coefficient,
        normal_drag_coefficient=case.normal_drag_coefficient,
        axial_stiffness_n=case.axial_stiffness_n,
        current_speed_mps=case.current_speed_mps,
        current_direction_deg=case.current_direction_deg,
        speed_change=case.speed_change,
        initial_speed_mps=case.initial_speed_mps,
        final_speed_mps=case.final_speed_mps,
        duration_s=case.duration_s,
        total_duration_s=case.total_duration_s,
        water_depth_m=case.water_depth_m,
        element_count=case.element_count,
        touchdown_tension_n=case.touchdown_tension_n,
        payout_initial_speed_mps=_initial_payout_speed(case),
        payout_final_speed_mps=_final_payout_speed(case),
        length_boundary_source=case.length_boundary_source,
        initial_suspended_length_m=case.initial_suspended_length_m,
        evidence_level=(
            "LA finite-difference angle motion with straight-line length boundary; "
            "Table 4-1 is diagnostic, not full Eq. 3.5.5 N/B iteration"
        ),
        initial_tension_n=history[0].top_tension_n,
        extreme_tension_n=min(tensions) if case.speed_change == "accel" else max(tensions),
        steady_tension_n=history[-1].top_tension_n,
        history=history,
        frames=frames,
        vessel_motion_segments=case.vessel_motion_segments,
        plough_motion_segments=case.plough_motion_segments,
        vessel_motion_samples=case.vessel_motion_samples,
        plough_motion_samples=case.plough_motion_samples,
        payout_speed_segments=case.payout_speed_segments,
    )


def _point_at_time(sample: _AngleSample) -> TimeHistoryPoint:
    return TimeHistoryPoint(
        time_s=float(sample.time_s),
        top_tension_n=float(sample.tension_n),
        tdp_x_m=float(sample.tdp_x_m),
        tdp_y_m=float(sample.tdp_y_m),
        suspended_length_m=float(sample.suspended_length_m),
        iterations=sample.integration_steps,
    )


def _frame_at_time(sample: _AngleSample) -> TimeHistoryFrame:
    ds = sample.suspended_length_m / max(len(sample.angles_rad), 1)
    top_to_bottom_tensions = tuple(reversed(sample.tensions_n))
    points = [
        TimeHistoryFramePoint(
            index=0,
            x_m=0.0,
            y_m=0.0,
            z_m=0.0,
            tension_n=float(top_to_bottom_tensions[0]),
        )
    ]
    x_m = 0.0
    y_m = 0.0
    z_m = 0.0
    top_to_bottom_angles = tuple(reversed(sample.angles_rad))
    top_to_bottom_psis = tuple(reversed(sample.psis_rad))
    for index, (angle, psi) in enumerate(zip(top_to_bottom_angles, top_to_bottom_psis), start=1):
        tangent = _tangent_components(angle, psi)
        x_m += ds * tangent[0]
        y_m += ds * tangent[1]
        z_m += ds * tangent[2]
        points.append(
            TimeHistoryFramePoint(
                index=index,
                x_m=float(x_m),
                y_m=float(y_m),
                z_m=float(z_m),
                tension_n=float(top_to_bottom_tensions[index]),
            )
        )
    return TimeHistoryFrame(time_s=float(sample.time_s), points=points)


def _integrate_angle_motion(case: DynamicCaseInput, sample_times: list[float]) -> list[_AngleSample]:
    """Integrate cable element angles with a finite-difference RK4 loop."""

    if not sample_times:
        return []

    initial = _straight_line_state(case, case.initial_speed_mps)
    angles = tuple(initial.theta_rad for _ in range(case.element_count))
    psis = tuple(initial.psi_rad for _ in range(case.element_count))
    state = _AngleState(
        angles_rad=angles,
        psis_rad=psis,
        angular_rates_radps=tuple(0.0 for _ in range(case.element_count)),
        azimuth_rates_radps=tuple(0.0 for _ in range(case.element_count)),
        suspended_length_m=initial.suspended_length_m,
    )
    samples: list[_AngleSample] = []
    next_sample = 0
    current_time = 0.0
    steps = 0
    dt_max = _angle_time_step_s(case)

    while next_sample < len(sample_times):
        target_time = sample_times[next_sample]
        while current_time + 1.0e-9 < target_time:
            dt = min(dt_max, target_time - current_time)
            state = _rk4_angle_step(case, current_time, state, dt)
            current_time += dt
            steps += 1
        samples.append(_angle_sample(case, target_time, state, max(steps * case.element_count, case.element_count)))
        next_sample += 1

    return samples


def _rk4_angle_step(case: DynamicCaseInput, time_s: float, state: _AngleState, dt: float) -> _AngleState:
    """Advance all element angles with one fourth-order Runge-Kutta step."""

    k1 = _angle_derivative(case, time_s, state)
    k2 = _angle_derivative(
        case,
        time_s + 0.5 * dt,
        _advance_angle_state(state, k1, 0.5 * dt),
    )
    k3 = _angle_derivative(
        case,
        time_s + 0.5 * dt,
        _advance_angle_state(state, k2, 0.5 * dt),
    )
    k4 = _angle_derivative(
        case,
        time_s + dt,
        _advance_angle_state(state, k3, dt),
    )
    return _combine_angle_steps(state, (k1, k2, k3, k4), dt)


def _angle_derivative(case: DynamicCaseInput, time_s: float, state: _AngleState) -> _AngleState:
    angle_accelerations, azimuth_accelerations = _angle_accelerations(case, time_s, state)
    return _AngleState(
        angles_rad=state.angular_rates_radps,
        psis_rad=state.azimuth_rates_radps,
        angular_rates_radps=tuple(angle_accelerations),
        azimuth_rates_radps=tuple(azimuth_accelerations),
        suspended_length_m=_suspended_length_rate_mps(case, time_s, state),
    )


def _advance_angle_state(state: _AngleState, derivative: _AngleState, dt: float) -> _AngleState:
    return _AngleState(
        angles_rad=tuple(
            _clamp_angle(angle + dt * delta)
            for angle, delta in zip(state.angles_rad, derivative.angles_rad)
        ),
        psis_rad=tuple(
            _wrap_azimuth(psi + dt * delta)
            for psi, delta in zip(state.psis_rad, derivative.psis_rad)
        ),
        angular_rates_radps=tuple(
            _clamp_angular_rate(rate + dt * delta)
            for rate, delta in zip(state.angular_rates_radps, derivative.angular_rates_radps)
        ),
        azimuth_rates_radps=tuple(
            _clamp_angular_rate(rate + dt * delta)
            for rate, delta in zip(state.azimuth_rates_radps, derivative.azimuth_rates_radps)
        ),
        suspended_length_m=_clamp_suspended_length_m(
            state.suspended_length_m + dt * derivative.suspended_length_m
        ),
    )


def _combine_angle_steps(
    state: _AngleState,
    derivatives: tuple[_AngleState, _AngleState, _AngleState, _AngleState],
    dt: float,
) -> _AngleState:
    k1, k2, k3, k4 = derivatives
    return _AngleState(
        angles_rad=tuple(
            _clamp_angle(
                angle
                + dt
                / 6.0
                * (
                    d1
                    + 2.0 * d2
                    + 2.0 * d3
                    + d4
                )
            )
            for angle, d1, d2, d3, d4 in zip(
                state.angles_rad,
                k1.angles_rad,
                k2.angles_rad,
                k3.angles_rad,
                k4.angles_rad,
            )
        ),
        psis_rad=tuple(
            _wrap_azimuth(
                psi
                + dt
                / 6.0
                * (
                    d1
                    + 2.0 * d2
                    + 2.0 * d3
                    + d4
                )
            )
            for psi, d1, d2, d3, d4 in zip(
                state.psis_rad,
                k1.psis_rad,
                k2.psis_rad,
                k3.psis_rad,
                k4.psis_rad,
            )
        ),
        angular_rates_radps=tuple(
            _clamp_angular_rate(
                rate
                + dt
                / 6.0
                * (
                    d1
                    + 2.0 * d2
                    + 2.0 * d3
                    + d4
                )
            )
            for rate, d1, d2, d3, d4 in zip(
                state.angular_rates_radps,
                k1.angular_rates_radps,
                k2.angular_rates_radps,
                k3.angular_rates_radps,
                k4.angular_rates_radps,
            )
        ),
        azimuth_rates_radps=tuple(
            _clamp_angular_rate(
                rate
                + dt
                / 6.0
                * (
                    d1
                    + 2.0 * d2
                    + 2.0 * d3
                    + d4
                )
            )
            for rate, d1, d2, d3, d4 in zip(
                state.azimuth_rates_radps,
                k1.azimuth_rates_radps,
                k2.azimuth_rates_radps,
                k3.azimuth_rates_radps,
                k4.azimuth_rates_radps,
            )
        ),
        suspended_length_m=_clamp_suspended_length_m(
            state.suspended_length_m
            + dt
            / 6.0
            * (
                k1.suspended_length_m
                + 2.0 * k2.suspended_length_m
                + 2.0 * k3.suspended_length_m
                + k4.suspended_length_m
            )
        ),
    )


def _angle_accelerations(case: DynamicCaseInput, time_s: float, state: _AngleState) -> tuple[list[float], list[float]]:
    """Return inclination and azimuth accelerations for all cable elements."""

    cable = get_cable("LA")
    speed = _vessel_speed(case, time_s)
    top_state = _straight_line_state(case, speed)
    top_boundary = top_state.theta_rad
    top_azimuth = top_state.psi_rad
    ds = _angle_element_length_m(case, state)
    tangential_accelerations = _element_tangential_accelerations(case, time_s, state)
    tensions = _finite_difference_tensions(
        case,
        time_s,
        state.angles_rad,
        state.psis_rad,
        tangential_accelerations_mps2=tangential_accelerations,
        suspended_length_m=_state_suspended_length_m(case, state),
    )
    mass_per_meter = max(_dynamic_mass_per_meter(cable), _MIN_SPEED_MPS)
    damping = _angle_damping_ratio(case)
    speed_accel = _speed_acceleration_mps2(case, time_s)
    suspended_ratio = _state_suspended_length_m(case, state) / max(case.water_depth_m, _MIN_SPEED_MPS)
    current_x, current_y = _relative_current_components(case, speed)
    relative_speed = math.hypot(current_x, current_y)
    angle_accelerations: list[float] = []
    azimuth_accelerations: list[float] = []

    for index, (angle, psi) in enumerate(zip(state.angles_rad, state.psis_rad)):
        lower = state.angles_rad[index - 1] if index > 0 else angle
        upper = state.angles_rad[index + 1] if index < len(state.angles_rad) - 1 else top_boundary
        curvature = (lower - 2.0 * angle + upper) / max(ds * ds, _MIN_SPEED_MPS)
        lower_psi = state.psis_rad[index - 1] if index > 0 else psi
        upper_psi = state.psis_rad[index + 1] if index < len(state.psis_rad) - 1 else top_azimuth
        azimuth_curvature = (
            _angle_difference(lower_psi, psi)
            + _angle_difference(upper_psi, psi)
        ) / max(ds * ds, _MIN_SPEED_MPS)
        mean_tension = max(0.5 * (tensions[index] + tensions[index + 1]), _MIN_SPEED_MPS)
        stiffness = mean_tension / mass_per_meter
        natural = math.sqrt(max(stiffness / max(ds * ds, _MIN_SPEED_MPS) + _GRAVITY_MPS2 / max(ds, _MIN_SPEED_MPS), _MIN_SPEED_MPS))
        force_balance = _straight_line_angle_residual(case, speed, angle)
        motion_acceleration = speed_accel * math.sin(angle) * suspended_ratio / max(ds, _MIN_SPEED_MPS)
        azimuth_residual = _angle_difference(top_azimuth, psi)
        azimuth_turning = relative_speed * relative_speed * azimuth_residual / max(ds * ds, _MIN_SPEED_MPS)
        azimuth_motion = speed_accel * math.cos(angle) * math.sin(azimuth_residual) / max(ds, _MIN_SPEED_MPS)
        angle_accelerations.append(
            stiffness * curvature
            + _GRAVITY_MPS2 / max(ds, _MIN_SPEED_MPS) * force_balance
            + motion_acceleration
            - 2.0 * damping * natural * state.angular_rates_radps[index]
        )
        azimuth_accelerations.append(
            stiffness * azimuth_curvature
            + azimuth_turning
            + azimuth_motion
            - 2.0 * damping * natural * state.azimuth_rates_radps[index]
        )

    return angle_accelerations, azimuth_accelerations


def _angle_sample(
    case: DynamicCaseInput,
    time_s: float,
    state: _AngleState,
    integration_steps: int,
) -> _AngleSample:
    tangential_accelerations = _element_tangential_accelerations(case, time_s, state)
    tensions = _finite_difference_tensions(
        case,
        time_s,
        state.angles_rad,
        state.psis_rad,
        tangential_accelerations_mps2=tangential_accelerations,
        suspended_length_m=_state_suspended_length_m(case, state),
    )
    ds = _angle_element_length_m(case, state)
    suspended_length_m = _state_suspended_length_m(case, state)
    tdp_x = sum(ds * _tangent_components(angle, psi)[0] for angle, psi in zip(state.angles_rad, state.psis_rad))
    tdp_y = sum(ds * _tangent_components(angle, psi)[1] for angle, psi in zip(state.angles_rad, state.psis_rad))
    return _AngleSample(
        time_s=time_s,
        tension_n=tensions[-1],
        tdp_x_m=tdp_x,
        tdp_y_m=tdp_y,
        suspended_length_m=suspended_length_m,
        angles_rad=state.angles_rad,
        psis_rad=state.psis_rad,
        tensions_n=tuple(tensions),
        integration_steps=integration_steps,
    )


def _finite_difference_tensions(
    case: DynamicCaseInput,
    time_s: float,
    angles_rad: tuple[float, ...],
    psis_rad: tuple[float, ...] | None = None,
    *,
    tangential_accelerations_mps2: tuple[float, ...] | None = None,
    suspended_length_m: float | None = None,
) -> list[float]:
    """Return bottom-to-top nodal tensions from element angles and loads."""

    cable = get_cable("LA")
    speed = _vessel_speed(case, time_s)
    if psis_rad is None:
        psi = _straight_line_state(case, speed).psi_rad
        psis_rad = tuple(psi for _ in angles_rad)
    if tangential_accelerations_mps2 is None:
        tangential_accelerations_mps2 = tuple(0.0 for _ in angles_rad)
    if len(psis_rad) != len(angles_rad):
        raise ValueError("psis_rad must have the same length as angles_rad")
    if len(tangential_accelerations_mps2) != len(angles_rad):
        raise ValueError("tangential_accelerations_mps2 must have the same length as angles_rad")
    ds = (
        suspended_length_m / max(len(angles_rad), 1)
        if suspended_length_m is not None
        else _angle_element_length_m(case, angles_rad)
    )
    mass_per_meter = _dynamic_mass_per_meter(cable)
    tension = case.touchdown_tension_n
    tensions = [tension]

    for angle, psi, tangential_acceleration in zip(angles_rad, psis_rad, tangential_accelerations_mps2):
        tangential_drag = _tangential_drag_for_angle(case, speed, angle, psi)
        vertical_weight = cable.submerged_weight_n_per_m * ds * math.sin(angle)
        dynamic_tension = -mass_per_meter * tangential_acceleration * ds
        tension += vertical_weight - tangential_drag * ds + dynamic_tension
        tensions.append(tension)

    return tensions


def _element_tangential_accelerations(
    case: DynamicCaseInput,
    time_s: float,
    state: _AngleState,
) -> tuple[float, ...]:
    """Return local tangential acceleration for each cable element."""

    vessel_acceleration_y = _speed_acceleration_mps2(case, time_s)
    return tuple(
        vessel_acceleration_y * _tangent_components(theta, psi)[1]
        for theta, psi in zip(state.angles_rad, state.psis_rad)
    )


def _tangential_drag_for_angle(
    case: DynamicCaseInput,
    vessel_speed_mps: float,
    theta: float,
    psi: float,
) -> float:
    cable = get_cable("LA")
    current_x, current_y = _relative_current_components(case, vessel_speed_mps)
    tangent = _tangent_components(theta, psi)
    along_tangent = current_x * tangent[0] + current_y * tangent[1]
    tangential_relative_speed = along_tangent - vessel_speed_mps
    return (
        -0.5
        * math.pi
        * _SEAWATER_DENSITY_KG_M3
        * cable.tangential_drag_coefficient
        * cable.diameter_m
        * tangential_relative_speed
        * abs(tangential_relative_speed)
    )


def _straight_line_angle_residual(case: DynamicCaseInput, vessel_speed_mps: float, theta: float) -> float:
    """Return the Eq. 3.39-3.43 straight-line force-balance residual."""

    current_x, current_y = _relative_current_components(case, vessel_speed_mps)
    relative_speed = math.hypot(current_x, current_y)
    ratio = _hydrodynamic_constant(get_cable("LA")) / max(relative_speed, _MIN_SPEED_MPS)
    cos_theta = max(0.0, min(1.0, math.cos(theta)))
    return cos_theta * cos_theta + ratio * ratio * cos_theta - 1.0


def _speed_acceleration_mps2(case: DynamicCaseInput, time_s: float) -> float:
    """Return the prescribed vessel acceleration during the speed-change window."""

    if time_s <= 0.0 or time_s > case.duration_s or case.duration_s <= 0.0:
        return 0.0
    return (case.final_speed_mps - case.initial_speed_mps) / case.duration_s


def _angle_element_length_m(case: DynamicCaseInput, state_or_angles: _AngleState | tuple[float, ...]) -> float:
    if isinstance(state_or_angles, _AngleState):
        return _state_suspended_length_m(case, state_or_angles) / max(len(state_or_angles.angles_rad), 1)
    angles_rad = state_or_angles
    return _inferred_suspended_length_m(case, angles_rad) / max(len(angles_rad), 1)


def _state_suspended_length_m(case: DynamicCaseInput, state: _AngleState) -> float:
    if state.suspended_length_m > _MIN_SPEED_MPS:
        return state.suspended_length_m
    return _inferred_suspended_length_m(case, state.angles_rad)


def _inferred_suspended_length_m(case: DynamicCaseInput, angles_rad: tuple[float, ...]) -> float:
    vertical_sum = sum(max(math.sin(angle), _MIN_SPEED_MPS) for angle in angles_rad)
    return case.water_depth_m / max(vertical_sum, _MIN_SPEED_MPS)


def _suspended_length_rate_mps(case: DynamicCaseInput, time_s: float, state: _AngleState) -> float:
    """Update L(t) from the available straight-line boundary sensitivity."""

    speed_acceleration = _speed_acceleration_mps2(case, time_s)
    speed = _vessel_speed(case, time_s)
    boundary_rate = 0.0
    if abs(speed_acceleration) > _MIN_SPEED_MPS:
        delta_speed = max(1.0e-4, abs(speed) * 1.0e-4)
        lower_speed = max(0.0, speed - delta_speed)
        upper_speed = speed + delta_speed
        lower_length = _straight_line_state(case, lower_speed).suspended_length_m
        upper_length = _straight_line_state(case, upper_speed).suspended_length_m
        d_length_d_speed = (upper_length - lower_length) / max(upper_speed - lower_speed, _MIN_SPEED_MPS)
        boundary_rate = d_length_d_speed * speed_acceleration
    return boundary_rate + _payout_speed(case, time_s) - speed


def _payout_speed(case: DynamicCaseInput, time_s: float) -> float:
    """Return the prescribed payout speed; defaults to the vessel speed table."""

    if case.payout_speed_segments:
        return _scalar_segment_speed(case.payout_speed_segments, time_s)
    initial = _initial_payout_speed(case)
    final = _final_payout_speed(case)
    if time_s >= case.duration_s:
        return final
    fraction = max(0.0, min(1.0, time_s / max(case.duration_s, 1.0e-12)))
    return initial + (final - initial) * fraction


def _initial_payout_speed(case: DynamicCaseInput) -> float:
    if case.payout_speed_segments:
        return case.payout_speed_segments[0].start_speed_mps
    return case.initial_speed_mps if case.payout_initial_speed_mps is None else case.payout_initial_speed_mps


def _final_payout_speed(case: DynamicCaseInput) -> float:
    if case.payout_speed_segments:
        return case.payout_speed_segments[-1].end_speed_mps
    return case.final_speed_mps if case.payout_final_speed_mps is None else case.payout_final_speed_mps


def _scalar_segment_speed(segments: tuple[SpeedSegment, ...], time_s: float) -> float:
    remaining = max(0.0, time_s)
    last_segment = None
    for segment in segments:
        last_segment = segment
        duration = max(segment.duration_s, _MIN_SPEED_MPS)
        if remaining <= duration:
            fraction = max(0.0, min(1.0, remaining / duration))
            return segment.start_speed_mps + (segment.end_speed_mps - segment.start_speed_mps) * fraction
        remaining -= duration
    return 0.0 if last_segment is None else last_segment.end_speed_mps


def _clamp_suspended_length_m(length_m: float) -> float:
    return max(_MIN_SPEED_MPS, length_m)


def _angle_damping_ratio(case: DynamicCaseInput) -> float:
    cable = get_cable("LA")
    return max(0.0, cable.tangential_drag_coefficient / max(cable.normal_drag_coefficient, _MIN_SPEED_MPS))


def _dynamic_mass_per_meter(cable) -> float:
    structural_mass = cable.weight_air_n_per_m / _GRAVITY_MPS2
    displaced_water_mass = _SEAWATER_DENSITY_KG_M3 * math.pi * cable.diameter_m * cable.diameter_m / 4.0
    return structural_mass + _CYLINDER_ADDED_MASS_COEFFICIENT * displaced_water_mass


def _angle_time_step_s(case: DynamicCaseInput) -> float:
    return max(0.02, min(0.05, case.total_duration_s / 7200.0))


def _clamp_angle(angle: float) -> float:
    return max(math.radians(3.0), min(math.radians(85.0), angle))


def _clamp_angular_rate(rate: float) -> float:
    return max(-1.0, min(1.0, rate))


def _wrap_azimuth(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _angle_difference(target: float, current: float) -> float:
    return math.atan2(math.sin(target - current), math.cos(target - current))


def _straight_line_state(case: DynamicCaseInput, vessel_speed_mps: float) -> _StraightLineState:
    """Return the thesis straight-line LA state at one vessel speed.

    The relations follow Eq. 3.39-3.43 for the straight-line angle and the
    steady top-tension balance ``Ts = w h - Dt L + T0``. No Table 4-1 values
    are read here.
    """

    current_x, current_y = _relative_current_components(case, vessel_speed_mps)
    relative_speed = math.hypot(current_x, current_y)
    hydrodynamic_constant = _hydrodynamic_constant(get_cable("LA"))
    ratio = hydrodynamic_constant / max(relative_speed, _MIN_SPEED_MPS)
    cos_theta = math.sqrt(1.0 + 0.25 * ratio**4) - 0.5 * ratio**2
    cos_theta = max(0.0, min(1.0, cos_theta))
    theta = math.acos(cos_theta)
    psi = math.atan2(current_y, current_x)
    top_tension, suspended_length = _top_tension_from_orientation(case, vessel_speed_mps, theta, psi)
    horizontal = suspended_length * cos_theta
    return _StraightLineState(
        theta_rad=theta,
        psi_rad=psi,
        suspended_length_m=suspended_length,
        top_tension_n=top_tension,
        tdp_x_m=horizontal * math.cos(psi),
        tdp_y_m=horizontal * math.sin(psi),
    )


def _top_tension_from_orientation(
    case: DynamicCaseInput,
    vessel_speed_mps: float,
    theta: float,
    psi: float,
) -> tuple[float, float]:
    """Return top tension and suspended length for one straight orientation."""

    cable = get_cable("LA")
    sin_theta = max(math.sin(theta), _MIN_SPEED_MPS)
    current_x, current_y = _relative_current_components(case, vessel_speed_mps)
    tangent = _tangent_components(theta, psi)
    along_tangent = current_x * tangent[0] + current_y * tangent[1]
    tangential_relative_speed = along_tangent - vessel_speed_mps
    tangential_drag = (
        -0.5
        * math.pi
        * _SEAWATER_DENSITY_KG_M3
        * cable.tangential_drag_coefficient
        * cable.diameter_m
        * tangential_relative_speed
        * abs(tangential_relative_speed)
    )
    suspended_length = case.water_depth_m / sin_theta
    top_tension = (
        case.touchdown_tension_n
        + cable.submerged_weight_n_per_m * case.water_depth_m
        - tangential_drag * suspended_length
    )
    return top_tension, suspended_length


def _relative_current_components(case: DynamicCaseInput, vessel_speed_mps: float) -> tuple[float, float]:
    """Return vessel-fixed horizontal water velocity components.

    ``x`` is the operation-track longitudinal/surge-aligned direction and
    ``y`` is the transverse/sway-aligned direction. The vessel advance is
    represented as apparent water motion in the positive ``x`` direction for
    this legacy LA diagnostic path.
    """

    direction = math.radians(case.current_direction_deg)
    environmental_x = case.current_speed_mps * math.cos(direction)
    environmental_y = case.current_speed_mps * math.sin(direction)
    return environmental_x + vessel_speed_mps, environmental_y


def _apparent_current_components(case: DynamicCaseInput, vessel_speed_mps: float) -> tuple[float, float]:
    """Backward-compatible name for vessel-fixed relative current components."""

    return _relative_current_components(case, vessel_speed_mps)


def _tangent_components(theta: float, psi: float) -> tuple[float, float, float]:
    """Return the global tangent convention shared with kinematics.py."""

    cos_theta = math.cos(theta)
    return (
        cos_theta * math.cos(psi),
        cos_theta * math.sin(psi),
        math.sin(theta),
    )


def _vessel_speed(case: DynamicCaseInput, time_s: float) -> float:
    """Return the linearly prescribed vessel speed at a time sample."""

    if time_s >= case.duration_s:
        return case.final_speed_mps
    fraction = max(0.0, min(1.0, time_s / max(case.duration_s, 1.0e-12)))
    return case.initial_speed_mps + (case.final_speed_mps - case.initial_speed_mps) * fraction


def _sample_times(case: DynamicCaseInput, points: int) -> list[float]:
    """Return report sample times while preserving the speed-change endpoint."""

    times = [case.total_duration_s * index / (points - 1) for index in range(points)]
    if 0.0 < case.duration_s < case.total_duration_s and points > 2:
        closest = min(range(1, points - 1), key=lambda index: abs(times[index] - case.duration_s))
        times[closest] = case.duration_s
    return times


def _hydrodynamic_constant(cable) -> float:
    if cable.hydrodynamic_constant > 0.0:
        return cable.hydrodynamic_constant
    return math.sqrt(
        2.0
        * cable.submerged_weight_n_per_m
        / (_SEAWATER_DENSITY_KG_M3 * cable.normal_drag_coefficient * cable.diameter_m)
    )

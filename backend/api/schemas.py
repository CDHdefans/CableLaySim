"""Small JSON helpers for the cable tension API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cable_tension.dynamic import DynamicCaseInput, TimeHistoryResult
from cable_tension.parameters import OperationCase
from cable_tension.solver import SolverResult


@dataclass(frozen=True)
class ApiResponse:
    """A test-friendly HTTP response object."""

    status: int
    body: bytes
    headers: dict[str, str]


def json_response(payload: dict[str, Any], *, status: int = 200) -> ApiResponse:
    """Serialize a JSON response with consistent headers."""

    return ApiResponse(
        status=status,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def error_response(
    error: str,
    message: str,
    *,
    status: int,
    details: dict[str, Any] | None = None,
) -> ApiResponse:
    """Return a structured API error payload."""

    payload: dict[str, Any] = {"error": error, "message": message}
    if details is not None:
        payload["details"] = details
    return json_response(payload, status=status)


def case_payload(case: OperationCase) -> dict[str, Any]:
    """Convert a named case into the frontend-facing input shape."""

    metadata = _case_example_metadata(case)
    return {
        "name": case.name,
        "label": metadata["label"],
        "description": metadata["description"],
        "group": _case_group(case),
        "example": metadata["example"],
        "display_order": metadata["display_order"],
        "suggested_output_dir": metadata["suggested_output_dir"],
        "inputs": {
            "cable": _cable_display_name(case.cable.name),
            "solver_model": case.solver_model,
            "diameter_m": case.cable.diameter_m,
            "weight_air_n_per_m": case.cable.weight_air_n_per_m,
            "submerged_weight_n_per_m": case.cable.submerged_weight_n_per_m,
            "hydrodynamic_constant": case.cable.hydrodynamic_constant,
            "tangential_drag_coefficient": case.cable.tangential_drag_coefficient,
            "normal_drag_coefficient": case.cable.normal_drag_coefficient,
            "total_length_m": case.cable.total_length_m,
            "axial_stiffness_n": case.cable.axial_stiffness_n,
            "max_water_depth_m": case.cable.max_water_depth_m,
            "max_allowable_tension_n": case.cable.max_allowable_tension_n,
            "min_bending_radius_m": case.cable.min_bending_radius_m,
            "initial_speed_mps": case.initial_speed_mps,
            "final_speed_mps": case.final_speed_mps,
            "duration_s": case.duration_s,
            "water_depth_m": case.water_depth_m,
            "touchdown_tension_n": case.touchdown_tension_n,
            "current_u_mps": case.current_u_mps,
            "current_v_mps": case.current_v_mps,
            "vessel_speed_mps": case.vessel_speed_mps,
            "payout_speed_mps": case.payout_speed_mps,
            "current_surface_mps": case.current_surface_mps,
            "current_bottom_mps": case.current_bottom_mps,
            "current_direction_deg": case.current_direction_deg,
        },
    }


def time_history_case_payload(case: DynamicCaseInput) -> dict[str, Any]:
    """Convert a named LA dynamic case into the frontend-facing input shape."""

    metadata = _dynamic_example_metadata(case)
    return {
        "name": case.case_name,
        "label": metadata["label"],
        "description": metadata["description"],
        "group": metadata["group"],
        "example": metadata["example"],
        "display_order": metadata["display_order"],
        "suggested_output_dir": metadata["suggested_output_dir"],
        "inputs": {
            "case_name": case.case_name,
            "diameter_m": case.diameter_m,
            "weight_air_n_per_m": case.weight_air_n_per_m,
            "submerged_weight_n_per_m": case.submerged_weight_n_per_m,
            "tangential_drag_coefficient": case.tangential_drag_coefficient,
            "normal_drag_coefficient": case.normal_drag_coefficient,
            "axial_stiffness_n": case.axial_stiffness_n,
            "current_speed_mps": case.current_speed_mps,
            "current_direction_deg": case.current_direction_deg,
            "speed_change": case.speed_change,
            "initial_speed_mps": case.initial_speed_mps,
            "final_speed_mps": case.final_speed_mps,
            "payout_initial_speed_mps": case.payout_initial_speed_mps,
            "payout_final_speed_mps": case.payout_final_speed_mps,
            "length_boundary_source": case.length_boundary_source,
            "duration_s": case.duration_s,
            "total_duration_s": case.total_duration_s,
            "water_depth_m": case.water_depth_m,
            "element_count": case.element_count,
            "touchdown_tension_n": case.touchdown_tension_n,
            "vessel_initial_x_m": case.vessel_initial_x_m,
            "vessel_initial_y_m": case.vessel_initial_y_m,
            "vessel_heading_deg": case.vessel_heading_deg,
            "plough_initial_x_m": case.plough_initial_x_m,
            "plough_initial_y_m": case.plough_initial_y_m,
            "plough_initial_z_m": case.plough_initial_z_m,
            "plough_speed_mps": case.plough_speed_mps,
            "plough_exit_speed_mps": case.plough_exit_speed_mps,
            "plough_heading_deg": case.plough_heading_deg,
            "initial_suspended_length_m": case.initial_suspended_length_m,
            "min_bending_radius_m": case.min_bending_radius_m,
            "vessel_motion_segments": [_motion_segment_payload(segment) for segment in case.vessel_motion_segments],
            "plough_motion_segments": [_motion_segment_payload(segment) for segment in case.plough_motion_segments],
            "vessel_motion_samples": [_motion_sample_payload(sample) for sample in case.vessel_motion_samples],
            "plough_motion_samples": [_motion_sample_payload(sample) for sample in case.plough_motion_samples],
            "payout_speed_segments": [_speed_segment_payload(segment) for segment in case.payout_speed_segments],
        },
    }


_CASE_EXAMPLES: dict[str, tuple[str, str, int, str]] = {
    "power_current_speed_1p50": (
        "500kV电力缆｜水深100 m、流速1.50 m/s",
        "填入 500kV 电力缆、水深、表层流速和底层流速。",
        30,
        "custom/500kv-standard-current-1p50",
    ),
    "power_current_direction_30": (
        "500kV电力缆｜流向30°",
        "在相同水深和流速下改相对流向，查看三维偏移。",
        40,
        "custom/500kv-current-direction-30deg",
    ),
    "power_pretension_3000": (
        "500kV电力缆｜触地点张力3000 N",
        "在相同水深和流速下改触地点张力。",
        50,
        "custom/500kv-touchdown-tension-3000n",
    ),
}


_DYNAMIC_CASE_EXAMPLES: dict[str, tuple[str, str, str, int, str]] = {
    "plough_straight_baseline_6min": (
        "常规基准",
        "船、放缆和埋设犁稳定同步前进，用作其他对比的基准。",
        "常规直线铺埋",
        10,
        "time_histories/plough-straight-baseline",
    ),
    "plough_straight_low_speed_6min": (
        "低速铺埋",
        "只降低船速、放缆速度和犁速，观察悬垂形态和张力变化。",
        "常规直线铺埋",
        20,
        "time_histories/plough-straight-low-speed",
    ),
    "plough_straight_high_speed_6min": (
        "高速铺埋",
        "只提高船速、放缆速度和犁速，观察速度敏感性。",
        "常规直线铺埋",
        30,
        "time_histories/plough-straight-high-speed",
    ),
    "plough_straight_low_tdp_tension_6min": (
        "低触地张力",
        "只降低触地点张力，观察入口张力、TDP 和悬垂形态变化。",
        "常规直线铺埋",
        40,
        "time_histories/plough-straight-low-tdp-tension",
    ),
    "plough_straight_high_tdp_tension_6min": (
        "高触地张力",
        "只提高触地点张力，观察张力分布和悬垂形态变化。",
        "常规直线铺埋",
        50,
        "time_histories/plough-straight-high-tdp-tension",
    ),
    "plough_cross_current_0p50_90deg_6min": (
        "横流0.50 m/s",
        "固定铺埋速度，施加垂向来流，观察侧偏和张力分布。",
        "横流偏载",
        110,
        "time_histories/plough-cross-current-0p50-90deg",
    ),
    "plough_cross_current_0p95_90deg_6min": (
        "横流0.95 m/s",
        "只提高横向海流速度，对比流速大小的影响。",
        "横流偏载",
        120,
        "time_histories/plough-cross-current-0p95-90deg",
    ),
    "plough_cross_current_0p95_60deg_6min": (
        "来流60°",
        "保持流速不变，将来流方向改为 60°。",
        "横流偏载",
        130,
        "time_histories/plough-cross-current-0p95-60deg",
    ),
    "plough_cross_current_0p95_30deg_6min": (
        "来流30°",
        "保持流速不变，将来流方向改为 30°。",
        "横流偏载",
        140,
        "time_histories/plough-cross-current-0p95-30deg",
    ),
    "plough_cross_current_0p95_0deg_6min": (
        "来流0°",
        "保持流速不变，将来流方向改为顺铺埋方向。",
        "横流偏载",
        150,
        "time_histories/plough-cross-current-0p95-0deg",
    ),
    "plough_decel_mild_6min": (
        "温和减速",
        "船端、放缆和犁端同步减速，观察顶张力峰值和回落。",
        "控速减速",
        210,
        "time_histories/plough-decel-mild",
    ),
    "plough_decel_strong_6min": (
        "强减速",
        "提高减速幅度，检查动态峰值和 TDP 迁移。",
        "控速减速",
        220,
        "time_histories/plough-decel-strong",
    ),
    "plough_decel_long_6min": (
        "长历时减速",
        "用更长减速历时释放加速度冲击，观察峰值是否降低。",
        "控速减速",
        230,
        "time_histories/plough-decel-long",
    ),
    "plough_payout_matched_6min": (
        "同步放缆",
        "放缆速度与犁速相同，用作放缆偏差基准。",
        "放缆偏快",
        310,
        "time_histories/plough-payout-matched",
    ),
    "plough_payout_fast_1p10_6min": (
        "放缆快10%",
        "放缆速度略高于犁速，观察悬垂段增长。",
        "放缆偏快",
        320,
        "time_histories/plough-payout-fast-1p10",
    ),
    "plough_payout_fast_1p25_6min": (
        "放缆快25%",
        "进一步提高放缆速度，检查入口张力和形态变化。",
        "放缆偏快",
        330,
        "time_histories/plough-payout-fast-1p25",
    ),
    "plough_material_la_6min": (
        "LA 信号缆",
        "同一船端和犁端轨迹下采用 LA 信号缆参数，作为缆型对比基准。",
        "信号缆与电力缆",
        410,
        "time_histories/plough-material-la",
    ),
    "plough_material_ha_6min": (
        "HA 信号缆",
        "只把缆型参数改为 HA 信号缆，观察单位重、直径和阻力系数改变后的张力与形态。",
        "信号缆与电力缆",
        420,
        "time_histories/plough-material-ha",
    ),
    "plough_material_power_500kv_6min": (
        "500 kV 电力缆",
        "只把缆型参数改为 500 kV 电力缆，观察重型电力缆在同一施工输入下的张力与形态。",
        "信号缆与电力缆",
        430,
        "time_histories/plough-material-power-500kv",
    ),
}

def _case_example_metadata(case: OperationCase) -> dict[str, str | int | bool]:
    configured = _CASE_EXAMPLES.get(case.name)
    if configured is not None:
        label, description, order, output_dir = configured
        return {
            "label": label,
            "description": description,
            "example": True,
            "display_order": order,
            "suggested_output_dir": output_dir,
        }
    return {
        "label": _fallback_case_label(case),
        "description": "批量复现用内部工况；默认不放入前端例子列表。",
        "example": False,
        "display_order": 999,
        "suggested_output_dir": f"custom/{_safe_slug(case.name)}",
    }


def _dynamic_example_metadata(case: DynamicCaseInput) -> dict[str, str | int | bool]:
    configured = _DYNAMIC_CASE_EXAMPLES.get(case.case_name)
    if configured is not None:
        label, description, group, order, output_dir = configured
        return {
            "label": label,
            "description": description,
            "group": group,
            "example": True,
            "display_order": order,
            "suggested_output_dir": output_dir,
        }
    direction = {"steady": "匀速", "accel": "加速", "decel": "减速"}.get(case.speed_change, case.speed_change)
    group = "工程铺埋" if case.length_boundary_source == "known_plough_trajectory" else "LA 动态"
    return {
        "label": f"LA｜{direction}时程，流速{case.current_speed_mps:.2f} m/s",
        "description": "批量复现用动态工况；默认不放入前端例子列表。",
        "group": group,
        "example": False,
        "display_order": 999,
        "suggested_output_dir": f"time_histories/{_safe_slug(case.case_name)}",
    }


def _fallback_case_label(case: OperationCase) -> str:
    if case.cable.name == "POWER_500KV":
        return f"500kV 电力缆｜水深 {case.water_depth_m:.0f} m"
    if case.cable.name in {"LA", "HA"}:
        return f"{case.cable.name} 信号缆｜水深 {case.water_depth_m:.0f} m"
    return f"{case.cable.name} 缆｜水深 {case.water_depth_m:.0f} m"


def _cable_display_name(name: str) -> str:
    if name == "POWER_500KV":
        return "500kV 电力缆"
    return name


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-_").lower()
    return slug[:80] or "case"


def run_case_payload(
    result: SolverResult,
    artifacts: dict[str, Path],
    output_root: Path,
    *,
    duration_s: float = 0.0,
) -> dict[str, Any]:
    """Convert solver output and written files into API JSON."""

    return {
        "case_name": result.case_name,
        "summary": {
            "top_tension_initial_n": result.top_tension_initial_n,
            "top_tension_min_n": result.top_tension_min_n,
            "top_tension_final_n": result.top_tension_final_n,
            "suspended_length_m": result.suspended_length_m,
            "layback_m": result.layback_m,
        },
        "artifacts": {
            name: path.resolve().relative_to(output_root.resolve()).as_posix()
            for name, path in artifacts.items()
        },
        "plot_data": {
            "profile": [_profile_point_payload(point) for point in result.profile],
            "time_history": {
                "source": "quasi_static_reference",
                "label": "准静态参考",
                "points": _reference_time_history_payload(result, duration_s),
            },
        },
    }


def run_time_history_payload(
    result: TimeHistoryResult,
    artifacts: dict[str, Path],
    output_root: Path,
) -> dict[str, Any]:
    """Convert a LA dynamic time-history result into API JSON."""

    payload = {
        "case_name": result.case_name,
        "summary": {
            "diameter_m": result.diameter_m,
            "weight_air_n_per_m": result.weight_air_n_per_m,
            "submerged_weight_n_per_m": result.submerged_weight_n_per_m,
            "tangential_drag_coefficient": result.tangential_drag_coefficient,
            "normal_drag_coefficient": result.normal_drag_coefficient,
            "axial_stiffness_n": result.axial_stiffness_n,
            "current_speed_mps": result.current_speed_mps,
            "current_direction_deg": result.current_direction_deg,
            "speed_change": result.speed_change,
            "initial_speed_mps": result.initial_speed_mps,
            "final_speed_mps": result.final_speed_mps,
            "payout_initial_speed_mps": result.payout_initial_speed_mps,
            "payout_final_speed_mps": result.payout_final_speed_mps,
            "length_boundary_source": result.length_boundary_source,
            "duration_s": result.duration_s,
            "total_duration_s": result.total_duration_s,
            "water_depth_m": result.water_depth_m,
            "element_count": result.element_count,
            "touchdown_tension_n": result.touchdown_tension_n,
            "evidence_level": result.evidence_level,
            "initial_tension_n": result.initial_tension_n,
            "extreme_tension_n": result.extreme_tension_n,
            "steady_tension_n": result.steady_tension_n,
            "integration_time_step_max_s": result.integration_time_step_max_s,
            "integration_time_step_min_s": result.integration_time_step_min_s,
            "spatial_step_mean_m": result.spatial_step_mean_m,
            "spatial_step_min_m": result.spatial_step_min_m,
            "xpbd_iterations_per_step": result.xpbd_iterations_per_step,
            "xpbd_iterations_per_step_min": result.xpbd_iterations_per_step_min,
            "xpbd_iterations_per_step_max": result.xpbd_iterations_per_step_max,
            "xpbd_iteration_limit_per_solve": result.xpbd_iteration_limit_per_solve,
            "axial_constraint_residual_max_m": result.axial_constraint_residual_max_m,
            "initial_suspended_length_m": result.initial_suspended_length_m,
            "geometric_length_deficit_max_m": result.geometric_length_deficit_max_m,
            "geometric_length_deficit_final_m": result.geometric_length_deficit_final_m,
            "vessel_motion_segments": [_motion_segment_payload(segment) for segment in result.vessel_motion_segments],
            "plough_motion_segments": [_motion_segment_payload(segment) for segment in result.plough_motion_segments],
            "vessel_motion_samples": [_motion_sample_payload(sample) for sample in result.vessel_motion_samples],
            "plough_motion_samples": [_motion_sample_payload(sample) for sample in result.plough_motion_samples],
            "payout_speed_segments": [_speed_segment_payload(segment) for segment in result.payout_speed_segments],
        },
        "artifacts": {
            name: path.resolve().relative_to(output_root.resolve()).as_posix()
            for name, path in artifacts.items()
        },
        "plot_data": {
            "time_history": {
                "source": "la_dynamic_xpbd_node_state",
                "label": "动态张力时程",
                "points": [_time_history_point_payload(point) for point in result.history],
            },
            "frames": {
                "source": "la_dynamic_xpbd_frames",
                "label": "动态三维帧",
                "items": [_time_history_frame_payload(frame) for frame in result.frames],
            },
        },
    }
    if result.length_boundary_source == "known_plough_trajectory":
        payload["summary"].update(
            {
                "plough_speed_mps": result.plough_speed_mps,
                "plough_exit_speed_mps": result.plough_exit_speed_mps,
                "plough_exit_speed_source": result.plough_exit_speed_source,
                "plough_inlet_tension_final_n": result.plough_inlet_tension_final_n,
                "plough_boundary_tension_final_n": result.plough_boundary_tension_final_n,
                "plough_adjacent_segment_tension_final_n": result.plough_adjacent_segment_tension_final_n,
                "plough_tension_status": result.plough_tension_status,
                "minimum_bend_radius_min_m": result.minimum_bend_radius_min_m,
                "minimum_bend_radius_limit_m": result.minimum_bend_radius_limit_m,
                "minimum_bend_radius_margin_m": result.minimum_bend_radius_margin_m,
                "minimum_bend_radius_status": result.minimum_bend_radius_status,
                "minimum_bend_radius_time_s": result.minimum_bend_radius_time_s,
                "minimum_bend_radius_node_index": result.minimum_bend_radius_node_index,
                "minimum_bend_radius_left_segment_m": result.minimum_bend_radius_left_segment_m,
                "minimum_bend_radius_right_segment_m": result.minimum_bend_radius_right_segment_m,
                "minimum_bend_radius_turn_angle_deg": result.minimum_bend_radius_turn_angle_deg,
                "minimum_bend_radius_node_depth_m": result.minimum_bend_radius_node_depth_m,
                "minimum_bend_radius_near_seabed": result.minimum_bend_radius_near_seabed,
                "minimum_bend_radius_excluded_tail_nodes": result.minimum_bend_radius_excluded_tail_nodes,
                "minimum_bend_radius_raw_m": result.minimum_bend_radius_raw_m,
                "minimum_bend_radius_raw_time_s": result.minimum_bend_radius_raw_time_s,
                "minimum_bend_radius_raw_node_index": result.minimum_bend_radius_raw_node_index,
                "minimum_bend_radius_raw_left_segment_m": result.minimum_bend_radius_raw_left_segment_m,
                "minimum_bend_radius_raw_right_segment_m": result.minimum_bend_radius_raw_right_segment_m,
                "minimum_bend_radius_raw_turn_angle_deg": result.minimum_bend_radius_raw_turn_angle_deg,
                "minimum_bend_radius_raw_node_depth_m": result.minimum_bend_radius_raw_node_depth_m,
                "minimum_bend_radius_raw_near_seabed": result.minimum_bend_radius_raw_near_seabed,
            }
        )
    return payload


def _motion_segment_payload(segment: Any) -> dict[str, float]:
    payload = {
        "duration_s": segment.duration_s,
        "start_speed_mps": segment.start_speed_mps,
        "end_speed_mps": segment.end_speed_mps,
        "heading_deg": segment.heading_deg,
    }
    for field in (
        "start_velocity_x_mps",
        "start_velocity_y_mps",
        "end_velocity_x_mps",
        "end_velocity_y_mps",
    ):
        value = getattr(segment, field, None)
        if value is not None:
            payload[field] = value
    return payload


def _motion_sample_payload(sample: Any) -> dict[str, float]:
    payload = {
        "time_s": sample.time_s,
        "x_m": sample.x_m,
        "y_m": sample.y_m,
    }
    for field in ("z_m", "velocity_x_mps", "velocity_y_mps", "velocity_z_mps"):
        value = getattr(sample, field, None)
        if value is not None:
            payload[field] = value
    return payload


def _speed_segment_payload(segment: Any) -> dict[str, float]:
    return {
        "duration_s": segment.duration_s,
        "start_speed_mps": segment.start_speed_mps,
        "end_speed_mps": segment.end_speed_mps,
    }


def _case_group(case: OperationCase) -> str:
    if case.solver_model == "power_500kv":
        return "500kV"
    if case.cable.name in {"LA", "HA"}:
        return case.cable.name
    return "Other"


def _profile_point_payload(point: Any) -> dict[str, float | int]:
    return {
        "index": point.index,
        "arc_m": point.arc_m,
        "x_m": point.x_m,
        "y_m": point.y_m,
        "z_m": point.z_m,
        "theta_rad": point.theta_rad,
        "psi_rad": point.psi_rad,
        "tangent_x": point.tangent_x,
        "tangent_y": point.tangent_y,
        "tangent_z": point.tangent_z,
        "current_x_mps": point.current_x_mps,
        "current_y_mps": point.current_y_mps,
        "current_z_mps": point.current_z_mps,
        "drag_x_n_per_m": point.drag_x_n_per_m,
        "drag_y_n_per_m": point.drag_y_n_per_m,
        "drag_z_n_per_m": point.drag_z_n_per_m,
        "tension_n": point.tension_n,
    }


def _time_history_point_payload(point: Any) -> dict[str, float | int]:
    payload: dict[str, float | int] = {
        "time_s": float(point.time_s),
        "top_tension_n": float(point.top_tension_n),
        "tdp_x_m": float(point.tdp_x_m),
        "tdp_y_m": float(point.tdp_y_m),
        "suspended_length_m": float(point.suspended_length_m),
        "iterations": int(point.iterations),
    }
    for name in (
        "plough_x_m",
        "plough_y_m",
        "plough_z_m",
        "plough_inlet_tension_n",
        "plough_boundary_tension_n",
        "plough_adjacent_segment_tension_n",
        "plough_entry_angle_deg",
        "minimum_bend_radius_m",
        "minimum_bend_radius_left_segment_m",
        "minimum_bend_radius_right_segment_m",
        "minimum_bend_radius_turn_angle_deg",
        "minimum_bend_radius_node_depth_m",
        "minimum_bend_radius_raw_m",
        "minimum_bend_radius_raw_left_segment_m",
        "minimum_bend_radius_raw_right_segment_m",
        "minimum_bend_radius_raw_turn_angle_deg",
        "minimum_bend_radius_raw_node_depth_m",
        "material_suspended_length_m",
        "geometric_length_deficit_m",
        "tdp_arc_length_m",
        "free_span_material_length_m",
        "seabed_contact_length_m",
        "seabed_normal_reaction_n",
    ):
        value = getattr(point, name, None)
        if value is not None:
            payload[name] = float(value)
    node_index = getattr(point, "minimum_bend_radius_node_index", None)
    if node_index is not None:
        payload["minimum_bend_radius_node_index"] = int(node_index)
    raw_node_index = getattr(point, "minimum_bend_radius_raw_node_index", None)
    if raw_node_index is not None:
        payload["minimum_bend_radius_raw_node_index"] = int(raw_node_index)
    excluded_tail_nodes = getattr(point, "minimum_bend_radius_excluded_tail_nodes", None)
    if excluded_tail_nodes is not None:
        payload["minimum_bend_radius_excluded_tail_nodes"] = int(excluded_tail_nodes)
    near_seabed = getattr(point, "minimum_bend_radius_near_seabed", None)
    if near_seabed is not None:
        payload["minimum_bend_radius_near_seabed"] = bool(near_seabed)
    raw_near_seabed = getattr(point, "minimum_bend_radius_raw_near_seabed", None)
    if raw_near_seabed is not None:
        payload["minimum_bend_radius_raw_near_seabed"] = bool(raw_near_seabed)
    return payload


def _time_history_frame_payload(frame: Any) -> dict[str, Any]:
    payload = {
        "time_s": float(frame.time_s),
        "points": [_time_history_frame_point_payload(point) for point in frame.points],
    }
    segment_tensions = getattr(frame, "segment_tensions_n", ())
    if segment_tensions:
        payload["segment_tensions_n"] = [float(tension) for tension in segment_tensions]
    for name in (
        "boundary",
        "vessel_x_m",
        "vessel_y_m",
        "vessel_z_m",
        "plough_x_m",
        "plough_y_m",
        "plough_z_m",
        "minimum_bend_radius_m",
        "minimum_bend_radius_left_segment_m",
        "minimum_bend_radius_right_segment_m",
        "minimum_bend_radius_turn_angle_deg",
        "minimum_bend_radius_node_depth_m",
        "minimum_bend_radius_raw_m",
        "minimum_bend_radius_raw_left_segment_m",
        "minimum_bend_radius_raw_right_segment_m",
        "minimum_bend_radius_raw_turn_angle_deg",
        "minimum_bend_radius_raw_node_depth_m",
    ):
        value = getattr(frame, name, None)
        if value is None:
            continue
        payload[name] = value if isinstance(value, str) else float(value)
    node_index = getattr(frame, "minimum_bend_radius_node_index", None)
    if node_index is not None:
        payload["minimum_bend_radius_node_index"] = int(node_index)
    raw_node_index = getattr(frame, "minimum_bend_radius_raw_node_index", None)
    if raw_node_index is not None:
        payload["minimum_bend_radius_raw_node_index"] = int(raw_node_index)
    excluded_tail_nodes = getattr(frame, "minimum_bend_radius_excluded_tail_nodes", None)
    if excluded_tail_nodes is not None:
        payload["minimum_bend_radius_excluded_tail_nodes"] = int(excluded_tail_nodes)
    near_seabed = getattr(frame, "minimum_bend_radius_near_seabed", None)
    if near_seabed is not None:
        payload["minimum_bend_radius_near_seabed"] = bool(near_seabed)
    raw_near_seabed = getattr(frame, "minimum_bend_radius_raw_near_seabed", None)
    if raw_near_seabed is not None:
        payload["minimum_bend_radius_raw_near_seabed"] = bool(raw_near_seabed)
    return payload


def _time_history_frame_point_payload(point: Any) -> dict[str, float | int]:
    return {
        "index": int(point.index),
        "x_m": float(point.x_m),
        "y_m": float(point.y_m),
        "z_m": float(point.z_m),
        "tension_n": float(point.tension_n),
    }


def realtime_frame_payload(result: Any) -> dict[str, Any]:
    """Serialize one latest realtime frame without batch artifacts."""

    point = result.point
    return {
        "session_id": result.session_id,
        "sequence": int(result.sequence),
        "time_s": float(result.time_s),
        "compute_wall_s": float(result.compute_wall_s),
        "realtime_factor": (
            None if result.realtime_factor is None else float(result.realtime_factor)
        ),
        "input_age_s": float(result.input_age_s),
        "input_status": result.input_status,
        "tensions": {
            "top_tension_n": float(point.top_tension_n),
            "plough_inlet_tension_n": float(point.plough_inlet_tension_n),
            "plough_boundary_tension_n": float(point.plough_boundary_tension_n),
        },
        "contact": {
            "tdp_x_m": float(point.tdp_x_m),
            "tdp_y_m": float(point.tdp_y_m),
            "tdp_arc_length_m": float(point.tdp_arc_length_m),
            "free_span_material_length_m": float(point.free_span_material_length_m),
            "seabed_contact_length_m": float(point.seabed_contact_length_m),
            "seabed_normal_reaction_n": float(point.seabed_normal_reaction_n),
        },
        "integration": {
            "time_step_min_s": result.integration_time_step_min_s,
            "time_step_max_s": result.integration_time_step_max_s,
            "axial_constraint_residual_max_m": result.axial_constraint_residual_max_m,
        },
        "frame": _time_history_frame_payload(result.frame),
    }


def _reference_time_history_payload(result: SolverResult, duration_s: float) -> list[dict[str, float]]:
    """Build a small top-tension reference history for steady solver results."""

    t_end = float(duration_s) if duration_s > 0.0 else 1.0
    t_mid = 0.5 * t_end
    tdp = result.profile[-1]
    candidates = [
        (0.0, result.top_tension_initial_n),
        (t_mid, result.top_tension_min_n),
        (t_end, result.top_tension_final_n),
    ]
    points: list[dict[str, float]] = []
    for time_s, tension_n in candidates:
        if points and abs(points[-1]["time_s"] - time_s) < 1.0e-12:
            points[-1]["top_tension_n"] = float(tension_n)
            continue
        points.append(
            {
                "time_s": float(time_s),
                "top_tension_n": float(tension_n),
                "tdp_x_m": float(tdp.x_m),
                "tdp_y_m": float(tdp.y_m),
            }
        )
    return points

"""求解结果输出工具。

算法说明：
本文件不参与张力计算，只把 `solver.py` 和 `dynamic.py` 的结果写成稳定文件名。
单工况目录固定包含 `summary.csv`、`profile.csv`、`profile.svg`；
动态工况目录固定包含 `time_summary.csv`、`time_history.csv`、`time_history.svg`。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .dynamic import TimeHistoryResult
from .solver import SolverResult


@dataclass(frozen=True)
class OutputFiles:
    """稳态/剖面工况写出的文件路径。"""

    summary_csv: Path
    profile_csv: Path
    profile_svg: Path


@dataclass(frozen=True)
class TimeHistoryOutputFiles:
    """动态时程工况写出的文件路径。"""

    summary_csv: Path
    history_csv: Path
    history_svg: Path


def write_result(result: SolverResult, output_dir: Path | str) -> OutputFiles:
    """写出单工况标量结果、剖面明细和剖面图。"""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = out_dir / "summary.csv"
    profile_csv = out_dir / "profile.csv"
    profile_svg = out_dir / "profile.svg"

    _write_summary(result, summary_csv)
    _write_profile(result, profile_csv)
    _write_svg(result, profile_svg)

    return OutputFiles(
        summary_csv=summary_csv,
        profile_csv=profile_csv,
        profile_svg=profile_svg,
    )


def write_time_history(
    result: TimeHistoryResult,
    output_dir: Path | str,
) -> TimeHistoryOutputFiles:
    """写出动态工况标量结果、时程明细和时程图。"""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = out_dir / "time_summary.csv"
    history_csv = out_dir / "time_history.csv"
    history_svg = out_dir / "time_history.svg"

    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_name",
                "diameter_m",
                "weight_air_n_per_m",
                "submerged_weight_n_per_m",
                "tangential_drag_coefficient",
                "normal_drag_coefficient",
                "axial_stiffness_n",
                "current_speed_mps",
                "current_direction_deg",
                "speed_change",
                "initial_speed_mps",
                "final_speed_mps",
                "payout_initial_speed_mps",
                "payout_final_speed_mps",
                "length_boundary_source",
                "initial_suspended_length_m",
                "duration_s",
                "total_duration_s",
                "water_depth_m",
                "element_count",
                "touchdown_tension_n",
                "initial_tension_n",
                "extreme_tension_n",
                "steady_tension_n",
                "plough_speed_mps",
                "plough_exit_speed_mps",
                "plough_exit_speed_source",
                "plough_inlet_tension_final_n",
                "plough_boundary_tension_final_n",
                "plough_adjacent_segment_tension_final_n",
                "plough_tension_status",
                "minimum_bend_radius_min_m",
                "minimum_bend_radius_limit_m",
                "minimum_bend_radius_margin_m",
                "minimum_bend_radius_status",
                "minimum_bend_radius_time_s",
                "minimum_bend_radius_node_index",
                "minimum_bend_radius_left_segment_m",
                "minimum_bend_radius_right_segment_m",
                "minimum_bend_radius_turn_angle_deg",
                "minimum_bend_radius_node_depth_m",
                "minimum_bend_radius_near_seabed",
                "minimum_bend_radius_excluded_tail_nodes",
                "minimum_bend_radius_raw_m",
                "minimum_bend_radius_raw_time_s",
                "minimum_bend_radius_raw_node_index",
                "minimum_bend_radius_raw_left_segment_m",
                "minimum_bend_radius_raw_right_segment_m",
                "minimum_bend_radius_raw_turn_angle_deg",
                "minimum_bend_radius_raw_node_depth_m",
                "minimum_bend_radius_raw_near_seabed",
                "integration_time_step_max_s",
                "integration_time_step_min_s",
                "spatial_step_mean_m",
                "spatial_step_min_m",
                "xpbd_iterations_per_step",
                "xpbd_iterations_per_step_min",
                "xpbd_iterations_per_step_max",
                "xpbd_iteration_limit_per_solve",
                "axial_constraint_residual_max_m",
                "geometric_length_deficit_max_m",
                "geometric_length_deficit_final_m",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_name": result.case_name,
                "diameter_m": f"{result.diameter_m:.6f}",
                "weight_air_n_per_m": f"{result.weight_air_n_per_m:.6f}",
                "submerged_weight_n_per_m": f"{result.submerged_weight_n_per_m:.6f}",
                "tangential_drag_coefficient": f"{result.tangential_drag_coefficient:.6f}",
                "normal_drag_coefficient": f"{result.normal_drag_coefficient:.6f}",
                "axial_stiffness_n": f"{result.axial_stiffness_n:.6f}",
                "current_speed_mps": f"{result.current_speed_mps:.6f}",
                "current_direction_deg": f"{result.current_direction_deg:.6f}",
                "speed_change": result.speed_change,
                "initial_speed_mps": f"{result.initial_speed_mps:.6f}",
                "final_speed_mps": f"{result.final_speed_mps:.6f}",
                "payout_initial_speed_mps": f"{result.payout_initial_speed_mps:.6f}",
                "payout_final_speed_mps": f"{result.payout_final_speed_mps:.6f}",
                "length_boundary_source": result.length_boundary_source,
                "initial_suspended_length_m": _optional_float(result.initial_suspended_length_m),
                "duration_s": f"{result.duration_s:.6f}",
                "total_duration_s": f"{result.total_duration_s:.6f}",
                "water_depth_m": f"{result.water_depth_m:.6f}",
                "element_count": result.element_count,
                "touchdown_tension_n": f"{result.touchdown_tension_n:.6f}",
                "initial_tension_n": f"{result.initial_tension_n:.6f}",
                "extreme_tension_n": f"{result.extreme_tension_n:.6f}",
                "steady_tension_n": f"{result.steady_tension_n:.6f}",
                "plough_speed_mps": _optional_float(result.plough_speed_mps),
                "plough_exit_speed_mps": _optional_float(result.plough_exit_speed_mps),
                "plough_exit_speed_source": result.plough_exit_speed_source,
                "plough_inlet_tension_final_n": _optional_float(result.plough_inlet_tension_final_n),
                "plough_boundary_tension_final_n": _optional_float(result.plough_boundary_tension_final_n),
                "plough_adjacent_segment_tension_final_n": _optional_float(result.plough_adjacent_segment_tension_final_n),
                "plough_tension_status": result.plough_tension_status,
                "minimum_bend_radius_min_m": _optional_float(result.minimum_bend_radius_min_m),
                "minimum_bend_radius_limit_m": _optional_float(result.minimum_bend_radius_limit_m),
                "minimum_bend_radius_margin_m": _optional_float(result.minimum_bend_radius_margin_m),
                "minimum_bend_radius_status": result.minimum_bend_radius_status,
                "minimum_bend_radius_time_s": _optional_float(result.minimum_bend_radius_time_s),
                "minimum_bend_radius_node_index": _optional_int(result.minimum_bend_radius_node_index),
                "minimum_bend_radius_left_segment_m": _optional_float(result.minimum_bend_radius_left_segment_m),
                "minimum_bend_radius_right_segment_m": _optional_float(result.minimum_bend_radius_right_segment_m),
                "minimum_bend_radius_turn_angle_deg": _optional_float(result.minimum_bend_radius_turn_angle_deg),
                "minimum_bend_radius_node_depth_m": _optional_float(result.minimum_bend_radius_node_depth_m),
                "minimum_bend_radius_near_seabed": _optional_bool(result.minimum_bend_radius_near_seabed),
                "minimum_bend_radius_excluded_tail_nodes": _optional_int(result.minimum_bend_radius_excluded_tail_nodes),
                "minimum_bend_radius_raw_m": _optional_float(result.minimum_bend_radius_raw_m),
                "minimum_bend_radius_raw_time_s": _optional_float(result.minimum_bend_radius_raw_time_s),
                "minimum_bend_radius_raw_node_index": _optional_int(result.minimum_bend_radius_raw_node_index),
                "minimum_bend_radius_raw_left_segment_m": _optional_float(result.minimum_bend_radius_raw_left_segment_m),
                "minimum_bend_radius_raw_right_segment_m": _optional_float(result.minimum_bend_radius_raw_right_segment_m),
                "minimum_bend_radius_raw_turn_angle_deg": _optional_float(result.minimum_bend_radius_raw_turn_angle_deg),
                "minimum_bend_radius_raw_node_depth_m": _optional_float(result.minimum_bend_radius_raw_node_depth_m),
                "minimum_bend_radius_raw_near_seabed": _optional_bool(result.minimum_bend_radius_raw_near_seabed),
                "integration_time_step_max_s": _optional_float(result.integration_time_step_max_s),
                "integration_time_step_min_s": _optional_float(result.integration_time_step_min_s),
                "spatial_step_mean_m": _optional_float(result.spatial_step_mean_m),
                "spatial_step_min_m": _optional_float(result.spatial_step_min_m),
                "xpbd_iterations_per_step": "" if result.xpbd_iterations_per_step is None else result.xpbd_iterations_per_step,
                "xpbd_iterations_per_step_min": "" if result.xpbd_iterations_per_step_min is None else result.xpbd_iterations_per_step_min,
                "xpbd_iterations_per_step_max": "" if result.xpbd_iterations_per_step_max is None else result.xpbd_iterations_per_step_max,
                "xpbd_iteration_limit_per_solve": "" if result.xpbd_iteration_limit_per_solve is None else result.xpbd_iteration_limit_per_solve,
                "axial_constraint_residual_max_m": _optional_float(result.axial_constraint_residual_max_m),
                "geometric_length_deficit_max_m": _optional_float(result.geometric_length_deficit_max_m),
                "geometric_length_deficit_final_m": _optional_float(result.geometric_length_deficit_final_m),
            }
        )

    with history_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "time_s",
                "top_tension_n",
                "tdp_x_m",
                "tdp_y_m",
                "suspended_length_m",
                "iterations",
                "plough_x_m",
                "plough_y_m",
                "plough_z_m",
                "plough_inlet_tension_n",
                "plough_boundary_tension_n",
                "plough_adjacent_segment_tension_n",
                "plough_entry_angle_deg",
                "minimum_bend_radius_m",
                "minimum_bend_radius_node_index",
                "minimum_bend_radius_left_segment_m",
                "minimum_bend_radius_right_segment_m",
                "minimum_bend_radius_turn_angle_deg",
                "minimum_bend_radius_node_depth_m",
                "minimum_bend_radius_near_seabed",
                "minimum_bend_radius_excluded_tail_nodes",
                "minimum_bend_radius_raw_m",
                "minimum_bend_radius_raw_node_index",
                "minimum_bend_radius_raw_left_segment_m",
                "minimum_bend_radius_raw_right_segment_m",
                "minimum_bend_radius_raw_turn_angle_deg",
                "minimum_bend_radius_raw_node_depth_m",
                "minimum_bend_radius_raw_near_seabed",
                "material_suspended_length_m",
                "geometric_length_deficit_m",
                "tdp_arc_length_m",
                "free_span_material_length_m",
                "seabed_contact_length_m",
                "seabed_normal_reaction_n",
            ],
        )
        writer.writeheader()
        for point in result.history:
            writer.writerow(
                {
                    "time_s": f"{point.time_s:.6f}",
                    "top_tension_n": f"{point.top_tension_n:.6f}",
                    "tdp_x_m": f"{point.tdp_x_m:.6f}",
                    "tdp_y_m": f"{point.tdp_y_m:.6f}",
                    "suspended_length_m": f"{point.suspended_length_m:.6f}",
                    "iterations": point.iterations,
                    "plough_x_m": _optional_float(point.plough_x_m),
                    "plough_y_m": _optional_float(point.plough_y_m),
                    "plough_z_m": _optional_float(point.plough_z_m),
                    "plough_inlet_tension_n": _optional_float(point.plough_inlet_tension_n),
                    "plough_boundary_tension_n": _optional_float(point.plough_boundary_tension_n),
                    "plough_adjacent_segment_tension_n": _optional_float(point.plough_adjacent_segment_tension_n),
                    "plough_entry_angle_deg": _optional_float(point.plough_entry_angle_deg),
                    "minimum_bend_radius_m": _optional_float(point.minimum_bend_radius_m),
                    "minimum_bend_radius_node_index": _optional_int(point.minimum_bend_radius_node_index),
                    "minimum_bend_radius_left_segment_m": _optional_float(point.minimum_bend_radius_left_segment_m),
                    "minimum_bend_radius_right_segment_m": _optional_float(point.minimum_bend_radius_right_segment_m),
                    "minimum_bend_radius_turn_angle_deg": _optional_float(point.minimum_bend_radius_turn_angle_deg),
                    "minimum_bend_radius_node_depth_m": _optional_float(point.minimum_bend_radius_node_depth_m),
                    "minimum_bend_radius_near_seabed": _optional_bool(point.minimum_bend_radius_near_seabed),
                    "minimum_bend_radius_excluded_tail_nodes": _optional_int(point.minimum_bend_radius_excluded_tail_nodes),
                    "minimum_bend_radius_raw_m": _optional_float(point.minimum_bend_radius_raw_m),
                    "minimum_bend_radius_raw_node_index": _optional_int(point.minimum_bend_radius_raw_node_index),
                    "minimum_bend_radius_raw_left_segment_m": _optional_float(point.minimum_bend_radius_raw_left_segment_m),
                    "minimum_bend_radius_raw_right_segment_m": _optional_float(point.minimum_bend_radius_raw_right_segment_m),
                    "minimum_bend_radius_raw_turn_angle_deg": _optional_float(point.minimum_bend_radius_raw_turn_angle_deg),
                    "minimum_bend_radius_raw_node_depth_m": _optional_float(point.minimum_bend_radius_raw_node_depth_m),
                    "minimum_bend_radius_raw_near_seabed": _optional_bool(point.minimum_bend_radius_raw_near_seabed),
                    "material_suspended_length_m": _optional_float(point.material_suspended_length_m),
                    "geometric_length_deficit_m": _optional_float(point.geometric_length_deficit_m),
                    "tdp_arc_length_m": _optional_float(point.tdp_arc_length_m),
                    "free_span_material_length_m": _optional_float(point.free_span_material_length_m),
                    "seabed_contact_length_m": _optional_float(point.seabed_contact_length_m),
                    "seabed_normal_reaction_n": _optional_float(point.seabed_normal_reaction_n),
                }
            )

    _write_time_svg(result, history_svg)
    return TimeHistoryOutputFiles(
        summary_csv=summary_csv,
        history_csv=history_csv,
        history_svg=history_svg,
    )


def _optional_float(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def _optional_int(value: int | None) -> str:
    return "" if value is None else str(value)


def _optional_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _write_summary(result: SolverResult, path: Path) -> None:
    """写出一行标量结果 CSV。"""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_name",
                "top_tension_initial_n",
                "top_tension_min_n",
                "top_tension_final_n",
                "suspended_length_m",
                "layback_m",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_name": result.case_name,
                "top_tension_initial_n": f"{result.top_tension_initial_n:.6f}",
                "top_tension_min_n": f"{result.top_tension_min_n:.6f}",
                "top_tension_final_n": f"{result.top_tension_final_n:.6f}",
                "suspended_length_m": f"{result.suspended_length_m:.6f}",
                "layback_m": f"{result.layback_m:.6f}",
            }
        )


def _write_profile(result: SolverResult, path: Path) -> None:
    """写出每个离散点的坐标、角度和张力。"""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "index",
                "arc_m",
                "x_m",
                "y_m",
                "z_m",
                "theta_rad",
                "psi_rad",
                "tangent_x",
                "tangent_y",
                "tangent_z",
                "current_x_mps",
                "current_y_mps",
                "current_z_mps",
                "drag_x_n_per_m",
                "drag_y_n_per_m",
                "drag_z_n_per_m",
                "tension_n",
            ],
        )
        writer.writeheader()
        for point in result.profile:
            writer.writerow(
                {
                    "index": point.index,
                    "arc_m": f"{point.arc_m:.6f}",
                    "x_m": f"{point.x_m:.6f}",
                    "y_m": f"{point.y_m:.6f}",
                    "z_m": f"{point.z_m:.6f}",
                    "theta_rad": f"{point.theta_rad:.9f}",
                    "psi_rad": f"{point.psi_rad:.9f}",
                    "tangent_x": f"{point.tangent_x:.9f}",
                    "tangent_y": f"{point.tangent_y:.9f}",
                    "tangent_z": f"{point.tangent_z:.9f}",
                    "current_x_mps": f"{point.current_x_mps:.6f}",
                    "current_y_mps": f"{point.current_y_mps:.6f}",
                    "current_z_mps": f"{point.current_z_mps:.6f}",
                    "drag_x_n_per_m": f"{point.drag_x_n_per_m:.6f}",
                    "drag_y_n_per_m": f"{point.drag_y_n_per_m:.6f}",
                    "drag_z_n_per_m": f"{point.drag_z_n_per_m:.6f}",
                    "tension_n": f"{point.tension_n:.6f}",
                }
            )


def _write_svg(result: SolverResult, path: Path) -> None:
    """写出便于快速查看的剖面 SVG。"""

    width = 720
    height = 480
    margin = 48
    min_x = min(point.x_m for point in result.profile)
    max_x = max(point.x_m for point in result.profile)
    x_span = max(max_x - min_x, 1.0)
    max_z = max(point.z_m for point in result.profile) or 1.0
    plot_w = width - margin * 2
    plot_h = height - margin * 2

    points = []
    for point in result.profile:
        x = margin + (point.x_m - min_x) / x_span * plot_w
        y = margin + point.z_m / max_z * plot_h
        points.append(f"{x:.2f},{y:.2f}")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" stroke="#333" stroke-width="1"/>
  <line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#333" stroke-width="1"/>
  <text x="{margin}" y="24" font-family="Arial, sans-serif" font-size="16">{result.case_name} profile</text>
  <text x="{width - margin - 145}" y="{height - 16}" font-family="Arial, sans-serif" font-size="12">signed x projection (m)</text>
  <text x="8" y="{margin + 12}" font-family="Arial, sans-serif" font-size="12">depth z (m)</text>
  <polyline points="{" ".join(points)}" fill="none" stroke="#1167b1" stroke-width="3"/>
  <circle cx="{points[0].split(',')[0]}" cy="{points[0].split(',')[1]}" r="4" fill="#555"/>
  <circle cx="{points[-1].split(',')[0]}" cy="{points[-1].split(',')[1]}" r="4" fill="#d33"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def _write_time_svg(result: TimeHistoryResult, path: Path) -> None:
    """写出便于快速查看的张力时程 SVG。"""

    width = 720
    height = 420
    margin = 48
    max_time = max(point.time_s for point in result.history) or 1.0
    tensions = [point.top_tension_n for point in result.history]
    min_tension = min(tensions)
    max_tension = max(tensions)
    span = max(max_tension - min_tension, 1.0)
    plot_w = width - margin * 2
    plot_h = height - margin * 2
    points = []
    for point in result.history:
        x = margin + point.time_s / max_time * plot_w
        y = height - margin - (point.top_tension_n - min_tension) / span * plot_h
        points.append(f"{x:.2f},{y:.2f}")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" stroke="#333" stroke-width="1"/>
  <line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#333" stroke-width="1"/>
  <text x="{margin}" y="24" font-family="Arial, sans-serif" font-size="16">{result.case_name}</text>
  <text x="{width - margin - 100}" y="{height - 16}" font-family="Arial, sans-serif" font-size="12">time (s)</text>
  <text x="8" y="{margin + 12}" font-family="Arial, sans-serif" font-size="12">T (N)</text>
  <polyline points="{" ".join(points)}" fill="none" stroke="#b51d1a" stroke-width="3"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")

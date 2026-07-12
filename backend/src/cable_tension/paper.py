"""批量运行工况并生成表格、曲线和明细输出。

算法说明：
本文件不改变求解算法，只做编排：

1. 读取 `cases.py` 中定义的命名工况。
2. 调用 `solver.py` 生成稳态/准静态剖面。
3. 调用 `dynamic.py` 生成 LA 多单元角运动张力时程。
4. 把输入表、结果表、单工况 CSV 和 SVG 图统一写到输出目录。

核查算法本身时应主要看 `solver.py`、`dynamic.py`、`hydrodynamics.py`
和 `contact.py`；本文件用于检查“同一批输入如何批量转成输出文件”。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .cases import get_case, list_cases
from .dynamic import (
    DynamicCaseInput,
    TimeHistoryResult,
    get_time_history_case,
    solve_time_history,
)
from .io import write_result, write_time_history
from .parameters import OperationCase
from .solver import SolverResult, solve_case


@dataclass(frozen=True)
class PaperReproductionResult:
    """批量输出完成后的简要返回值。"""

    output_dir: Path
    case_count: int


_TABLE_4_3_CASES = [
    "power_current_speed_0p50",
    "power_current_speed_1p00",
    "power_current_speed_1p50",
    "power_current_speed_2p00",
]

_TABLE_4_4_CASES = [
    "power_current_direction_90",
    "power_current_direction_60",
    "power_current_direction_30",
    "power_current_direction_0",
]

_TABLE_4_5_CASES = [
    "power_pretension_2000",
    "power_pretension_3000",
    "power_pretension_4000",
    "power_pretension_5000",
]

_PAPER_TIME_HISTORY_CASES = [
    "la_dynamic_accel_current_1p00",
    "la_dynamic_accel_current_1p50",
    "la_dynamic_decel_current_1p00",
    "la_dynamic_decel_current_1p50",
]


def reproduce_paper(output_dir: Path | str, *, points: int = 201) -> PaperReproductionResult:
    """生成全部预设工况的输入表、结果表、曲线和明细输出。"""

    out_dir = Path(output_dir)
    inputs_dir = out_dir / "inputs"
    tables_dir = out_dir / "tables"
    figures_dir = out_dir / "figures"
    cases_dir = out_dir / "cases"
    dynamics_dir = out_dir / "time_histories"
    for directory in (inputs_dir, tables_dir, figures_dir, cases_dir, dynamics_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # 单一批量入口：脚本、手工运行和交付包中的使用方式都写出同一套目录结构。
    all_case_names = [name for name in list_cases() if _is_reproduction_case(name)]
    results: dict[str, SolverResult] = {}
    for name in all_case_names:
        # 稳态/准静态工况：求解后立即写入单工况目录，便于逐个核查。
        case = get_case(name)
        result = solve_case(case, points=points)
        results[name] = result
        write_result(result, cases_dir / name)
    time_results: dict[str, TimeHistoryResult] = {}
    for name in _PAPER_TIME_HISTORY_CASES:
        # 动态工况：输出时程 CSV 和 SVG，表格只汇总初值、极值和稳态值。
        result = solve_time_history(name, points=points)
        time_results[name] = result
        write_time_history(result, dynamics_dir / name)

    _write_cases_csv([get_case(name) for name in all_case_names], inputs_dir / "cases.csv")
    _write_dynamic_inputs_csv(
        [get_time_history_case(name) for name in _PAPER_TIME_HISTORY_CASES],
        inputs_dir / "time_history_cases.csv",
    )
    _write_table_4_1(time_results, tables_dir / "table_4_1_dynamic_la.csv")
    _write_table(results, _TABLE_4_3_CASES, tables_dir / "table_4_3_current_speed.csv", "current_surface_mps")
    _write_table(results, _TABLE_4_4_CASES, tables_dir / "table_4_4_current_direction.csv", "current_direction_deg")
    _write_table(results, _TABLE_4_5_CASES, tables_dir / "table_4_5_pretension.csv", "touchdown_tension_n")
    _write_overlay_svg(
        [results[name] for name in _TABLE_4_3_CASES],
        figures_dir / "fig_4_11_current_speed.svg",
        title="Fig. 4-11 current speed comparison",
        projection="x",
    )
    _write_overlay_svg(
        [results[name] for name in _TABLE_4_4_CASES],
        figures_dir / "fig_4_12_current_direction.svg",
        title="Fig. 4-12 current direction comparison",
        projection="xy",
    )
    _write_overlay_svg(
        [results[name] for name in _TABLE_4_5_CASES],
        figures_dir / "fig_4_13_pretension.svg",
        title="Fig. 4-13 pretension comparison",
        projection="y",
    )
    _write_time_overlay_svg(
        [time_results["la_dynamic_accel_current_1p00"], time_results["la_dynamic_accel_current_1p50"]],
        figures_dir / "fig_4_1_la_acceleration.svg",
        title="Fig. 4-1 LA acceleration top tension",
    )
    _write_time_overlay_svg(
        [time_results["la_dynamic_decel_current_1p00"], time_results["la_dynamic_decel_current_1p50"]],
        figures_dir / "fig_4_2_la_deceleration.svg",
        title="Fig. 4-2 LA deceleration top tension",
    )
    _write_input_output_doc(out_dir / "INPUT_OUTPUT.md")

    return PaperReproductionResult(
        output_dir=out_dir,
        case_count=len(all_case_names) + len(time_results),
    )


def _is_reproduction_case(name: str) -> bool:
    """判断该命名工况是否进入批量输出。"""

    return (
        name in {"la_accel_200m", "la_decel_200m", "ha_accel_200m", "ha_decel_200m"}
        or name.startswith("power_")
    )


def _write_cases_csv(cases: list[OperationCase], path: Path) -> None:
    """写出批量运行所用的完整输入表。"""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_name",
                "cable",
                "diameter_m",
                "submerged_weight_n_per_m",
                "initial_speed_mps",
                "final_speed_mps",
                "duration_s",
                "water_depth_m",
                "touchdown_tension_n",
                "vessel_speed_mps",
                "payout_speed_mps",
                "current_surface_mps",
                "current_bottom_mps",
                "current_direction_deg",
            ],
        )
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_name": case.name,
                    "cable": case.cable.name,
                    "diameter_m": case.cable.diameter_m,
                    "submerged_weight_n_per_m": case.cable.submerged_weight_n_per_m,
                    "initial_speed_mps": case.initial_speed_mps,
                    "final_speed_mps": case.final_speed_mps,
                    "duration_s": case.duration_s,
                    "water_depth_m": case.water_depth_m,
                    "touchdown_tension_n": case.touchdown_tension_n,
                    "vessel_speed_mps": _empty_none(case.vessel_speed_mps),
                    "payout_speed_mps": _empty_none(case.payout_speed_mps),
                    "current_surface_mps": _empty_none(case.current_surface_mps),
                    "current_bottom_mps": _empty_none(case.current_bottom_mps),
                    "current_direction_deg": _empty_none(case.current_direction_deg),
                }
            )


def _write_table(results: dict[str, SolverResult], names: list[str], path: Path, variable: str) -> None:
    """把一组已求解工况整理成一张参数扫描结果表。"""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_name", variable, "top_tension_n", "tdp_x_m", "tdp_y_m"],
        )
        writer.writeheader()
        for name in names:
            result = results[name]
            case = get_case(name)
            tdp = result.profile[-1]
            writer.writerow(
                {
                    "case_name": name,
                    variable: getattr(case, variable),
                    "top_tension_n": f"{result.top_tension_final_n:.3f}",
                    "tdp_x_m": f"{tdp.x_m:.3f}",
                    "tdp_y_m": f"{tdp.y_m:.3f}",
                }
            )


def _write_dynamic_inputs_csv(cases: list[DynamicCaseInput], path: Path) -> None:
    """写出动态时程工况的标量锚点。"""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_name",
                "cable",
                "current_speed_mps",
                "current_direction_deg",
                "speed_change",
                "initial_speed_mps",
                "final_speed_mps",
                "payout_initial_speed_mps",
                "payout_final_speed_mps",
                "length_boundary_source",
                "duration_s",
                "water_depth_m",
                "touchdown_tension_n",
                "total_duration_s",
                "element_count",
            ],
        )
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_name": case.case_name,
                    "cable": "LA",
                    "current_speed_mps": f"{case.current_speed_mps:.2f}",
                    "current_direction_deg": f"{case.current_direction_deg:.1f}",
                    "speed_change": case.speed_change,
                    "initial_speed_mps": f"{case.initial_speed_mps:.2f}",
                    "final_speed_mps": f"{case.final_speed_mps:.2f}",
                    "payout_initial_speed_mps": (
                        f"{case.payout_initial_speed_mps:.2f}"
                        if case.payout_initial_speed_mps is not None
                        else "same_as_initial_speed_mps"
                    ),
                    "payout_final_speed_mps": (
                        f"{case.payout_final_speed_mps:.2f}"
                        if case.payout_final_speed_mps is not None
                        else "same_as_final_speed_mps"
                    ),
                    "length_boundary_source": case.length_boundary_source,
                    "duration_s": f"{case.duration_s:.1f}",
                    "water_depth_m": f"{case.water_depth_m:.1f}",
                    "touchdown_tension_n": f"{case.touchdown_tension_n:.1f}",
                    "total_duration_s": f"{case.total_duration_s:.1f}",
                    "element_count": case.element_count,
                }
            )


def _write_table_4_1(results: dict[str, TimeHistoryResult], path: Path) -> None:
    """写出 LA 动态工况的初值、极值和稳态张力表。"""

    order = [
        "la_dynamic_accel_current_1p00",
        "la_dynamic_accel_current_1p50",
        "la_dynamic_decel_current_1p00",
        "la_dynamic_decel_current_1p50",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_name",
                "speed_change",
                "current_speed_mps",
                "initial_tension_n",
                "extreme_tension_n",
                "steady_tension_n",
            ],
        )
        writer.writeheader()
        for name in order:
            result = results[name]
            writer.writerow(
                {
                    "case_name": result.case_name,
                    "speed_change": result.speed_change,
                    "current_speed_mps": f"{result.current_speed_mps:.2f}",
                    "initial_tension_n": f"{result.initial_tension_n:.3f}",
                    "extreme_tension_n": f"{result.extreme_tension_n:.3f}",
                    "steady_tension_n": f"{result.steady_tension_n:.3f}",
                }
            )


def _write_overlay_svg(
    results: list[SolverResult],
    path: Path,
    *,
    title: str,
    projection: str,
) -> None:
    """为一组剖面结果写出 SVG 叠加图。"""

    width = 760
    height = 520
    margin = 58
    colors = ["#111111", "#d62728", "#1f77b4", "#cc33cc"]
    # 根据所有曲线的最大水平距离和最大深度统一缩放坐标轴。
    max_horizontal = max(
        max(_project_horizontal(point.x_m, point.y_m, projection) for point in result.profile)
        for result in results
    ) or 1.0
    max_depth = max(max(point.z_m for point in result.profile) for result in results) or 1.0
    plot_w = width - margin * 2
    plot_h = height - margin * 2

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin}" y="28" font-family="Arial, sans-serif" font-size="17">{title}</text>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" stroke="#333"/>',
        f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#333"/>',
    ]
    x_label = _projection_axis_label(projection)
    _append_xy_axes(
        lines,
        width=width,
        height=height,
        margin=margin,
        plot_w=plot_w,
        plot_h=plot_h,
        x_max=max_horizontal,
        y_max=max_depth,
        x_label=x_label,
        y_label="Depth z (m)",
    )
    for index, result in enumerate(results):
        # 不同工况共用一张图，便于核查流速、流向或预张力变化带来的剖面变化。
        points = []
        for point in result.profile:
            horizontal = _project_horizontal(point.x_m, point.y_m, projection)
            x = margin + horizontal / max_horizontal * plot_w
            y = margin + point.z_m / max_depth * plot_h
            points.append(f"{x:.2f},{y:.2f}")
        color = colors[index % len(colors)]
        lines.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{width - margin - 185}" y="{margin + 22 * index}" '
            f'font-family="Arial, sans-serif" font-size="12" fill="{color}">{result.case_name}</text>'
        )
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_time_overlay_svg(
    results: list[TimeHistoryResult],
    path: Path,
    *,
    title: str,
) -> None:
    """为 LA 加速/减速工况写出顶端张力时程叠加图。"""

    width = 760
    height = 460
    margin = 58
    colors = ["#111111", "#d62728"]
    max_time = max(max(point.time_s for point in result.history) for result in results) or 1.0
    all_tensions = [point.top_tension_n for result in results for point in result.history]
    min_tension = min(all_tensions)
    max_tension = max(all_tensions)
    span = max(max_tension - min_tension, 1.0)
    plot_w = width - margin * 2
    plot_h = height - margin * 2
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin}" y="28" font-family="Arial, sans-serif" font-size="17">{title}</text>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" stroke="#333"/>',
        f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#333"/>',
    ]
    _append_time_axes(
        lines,
        width=width,
        height=height,
        margin=margin,
        plot_w=plot_w,
        plot_h=plot_h,
        max_time=max_time,
        min_tension=min_tension,
        max_tension=max_tension,
    )
    for index, result in enumerate(results):
        points = []
        for point in result.history:
            x = margin + point.time_s / max_time * plot_w
            y = height - margin - (point.top_tension_n - min_tension) / span * plot_h
            points.append(f"{x:.2f},{y:.2f}")
        color = colors[index % len(colors)]
        lines.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{width - margin - 185}" y="{margin + 22 * index}" '
            f'font-family="Arial, sans-serif" font-size="12" fill="{color}">{result.case_name}</text>'
        )
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def _project_horizontal(x: float, y: float, projection: str) -> float:
    """按指定投影方式把三维剖面压到水平坐标轴。"""

    if projection == "x":
        return x
    if projection == "y":
        return y
    if projection == "xy":
        return (x * x + y * y) ** 0.5
    raise ValueError(f"unknown projection: {projection}")


def _projection_axis_label(projection: str) -> str:
    """返回剖面投影图的横坐标标签。"""

    if projection == "x":
        return "X distance (m)"
    if projection == "y":
        return "Y distance (m)"
    return "Plan distance xy (m)"


def _append_xy_axes(
    lines: list[str],
    *,
    width: int,
    height: int,
    margin: int,
    plot_w: int,
    plot_h: int,
    x_max: float,
    y_max: float,
    x_label: str,
    y_label: str,
) -> None:
    """为剖面 SVG 添加坐标刻度和坐标轴标签。"""

    for tick in range(5):
        fraction = tick / 4
        x = margin + fraction * plot_w
        y = margin + fraction * plot_h
        x_value = fraction * x_max
        y_value = fraction * y_max
        lines.append(
            f'<line class="axis-tick" x1="{x:.2f}" y1="{height - margin}" '
            f'x2="{x:.2f}" y2="{height - margin + 6}" stroke="#333"/>'
        )
        lines.append(
            f'<text class="axis-tick" x="{x:.2f}" y="{height - margin + 22}" '
            f'font-family="Arial, sans-serif" font-size="11" text-anchor="middle">{x_value:.1f}</text>'
        )
        lines.append(
            f'<line class="axis-tick" x1="{margin - 6}" y1="{y:.2f}" '
            f'x2="{margin}" y2="{y:.2f}" stroke="#333"/>'
        )
        lines.append(
            f'<text class="axis-tick" x="{margin - 10}" y="{y + 4:.2f}" '
            f'font-family="Arial, sans-serif" font-size="11" text-anchor="end">{y_value:.1f}</text>'
        )
    lines.append(
        f'<text x="{margin + plot_w / 2:.2f}" y="{height - 14}" '
        f'font-family="Arial, sans-serif" font-size="13" text-anchor="middle">{x_label}</text>'
    )
    lines.append(
        f'<text x="18" y="{margin + plot_h / 2:.2f}" transform="rotate(-90 18 {margin + plot_h / 2:.2f})" '
        f'font-family="Arial, sans-serif" font-size="13" text-anchor="middle">{y_label}</text>'
    )


def _append_time_axes(
    lines: list[str],
    *,
    width: int,
    height: int,
    margin: int,
    plot_w: int,
    plot_h: int,
    max_time: float,
    min_tension: float,
    max_tension: float,
) -> None:
    """为张力时程 SVG 添加坐标刻度和坐标轴标签。"""

    span = max(max_tension - min_tension, 1.0)
    for tick in range(5):
        fraction = tick / 4
        x = margin + fraction * plot_w
        y = height - margin - fraction * plot_h
        time_value = fraction * max_time
        tension_value = min_tension + fraction * span
        lines.append(
            f'<line class="axis-tick" x1="{x:.2f}" y1="{height - margin}" '
            f'x2="{x:.2f}" y2="{height - margin + 6}" stroke="#333"/>'
        )
        lines.append(
            f'<text class="axis-tick" x="{x:.2f}" y="{height - margin + 22}" '
            f'font-family="Arial, sans-serif" font-size="11" text-anchor="middle">{time_value:.0f}</text>'
        )
        lines.append(
            f'<line class="axis-tick" x1="{margin - 6}" y1="{y:.2f}" '
            f'x2="{margin}" y2="{y:.2f}" stroke="#333"/>'
        )
        lines.append(
            f'<text class="axis-tick" x="{margin - 10}" y="{y + 4:.2f}" '
            f'font-family="Arial, sans-serif" font-size="11" text-anchor="end">{tension_value:.0f}</text>'
        )
    lines.append(
        f'<text x="{margin + plot_w / 2:.2f}" y="{height - 14}" '
        f'font-family="Arial, sans-serif" font-size="13" text-anchor="middle">Time t (s)</text>'
    )
    lines.append(
        f'<text x="18" y="{margin + plot_h / 2:.2f}" transform="rotate(-90 18 {margin + plot_h / 2:.2f})" '
        f'font-family="Arial, sans-serif" font-size="13" text-anchor="middle">Top tension T (N)</text>'
    )


def _write_input_output_doc(path: Path) -> None:
    """在输出目录内写一份便携输入输出说明。"""

    path.write_text(
        """# Input And Output Contract

## Inputs

Inputs are generated in `inputs/cases.csv`. Each row is one thesis reproduction case.

Core fields:

- `case_name`: unique case id used by the CLI and output folders.
- `cable`: cable parameter set.
- `diameter_m`: equivalent cable diameter.
- `submerged_weight_n_per_m`: submerged unit weight.
- `initial_speed_mps`, `final_speed_mps`, `duration_s`: transient laying speed settings for Chapter 3/4 dynamic cases.
- `water_depth_m`: laying water depth.
- `touchdown_tension_n`: specified pre-tension at the touch-down point.
- `vessel_speed_mps`, `payout_speed_mps`: steady engineering laying speeds.
- `current_surface_mps`, `current_bottom_mps`, `current_direction_deg`: current profile and direction.

## Outputs

- `tables/table_4_1_dynamic_la.csv`: algorithmic LA dynamic top-tension scalars.
- `tables/table_4_3_current_speed.csv`: algorithmic top tension and TDP coordinates versus current speed.
- `tables/table_4_4_current_direction.csv`: algorithmic top tension and TDP coordinates versus current direction.
- `tables/table_4_5_pretension.csv`: algorithmic top tension and TDP coordinates versus TDP pre-tension.
- `figures/*.svg`: profile comparison figures.
## Algorithm Notes

- LA/HA static/profile output uses a simplified steady approximation.
- 500 kV current speed, direction, and pre-tension cases use the quasi-static path in `solver.py`.
- LA time-history output uses the finite-difference angle-motion path in `dynamic.py`.
- `time_histories/<case_name>/time_summary.csv`: top-tension scalar summary for dynamic LA cases.
- `time_histories/<case_name>/time_history.csv`: time, top tension, TDP coordinates, suspended length, and solver iteration marker.
- `time_histories/<case_name>/time_history.svg`: time-history plot.
- `cases/<case_name>/summary.csv`: scalar result summary for one case.
- `cases/<case_name>/profile.csv`: signed 3D cable profile, orientation, current, drag, and tension distribution.
- `cases/<case_name>/profile.svg`: single-case profile plot.
""",
        encoding="utf-8",
    )


def _empty_none(value: float | None) -> str | float:
    """把 None 写成 CSV 空单元格。"""

    return "" if value is None else value

"""Diagnose the fully suspended project/OrcaFlex endpoint-tension gap.

This script is an attribution harness.  It does not modify solver inputs with
fitted coefficients and never writes OrcaFlex values into the project solver.
Each project-side ablation changes one numerical/model choice at a time and is
compared with the frozen 48-element OrcaFlex 60 s endpoint history.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND_ROOT / "src"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cable_tension.dynamic import get_time_history_case  # noqa: E402
from cable_tension import dynamic_laying  # noqa: E402
from scripts.analyze_orcaflex_60s_validation import (  # noqa: E402
    _validate_artifact_contract,
    _validate_output_times,
)
from scripts.validate_orcaflex import _build_project_prehistory_case  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _trapezoidal_mean(values: list[float], times: list[float]) -> float:
    integral = sum(
        (right_t - left_t) * (left_v + right_v) * 0.5
        for left_t, right_t, left_v, right_v in zip(
            times, times[1:], values, values[1:]
        )
    )
    return integral / (times[-1] - times[0])


def _metrics(project: list[float], reference: list[float], times: list[float]) -> dict[str, float]:
    project_mean = _trapezoidal_mean(project, times)
    reference_mean = _trapezoidal_mean(reference, times)
    rmse = math.sqrt(
        _trapezoidal_mean(
            [(left - right) ** 2 for left, right in zip(project, reference)],
            times,
        )
    )
    return {
        "project_mean_n": project_mean,
        "orcaflex_mean_n": reference_mean,
        "mean_error_n": project_mean - reference_mean,
        "mean_error_pct": (project_mean - reference_mean) / reference_mean * 100.0,
        "nrmse_pct": rmse / reference_mean * 100.0,
        "mean_pointwise_error_n": statistics.fmean(
            left - right for left, right in zip(project, reference)
        ),
    }


def _window(
    times: list[float],
    project: list[float],
    reference: list[float],
    start_s: float,
    end_s: float,
) -> dict[str, float]:
    indices = [
        index for index, value in enumerate(times)
        if start_s - 1.0e-9 <= value <= end_s + 1.0e-9
    ]
    selected_times = [times[index] for index in indices]
    selected_project = [project[index] for index in indices]
    selected_reference = [reference[index] for index in indices]
    return _metrics(selected_project, selected_reference, selected_times)


def _project_history(
    element_count: int,
    prehistory_duration_s: float,
) -> tuple[list[float], list[float], list[float], dict[str, float]]:
    base_case = replace(
        get_time_history_case("plough_payout_matched_6min"),
        element_count=element_count,
        plough_initial_z_m=70.0,
        initial_suspended_length_m=96.0,
        current_speed_mps=0.35,
        current_direction_deg=90.0,
    )
    project_case = _build_project_prehistory_case(
        base_case,
        prehistory_duration_s=prehistory_duration_s,
        physical_output_window_s=60.0,
    )
    started = time.perf_counter()
    output_points = int(round(prehistory_duration_s + 60.0)) + 1
    result = dynamic_laying.solve_dynamic_laying_time_history(
        project_case,
        points=output_points,
    )
    elapsed = time.perf_counter() - started
    points = [
        point for point in result.history
        if point.time_s >= prehistory_duration_s - 1.0e-9
    ]
    return (
        [float(point.time_s) - prehistory_duration_s for point in points],
        [float(point.top_tension_n) for point in points],
        [float(point.plough_boundary_tension_n) for point in points],
        {
            "wall_clock_s": elapsed,
            "internal_step_min_s": float(result.integration_time_step_min_s),
            "internal_step_max_s": float(result.integration_time_step_max_s),
            "xpbd_iterations_per_step_max": float(result.xpbd_iterations_per_step_max),
        },
    )


def _run_variant(
    name: str,
    element_count: int,
    reference_times: list[float],
    reference_fairlead: list[float],
    reference_plough: list[float],
    prehistory_duration_s: float,
    patch: Callable[[], Callable[[], None]] | None = None,
) -> dict[str, object]:
    restore = patch() if patch is not None else lambda: None
    try:
        times, fairlead, plough, runtime = _project_history(
            element_count,
            prehistory_duration_s,
        )
    finally:
        restore()
    if len(times) != len(reference_times) or any(
        abs(left - right) > 1.0e-8 for left, right in zip(times, reference_times)
    ):
        raise RuntimeError(f"{name}: project and OrcaFlex output times do not match")
    return {
        "variant": name,
        "element_count": element_count,
        "runtime": runtime,
        "fairlead": _metrics(fairlead, reference_fairlead, times),
        "plough": _metrics(plough, reference_plough, times),
        "samples": [
            {
                "time_s": times[index],
                "project_fairlead_n": fairlead[index],
                "orcaflex_fairlead_n": reference_fairlead[index],
                "fairlead_error_n": fairlead[index] - reference_fairlead[index],
                "project_plough_n": plough[index],
                "orcaflex_plough_n": reference_plough[index],
                "plough_error_n": plough[index] - reference_plough[index],
            }
            for index in (0, 10, 30, 60)
        ],
        "windows": {
            f"{start:g}-{end:g}": {
                "fairlead": _window(times, fairlead, reference_fairlead, start, end),
                "plough": _window(times, plough, reference_plough, start, end),
            }
            for start, end in ((0.0, 10.0), (10.0, 30.0), (30.0, 60.0), (50.0, 60.0))
        },
    }


def _patch_mass(added_mass_fraction: float) -> Callable[[], None]:
    original = dynamic_laying._dynamic_mass_per_meter

    def mass_per_meter(case) -> float:
        structural_mass = case.cable.weight_air_n_per_m / dynamic_laying._GRAVITY_MPS2
        displaced_mass = (
            dynamic_laying._SEAWATER_DENSITY_KG_M3
            * math.pi
            * case.cable.diameter_m
            * case.cable.diameter_m
            / 4.0
        )
        return structural_mass + added_mass_fraction * displaced_mass

    dynamic_laying._dynamic_mass_per_meter = mass_per_meter

    def restore() -> None:
        dynamic_laying._dynamic_mass_per_meter = original

    return restore


def _patch_step_cap(cap_s: float) -> Callable[[], None]:
    original = dynamic_laying._time_history_step_limit_s

    def step_limit(dynamic_case, state, *, base_step_s: float) -> float:
        return min(cap_s, original(dynamic_case, state, base_step_s=base_step_s))

    dynamic_laying._time_history_step_limit_s = step_limit

    def restore() -> None:
        dynamic_laying._time_history_step_limit_s = original

    return restore


def _patch_relative_payout_velocity() -> Callable[[], None]:
    """Treat payout as material velocity relative to the moving mesh."""

    original = dynamic_laying._segment_material_velocity

    def material_velocity(*, node_velocity, tangent, payout_speed_mps):
        return dynamic_laying._add(
            node_velocity,
            dynamic_laying._mul(tangent, payout_speed_mps),
        )

    dynamic_laying._segment_material_velocity = material_velocity

    def restore() -> None:
        dynamic_laying._segment_material_velocity = original

    return restore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prehistory-duration-s", type=float, default=60.0)
    parser.add_argument("--expected-active-length-m", type=float, default=96.0)
    parser.add_argument("--expected-plough-depth-m", type=float, default=70.0)
    args = parser.parse_args()

    rows = _read_csv(args.endpoint_csv)
    if not rows:
        raise ValueError("OrcaFlex endpoint CSV is empty")
    scenario_case = get_time_history_case("plough_payout_matched_6min")
    _validate_artifact_contract(
        args.endpoint_csv.parent,
        expected_plough_depth_m=args.expected_plough_depth_m,
        expected_active_length_m=args.expected_active_length_m,
        expected_prehistory_duration_s=args.prehistory_duration_s,
        expected_diameter_m=scenario_case.diameter_m,
        expected_dry_mass_per_m=scenario_case.weight_air_n_per_m / dynamic_laying._GRAVITY_MPS2,
        expected_axial_stiffness_n=scenario_case.axial_stiffness_n,
        expected_normal_drag_coefficient=scenario_case.normal_drag_coefficient,
        expected_axial_drag_coefficient=scenario_case.tangential_drag_coefficient,
    )
    rows = _validate_output_times(rows)
    reference_times = [float(row["time_s"]) for row in rows]
    reference_fairlead = [float(row["end_b_effective_tension_n"]) for row in rows]
    reference_plough = [float(row["end_a_effective_tension_n"]) for row in rows]

    variants = [
        _run_variant(
            "baseline_48",
            48,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
        ),
        _run_variant(
            "no_added_mass_48",
            48,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
            patch=lambda: _patch_mass(0.0),
        ),
        _run_variant(
            "step_cap_0p008333_48",
            48,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
            patch=lambda: _patch_step_cap(0.008333333333333333),
        ),
        _run_variant(
            "mesh_24",
            24,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
        ),
        _run_variant(
            "mesh_96",
            96,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
        ),
        _run_variant(
            "relative_payout_velocity_48",
            48,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
            patch=_patch_relative_payout_velocity,
        ),
        _run_variant(
            "relative_payout_velocity_mesh_96",
            96,
            reference_times,
            reference_fairlead,
            reference_plough,
            args.prehistory_duration_s,
            patch=_patch_relative_payout_velocity,
        ),
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "reference_contract": {
                    "endpoint_csv": str(args.endpoint_csv),
                    "prehistory_duration_s": args.prehistory_duration_s,
                    "expected_plough_depth_m": args.expected_plough_depth_m,
                    "expected_active_length_m": args.expected_active_length_m,
                    "observed_active_length_m": float(rows[0]["active_length_m"]),
                    "diameter_m": scenario_case.diameter_m,
                    "dry_mass_per_m": scenario_case.weight_air_n_per_m / dynamic_laying._GRAVITY_MPS2,
                    "axial_stiffness_n": scenario_case.axial_stiffness_n,
                    "normal_drag_coefficient": scenario_case.normal_drag_coefficient,
                    "axial_drag_coefficient": scenario_case.tangential_drag_coefficient,
                    "output_start_s": reference_times[0],
                    "output_end_s": reference_times[-1],
                },
                "variants": variants,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

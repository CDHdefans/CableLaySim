"""Summarize the agreed 60 s suspended and light-contact OrcaFlex comparisons."""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
from dataclasses import replace
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND_ROOT / "src"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cable_tension.dynamic import get_time_history_case  # noqa: E402
from cable_tension.dynamic_laying import solve_dynamic_laying_time_history  # noqa: E402
from scripts.validate_orcaflex import (  # noqa: E402
    ORCAFLEX_PREHISTORY_RAMP_DURATION_S,
    _build_project_prehistory_case,
    _prehistory_travel_time_s,
    _smootherstep_velocity_fraction,
)


CURVE_FIELDS = (
    "scenario",
    "location",
    "status",
    "sample_count",
    "applicable_time_start_s",
    "applicable_time_end_s",
    "project_mean_n",
    "orcaflex_mean_n",
    "mean_error_pct",
    "nrmse_pct",
    "correlation",
    "project_min_n",
    "orcaflex_min_n",
    "project_max_n",
    "orcaflex_max_n",
    "project_peak_time_s",
    "orcaflex_peak_time_s",
    "peak_time_delta_s",
    "peak_error_pct",
)

CONTACT_STATE_FIELDS = (
    "scenario",
    "time_s",
    "state",
    "project_contact_length_m",
    "orcaflex_contact_length_m",
)

DISTRIBUTION_FIELDS = (
    "scenario",
    "time_s",
    "project_mean_n",
    "orcaflex_mean_n",
    "mean_error_pct",
    "nrmse_pct",
    "correlation",
    "project_min_n",
    "orcaflex_min_n",
    "project_max_n",
    "orcaflex_max_n",
)

PROFILE_FIELDS = (
    "scenario",
    "time_s",
    "normalized_arc_fairlead_to_plough",
    "project_tension_n",
    "orcaflex_tension_n",
    "project_minus_orcaflex_n",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suspended-dir", type=Path, required=True)
    parser.add_argument("--contact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scenarios = (
        ("suspended_no_contact", args.suspended_dir, 96.0, 70.0),
        ("light_contact", args.contact_dir, 110.0, 80.0),
    )
    curve_rows: list[dict[str, object]] = []
    distribution_rows: list[dict[str, object]] = []
    profile_rows: list[dict[str, object]] = []
    contact_state_rows: list[dict[str, object]] = []
    contact_audit: list[tuple[str, float, float, float, dict[str, int]]] = []

    for scenario, directory, active_length_m, plough_depth_m in scenarios:
        _validate_artifact_contract(
            directory,
            expected_plough_depth_m=plough_depth_m,
            expected_active_length_m=active_length_m,
        )
        endpoint_path = _single_matching_file(directory, "*_orcaflex_endpoint_tension.csv")
        distribution_path = _single_matching_file(directory, "*_orcaflex_distribution.csv")
        endpoints = _read_csv(endpoint_path)
        one_second_rows = _validate_output_times(endpoints)
        times = [float(row["time_s"]) for row in one_second_rows]
        project_contact = max(float(row["project_seabed_contact_length_m"]) for row in one_second_rows)
        orcaflex_contact = max(float(row["orcaflex_seabed_contact_length_m"]) for row in one_second_rows)
        tdp_rows, contact_counts = _both_contact_rows(one_second_rows)
        contact_state_rows.extend(_contact_state_output_rows(scenario, one_second_rows))

        curve_pairs = (
            ("fairlead", "project_fairlead_tension_n", "end_b_effective_tension_n", one_second_rows),
            ("plough", "project_plough_boundary_tension_n", "end_a_effective_tension_n", one_second_rows),
            ("tdp", "project_tdp_tension_n", "orcaflex_tdp_effective_tension_n", tdp_rows),
        )
        for location, project_field, orcaflex_field, applicable_rows in curve_pairs:
            if not applicable_rows:
                curve_rows.append(_not_applicable_curve_row(scenario, location, len(times)))
                continue
            applicable_times = [float(row["time_s"]) for row in applicable_rows]
            project_values = [float(row[project_field]) for row in applicable_rows]
            orcaflex_values = [float(row[orcaflex_field]) for row in applicable_rows]
            curve_rows.append(
                _curve_metrics(
                    scenario,
                    location,
                    project_values,
                    orcaflex_values,
                    applicable_times,
                    status="applicable_both_contact" if location == "tdp" else "applicable",
                )
            )

        base_case = replace(
            get_time_history_case("plough_payout_matched_6min"),
            element_count=48,
            plough_initial_z_m=plough_depth_m,
            initial_suspended_length_m=active_length_m,
            current_speed_mps=0.35,
            current_direction_deg=90.0,
        )
        project_case = _build_project_prehistory_case(
            base_case,
            prehistory_duration_s=60.0,
            physical_output_window_s=60.0,
        )
        result = solve_dynamic_laying_time_history(project_case, points=121)
        _validate_project_replay(
            one_second_rows,
            result,
            prehistory_duration_s=60.0,
        )
        frames = {
            round(frame.time_s - 60.0, 9): frame
            for frame in result.frames
            if frame.time_s >= 60.0 - 1.0e-9
        }
        orcaflex_distribution = _read_csv(distribution_path)
        for snapshot_time in (10.0, 30.0, 60.0):
            project_x, project_y = _project_distribution(frames[snapshot_time])
            orcaflex_x, orcaflex_y = _orcaflex_distribution(
                orcaflex_distribution,
                snapshot_time,
            )
            grid = [index / 100.0 for index in range(101)]
            project_grid = [_interpolate(project_x, project_y, station) for station in grid]
            orcaflex_grid = [_interpolate(orcaflex_x, orcaflex_y, station) for station in grid]
            distribution_rows.append(
                _distribution_metrics(
                    scenario,
                    snapshot_time,
                    project_grid,
                    orcaflex_grid,
                )
            )
            for station, project_tension, orcaflex_tension in zip(
                grid,
                project_grid,
                orcaflex_grid,
            ):
                profile_rows.append({
                    "scenario": scenario,
                    "time_s": f"{snapshot_time:g}",
                    "normalized_arc_fairlead_to_plough": f"{station:.2f}",
                    "project_tension_n": f"{project_tension:.9g}",
                    "orcaflex_tension_n": f"{orcaflex_tension:.9g}",
                    "project_minus_orcaflex_n": f"{project_tension - orcaflex_tension:.9g}",
                })
        maximum_depth = max(point.z_m for frame in result.frames for point in frame.points)
        contact_audit.append(
            (scenario, project_contact, orcaflex_contact, maximum_depth, contact_counts)
        )

    args.output.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output / "curve_metrics.csv", CURVE_FIELDS, curve_rows)
    _write_csv(args.output / "distribution_metrics.csv", DISTRIBUTION_FIELDS, distribution_rows)
    _write_csv(args.output / "distribution_profiles.csv", PROFILE_FIELDS, profile_rows)
    _write_csv(args.output / "contact_states.csv", CONTACT_STATE_FIELDS, contact_state_rows)
    _write_summary(
        args.output / "summary.md",
        contact_audit=contact_audit,
        curve_rows=curve_rows,
        distribution_rows=distribution_rows,
    )
    print(args.output / "summary.md")
    return 0


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _single_matching_file(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one artifact matching {pattern!r} in {directory}, found {len(matches)}."
        )
    return matches[0]


def _validate_output_times(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected = [
        row
        for row in rows
        if abs(float(row["time_s"]) - round(float(row["time_s"]))) <= 1.0e-7
    ]
    actual = [float(row["time_s"]) for row in selected]
    expected = [float(value) for value in range(61)]
    if actual != expected:
        raise ValueError("Endpoint output must contain each physical second in 0..60 exactly once.")
    return selected


def _validate_artifact_contract(
    directory: Path,
    *,
    expected_plough_depth_m: float,
    expected_active_length_m: float,
    expected_prehistory_duration_s: float = 60.0,
    expected_output_window_s: float = 60.0,
    expected_element_count: int = 48,
    expected_time_step_s: float = 0.01,
    expected_current_speed_mps: float = 0.35,
    expected_current_direction_deg: float = 90.0,
    expected_endpoint_speed_mps: float = 0.8,
    expected_diameter_m: float | None = None,
    expected_dry_mass_per_m: float | None = None,
    expected_axial_stiffness_n: float | None = None,
    expected_normal_drag_coefficient: float | None = None,
    expected_axial_drag_coefficient: float | None = None,
) -> None:
    report_path = _single_matching_file(directory, "*_orcaflex_dynamic_report.md")
    model_path = _single_matching_file(directory, "*_orcaflex_dynamic.dat")
    input_path = _single_matching_file(directory, "*_orcaflex_dynamic_input.csv")
    report = report_path.read_text(encoding="utf-8")
    required_report_fragments = (
        "Status: `dynamic_completed`",
        f"Physical output window: `0` to `{expected_output_window_s:g}` s",
        f"Project plough depth: `{expected_plough_depth_m:g}` m",
        f"Validation element count: `{expected_element_count}`",
        f"Implicit constant time step: `{expected_time_step_s:g}` s",
        f"Prehistory dynamic interval: physical `-{expected_prehistory_duration_s:g}` to `0` s",
    )
    for fragment in required_report_fragments:
        if fragment not in report:
            raise ValueError(f"Artifact report does not satisfy validation contract: {fragment}")

    model = model_path.read_text(encoding="utf-8")
    current_speed = _model_scalar(model, "RefCurrentSpeed")
    current_direction = _model_scalar(model, "RefCurrentDirection")
    if not math.isclose(current_speed, expected_current_speed_mps, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError(
            f"Artifact current speed is {current_speed:g}, expected {expected_current_speed_mps:g} m/s."
        )
    if not math.isclose(current_direction, expected_current_direction_deg, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError(
            f"Artifact current direction is {current_direction:g}, expected {expected_current_direction_deg:g} deg."
        )
    scalar_expectations = (
        ("OD", expected_diameter_m),
        ("MassPerUnitLength", expected_dry_mass_per_m),
        ("EA", expected_axial_stiffness_n),
    )
    for field, expected in scalar_expectations:
        if expected is None:
            continue
        actual = _model_scalar(model, field)
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError(f"Artifact {field} is {actual:g}, expected {expected:g}.")
    if expected_normal_drag_coefficient is not None or expected_axial_drag_coefficient is not None:
        normal_drag, axial_drag = _model_drag_coefficients(model)
        if expected_normal_drag_coefficient is not None and not math.isclose(
            normal_drag, expected_normal_drag_coefficient, rel_tol=0.0, abs_tol=1.0e-12
        ):
            raise ValueError("Artifact normal drag coefficient does not match the scenario contract.")
        if expected_axial_drag_coefficient is not None and not math.isclose(
            axial_drag, expected_axial_drag_coefficient, rel_tol=0.0, abs_tol=1.0e-12
        ):
            raise ValueError("Artifact axial drag coefficient does not match the scenario contract.")

    input_rows = _read_csv(input_path)
    if not input_rows:
        raise ValueError("OrcaFlex dynamic input artifact is empty.")
    physical_times = [float(row["physical_time_s"]) for row in input_rows]
    if any(later <= earlier for earlier, later in zip(physical_times, physical_times[1:])):
        raise ValueError("Dynamic input physical times must be strictly increasing.")
    if not math.isclose(physical_times[0], -expected_prehistory_duration_s, abs_tol=1.0e-9) or not math.isclose(
        physical_times[-1], expected_output_window_s, abs_tol=1.0e-9
    ):
        raise ValueError(
            "Dynamic input physical-time range does not match the prehistory/output contract."
        )
    active_lengths = [float(row["active_length_m"]) for row in input_rows]
    for row, active_length in zip(input_rows, active_lengths):
        fairlead_rate = float(row["fairlead_payout_rate_mps"])
        plough_rate = float(row["plough_exit_rate_mps"])
        net_rate = float(row["suspended_length_rate_mps"])
        if not math.isclose(fairlead_rate, plough_rate, rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError("All validation input rows must use matched two-end material flow.")
        if not math.isclose(net_rate, 0.0, rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError("Matched two-end material flow must keep zero suspended-length rate.")
        if not math.isclose(active_length, active_lengths[0], rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError("Matched two-end material flow must keep active length constant.")
        if not math.isclose(active_length, expected_active_length_m, abs_tol=0.05):
            raise ValueError("Artifact active length does not match the scenario contract.")
        for component in ("dx_m", "dy_m", "dz_m"):
            fairlead = float(row[f"fairlead_{component}"])
            plough = float(row[f"plough_{component}"])
            if not math.isclose(fairlead, plough, rel_tol=0.0, abs_tol=1.0e-9):
                raise ValueError("Fairlead and plough endpoint translations must match throughout prehistory and output.")
    ramp_duration_s = min(
        ORCAFLEX_PREHISTORY_RAMP_DURATION_S,
        expected_prehistory_duration_s,
    )
    for row in input_rows:
        physical_time_s = float(row["physical_time_s"])
        if physical_time_s > 1.0e-9:
            continue
        elapsed_s = physical_time_s + expected_prehistory_duration_s
        expected_x_m = expected_endpoint_speed_mps * _prehistory_travel_time_s(
            elapsed_s,
            ramp_duration_s,
        )
        if not math.isclose(float(row["fairlead_dx_m"]), expected_x_m, abs_tol=1.0e-8):
            raise ValueError("Prehistory endpoint trajectory does not match the quintic start-up contract.")
        if not math.isclose(float(row["fairlead_dy_m"]), 0.0, abs_tol=1.0e-9) or not math.isclose(
            float(row["fairlead_dz_m"]), 0.0, abs_tol=1.0e-9
        ):
            raise ValueError("Prehistory endpoint trajectory must remain on the +X validation route.")
        ramp_fraction = _smootherstep_velocity_fraction(
            min(1.0, elapsed_s / max(ramp_duration_s, 1.0e-12))
        )
        expected_rate_mps = expected_endpoint_speed_mps * ramp_fraction
        if not math.isclose(float(row["fairlead_payout_rate_mps"]), expected_rate_mps, abs_tol=1.0e-8):
            raise ValueError("Prehistory material rate does not match the quintic start-up contract.")
    physical_rows = [row for row in input_rows if float(row["physical_time_s"]) >= -1.0e-9]
    for row in physical_rows:
        if not math.isclose(float(row["fairlead_payout_rate_mps"]), expected_endpoint_speed_mps, abs_tol=1.0e-9):
            raise ValueError("Physical-window fairlead payout does not match the scenario contract.")
        if not math.isclose(float(row["plough_exit_rate_mps"]), expected_endpoint_speed_mps, abs_tol=1.0e-9):
            raise ValueError("Physical-window plough exit rate does not match the scenario contract.")
    if len(physical_rows) >= 2:
        first = physical_rows[0]
        first_time = float(first["physical_time_s"])
        first_x = float(first["fairlead_dx_m"])
        for row in physical_rows[1:]:
            elapsed = float(row["physical_time_s"]) - first_time
            expected_x = first_x + expected_endpoint_speed_mps * elapsed
            if not math.isclose(float(row["fairlead_dx_m"]), expected_x, abs_tol=1.0e-8):
                raise ValueError("Physical-window endpoint translation speed does not match the scenario contract.")
            if not math.isclose(float(row["fairlead_dy_m"]), float(first["fairlead_dy_m"]), abs_tol=1.0e-9):
                raise ValueError("Physical-window endpoint Y translation must remain constant.")
            if not math.isclose(float(row["fairlead_dz_m"]), float(first["fairlead_dz_m"]), abs_tol=1.0e-9):
                raise ValueError("Physical-window endpoint Z translation must remain constant.")


def _model_scalar(model_text: str, field: str) -> float:
    match = re.search(rf"^\s*{re.escape(field)}:\s*([-+0-9.eE]+)\s*$", model_text, re.MULTILINE)
    if match is None:
        raise ValueError(f"OrcaFlex model does not define {field}.")
    return float(match.group(1))


def _model_drag_coefficients(model_text: str) -> tuple[float, float]:
    match = re.search(r"^\s*Cd:\s*\[\s*([-+0-9.eE]+)\s*,\s*~\s*,\s*([-+0-9.eE]+)\s*\]\s*$", model_text, re.MULTILINE)
    if match is None:
        raise ValueError("OrcaFlex model does not define normal/axial Cd.")
    return float(match.group(1)), float(match.group(2))


def _validate_project_replay(
    endpoint_rows: list[dict[str, str]],
    result,
    *,
    prehistory_duration_s: float,
) -> None:
    history_by_physical_time = {
        round(float(point.time_s) - prehistory_duration_s, 9): point
        for point in result.history
        if float(point.time_s) >= prehistory_duration_s - 1.0e-9
    }
    field_map = (
        ("project_fairlead_tension_n", "top_tension_n"),
        ("project_plough_boundary_tension_n", "plough_boundary_tension_n"),
        ("project_tdp_tension_n", "plough_inlet_tension_n"),
        ("project_seabed_contact_length_m", "seabed_contact_length_m"),
    )
    for row in endpoint_rows:
        physical_time = round(float(row["time_s"]), 9)
        point = history_by_physical_time.get(physical_time)
        if point is None:
            raise ValueError(f"Current project replay has no frame at physical t={physical_time:g} s.")
        for csv_field, result_field in field_map:
            expected = float(row[csv_field])
            actual = float(getattr(point, result_field))
            if not math.isclose(actual, expected, rel_tol=1.0e-8, abs_tol=1.0e-6):
                raise ValueError(
                    f"Current project replay does not match artifact field {csv_field} "
                    f"at physical t={physical_time:g} s: {actual:.12g} != {expected:.12g}."
                )
        active_length = float(point.free_span_material_length_m) + float(
            point.seabed_contact_length_m
        )
        expected_active_length = float(row["active_length_m"])
        if not math.isclose(
            active_length,
            expected_active_length,
            rel_tol=1.0e-8,
            abs_tol=1.0e-6,
        ):
            raise ValueError(
                "Current project replay active length does not match the OrcaFlex artifact "
                f"at physical t={physical_time:g} s."
            )


def _contact_state(row: dict[str, str]) -> str:
    project = float(row["project_seabed_contact_length_m"]) > 1.0e-6
    orcaflex = float(row["orcaflex_seabed_contact_length_m"]) > 1.0e-6
    if project and orcaflex:
        return "both_contact"
    if project:
        return "project_only"
    if orcaflex:
        return "orcaflex_only"
    return "neither"


def _both_contact_rows(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    counts = {state: 0 for state in ("both_contact", "project_only", "orcaflex_only", "neither")}
    selected: list[dict[str, str]] = []
    for row in rows:
        state = _contact_state(row)
        counts[state] += 1
        if state == "both_contact":
            selected.append(row)
    return selected, counts


def _contact_state_output_rows(
    scenario: str,
    rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    return [
        {
            "scenario": scenario,
            "time_s": row["time_s"],
            "state": _contact_state(row),
            "project_contact_length_m": row["project_seabed_contact_length_m"],
            "orcaflex_contact_length_m": row["orcaflex_seabed_contact_length_m"],
        }
        for row in rows
    ]


def _write_csv(path: Path, fields, rows) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _trapezoidal_time_mean(values: list[float], times: list[float]) -> float:
    if len(values) != len(times) or len(values) < 2:
        raise ValueError("Time-weighted metrics require at least two paired samples.")
    intervals = [later - earlier for earlier, later in zip(times, times[1:])]
    if any(interval <= 0.0 for interval in intervals):
        raise ValueError("Metric sample times must be strictly increasing.")
    integral = sum(
        interval * (left + right) * 0.5
        for interval, left, right in zip(intervals, values, values[1:])
    )
    return integral / (times[-1] - times[0])


def _correlation(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    return sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right)
    ) / max(left_scale * right_scale, 1.0e-30)


def _curve_metrics(
    scenario,
    location,
    project,
    orcaflex,
    times,
    *,
    status="applicable",
) -> dict[str, object]:
    project_mean = _trapezoidal_time_mean(project, times)
    orcaflex_mean = _trapezoidal_time_mean(orcaflex, times)
    rmse = math.sqrt(
        _trapezoidal_time_mean([(a - b) ** 2 for a, b in zip(project, orcaflex)], times)
    )
    project_peak = max(range(len(project)), key=project.__getitem__)
    orcaflex_peak = max(range(len(orcaflex)), key=orcaflex.__getitem__)
    return {
        "scenario": scenario,
        "location": location,
        "status": status,
        "sample_count": len(times),
        "applicable_time_start_s": f"{times[0]:.9g}",
        "applicable_time_end_s": f"{times[-1]:.9g}",
        "project_mean_n": f"{project_mean:.9g}",
        "orcaflex_mean_n": f"{orcaflex_mean:.9g}",
        "mean_error_pct": f"{(project_mean - orcaflex_mean) / orcaflex_mean * 100.0:.6g}",
        "nrmse_pct": f"{rmse / orcaflex_mean * 100.0:.6g}",
        "correlation": f"{_correlation(project, orcaflex):.9g}",
        "project_min_n": f"{min(project):.9g}",
        "orcaflex_min_n": f"{min(orcaflex):.9g}",
        "project_max_n": f"{max(project):.9g}",
        "orcaflex_max_n": f"{max(orcaflex):.9g}",
        "project_peak_time_s": f"{times[project_peak]:.9g}",
        "orcaflex_peak_time_s": f"{times[orcaflex_peak]:.9g}",
        "peak_time_delta_s": f"{abs(times[project_peak] - times[orcaflex_peak]):.9g}",
        "peak_error_pct": f"{(project[project_peak] - orcaflex[orcaflex_peak]) / orcaflex[orcaflex_peak] * 100.0:.6g}",
    }


def _not_applicable_curve_row(scenario: str, location: str, sample_count: int) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in CURVE_FIELDS}
    row.update({
        "scenario": scenario,
        "location": location,
        "status": "not_applicable_no_contact",
        "sample_count": sample_count,
    })
    return row


def _project_distribution(frame) -> tuple[list[float], list[float]]:
    lengths = [
        math.dist((left.x_m, left.y_m, left.z_m), (right.x_m, right.y_m, right.z_m))
        for left, right in zip(frame.points, frame.points[1:])
    ]
    total_length = sum(lengths)
    coordinate = 0.0
    stations = []
    for length in lengths:
        stations.append((coordinate + 0.5 * length) / total_length)
        coordinate += length
    return stations, [float(value) for value in frame.segment_tensions_n]


def _orcaflex_distribution(rows, time_s: float) -> tuple[list[float], list[float]]:
    pairs = sorted(
        (
            1.0 - float(row["normalized_active_arc"]),
            float(row["effective_tension_n"]),
        )
        for row in rows
        if abs(float(row["time_s"]) - time_s) <= 1.0e-7
    )
    if not pairs:
        raise ValueError(f"OrcaFlex distribution has no frame at t={time_s:g} s")
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def _interpolate(stations: list[float], values: list[float], station: float) -> float:
    if station <= stations[0]:
        return values[0]
    if station >= stations[-1]:
        return values[-1]
    for index in range(len(stations) - 1):
        if station > stations[index + 1]:
            continue
        fraction = (station - stations[index]) / (stations[index + 1] - stations[index])
        return values[index] + fraction * (values[index + 1] - values[index])
    return values[-1]


def _distribution_metrics(scenario, time_s, project, orcaflex) -> dict[str, object]:
    project_mean = statistics.fmean(project)
    orcaflex_mean = statistics.fmean(orcaflex)
    rmse = math.sqrt(statistics.fmean((a - b) ** 2 for a, b in zip(project, orcaflex)))
    return {
        "scenario": scenario,
        "time_s": f"{time_s:g}",
        "project_mean_n": f"{project_mean:.9g}",
        "orcaflex_mean_n": f"{orcaflex_mean:.9g}",
        "mean_error_pct": f"{(project_mean - orcaflex_mean) / orcaflex_mean * 100.0:.6g}",
        "nrmse_pct": f"{rmse / orcaflex_mean * 100.0:.6g}",
        "correlation": f"{_correlation(project, orcaflex):.9g}",
        "project_min_n": f"{min(project):.9g}",
        "orcaflex_min_n": f"{min(orcaflex):.9g}",
        "project_max_n": f"{max(project):.9g}",
        "orcaflex_max_n": f"{max(orcaflex):.9g}",
    }


def _write_summary(path, *, contact_audit, curve_rows, distribution_rows) -> None:
    lines = [
        "# OrcaFlex 60 s Dynamic Validation Summary",
        "",
        "Both scenarios use 48 elements, 0.01 s OrcaFlex integration, 60 s balanced prehistory, and physical 0..60 s comparison. Curve metrics use 1 s samples. Distribution profiles use normalized arc from fairlead (0) to plough (1).",
        "",
        "## Contact audit",
        "",
        "| Scenario | Project max contact length (m) | OrcaFlex max contact length (m) | Project max depth (m) | Both contact | Project only | OrcaFlex only | Neither |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {scenario} | {project_contact:.6g} | {orcaflex_contact:.6g} | {maximum_depth:.6g} | {counts['both_contact']} | {counts['project_only']} | {counts['orcaflex_only']} | {counts['neither']} |"
        for scenario, project_contact, orcaflex_contact, maximum_depth, counts in contact_audit
    )
    lines.extend([
        "",
        "## Curve metrics",
        "",
        "NRMSE is normalized by the corresponding OrcaFlex time mean. TDP metrics use only frames where both solvers report seabed contact.",
        "",
        "| Scenario | Location | Status | Samples | Time range (s) | Project mean (N) | OrcaFlex mean (N) | Mean error (%) | NRMSE (%) | Correlation | Peak time delta (s) |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ])
    lines.extend(
        f"| {row['scenario']} | {row['location']} | {row['status']} | {row['sample_count']} | {_time_range(row)} | {row['project_mean_n'] or '-'} | {row['orcaflex_mean_n'] or '-'} | {row['mean_error_pct'] or '-'} | {row['nrmse_pct'] or '-'} | {row['correlation'] or '-'} | {row['peak_time_delta_s'] or '-'} |"
        for row in curve_rows
    )
    lines.extend([
        "",
        "## Distribution metrics",
        "",
        "Distribution mean and RMSE use 101 uniformly spaced normalized-arc stations; NRMSE is normalized by the OrcaFlex station mean.",
        "",
        "| Scenario | Time (s) | Project mean (N) | OrcaFlex mean (N) | Mean error (%) | NRMSE (%) | Correlation |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    lines.extend(
        f"| {row['scenario']} | {row['time_s']} | {row['project_mean_n']} | {row['orcaflex_mean_n']} | {row['mean_error_pct']} | {row['nrmse_pct']} | {row['correlation']} |"
        for row in distribution_rows
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _time_range(row: dict[str, object]) -> str:
    start = row["applicable_time_start_s"]
    end = row["applicable_time_end_s"]
    return f"{start}..{end}" if start != "" and end != "" else "-"


if __name__ == "__main__":
    raise SystemExit(main())

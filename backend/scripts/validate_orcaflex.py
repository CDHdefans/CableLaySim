"""Build an OrcaFlex validation-layer probe for known-plough cases.

This script is intentionally outside the production solver. It checks whether
the installed OrcaFlex Python API can be imported and initialized, writes the
same-input mapping needed for later OrcaFlex comparisons, and records endpoint
motion histories in OrcaFlex z-up coordinates. It does not feed OrcaFlex values
back into project results.
"""

from __future__ import annotations

import argparse
import collections
import collections.abc
import csv
import filecmp
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND_ROOT / "src"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts.validate_moordyn_moorpy import (  # noqa: E402
    PROJECT_GRAVITY_MPS2,
    PROJECT_SEABED_FRICTION_COEFFICIENT,
    PROJECT_SEAWATER_DENSITY_KG_M3,
    _build_project_snapshot,
    _fmt3,
    _project_current_components,
)
from cable_tension.dynamic import _CYLINDER_ADDED_MASS_COEFFICIENT, get_time_history_case  # noqa: E402


ORCAFLEX_INPUT_MAPPING_FIELDS = (
    "category",
    "project_input",
    "project_value",
    "orcaflex_target",
    "orcaflex_value",
    "status",
    "notes",
)

ORCAFLEX_ENDPOINT_HISTORY_FIELDS = (
    "time_s",
    "fairlead_x_m",
    "fairlead_y_m",
    "fairlead_z_m",
    "fairlead_vx_mps",
    "fairlead_vy_mps",
    "fairlead_vz_mps",
    "plough_x_m",
    "plough_y_m",
    "plough_z_m",
    "plough_vx_mps",
    "plough_vy_mps",
    "plough_vz_mps",
    "unstretched_length_m",
    "unstretched_length_rate_mps",
)

ORCAFLEX_PROBE_FIELDS = ("key", "value")

ORCAFLEX_DYNAMIC_INPUT_FIELDS = (
    "time_s",
    "physical_time_s",
    "fairlead_dx_m",
    "fairlead_dy_m",
    "fairlead_dz_m",
    "plough_dx_m",
    "plough_dy_m",
    "plough_dz_m",
    "suspended_length_rate_mps",
    "fairlead_payout_rate_mps",
    "plough_exit_rate_mps",
    "active_length_m",
)

ORCAFLEX_STATIC_PROBE_CASE = "plough_straight_baseline_6min"
ORCAFLEX_DYNAMIC_BASELINE_CASE = "plough_payout_matched_6min"
ORCAFLEX_BUILD_UP_DURATION_S = 1.0e-6
ORCAFLEX_DYNAMIC_TIME_STEP_S = 0.01
ORCAFLEX_DYNAMIC_LOG_INTERVAL_S = 0.01
ORCAFLEX_NORMAL_ADDED_MASS_COEFFICIENT = _CYLINDER_ADDED_MASS_COEFFICIENT
ORCAFLEX_AXIAL_ADDED_MASS_COEFFICIENT = 0.0
ORCAFLEX_MINIMUM_INACTIVE_FEED_RESERVE_M = 0.01
ORCAFLEX_SHORTEST_VIABLE_SEGMENT_FACTOR = 0.001
ORCAFLEX_PREHISTORY_RATE_TOLERANCE_MPS = 1.0e-12
ORCAFLEX_PREHISTORY_KINEMATIC_TOLERANCE = 1.0e-9
ORCAFLEX_PREHISTORY_RAMP_DURATION_S = 10.0
ORCAFLEX_PREHISTORY_SAMPLE_INTERVAL_S = 0.1

ORCAFLEX_ENDPOINT_TENSION_FIELDS = (
    "time_s",
    "plough_expected_x_m",
    "plough_expected_y_m",
    "plough_expected_z_m",
    "plough_actual_x_m",
    "plough_actual_y_m",
    "plough_actual_z_m",
    "plough_position_error_m",
    "fairlead_expected_x_m",
    "fairlead_expected_y_m",
    "fairlead_expected_z_m",
    "fairlead_actual_x_m",
    "fairlead_actual_y_m",
    "fairlead_actual_z_m",
    "fairlead_position_error_m",
    "end_a_effective_tension_n",
    "end_b_effective_tension_n",
    "active_length_m",
    "project_tdp_arc_length_m",
    "project_free_span_material_length_m",
    "project_seabed_contact_length_m",
    "project_tdp_tension_n",
    "project_seabed_normal_reaction_n",
    "project_fairlead_tension_n",
    "project_plough_boundary_tension_n",
    "project_plough_adjacent_tension_n",
    "orcaflex_tdp_arc_length_m",
    "orcaflex_seabed_contact_length_m",
    "orcaflex_tdp_effective_tension_n",
    "orcaflex_seabed_normal_resultant_n",
)

ORCAFLEX_DISTRIBUTION_FIELDS = (
    "time_s",
    "arc_length_m",
    "normalized_active_arc",
    "x_m",
    "y_m",
    "z_m",
    "effective_tension_n",
    "seabed_normal_resistance_n",
    "in_seabed_contact",
    "active_length_m",
)


@dataclass(frozen=True)
class OrcaFlexProbe:
    status: str
    import_status: str
    dll_version: str
    python_executable: str
    python_version: str
    module_path: str
    model_status: str
    license_env: str
    flexnet_ini_exists: bool
    notes: str


@dataclass(frozen=True)
class OrcaFlexDynamicInput:
    """Endpoint motion and two-end material histories for OrcaFlex dynamics.

    ``suspended_length_rates_mps`` is dL_s/dt=q_f-q_p.  It is deliberately
    not the raw ship-end payout encoder rate q_f.
    """

    times_s: tuple[float, ...]
    plough_initial_position_m: tuple[float, float, float]
    fairlead_initial_position_m: tuple[float, float, float]
    plough_displacements_m: tuple[tuple[float, float, float], ...]
    fairlead_displacements_m: tuple[tuple[float, float, float], ...]
    suspended_length_rates_mps: tuple[float, ...]
    active_lengths_m: tuple[float, ...]
    initial_active_length_m: float
    full_line_length_m: float
    physical_output_times_s: tuple[float, ...] = ()
    physical_time_offset_s: float = 0.0
    prehistory_duration_s: float = 0.0
    fairlead_payout_rates_mps: tuple[float, ...] = ()
    plough_exit_rates_mps: tuple[float, ...] = ()


def _build_orcaflex_dynamic_input(endpoint_drive_samples: Sequence[object]) -> OrcaFlexDynamicInput:
    """Use the z-up endpoint snapshots directly in OrcaFlex dynamic input."""

    if not endpoint_drive_samples:
        raise ValueError("At least one endpoint drive sample is required for OrcaFlex dynamics.")

    times_s = tuple(float(sample.time_s) for sample in endpoint_drive_samples)
    if any(later <= earlier for earlier, later in zip(times_s, times_s[1:])):
        raise ValueError("OrcaFlex dynamic endpoint sample times must be strictly increasing.")

    plough_positions = tuple(
        _orcaflex_snapshot_position(sample.plough_position_m)
        for sample in endpoint_drive_samples
    )
    fairlead_positions = tuple(
        _orcaflex_snapshot_position(sample.fairlead_position_m)
        for sample in endpoint_drive_samples
    )
    initial_active_length_m = float(endpoint_drive_samples[0].unstretched_length_m)
    full_line_length_m = max(float(sample.unstretched_length_m) for sample in endpoint_drive_samples)
    if initial_active_length_m <= 0.0 or full_line_length_m < initial_active_length_m:
        raise ValueError("OrcaFlex dynamic active line lengths must be positive and non-decreasing from the initial frame.")

    net_rates = tuple(
        _normalise_net_suspended_length_rate(float(sample.unstretched_length_rate_mps))
        for sample in endpoint_drive_samples
    )
    fairlead_payout_rates = tuple(
        _endpoint_material_rate(sample, "fairlead", net_rate)
        for sample, net_rate in zip(endpoint_drive_samples, net_rates)
    )
    plough_exit_rates = tuple(
        _endpoint_material_rate(sample, "plough", net_rate)
        for sample, net_rate in zip(endpoint_drive_samples, net_rates)
    )
    return OrcaFlexDynamicInput(
        times_s=times_s,
        plough_initial_position_m=plough_positions[0],
        fairlead_initial_position_m=fairlead_positions[0],
        plough_displacements_m=tuple(_subtract(position, plough_positions[0]) for position in plough_positions),
        fairlead_displacements_m=tuple(_subtract(position, fairlead_positions[0]) for position in fairlead_positions),
        suspended_length_rates_mps=net_rates,
        active_lengths_m=tuple(
            float(sample.unstretched_length_m)
            for sample in endpoint_drive_samples
        ),
        initial_active_length_m=initial_active_length_m,
        full_line_length_m=full_line_length_m,
        physical_output_times_s=times_s,
        fairlead_payout_rates_mps=fairlead_payout_rates,
        plough_exit_rates_mps=plough_exit_rates,
    )


def _orcaflex_snapshot_position(position_m: Sequence[float]) -> tuple[float, float, float]:
    """Validate an endpoint position already converted to OrcaFlex z-up axes."""

    if len(position_m) != 3:
        raise ValueError("Project endpoint position must have exactly three coordinates.")
    return (float(position_m[0]), float(position_m[1]), float(position_m[2]))


def _slice_endpoint_drive_samples(
    endpoint_drive_samples: Sequence[object],
    *,
    physical_output_window_s: float,
) -> tuple[object, ...]:
    """Keep existing endpoint samples through an exact physical output time."""

    if not math.isfinite(physical_output_window_s) or physical_output_window_s <= 0.0:
        raise ValueError("physical_output_window_s must be a positive finite number.")
    for index, sample in enumerate(endpoint_drive_samples):
        if math.isclose(float(sample.time_s), physical_output_window_s, rel_tol=0.0, abs_tol=1.0e-9):
            return tuple(endpoint_drive_samples[: index + 1])
    raise ValueError(
        "physical_output_window_s must match an existing endpoint-history sample; "
        "the validation slice does not interpolate or rewrite physical inputs."
    )


def _normalise_net_suspended_length_rate(rate_mps: float) -> float:
    """Remove finite-difference round-off from an analytically balanced dL_s/dt."""

    return 0.0 if abs(rate_mps) <= 1.0e-12 else rate_mps


def _endpoint_material_rate(sample: object, endpoint: str, net_rate_mps: float) -> float:
    if endpoint == "fairlead":
        value = getattr(sample, "fairlead_payout_speed_mps", None)
        fallback = max(0.0, net_rate_mps)
    elif endpoint == "plough":
        value = getattr(sample, "plough_exit_speed_mps", None)
        fallback = max(0.0, -net_rate_mps)
    else:
        raise ValueError(f"unsupported material-rate endpoint: {endpoint}")
    resolved = fallback if value is None else float(value)
    if not math.isfinite(resolved) or resolved < 0.0:
        raise ValueError(f"{endpoint} material rate must be finite and non-negative")
    return resolved


def _build_orcaflex_prehistory_input(
    endpoint_drive_samples: Sequence[object],
    *,
    prehistory_duration_s: float,
) -> OrcaFlexDynamicInput:
    """Build a model-clock prehistory without changing physical 0..T inputs."""

    physical_input = _build_orcaflex_dynamic_input(endpoint_drive_samples)
    if not math.isfinite(prehistory_duration_s) or prehistory_duration_s < 0.0:
        raise ValueError("prehistory_duration_s must be a non-negative finite number.")
    if prehistory_duration_s == 0.0:
        return physical_input

    _validate_orcaflex_prehistory_conditions(endpoint_drive_samples, physical_input)
    first_sample = endpoint_drive_samples[0]
    plough_velocity = _orcaflex_snapshot_position(first_sample.plough_velocity_mps)
    fairlead_velocity = _orcaflex_snapshot_position(first_sample.fairlead_velocity_mps)
    ramp_duration_s = min(ORCAFLEX_PREHISTORY_RAMP_DURATION_S, prehistory_duration_s)
    total_travel_time_s = _prehistory_travel_time_s(prehistory_duration_s, ramp_duration_s)
    plough_initial = _subtract(
        physical_input.plough_initial_position_m,
        _scale_vector(plough_velocity, total_travel_time_s),
    )
    fairlead_initial = _subtract(
        physical_input.fairlead_initial_position_m,
        _scale_vector(fairlead_velocity, total_travel_time_s),
    )

    prehistory_sample_count = max(
        1,
        math.ceil(prehistory_duration_s / ORCAFLEX_PREHISTORY_SAMPLE_INTERVAL_S),
    )
    prehistory_times = tuple(
        prehistory_duration_s * index / prehistory_sample_count
        for index in range(prehistory_sample_count)
    )
    model_times = (*prehistory_times, *(prehistory_duration_s + time_s for time_s in physical_input.times_s))
    prehistory_rate_fractions = tuple(
        _smootherstep_velocity_fraction(min(1.0, time_s / max(ramp_duration_s, 1.0e-12)))
        for time_s in prehistory_times
    )
    plough_positions = tuple(
        _add(physical_input.plough_initial_position_m, displacement)
        for displacement in physical_input.plough_displacements_m
    )
    fairlead_positions = tuple(
        _add(physical_input.fairlead_initial_position_m, displacement)
        for displacement in physical_input.fairlead_displacements_m
    )
    return OrcaFlexDynamicInput(
        times_s=model_times,
        plough_initial_position_m=plough_initial,
        fairlead_initial_position_m=fairlead_initial,
        plough_displacements_m=(
            *(
                _scale_vector(plough_velocity, _prehistory_travel_time_s(time_s, ramp_duration_s))
                for time_s in prehistory_times
            ),
            *(_subtract(position, plough_initial) for position in plough_positions),
        ),
        fairlead_displacements_m=(
            *(
                _scale_vector(fairlead_velocity, _prehistory_travel_time_s(time_s, ramp_duration_s))
                for time_s in prehistory_times
            ),
            *(_subtract(position, fairlead_initial) for position in fairlead_positions),
        ),
        suspended_length_rates_mps=(
            *(0.0 for _ in prehistory_times),
            *physical_input.suspended_length_rates_mps,
        ),
        active_lengths_m=(
            *(physical_input.initial_active_length_m for _ in prehistory_times),
            *physical_input.active_lengths_m,
        ),
        initial_active_length_m=physical_input.initial_active_length_m,
        full_line_length_m=physical_input.full_line_length_m,
        physical_output_times_s=physical_input.physical_output_times_s,
        physical_time_offset_s=prehistory_duration_s,
        prehistory_duration_s=prehistory_duration_s,
        fairlead_payout_rates_mps=(
            *(physical_input.fairlead_payout_rates_mps[0] * fraction for fraction in prehistory_rate_fractions),
            *physical_input.fairlead_payout_rates_mps,
        ),
        plough_exit_rates_mps=(
            *(physical_input.plough_exit_rates_mps[0] * fraction for fraction in prehistory_rate_fractions),
            *physical_input.plough_exit_rates_mps,
        ),
    )


def _prehistory_travel_time_s(time_s: float, ramp_duration_s: float) -> float:
    """Integrate a quintic smootherstep velocity ramp and return distance / final speed."""

    if ramp_duration_s <= 0.0 or time_s >= ramp_duration_s:
        return time_s - 0.5 * ramp_duration_s
    u = time_s / ramp_duration_s
    return ramp_duration_s * (u**6 - 3.0 * u**5 + 2.5 * u**4)


def _build_project_prehistory_case(
    dynamic_case: object,
    *,
    prehistory_duration_s: float,
    physical_output_window_s: float,
) -> object:
    """Build a validation-only project case with the OrcaFlex smooth start-up history."""

    from cable_tension.dynamic import MotionSegment, SpeedSegment

    if prehistory_duration_s <= 0.0 or physical_output_window_s <= 0.0:
        raise ValueError("Project prehistory and physical output window must both be positive.")
    if getattr(dynamic_case, "vessel_motion_segments", ()) or getattr(dynamic_case, "plough_motion_segments", ()):
        raise ValueError("Project prehistory validation requires a baseline without existing motion segments.")
    if getattr(dynamic_case, "vessel_motion_samples", ()) or getattr(dynamic_case, "plough_motion_samples", ()):
        raise ValueError("Project prehistory validation requires a baseline without existing motion samples.")

    endpoint_speed_mps = float(dynamic_case.initial_speed_mps)
    expected_speeds = (
        float(dynamic_case.final_speed_mps),
        float(dynamic_case.plough_speed_mps),
        float(dynamic_case.payout_initial_speed_mps),
        float(dynamic_case.payout_final_speed_mps),
    )
    if not all(math.isclose(speed, endpoint_speed_mps, rel_tol=0.0, abs_tol=1.0e-12) for speed in expected_speeds):
        raise ValueError("Project smooth prehistory currently requires matched constant vessel, plough, and payout speeds.")
    if not math.isclose(float(dynamic_case.vessel_heading_deg), 0.0, abs_tol=1.0e-12) or not math.isclose(
        float(dynamic_case.plough_heading_deg),
        0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError("Project smooth prehistory currently requires the straight +X validation route.")

    ramp_duration_s = min(ORCAFLEX_PREHISTORY_RAMP_DURATION_S, prehistory_duration_s)
    ramp_segment_count = max(1, math.ceil(ramp_duration_s / ORCAFLEX_PREHISTORY_SAMPLE_INTERVAL_S))
    ramp_step_s = ramp_duration_s / ramp_segment_count
    motion_segments = []
    payout_segments = []
    for index in range(ramp_segment_count):
        start_fraction = _smootherstep_velocity_fraction(index / ramp_segment_count)
        end_fraction = _smootherstep_velocity_fraction((index + 1) / ramp_segment_count)
        start_speed = endpoint_speed_mps * start_fraction
        end_speed = endpoint_speed_mps * end_fraction
        motion_segments.append(MotionSegment(ramp_step_s, start_speed, end_speed, 0.0))
        payout_segments.append(SpeedSegment(ramp_step_s, start_speed, end_speed))

    total_duration_s = prehistory_duration_s + physical_output_window_s
    constant_duration_s = total_duration_s - ramp_duration_s
    if constant_duration_s > 0.0:
        motion_segments.append(MotionSegment(constant_duration_s, endpoint_speed_mps, endpoint_speed_mps, 0.0))
        payout_segments.append(SpeedSegment(constant_duration_s, endpoint_speed_mps, endpoint_speed_mps))

    prehistory_distance_m = endpoint_speed_mps * _prehistory_travel_time_s(
        prehistory_duration_s,
        ramp_duration_s,
    )
    return replace(
        dynamic_case,
        case_name=f"{dynamic_case.case_name}_smooth_prehistory",
        duration_s=total_duration_s,
        total_duration_s=total_duration_s,
        vessel_initial_x_m=float(dynamic_case.vessel_initial_x_m) - prehistory_distance_m,
        plough_initial_x_m=float(dynamic_case.plough_initial_x_m) - prehistory_distance_m,
        vessel_motion_segments=tuple(motion_segments),
        plough_motion_segments=tuple(motion_segments),
        payout_speed_segments=tuple(payout_segments),
    )


def _smootherstep_velocity_fraction(fraction: float) -> float:
    u = max(0.0, min(1.0, fraction))
    return 6.0 * u**5 - 15.0 * u**4 + 10.0 * u**3


def _validate_orcaflex_prehistory_conditions(
    endpoint_drive_samples: Sequence[object],
    physical_input: OrcaFlexDynamicInput,
) -> None:
    if len(endpoint_drive_samples) < 2:
        raise ValueError("OrcaFlex prehistory requires at least two endpoint-history samples.")
    if any(abs(rate) > ORCAFLEX_PREHISTORY_RATE_TOLERANCE_MPS for rate in physical_input.suspended_length_rates_mps):
        raise ValueError("OrcaFlex prehistory requires zero net suspended-length rate throughout the physical history.")
    first, second = endpoint_drive_samples[:2]
    interval_s = float(second.time_s) - float(first.time_s)
    if interval_s <= 0.0:
        raise ValueError("OrcaFlex prehistory requires a strictly increasing first endpoint-history segment.")
    plough_velocity = _orcaflex_snapshot_position(first.plough_velocity_mps)
    fairlead_velocity = _orcaflex_snapshot_position(first.fairlead_velocity_mps)
    plough_displacement = _subtract(
        _orcaflex_snapshot_position(second.plough_position_m),
        _orcaflex_snapshot_position(first.plough_position_m),
    )
    fairlead_displacement = _subtract(
        _orcaflex_snapshot_position(second.fairlead_position_m),
        _orcaflex_snapshot_position(first.fairlead_position_m),
    )
    if not _vectors_close(plough_velocity, fairlead_velocity) or not _vectors_close(
        plough_displacement,
        fairlead_displacement,
    ):
        raise ValueError(
            "OrcaFlex prehistory requires a common endpoint translation: equal first-segment "
            "plough/fairlead velocity and displacement vectors."
        )
    for endpoint in ("plough", "fairlead"):
        first_velocity = _orcaflex_snapshot_position(getattr(first, f"{endpoint}_velocity_mps"))
        second_velocity = _orcaflex_snapshot_position(getattr(second, f"{endpoint}_velocity_mps"))
        if not _vectors_close(first_velocity, second_velocity):
            raise ValueError(f"OrcaFlex prehistory requires constant first endpoint velocity for {endpoint}.")
        first_position = _orcaflex_snapshot_position(getattr(first, f"{endpoint}_position_m"))
        second_position = _orcaflex_snapshot_position(getattr(second, f"{endpoint}_position_m"))
        expected_second_position = _add(first_position, _scale_vector(first_velocity, interval_s))
        if not _vectors_close(second_position, expected_second_position):
            raise ValueError(f"OrcaFlex prehistory requires first endpoint velocity to match the recorded {endpoint} position increment.")


def _vectors_close(left: tuple[float, float, float], right: tuple[float, float, float]) -> bool:
    return all(
        math.isclose(left[index], right[index], rel_tol=0.0, abs_tol=ORCAFLEX_PREHISTORY_KINEMATIC_TOLERANCE)
        for index in range(3)
    )


def _scale_vector(vector: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _subtract(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _constraint_history_rows(
    dynamic_input: OrcaFlexDynamicInput,
    *,
    endpoint: str,
) -> tuple[tuple[float, float, float, float, float, float, float], ...]:
    if endpoint == "plough":
        displacements_m = dynamic_input.plough_displacements_m
    elif endpoint == "fairlead":
        displacements_m = dynamic_input.fairlead_displacements_m
    else:
        raise ValueError(f"Unsupported OrcaFlex constraint endpoint: {endpoint}")
    return tuple(
        (time_s, displacement[0], displacement[1], displacement[2], 0.0, 0.0, 0.0)
        for time_s, displacement in zip(dynamic_input.times_s, displacements_m)
    )


def _net_suspended_length_history_rows(
    dynamic_input: OrcaFlexDynamicInput,
) -> tuple[tuple[float, float], ...]:
    """Return the net-length audit history; the model uses both endpoint rates."""

    return tuple(zip(dynamic_input.times_s, dynamic_input.suspended_length_rates_mps))


def _endpoint_material_rate_history_rows(
    dynamic_input: OrcaFlexDynamicInput,
    *,
    endpoint: str,
) -> tuple[tuple[float, float], ...]:
    if endpoint == "fairlead":
        rates = dynamic_input.fairlead_payout_rates_mps
        sign = 1.0
    elif endpoint == "plough":
        rates = dynamic_input.plough_exit_rates_mps
        sign = -1.0
    else:
        raise ValueError(f"unsupported material-rate endpoint: {endpoint}")
    if len(rates) != len(dynamic_input.times_s):
        raise ValueError(f"{endpoint} material-rate history must match dynamic times")
    return tuple((time_s, sign * rate) for time_s, rate in zip(dynamic_input.times_s, rates))


def _full_line_length_for_orcaflex_feeding(
    dynamic_input: OrcaFlexDynamicInput,
    *,
    element_count: int,
) -> float:
    """Keep an inactive capacity reserve needed by OrcaFlex line feeding."""

    if element_count < 1:
        raise ValueError("OrcaFlex dynamic element count must be positive.")
    target_segment_length_m = dynamic_input.initial_active_length_m / float(element_count)
    inactive_reserve_m = max(
        ORCAFLEX_MINIMUM_INACTIVE_FEED_RESERVE_M,
        ORCAFLEX_SHORTEST_VIABLE_SEGMENT_FACTOR * target_segment_length_m,
    )
    fairlead_rates = dynamic_input.fairlead_payout_rates_mps
    if len(fairlead_rates) != len(dynamic_input.times_s):
        raise ValueError("fairlead payout-rate history must match dynamic times")
    cumulative_feed_m = 0.0
    maximum_feed_m = 0.0
    for index in range(len(dynamic_input.times_s) - 1):
        dt_s = dynamic_input.times_s[index + 1] - dynamic_input.times_s[index]
        cumulative_feed_m += 0.5 * (fairlead_rates[index] + fairlead_rates[index + 1]) * dt_s
        maximum_feed_m = max(maximum_feed_m, cumulative_feed_m)
    return max(
        dynamic_input.full_line_length_m,
        dynamic_input.initial_active_length_m + maximum_feed_m,
    ) + inactive_reserve_m


def run_validation(
    output_dir: Path | str,
    *,
    case_name: str = "plough_straight_baseline_6min",
    points: int = 7,
    create_model: bool = True,
) -> dict[str, str]:
    """Run the project-side OrcaFlex validation probe and write artifacts."""

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    snapshot = _build_project_snapshot(case_name, points=points)
    probe = _probe_orcaflex_api(create_model=create_model, runtime_root=output_root / "_orcfxapi_runtime")

    mapping_csv = output_root / f"{case_name}_orcaflex_input_mapping.csv"
    endpoint_history_csv = output_root / f"{case_name}_orcaflex_endpoint_history.csv"
    probe_csv = output_root / f"{case_name}_orcaflex_probe.csv"
    probe_json = output_root / f"{case_name}_orcaflex_probe.json"
    report_md = output_root / f"{case_name}_orcaflex_validation_report.md"

    mapping_rows = _build_orcaflex_input_mapping_rows(snapshot, probe)
    _write_mapping_csv(mapping_rows, mapping_csv)
    _write_endpoint_history_csv(snapshot, endpoint_history_csv)
    _write_probe_csv(probe, probe_csv)
    _write_probe_json(probe, probe_json)
    _write_report(
        snapshot,
        probe,
        mapping_csv=mapping_csv,
        endpoint_history_csv=endpoint_history_csv,
        probe_csv=probe_csv,
        report_md=report_md,
    )

    return {
        "status": probe.status,
        "mapping_csv": str(mapping_csv),
        "endpoint_history_csv": str(endpoint_history_csv),
        "probe_csv": str(probe_csv),
        "probe_json": str(probe_json),
        "report_md": str(report_md),
    }


def run_dynamic_validation(
    output_dir: Path | str,
    *,
    case_name: str = ORCAFLEX_DYNAMIC_BASELINE_CASE,
    points: int = 361,
    run_model: bool = False,
    physical_output_window_s: float | None = None,
    prehistory_duration_s: float = 0.0,
    element_count: int = 24,
    time_step_s: float = ORCAFLEX_DYNAMIC_TIME_STEP_S,
    initial_active_length_m: float | None = None,
    current_speed_mps: float | None = None,
    current_direction_deg: float | None = None,
    plough_depth_m: float | None = None,
) -> dict[str, str]:
    """Write same-input dynamic artifacts and optionally run the OrcaFlex model."""

    element_count, time_step_s = _validate_dynamic_discretisation(
        element_count=element_count,
        time_step_s=time_step_s,
    )
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    project_case = get_time_history_case(case_name)
    project_overrides: dict[str, object] = {"element_count": element_count}
    if initial_active_length_m is not None:
        if not math.isfinite(initial_active_length_m) or initial_active_length_m <= 0.0:
            raise ValueError("initial_active_length_m must be a positive finite number.")
        project_overrides["initial_suspended_length_m"] = float(initial_active_length_m)
    if current_speed_mps is not None:
        if not math.isfinite(current_speed_mps) or current_speed_mps < 0.0:
            raise ValueError("current_speed_mps must be finite and non-negative.")
        project_overrides["current_speed_mps"] = float(current_speed_mps)
    if current_direction_deg is not None:
        if not math.isfinite(current_direction_deg):
            raise ValueError("current_direction_deg must be finite.")
        project_overrides["current_direction_deg"] = float(current_direction_deg)
    if plough_depth_m is not None:
        if (
            not math.isfinite(plough_depth_m)
            or plough_depth_m <= 0.0
            or plough_depth_m > project_case.water_depth_m
        ):
            raise ValueError("plough_depth_m must be finite and within (0, water_depth_m].")
        project_overrides["plough_initial_z_m"] = float(plough_depth_m)
    project_case = replace(project_case, **project_overrides)
    if prehistory_duration_s > 0.0:
        if physical_output_window_s is None:
            raise ValueError("project/OrcaFlex prehistory comparison requires physical_output_window_s")
        project_case = _build_project_prehistory_case(
            project_case,
            prehistory_duration_s=prehistory_duration_s,
            physical_output_window_s=physical_output_window_s,
        )
    elif physical_output_window_s is not None:
        project_case = replace(
            project_case,
            total_duration_s=float(physical_output_window_s),
            duration_s=min(float(project_case.duration_s), float(physical_output_window_s)),
        )
    snapshot = _build_project_snapshot(
        case_name,
        points=points,
        dynamic_case_override=project_case,
    )
    endpoint_drive_samples = snapshot.endpoint_drive_samples
    if prehistory_duration_s > 0.0:
        endpoint_drive_samples = _rebase_endpoint_drive_samples(
            endpoint_drive_samples,
            physical_time_offset_s=prehistory_duration_s,
        )
    if physical_output_window_s is not None:
        endpoint_drive_samples = _slice_endpoint_drive_samples(
            endpoint_drive_samples,
            physical_output_window_s=physical_output_window_s,
        )
    dynamic_input = _build_orcaflex_prehistory_input(
        endpoint_drive_samples,
        prehistory_duration_s=prehistory_duration_s,
    )

    dynamic_input_csv = output_root / f"{case_name}_orcaflex_dynamic_input.csv"
    fairlead_motion_file = output_root / f"{case_name}_orcaflex_fairlead_motion.txt"
    plough_motion_file = output_root / f"{case_name}_orcaflex_plough_motion.txt"
    net_suspended_length_history_csv = output_root / f"{case_name}_orcaflex_net_suspended_length_history.csv"
    dynamic_report_md = output_root / f"{case_name}_orcaflex_dynamic_report.md"

    _write_dynamic_input_csv(dynamic_input, dynamic_input_csv)
    _write_constraint_time_history(
        _constraint_history_rows(dynamic_input, endpoint="fairlead"),
        fairlead_motion_file,
    )
    _write_constraint_time_history(
        _constraint_history_rows(dynamic_input, endpoint="plough"),
        plough_motion_file,
    )
    _write_net_suspended_length_history_csv(
        _net_suspended_length_history_rows(dynamic_input),
        net_suspended_length_history_csv,
    )

    report: dict[str, str] = {
        "status": "input_written",
        "model_build_status": "not_run",
        "statics_status": "not_run",
        "dynamic_status": "not_run",
        "extraction_status": "not_run",
        "dynamic_input_csv": str(dynamic_input_csv),
        "fairlead_motion_file": str(fairlead_motion_file),
        "plough_motion_file": str(plough_motion_file),
        "net_suspended_length_history_csv": str(net_suspended_length_history_csv),
        "dynamic_report_md": str(dynamic_report_md),
        "requested_physical_output_end_time_s": _csv_number(
            _physical_output_times(dynamic_input)[-1]
        ),
        "element_count": str(element_count),
        "implicit_time_step_s": _csv_number(time_step_s),
        "project_initial_active_length_m": _csv_number(project_case.initial_suspended_length_m),
        "project_plough_depth_m": _csv_number(project_case.plough_initial_z_m),
    }
    if physical_output_window_s is not None:
        report["requested_physical_output_window_s"] = _csv_number(physical_output_window_s)
    if prehistory_duration_s > 0.0:
        report["prehistory_duration_s"] = _csv_number(prehistory_duration_s)

    if run_model:
        runtime_input_root = Path(tempfile.gettempdir()) / "orcaflex_dynamic_validation" / case_name
        if not str(runtime_input_root).isascii():
            raise RuntimeError("OrcaFlex dynamic runtime input directory must be ASCII-only.")
        runtime_fairlead_motion_file = _copy_orcaflex_runtime_history(
            fairlead_motion_file,
            runtime_input_root,
            runtime_filename="fairlead_motion.txt",
        )
        runtime_plough_motion_file = _copy_orcaflex_runtime_history(
            plough_motion_file,
            runtime_input_root,
            runtime_filename="plough_motion.txt",
        )
        report["runtime_fairlead_motion_file"] = str(runtime_fairlead_motion_file)
        report["runtime_plough_motion_file"] = str(runtime_plough_motion_file)
        probe = _probe_orcaflex_api(create_model=True, runtime_root=output_root / "_orcfxapi_runtime")
        report["probe_status"] = probe.status
        report["probe_notes"] = probe.notes
        if probe.status != "model_created":
            report["status"] = probe.status
        else:
            model_dat = output_root / f"{case_name}_orcaflex_dynamic.dat"
            model_sim = output_root / f"{case_name}_orcaflex_dynamic.sim"
            endpoint_tension_csv = output_root / f"{case_name}_orcaflex_endpoint_tension.csv"
            distribution_csv = output_root / f"{case_name}_orcaflex_distribution.csv"
            try:
                import OrcFxAPI  # type: ignore[import-not-found]

                model, line = _build_orcaflex_dynamic_model(
                    OrcFxAPI,
                    snapshot=snapshot,
                    dynamic_input=dynamic_input,
                    fairlead_motion_file=runtime_fairlead_motion_file,
                    plough_motion_file=runtime_plough_motion_file,
                    element_count=element_count,
                    time_step_s=time_step_s,
                )
                report["model_build_status"] = "completed"
                report["model_full_line_length_m"] = _csv_number(float(line.Length[0]))
                report["line_feeding_reserve_m"] = _csv_number(
                    float(line.Length[0]) - dynamic_input.full_line_length_m
                )
            except Exception as exc:  # pragma: no cover - depends on local OrcaFlex runtime
                _record_dynamic_stage_failure(report, "model_build", exc)
            else:
                try:
                    model.CalculateStatics()
                    report["statics_engine_state"] = str(model.state)
                    if report["statics_engine_state"] != "InStaticState":
                        raise RuntimeError(
                            "OrcaFlex did not reach InStaticState after CalculateStatics: "
                            f"{report['statics_engine_state']}"
                        )
                    _save_orcaflex_text_data(model, OrcFxAPI, model_dat)
                    report["model_dat"] = str(model_dat)
                    report["statics_status"] = "completed"
                except Exception as exc:  # pragma: no cover - depends on local OrcaFlex runtime
                    _record_dynamic_stage_failure(report, "statics", exc)
                else:
                    try:
                        model.RunSimulation()
                        report["dynamic_engine_state"] = str(model.state)
                        if report["dynamic_engine_state"] != "SimulationStopped":
                            raise RuntimeError(
                                "OrcaFlex dynamic simulation did not complete normally: "
                                f"{report['dynamic_engine_state']}"
                            )
                        model.SaveSimulation(str(model_sim))
                        report["model_sim"] = str(model_sim)
                        report["dynamic_status"] = "completed"
                    except Exception as exc:  # pragma: no cover - depends on local OrcaFlex runtime
                        report["dynamic_engine_state"] = str(model.state)
                        try:
                            report["dynamic_failure_time_s"] = _csv_number(
                                float(model.simulationTimeStatus.CurrentTime)
                            )
                            failed_model_sim = output_root / f"{case_name}_orcaflex_dynamic_failed.sim"
                            model.SaveSimulation(str(failed_model_sim))
                            report["failed_model_sim"] = str(failed_model_sim)
                        except Exception as capture_exc:
                            report["failure_capture_error"] = f"{type(capture_exc).__name__}: {capture_exc}"
                        _record_dynamic_stage_failure(report, "dynamic", exc)
                    else:
                        try:
                            endpoint_rows, distribution_rows = _extract_orcaflex_dynamic_results(
                                OrcFxAPI,
                                line=line,
                                dynamic_input=dynamic_input,
                                project_samples=endpoint_drive_samples,
                            )
                            _write_orcaflex_endpoint_tension_csv(endpoint_rows, endpoint_tension_csv)
                            _write_orcaflex_distribution_csv(distribution_rows, distribution_csv)
                            _record_dynamic_result_audit(report, endpoint_rows, distribution_rows)
                            report.update(_logged_endpoint_tension_diagnostics(
                                OrcFxAPI,
                                line=line,
                                dynamic_input=dynamic_input,
                            ))
                            report["max_endpoint_position_error_m"] = _csv_number(
                                max(
                                    *(float(row["plough_position_error_m"]) for row in endpoint_rows),
                                    *(float(row["fairlead_position_error_m"]) for row in endpoint_rows),
                                )
                            )
                            report["endpoint_tension_csv"] = str(endpoint_tension_csv)
                            report["distribution_csv"] = str(distribution_csv)
                            report["extraction_status"] = "completed"
                            report["status"] = "dynamic_completed"
                        except Exception as exc:  # pragma: no cover - depends on local OrcaFlex runtime
                            _record_dynamic_stage_failure(report, "extraction", exc)

    _write_dynamic_report(snapshot, dynamic_input, report, dynamic_report_md)
    return report


def _validate_dynamic_discretisation(*, element_count: int, time_step_s: float) -> tuple[int, float]:
    if isinstance(element_count, bool) or not isinstance(element_count, int) or element_count < 1:
        raise ValueError("element_count must be a positive integer.")
    resolved_time_step_s = float(time_step_s)
    if not math.isfinite(resolved_time_step_s) or resolved_time_step_s <= 0.0:
        raise ValueError("time_step_s must be a finite positive value in seconds.")
    return element_count, resolved_time_step_s


def _write_dynamic_input_csv(dynamic_input: OrcaFlexDynamicInput, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORCAFLEX_DYNAMIC_INPUT_FIELDS)
        writer.writeheader()
        for index, time_s in enumerate(dynamic_input.times_s):
            fairlead = dynamic_input.fairlead_displacements_m[index]
            plough = dynamic_input.plough_displacements_m[index]
            writer.writerow(
                {
                    "time_s": _csv_number(time_s),
                    "physical_time_s": _csv_number(time_s - dynamic_input.physical_time_offset_s),
                    "fairlead_dx_m": _csv_number(fairlead[0]),
                    "fairlead_dy_m": _csv_number(fairlead[1]),
                    "fairlead_dz_m": _csv_number(fairlead[2]),
                    "plough_dx_m": _csv_number(plough[0]),
                    "plough_dy_m": _csv_number(plough[1]),
                    "plough_dz_m": _csv_number(plough[2]),
                    "suspended_length_rate_mps": _csv_number(dynamic_input.suspended_length_rates_mps[index]),
                    "fairlead_payout_rate_mps": _csv_number(dynamic_input.fairlead_payout_rates_mps[index]),
                    "plough_exit_rate_mps": _csv_number(dynamic_input.plough_exit_rates_mps[index]),
                    "active_length_m": _csv_number(dynamic_input.active_lengths_m[index]),
                }
            )


def _write_constraint_time_history(
    rows: Sequence[tuple[float, float, float, float, float, float, float]],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_up = (-ORCAFLEX_BUILD_UP_DURATION_S, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    with path.open("w", encoding="ascii", newline="\n") as handle:
        for row in (build_up, *rows):
            handle.write("\t".join(_csv_number(value) for value in row) + "\n")


def _write_net_suspended_length_history_csv(rows: Sequence[tuple[float, float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("time_s", "suspended_length_rate_mps"))
        for time_s, payout_rate_mps in rows:
            writer.writerow((_csv_number(time_s), _csv_number(payout_rate_mps)))


def _copy_orcaflex_runtime_history(
    source: Path,
    runtime_dir: Path,
    *,
    runtime_filename: str = "history.txt",
) -> Path:
    """Mirror external motion input at an ASCII-only path accepted by OrcaFlex 11.0."""

    runtime_dir.mkdir(parents=True, exist_ok=True)
    destination = runtime_dir / runtime_filename
    if not str(destination).isascii():
        raise ValueError("OrcaFlex dynamic runtime history path must be ASCII-only.")
    shutil.copy2(source, destination)
    return destination


def _write_dynamic_report(
    snapshot: object,
    dynamic_input: OrcaFlexDynamicInput,
    report: dict[str, str],
    path: Path,
) -> None:
    physical_output_times = _physical_output_times(dynamic_input)
    element_count = report.get("element_count", "not_recorded")
    implicit_time_step_s = report.get("implicit_time_step_s", "not_recorded")
    project_submerged_weight_n_per_m = float(snapshot.submerged_weight_n_per_m)
    orcaflex_implied_submerged_weight_n_per_m = (
        float(snapshot.weight_air_n_per_m)
        - PROJECT_SEAWATER_DENSITY_KG_M3
        * PROJECT_GRAVITY_MPS2
        * math.pi
        * float(snapshot.diameter_m) ** 2
        / 4.0
    )
    submerged_weight_difference_n_per_m = (
        orcaflex_implied_submerged_weight_n_per_m - project_submerged_weight_n_per_m
    )
    lines = [
        "# OrcaFlex Dynamic Validation",
        "",
        f"- Case: `{snapshot.case_name}`.",
        f"- Status: `{report['status']}`.",
        "- End A is the plough-inlet constraint; End B is the fairlead constraint and the feeding end.",
        "- Constraint histories use z-up displacements relative to their first project frame.",
        f"- Physical output window: `{physical_output_times[0]:.12g}` to `{physical_output_times[-1]:.12g}` s.",
        f"- Initial active length: `{dynamic_input.initial_active_length_m:.12g}` m.",
        f"- Project plough depth: `{report.get('project_plough_depth_m', 'not_recorded')}` m.",
        f"- Maximum active length: `{dynamic_input.full_line_length_m:.12g}` m.",
        "- Snapshot endpoint coordinates are already OrcaFlex z-up coordinates: the import uses X=x, Y=y, Z=z directly and does not apply a second sign change.",
        "- `suspended_length_rate_mps` is the audit quantity dL_s/dt=q_f-q_p. OrcaFlex receives q_f separately as positive End B payout and q_p separately as negative End A haul-in.",
        "- The matched-speed baseline has q_f=q_p=0.8 m/s and dL_s/dt=0: active length remains constant while cable material moves from fairlead to plough through the active line.",
        "- This is a tension-only baseline with explicit EI=0 and GJ=0 plus CompressionIsLimited=Yes. It has no material bending or torsional stiffness; slackness/contact sensitivity requires a later model with real EI/GJ, never OrcaFlex defaults.",
        f"- Validation element count: `{element_count}`; OrcaFlex TargetSegmentLength is initial active length divided by this count.",
        f"- Implicit constant time step: `{implicit_time_step_s}` s.",
        f"- TargetLogSampleInterval: `{implicit_time_step_s}` s, explicitly kept equal to the implicit integration step. Time-alignment bound: `{implicit_time_step_s}` s. Spike logging remains a diagnostic limitation; no filtering, fitting, or backfill is applied.",
        "- No OrcaFlex result has been written into the project solver.",
        "",
        "## Files",
        "",
    ]
    for key in ("dynamic_input_csv", "fairlead_motion_file", "plough_motion_file", "net_suspended_length_history_csv"):
        lines.append(f"- `{key}`: `{Path(report[key]).name}`.")
    for key in ("model_dat", "model_sim", "failed_model_sim", "endpoint_tension_csv", "distribution_csv"):
        if key in report:
            lines.append(f"- `{key}`: `{Path(report[key]).name}`.")
    if "runtime_fairlead_motion_file" in report:
        lines.append("- OrcaFlex runtime motion files are byte-identical ASCII-path copies of the audit files.")
    if "prehistory_duration_s" in report:
        ramp_duration_s = min(
            ORCAFLEX_PREHISTORY_RAMP_DURATION_S,
            float(report["prehistory_duration_s"]),
        )
        lines.append(
            "- Prehistory dynamic interval: physical "
            f"`-{report['prehistory_duration_s']}` to `0` s maps to OrcaFlex model time "
            f"`0` to `{report['prehistory_duration_s']}` s; physical output remains `0..{_csv_number(physical_output_times[-1])}` s."
        )
        lines.append(
            f"- Prehistory start-up: the first `{_csv_number(ramp_duration_s)}` s use a quintic velocity ramp from rest; "
            "the remaining prehistory holds the measured constant endpoint speed. Material properties are unchanged."
        )
    for key, label in (
        ("model_build_status", "Model build"),
        ("statics_status", "Static calculation"),
        ("dynamic_status", "Dynamic calculation"),
        ("extraction_status", "Result extraction"),
    ):
        if key in report:
            lines.append(f"- {label} status: `{report[key]}`.")
    if "statics_engine_state" in report:
        lines.append(f"- OrcaFlex static engine state: `{report['statics_engine_state']}`.")
    if "dynamic_engine_state" in report:
        lines.append(f"- OrcaFlex dynamic engine state: `{report['dynamic_engine_state']}`.")
    if "line_feeding_reserve_m" in report:
        lines.append(
            "- Inactive line reserve for OrcaFlex feeding capacity: "
            f"`{report['line_feeding_reserve_m']}` m; it is excluded from active-line loads."
        )
    if "max_endpoint_position_error_m" in report:
        lines.append(
            "- Maximum prescribed-endpoint position error at extracted physical times: "
            f"`{report['max_endpoint_position_error_m']}` m."
        )
    if "requested_physical_output_end_time_s" in report:
        lines.append(
            "- Requested physical output end time: "
            f"`{report['requested_physical_output_end_time_s']}` s."
        )
    if "actual_output_end_time_s" in report:
        lines.append(f"- Actual extracted output end time: `{report['actual_output_end_time_s']}` s.")
    if "extracted_plough_z_m" in report:
        lines.append(f"- Plough endpoint Z: `{report['extracted_plough_z_m']}` m (seabed reference: `-80` m).")
    if "extracted_fairlead_z_m" in report:
        lines.append(f"- Fairlead endpoint Z: `{report['extracted_fairlead_z_m']}` m (water-surface reference: `0` m).")
    if "tensions_finite" in report:
        lines.append(f"- Tensions finite: `{report['tensions_finite']}`.")
    if "endpoint_tension_max_n" in report:
        lines.extend(
            (
                "- Endpoint-tension diagnostics cover unfiltered native log samples over the physical output window only:",
                f"  native log samples `{report.get('endpoint_tension_log_sample_count', 'not_available')}`; maximum `{report['endpoint_tension_max_n']}` N; median `{report['endpoint_tension_median_n']}` N; negative values `{report['endpoint_tension_negative_count']}`; maximum same-endpoint adjacent-output jump `{report['endpoint_tension_max_adjacent_jump_n']}` N.",
            )
        )
    if "dynamic_failure_time_s" in report:
        lines.append(f"- Dynamic failure time: `{report['dynamic_failure_time_s']}` s.")
    if "probe_status" in report:
        lines.append(f"- OrcaFlex probe status: `{report['probe_status']}`.")
    if "error_stage" in report:
        lines.append(f"- Failure stage: `{report['error_stage']}`.")
    if "error" in report:
        lines.append(f"- Error: `{report['error']}`.")
    if "failure_capture_error" in report:
        lines.append(f"- Failure capture error: `{report['failure_capture_error']}`.")
    lines.extend(
        (
            "",
            "## Material And Environment Audit",
            "",
            f"- OrcaFlex model units: `m, kg, N, s`; gravity: `{PROJECT_GRAVITY_MPS2:.12g} m/s^2`. Material inputs and extracted forces use this explicit project unit contract.",
            f"- Outer diameter OD: `{float(snapshot.diameter_m):.12g}` m. Source: project validation snapshot -> OrcaFlex line type outer diameter.",
            f"- Dry mass / unit weight: `{float(snapshot.weight_air_n_per_m) / PROJECT_GRAVITY_MPS2:.12g}` kg/m / `{float(snapshot.weight_air_n_per_m):.12g}` N/m. Source: project validation snapshot; mass is derived using project gravity.",
            f"- Project submerged unit weight: `{project_submerged_weight_n_per_m:.12g}` N/m. Source: project validation snapshot.",
            f"- OrcaFlex implied submerged unit weight: `{orcaflex_implied_submerged_weight_n_per_m:.12g}` N/m from OD, dry unit weight, seawater density, and project gravity. Difference (OrcaFlex implied - project): `{submerged_weight_difference_n_per_m:.12g}` N/m.",
            f"- Axial stiffness EA: `{float(snapshot.axial_stiffness_n):.12g}` N. Source: project validation snapshot -> OrcaFlex line type EA.",
            f"- Drag coefficients Cd (dimensionless): normal `{float(snapshot.normal_drag_coefficient):.12g}`, axial `{float(snapshot.tangential_drag_coefficient):.12g}`. Source: project validation snapshot.",
            "- hydrodynamic_constant is a derived quantity from weight, OD, and Cd; it is not an OrcaFlex independent material field.",
            "- CableParameters.total_length_m is spool/available cable length and must not replace this case's active suspended length.",
            "- Added mass: OrcaFlex uses normal `Ca=1` and axial `Ca=0`. The current project solver instead adds the unit-cylinder displaced-water mass to one scalar nodal mass in every coordinate, so the directional inertia models are not matched. Neither side uses a fitted coefficient.",
            f"- Seawater density: `{PROJECT_SEAWATER_DENSITY_KG_M3:.12g}` kg/m^3. Source: shared project validation constant.",
            f"- Water depth: `{float(snapshot.water_depth_m):.12g}` m. Source: project validation snapshot.",
            f"- Seabed normal/shear stiffness: `1e4 / 1e3` N/m. Source: explicit validation-model elastic-seabed settings; dimensionless friction coefficient `{PROJECT_SEABED_FRICTION_COEFFICIENT:.12g}` from the shared project validation constant.",
            "- EI/GJ: `0 / 0` N m^2. Source: explicit tension-only baseline assignment, not a verified real-material property. Real material EI/GJ remains unknown and is required before slackness/contact sensitivity validation.",
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record_dynamic_result_audit(
    report: dict[str, str],
    endpoint_rows: Sequence[dict[str, str]],
    distribution_rows: Sequence[dict[str, str]],
) -> None:
    if not endpoint_rows or not distribution_rows:
        raise RuntimeError("OrcaFlex dynamic extraction returned no endpoint or distribution rows.")
    tension_values = [
        float(row[field])
        for row in endpoint_rows
        for field in ("end_a_effective_tension_n", "end_b_effective_tension_n")
    ]
    tension_values.extend(float(row["effective_tension_n"]) for row in distribution_rows)
    if not all(math.isfinite(value) for value in tension_values):
        raise RuntimeError("OrcaFlex extraction contains non-finite effective tension values.")
    final_endpoint = endpoint_rows[-1]
    report["actual_output_end_time_s"] = _csv_number(float(final_endpoint["time_s"]))
    report["extracted_plough_z_m"] = _csv_number(float(final_endpoint["plough_actual_z_m"]))
    report["extracted_fairlead_z_m"] = _csv_number(float(final_endpoint["fairlead_actual_z_m"]))
    report["tensions_finite"] = "yes"


def _endpoint_tension_diagnostics(endpoint_rows: Sequence[dict[str, str]]) -> dict[str, str]:
    if not endpoint_rows:
        raise ValueError("Endpoint-tension diagnostics require at least one output row.")
    return _tension_diagnostics_from_series(
        [float(row["end_a_effective_tension_n"]) for row in endpoint_rows],
        [float(row["end_b_effective_tension_n"]) for row in endpoint_rows],
    )


def _logged_endpoint_tension_diagnostics(
    orcfxapi: object,
    *,
    line: object,
    dynamic_input: OrcaFlexDynamicInput,
) -> dict[str, str]:
    physical_times = _physical_output_times(dynamic_input)
    period = orcfxapi.SpecifiedPeriod(
        dynamic_input.physical_time_offset_s + physical_times[0],
        dynamic_input.physical_time_offset_s + physical_times[-1],
    )
    end_a = [float(value) for value in line.TimeHistory("Effective tension", period=period, objectExtra=orcfxapi.oeEndA)]
    end_b = [float(value) for value in line.TimeHistory("Effective tension", period=period, objectExtra=orcfxapi.oeEndB)]
    diagnostics = _tension_diagnostics_from_series(end_a, end_b)
    diagnostics["endpoint_tension_log_sample_count"] = str(len(end_a))
    return diagnostics


def _tension_diagnostics_from_series(end_a: Sequence[float], end_b: Sequence[float]) -> dict[str, str]:
    if not end_a or not end_b or len(end_a) != len(end_b):
        raise ValueError("Endpoint-tension diagnostics require equal non-empty End A/End B series.")
    values = [*end_a, *end_b]
    jumps = [
        abs(series[index] - series[index - 1])
        for series in (end_a, end_b)
        for index in range(1, len(series))
    ]
    return {
        "endpoint_tension_max_n": _csv_number(max(values)),
        "endpoint_tension_median_n": _csv_number(statistics.median(values)),
        "endpoint_tension_negative_count": str(sum(value < 0.0 for value in values)),
        "endpoint_tension_max_adjacent_jump_n": _csv_number(max(jumps, default=0.0)),
    }


def _record_dynamic_stage_failure(report: dict[str, str], stage: str, exc: Exception) -> None:
    if stage not in {"model_build", "statics", "dynamic", "extraction"}:
        raise ValueError(f"Unsupported OrcaFlex dynamic failure stage: {stage}")
    report["status"] = f"{stage}_failed"
    report[f"{stage}_status"] = "failed"
    report["error_stage"] = stage
    report["error"] = f"{type(exc).__name__}: {exc}"


def _build_orcaflex_dynamic_model(
    orcfxapi: object,
    *,
    snapshot: object,
    dynamic_input: OrcaFlexDynamicInput,
    fairlead_motion_file: Path,
    plough_motion_file: Path,
    element_count: int = 24,
    time_step_s: float = ORCAFLEX_DYNAMIC_TIME_STEP_S,
) -> tuple[object, object]:
    if dynamic_input.times_s[0] != 0.0:
        raise ValueError("OrcaFlex dynamic physical time history must start at 0 s.")
    element_count, time_step_s = _validate_dynamic_discretisation(
        element_count=element_count,
        time_step_s=time_step_s,
    )

    model = orcfxapi.Model()
    _configure_orcaflex_project_units(model)
    model.general.StageDuration = (ORCAFLEX_BUILD_UP_DURATION_S, dynamic_input.times_s[-1])
    model.general.ImplicitConstantTimeStep = time_step_s
    model.general.TargetLogSampleInterval = time_step_s

    environment = model.environment
    environment.Density = PROJECT_SEAWATER_DENSITY_KG_M3
    environment.WaterDepth = float(snapshot.water_depth_m)
    environment.WaveHeight = 0.0
    environment.SeabedModel = "Elastic"
    environment.SeabedNormalStiffness = 1.0e4
    environment.SeabedShearStiffness = 1.0e3
    environment.CurrentMethod = "Interpolated"
    environment.RefCurrentSpeed = float(snapshot.current_speed_mps)
    environment.RefCurrentDirection = float(snapshot.current_direction_deg)
    environment.CurrentDepth = (0.0, float(snapshot.water_depth_m))
    environment.CurrentFactor = (1.0, 1.0)
    environment.CurrentRotation = (0.0, 0.0)

    _create_orcaflex_imposed_constraint(
        model,
        orcfxapi,
        name="PloughDrive",
        initial_position_m=dynamic_input.plough_initial_position_m,
        motion_file=plough_motion_file,
    )
    _create_orcaflex_imposed_constraint(
        model,
        orcfxapi,
        name="FairleadDrive",
        initial_position_m=dynamic_input.fairlead_initial_position_m,
        motion_file=fairlead_motion_file,
    )

    line_type = model.CreateObject(orcfxapi.otLineType)
    _configure_orcaflex_project_cable_line_type(line_type, snapshot)

    fairlead_payout_source = model.CreateObject(orcfxapi.otPayoutRate)
    fairlead_payout_source.name = "FairleadPayoutRate"
    fairlead_payout_rows = (
        (-ORCAFLEX_BUILD_UP_DURATION_S, 0.0),
        *_endpoint_material_rate_history_rows(dynamic_input, endpoint="fairlead"),
    )
    fairlead_payout_source.SetDataRowCount("IndependentValue", len(fairlead_payout_rows))
    fairlead_payout_source.IndependentValue = tuple(row[0] for row in fairlead_payout_rows)
    fairlead_payout_source.DependentValue = tuple(row[1] for row in fairlead_payout_rows)

    plough_haul_in_source = model.CreateObject(orcfxapi.otPayoutRate)
    plough_haul_in_source.name = "PloughHaulInRate"
    plough_haul_in_rows = (
        (-ORCAFLEX_BUILD_UP_DURATION_S, 0.0),
        *_endpoint_material_rate_history_rows(dynamic_input, endpoint="plough"),
    )
    plough_haul_in_source.SetDataRowCount("IndependentValue", len(plough_haul_in_rows))
    plough_haul_in_source.IndependentValue = tuple(row[0] for row in plough_haul_in_rows)
    plough_haul_in_source.DependentValue = tuple(row[1] for row in plough_haul_in_rows)

    line = model.CreateObject(orcfxapi.otLine)
    line.name = "Cable"
    line.TopEnd = "End B"
    line.Connection = ("PloughDrive", "FairleadDrive")
    line.ConnectionX = (0.0, 0.0)
    line.ConnectionY = (0.0, 0.0)
    line.ConnectionZ = (0.0, 0.0)
    line.ConnectionInitialArclength = (0.0, dynamic_input.initial_active_length_m)
    line.ConnectionPayoutRate = ("PloughHaulInRate", "FairleadPayoutRate")
    line.LineType = ("ProjectCable",)
    line.Length = (
        _full_line_length_for_orcaflex_feeding(
            dynamic_input,
            element_count=element_count,
        ),
    )
    line.TargetSegmentLength = (dynamic_input.initial_active_length_m / float(element_count),)
    line.StaticsStep1 = "Catenary"
    line.StaticsStep2 = "Full statics"
    line.IncludeSeabedFrictionInStatics = "Yes"
    line.LayAzimuth = 0.0
    line.AsLaidTension = 0.0
    return model, line


def _configure_orcaflex_project_units(model: object) -> None:
    """Use the project's metre-kilogram-newton-second unit contract in OrcaFlex."""

    general = model.general
    general.UnitsSystem = "User"
    general.LengthUnits = "m"
    general.MassUnits = "kg"
    general.ForceUnits = "N"
    general.g = PROJECT_GRAVITY_MPS2


def _configure_orcaflex_project_cable_line_type(line_type: object, snapshot: object) -> None:
    """Apply the physical cable line type shared by the project and validation models."""

    line_type.name = "ProjectCable"
    line_type.OD = float(snapshot.diameter_m)
    line_type.ID = 0.0
    line_type.MassPerUnitLength = float(snapshot.weight_air_n_per_m) / PROJECT_GRAVITY_MPS2
    line_type.EA = float(snapshot.axial_stiffness_n)
    line_type.NormalDragCoefficient = float(snapshot.normal_drag_coefficient)
    line_type.AxialDragCoefficient = float(snapshot.tangential_drag_coefficient)
    line_type.NormalAddedMassCoefficient = ORCAFLEX_NORMAL_ADDED_MASS_COEFFICIENT
    line_type.AxialAddedMassCoefficient = ORCAFLEX_AXIAL_ADDED_MASS_COEFFICIENT
    line_type.EI = 0.0
    line_type.GJ = 0.0
    line_type.CompressionIsLimited = "Yes"
    line_type.SeabedNormalFrictionCoefficient = PROJECT_SEABED_FRICTION_COEFFICIENT
    line_type.SeabedAxialFrictionCoefficient = PROJECT_SEABED_FRICTION_COEFFICIENT


def _create_orcaflex_imposed_constraint(
    model: object,
    orcfxapi: object,
    *,
    name: str,
    initial_position_m: tuple[float, float, float],
    motion_file: Path,
) -> None:
    constraint = model.CreateObject(orcfxapi.otConstraint)
    constraint.name = name
    constraint.ConstraintType = "Imposed motion"
    constraint.InitialX = initial_position_m[0]
    constraint.InitialY = initial_position_m[1]
    constraint.InitialZ = initial_position_m[2]
    constraint.TimeHistoryDataSource = "External"
    constraint.TimeHistoryFileName = str(motion_file)
    constraint.TimeHistoryInterpolation = "Linear"
    constraint.TimeHistoryTimeOrigin = 0.0


def _save_orcaflex_text_data(model: object, orcfxapi: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(model.SaveDataMem(orcfxapi.DataFileType.Text)))


def _extract_orcaflex_dynamic_results(
    orcfxapi: object,
    *,
    line: object,
    dynamic_input: OrcaFlexDynamicInput,
    project_samples: Sequence[object] = (),
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    endpoint_rows: list[dict[str, str]] = []
    distribution_rows: list[dict[str, str]] = []
    for physical_time_s in _physical_output_times(dynamic_input):
        model_time_s = physical_time_s + dynamic_input.physical_time_offset_s
        index = _dynamic_input_time_index(dynamic_input, model_time_s)
        period = orcfxapi.SpecifiedPeriod(model_time_s, model_time_s)
        plough_expected = _add(dynamic_input.plough_initial_position_m, dynamic_input.plough_displacements_m[index])
        fairlead_expected = _add(dynamic_input.fairlead_initial_position_m, dynamic_input.fairlead_displacements_m[index])
        plough_actual = _line_endpoint_position(line, orcfxapi, period, orcfxapi.oeEndA)
        fairlead_actual = _line_endpoint_position(line, orcfxapi, period, orcfxapi.oeEndB)
        project_sample = _sample_at_physical_time(project_samples, physical_time_s)
        endpoint_rows.append(
            {
                "time_s": _csv_number(physical_time_s),
                "plough_expected_x_m": _csv_number(plough_expected[0]),
                "plough_expected_y_m": _csv_number(plough_expected[1]),
                "plough_expected_z_m": _csv_number(plough_expected[2]),
                "plough_actual_x_m": _csv_number(plough_actual[0]),
                "plough_actual_y_m": _csv_number(plough_actual[1]),
                "plough_actual_z_m": _csv_number(plough_actual[2]),
                "plough_position_error_m": _csv_number(_position_error_m(plough_expected, plough_actual)),
                "fairlead_expected_x_m": _csv_number(fairlead_expected[0]),
                "fairlead_expected_y_m": _csv_number(fairlead_expected[1]),
                "fairlead_expected_z_m": _csv_number(fairlead_expected[2]),
                "fairlead_actual_x_m": _csv_number(fairlead_actual[0]),
                "fairlead_actual_y_m": _csv_number(fairlead_actual[1]),
                "fairlead_actual_z_m": _csv_number(fairlead_actual[2]),
                "fairlead_position_error_m": _csv_number(_position_error_m(fairlead_expected, fairlead_actual)),
                "end_a_effective_tension_n": _csv_number(_line_result(line, "Effective tension", period, orcfxapi.oeEndA)),
                "end_b_effective_tension_n": _csv_number(_line_result(line, "Effective tension", period, orcfxapi.oeEndB)),
                "active_length_m": _csv_number(dynamic_input.active_lengths_m[index]),
                "project_tdp_arc_length_m": _csv_number(
                    getattr(project_sample, "project_tdp_arc_length_m", None)
                ),
                "project_free_span_material_length_m": _csv_number(
                    getattr(project_sample, "project_free_span_material_length_m", None)
                ),
                "project_seabed_contact_length_m": _csv_number(
                    getattr(project_sample, "project_seabed_contact_length_m", None)
                ),
                "project_tdp_tension_n": _csv_number(
                    getattr(project_sample, "project_tdp_tension_n", None)
                ),
                "project_seabed_normal_reaction_n": _csv_number(
                    getattr(project_sample, "project_seabed_normal_reaction_n", None)
                ),
                "project_fairlead_tension_n": _csv_number(
                    getattr(project_sample, "project_fairlead_tension_n", None)
                ),
                "project_plough_boundary_tension_n": _csv_number(
                    getattr(project_sample, "project_plough_boundary_tension_n", None)
                ),
                "project_plough_adjacent_tension_n": _csv_number(
                    getattr(project_sample, "project_plough_adjacent_tension_n", None)
                ),
            }
        )

        tension_graph = line.RangeGraph("Effective tension", period=period)
        seabed_graph = line.RangeGraph("Seabed normal resistance", period=period)
        x_graph = line.RangeGraph("X", period=period)
        y_graph = line.RangeGraph("Y", period=period)
        z_graph = line.RangeGraph("Z", period=period)
        frame_distribution_rows = _distribution_rows_from_range_graphs(
            time_s=physical_time_s,
            active_length_m=dynamic_input.active_lengths_m[index],
            tension_graph=tension_graph,
            seabed_graph=seabed_graph,
            x_graph=x_graph,
            y_graph=y_graph,
            z_graph=z_graph,
        )
        endpoint_rows[-1].update(
            _contact_metrics_from_range_graphs(
                tension_graph=tension_graph,
                seabed_graph=seabed_graph,
                active_length_m=dynamic_input.active_lengths_m[index],
            )
        )
        distribution_rows.extend(frame_distribution_rows)
    return endpoint_rows, distribution_rows


def _sample_at_physical_time(samples: Sequence[object], time_s: float) -> object | None:
    for sample in samples:
        if math.isclose(float(getattr(sample, "time_s")), time_s, rel_tol=0.0, abs_tol=1.0e-9):
            return sample
    return None


def _rebase_endpoint_drive_samples(
    samples: Sequence[object],
    *,
    physical_time_offset_s: float,
) -> tuple[object, ...]:
    """Keep the physical comparison window and reset its first time to zero."""

    if physical_time_offset_s < 0.0 or not math.isfinite(physical_time_offset_s):
        raise ValueError("physical_time_offset_s must be finite and non-negative")
    rebased = tuple(
        replace(sample, time_s=float(sample.time_s) - physical_time_offset_s)
        for sample in samples
        if float(sample.time_s) >= physical_time_offset_s - 1.0e-9
    )
    if not rebased:
        raise ValueError("project endpoint history contains no physical-window samples")
    if not math.isclose(float(rebased[0].time_s), 0.0, rel_tol=0.0, abs_tol=1.0e-9):
        raise ValueError("project endpoint history does not contain the exact physical-window start")
    return rebased


def _physical_output_times(dynamic_input: OrcaFlexDynamicInput) -> tuple[float, ...]:
    return dynamic_input.physical_output_times_s or dynamic_input.times_s


def _dynamic_input_time_index(dynamic_input: OrcaFlexDynamicInput, model_time_s: float) -> int:
    for index, time_s in enumerate(dynamic_input.times_s):
        if math.isclose(time_s, model_time_s, rel_tol=0.0, abs_tol=1.0e-9):
            return index
    raise ValueError(f"OrcaFlex dynamic input has no model-history row for {model_time_s:.12g} s.")


def _distribution_rows_from_range_graphs(
    *,
    time_s: float,
    active_length_m: float,
    tension_graph: object,
    seabed_graph: object,
    x_graph: object,
    y_graph: object,
    z_graph: object,
) -> list[dict[str, str]]:
    """Sample all result fields on the complete effective-tension arc-length grid."""

    tension_x, tensions = _range_graph_samples(tension_graph, field_name="effective tension")
    if not tension_x:
        raise ValueError("OrcaFlex effective-tension range graph contains no samples.")
    graph_start = tension_x[0]
    graph_length = max(tension_x[-1] - graph_start, 1.0e-12)
    rows: list[dict[str, str]] = []
    for arc_length_m, tension_n in zip(tension_x, tensions):
        seabed_normal = _interpolate_range_graph(
            seabed_graph,
            arc_length_m,
            field_name="seabed normal resistance",
            outside_value=0.0,
        )
        rows.append(
            {
                "time_s": _csv_number(time_s),
                "arc_length_m": _csv_number(arc_length_m),
                "normalized_active_arc": _csv_number((arc_length_m - graph_start) / graph_length),
                "x_m": _csv_number(_interpolate_range_graph(x_graph, arc_length_m, field_name="X")),
                "y_m": _csv_number(_interpolate_range_graph(y_graph, arc_length_m, field_name="Y")),
                "z_m": _csv_number(_interpolate_range_graph(z_graph, arc_length_m, field_name="Z")),
                "effective_tension_n": _csv_number(tension_n),
                "seabed_normal_resistance_n": _csv_number(seabed_normal),
                "in_seabed_contact": "true" if seabed_normal > 0.0 else "false",
                "active_length_m": _csv_number(active_length_m),
            }
        )
    return rows


def _contact_metrics_from_distribution_rows(
    rows: Sequence[dict[str, str]],
    *,
    active_length_m: float,
) -> dict[str, str]:
    """Integrate OrcaFlex contact results on its End-A material-arc grid."""

    if not rows:
        raise ValueError("OrcaFlex distribution rows are required for contact metrics.")
    arc = [float(row["arc_length_m"]) for row in rows]
    tension = [float(row["effective_tension_n"]) for row in rows]
    normal = [max(0.0, float(row["seabed_normal_resistance_n"])) for row in rows]
    if any(right <= left for left, right in zip(arc, arc[1:])):
        raise ValueError("OrcaFlex distribution arc lengths must be strictly increasing.")

    normal_resultant = sum(
        0.5 * (normal[index] + normal[index + 1]) * (arc[index + 1] - arc[index])
        for index in range(len(arc) - 1)
    )
    positive_indices = [index for index, value in enumerate(normal) if value > 0.0]
    if not positive_indices:
        return {
            "orcaflex_tdp_arc_length_m": _csv_number(max(0.0, active_length_m)),
            "orcaflex_seabed_contact_length_m": "0",
            "orcaflex_tdp_effective_tension_n": "",
            "orcaflex_seabed_normal_resultant_n": _csv_number(normal_resultant),
        }

    last_positive = positive_indices[-1]
    contact_end_arc = arc[last_positive]
    if last_positive + 1 < len(arc):
        contact_end_arc = arc[last_positive + 1]
    graph_start = arc[0]
    contact_length = max(0.0, min(active_length_m, contact_end_arc - graph_start))
    tdp_from_fairlead = max(0.0, active_length_m - contact_length)
    tdp_tension = _interpolate_scalar_samples(arc, tension, contact_end_arc)
    return {
        "orcaflex_tdp_arc_length_m": _csv_number(tdp_from_fairlead),
        "orcaflex_seabed_contact_length_m": _csv_number(contact_length),
        "orcaflex_tdp_effective_tension_n": _csv_number(tdp_tension),
        "orcaflex_seabed_normal_resultant_n": _csv_number(normal_resultant),
    }


def _contact_metrics_from_range_graphs(
    *,
    tension_graph: object,
    seabed_graph: object,
    active_length_m: float,
) -> dict[str, str]:
    """Use OrcaFlex's native seabed-result grid for contact reconstruction."""

    tension_arc, tension_values = _range_graph_samples(tension_graph, field_name="effective tension")
    seabed_arc, seabed_values = _range_graph_samples(
        seabed_graph,
        field_name="seabed normal resistance",
    )
    normal = [max(0.0, value) for value in seabed_values]
    normal_resultant = sum(
        0.5 * (normal[index] + normal[index + 1]) * (seabed_arc[index + 1] - seabed_arc[index])
        for index in range(len(seabed_arc) - 1)
    )
    positive_indices = [index for index, value in enumerate(normal) if value > 0.0]
    if not positive_indices:
        return {
            "orcaflex_tdp_arc_length_m": _csv_number(max(0.0, active_length_m)),
            "orcaflex_seabed_contact_length_m": "0",
            "orcaflex_tdp_effective_tension_n": "",
            "orcaflex_seabed_normal_resultant_n": _csv_number(normal_resultant),
        }

    last_positive = positive_indices[-1]
    contact_end_arc = seabed_arc[last_positive]
    if last_positive + 1 < len(seabed_arc):
        contact_end_arc = 0.5 * (contact_end_arc + seabed_arc[last_positive + 1])
    contact_length = max(0.0, min(active_length_m, contact_end_arc - seabed_arc[0]))
    return {
        "orcaflex_tdp_arc_length_m": _csv_number(max(0.0, active_length_m - contact_length)),
        "orcaflex_seabed_contact_length_m": _csv_number(contact_length),
        "orcaflex_tdp_effective_tension_n": _csv_number(
            _interpolate_scalar_samples(tension_arc, tension_values, contact_end_arc)
        ),
        "orcaflex_seabed_normal_resultant_n": _csv_number(normal_resultant),
    }


def _interpolate_scalar_samples(xs: Sequence[float], ys: Sequence[float], target: float) -> float:
    if len(xs) != len(ys) or not xs:
        raise ValueError("sample coordinates and values must have the same non-zero length")
    if target <= xs[0]:
        return float(ys[0])
    if target >= xs[-1]:
        return float(ys[-1])
    for index in range(len(xs) - 1):
        if target > xs[index + 1]:
            continue
        fraction = (target - xs[index]) / (xs[index + 1] - xs[index])
        return float(ys[index] + fraction * (ys[index + 1] - ys[index]))
    return float(ys[-1])


def _interpolate_range_graph(
    graph: object,
    arc_length_m: float,
    *,
    field_name: str,
    outside_value: float | None = None,
) -> float:
    samples_x, samples_y = _range_graph_samples(graph, field_name=field_name)
    target = float(arc_length_m)
    if target < samples_x[0] or target > samples_x[-1]:
        if outside_value is not None:
            return float(outside_value)
        raise ValueError(
            f"OrcaFlex {field_name} range graph does not cover effective-tension arc length {target:.12g} m."
        )
    for index, sample_x in enumerate(samples_x):
        if target == sample_x:
            return samples_y[index]
        if target < sample_x:
            left_x = samples_x[index - 1]
            left_y = samples_y[index - 1]
            fraction = (target - left_x) / (sample_x - left_x)
            return left_y + fraction * (samples_y[index] - left_y)
    return samples_y[-1]


def _range_graph_samples(graph: object, *, field_name: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    samples_x = tuple(float(value) for value in graph.X)
    samples_y = tuple(float(value) for value in graph.Mean)
    if len(samples_x) != len(samples_y) or not samples_x:
        raise ValueError(f"OrcaFlex {field_name} range graph has inconsistent samples.")
    if any(later <= earlier for earlier, later in zip(samples_x, samples_x[1:])):
        raise ValueError(f"OrcaFlex {field_name} range graph arc lengths must be strictly increasing.")
    return samples_x, samples_y


def _line_endpoint_position(
    line: object,
    orcfxapi: object,
    period: object,
    object_extra: object,
) -> tuple[float, float, float]:
    return (
        _line_result(line, "X", period, object_extra),
        _line_result(line, "Y", period, object_extra),
        _line_result(line, "Z", period, object_extra),
    )


def _line_result(line: object, variable_name: str, period: object, object_extra: object) -> float:
    values = line.TimeHistory(variable_name, period=period, objectExtra=object_extra)
    if len(values) != 1:
        raise ValueError(f"Expected one OrcaFlex result at the requested physical time for {variable_name}.")
    return float(values[0])


def _write_orcaflex_endpoint_tension_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORCAFLEX_ENDPOINT_TENSION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_orcaflex_distribution_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORCAFLEX_DISTRIBUTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _add(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _position_error_m(
    expected: tuple[float, float, float],
    actual: tuple[float, float, float],
) -> float:
    return math.sqrt(sum((actual[index] - expected[index]) ** 2 for index in range(3)))


def _probe_orcaflex_api(*, create_model: bool, runtime_root: Path | None = None) -> OrcaFlexProbe:
    """Import OrcFxAPI and optionally create an empty model handle."""

    _patch_orcfxapi_collections_compat()
    runtime_note = _prepare_orcaflex_runtime_override(runtime_root)
    # Record only configuration presence. License server values may contain
    # private hostnames or credentials and must not be written to reports.
    license_env = "; ".join(
        f"{name}=set"
        for name in ("LM_LICENSE_FILE", "ORCAFLEX_LICENSE_FILE", "ORCINA_LICENSE_FILE", "_OrcFxAPIlib")
        if os.environ.get(name)
    )
    flexnet_ini = Path(r"C:\ProgramData\Orcina\FlexNet.ini")
    try:
        import OrcFxAPI  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on local installation
        return OrcaFlexProbe(
            status="api_import_failed",
            import_status="failed",
            dll_version="",
            python_executable=sys.executable,
            python_version=sys.version.split()[0],
            module_path="",
            model_status="not_attempted",
            license_env=license_env,
            flexnet_ini_exists=flexnet_ini.exists(),
            notes=_join_notes(runtime_note, f"{type(exc).__name__}: {exc}"),
        )

    dll_version = _safe_dll_version(OrcFxAPI)
    module_path = str(getattr(OrcFxAPI, "__file__", ""))
    if not create_model:
        return OrcaFlexProbe(
            status="api_import_ok",
            import_status="ok",
            dll_version=dll_version,
            python_executable=sys.executable,
            python_version=sys.version.split()[0],
            module_path=module_path,
            model_status="not_attempted",
            license_env=license_env,
            flexnet_ini_exists=flexnet_ini.exists(),
            notes=_join_notes(runtime_note, "OrcFxAPI import succeeded; model creation was skipped."),
        )

    try:
        model = OrcFxAPI.Model()
    except Exception as exc:  # pragma: no cover - depends on local licence state
        notes = f"{type(exc).__name__}: {exc}"
        status = "license_unavailable" if _looks_like_license_error(notes) else "model_create_failed"
        return OrcaFlexProbe(
            status=status,
            import_status="ok",
            dll_version=dll_version,
            python_executable=sys.executable,
            python_version=sys.version.split()[0],
            module_path=module_path,
            model_status="failed",
            license_env=license_env,
            flexnet_ini_exists=flexnet_ini.exists(),
            notes=_join_notes(runtime_note, notes),
        )

    licence_note = _model_licence_note(model)
    return OrcaFlexProbe(
        status="model_created",
        import_status="ok",
        dll_version=dll_version,
        python_executable=sys.executable,
        python_version=sys.version.split()[0],
        module_path=module_path,
        model_status="created",
        license_env=license_env,
        flexnet_ini_exists=flexnet_ini.exists(),
        notes=_join_notes(runtime_note, "OrcFxAPI import and Model() creation succeeded.", licence_note),
    )


def _patch_orcfxapi_collections_compat() -> None:
    """Patch old OrcFxAPI.py imports on Python versions where aliases moved."""

    for name in ("MutableMapping", "Mapping", "Sequence"):
        if not hasattr(collections, name) and hasattr(collections.abc, name):
            setattr(collections, name, getattr(collections.abc, name))


def _prepare_orcaflex_runtime_override(runtime_root: Path | None = None) -> str:
    """Load OrcFxAPI from a validation-local copy that matches the GUI runtime."""

    if "OrcFxAPI" in sys.modules:
        return "OrcFxAPI was already imported; runtime override was not applied."
    try:
        import OrcFxAPIConfig  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on local installation
        return f"OrcFxAPIConfig import failed before runtime override: {type(exc).__name__}: {exc}"

    try:
        api_dll = Path(OrcFxAPIConfig.getLibPath())
    except Exception as exc:  # pragma: no cover - depends on local installation
        return f"OrcFxAPI runtime path unavailable: {type(exc).__name__}: {exc}"

    api_win_dir = api_dll.parent
    install_root = _installed_orcaflex_root(api_dll)
    gui_lib_dir = install_root / "lib64"
    api_lib_dir = api_win_dir / "lib64"
    gui_comptran = gui_lib_dir / "comptran.dll"
    api_comptran = api_lib_dir / "comptran.dll"
    if not gui_comptran.exists() or not api_comptran.exists():
        return "OrcFxAPI runtime override not applied; GUI/API comptran.dll comparison files were not both present."
    if _same_file_payload(gui_comptran, api_comptran):
        return "OrcFxAPI runtime override not needed; GUI/API comptran.dll files already match."

    root = Path(runtime_root) if runtime_root is not None else Path(tempfile.gettempdir()) / "orcfxapi_runtime"
    runtime_dir = root / "Win64"
    try:
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        shutil.copytree(api_win_dir, runtime_dir)
        runtime_lib_dir = runtime_dir / "lib64"
        for source in gui_lib_dir.iterdir():
            if source.is_file():
                shutil.copy2(source, runtime_lib_dir / source.name)
    except Exception as exc:  # pragma: no cover - filesystem/environment dependent
        return f"OrcFxAPI runtime override failed: {type(exc).__name__}: {exc}"

    os.environ["_OrcFxAPIlib"] = str(runtime_dir / "OrcFxAPI.dll")
    return (
        "OrcFxAPI runtime override applied: using a validation-local Win64 copy "
        f"at {runtime_dir}; GUI lib64 files from {gui_lib_dir} overlay the API lib64 copy."
    )


def _installed_orcaflex_root(api_dll: Path) -> Path:
    if api_dll.parent.name.lower() in {"win64", "win32"} and api_dll.parent.parent.name.lower() == "orcfxapi":
        return api_dll.parent.parent.parent
    return api_dll.parent.parent


def _same_file_payload(left: Path, right: Path) -> bool:
    try:
        return filecmp.cmp(left, right, shallow=False)
    except OSError:
        return False


def _safe_dll_version(orcfxapi: object) -> str:
    try:
        version = getattr(orcfxapi, "DLLVersion")()
    except Exception as exc:  # pragma: no cover - depends on local installation
        return f"unavailable: {type(exc).__name__}: {exc}"
    return str(version)


def _model_licence_note(model: object) -> str:
    status = getattr(model, "licenceStatus", "")
    location = getattr(model, "licenceFileLocation", "")
    parts = []
    if status:
        parts.append(f"licenceStatus={status}")
    if location:
        parts.append(f"licenceFileLocation={location}")
    return "; ".join(parts)


def _join_notes(*notes: str) -> str:
    return " | ".join(note for note in notes if note)


def _looks_like_license_error(message: str) -> bool:
    text = message.lower()
    return "licence" in text or "license" in text or "flexnet" in text or "hasp" in text


def _build_orcaflex_input_mapping_rows(snapshot: object, probe: OrcaFlexProbe) -> list[dict[str, str]]:
    current_x, current_y = _project_current_components(snapshot)
    mass_per_m = float(snapshot.weight_air_n_per_m) / PROJECT_GRAVITY_MPS2
    buoyancy_n_per_m = (
        PROJECT_SEAWATER_DENSITY_KG_M3
        * PROJECT_GRAVITY_MPS2
        * math.pi
        * float(snapshot.diameter_m) ** 2
        / 4.0
    )
    implied_submerged_weight = float(snapshot.weight_air_n_per_m) - buoyancy_n_per_m
    endpoint_seed = snapshot.endpoint_drive_samples[0] if snapshot.endpoint_drive_samples else None
    endpoint_last = snapshot.endpoint_drive_samples[-1] if snapshot.endpoint_drive_samples else None
    endpoint_window = (
        f"{endpoint_seed.time_s:.12g}..{endpoint_last.time_s:.12g} s"
        if endpoint_seed is not None and endpoint_last is not None
        else "no endpoint replay samples"
    )
    return [
        _mapping_row("environment", "OrcFxAPI probe status", probe.status, "OrcaFlex Python API", probe.status, probe.status),
        _mapping_row("identity", "case_name", snapshot.case_name, "model/file prefix", snapshot.case_name, "matched"),
        _mapping_row(
            "coordinates",
            "project solver frame -> validation snapshot",
            "x forward, y transverse, z down -> X, Y, Z (z up)",
            "OrcaFlex global axes",
            "X=x, Y=y, Z=z (snapshot passthrough)",
            "matched",
            "The project-to-snapshot conversion is performed once in validate_moordyn_moorpy; OrcaFlex uses that z-up snapshot without a second sign change.",
        ),
        _mapping_row(
            "geometry",
            "water_depth_m",
            snapshot.water_depth_m,
            "environment water depth / flat seabed",
            snapshot.water_depth_m,
            "matched",
        ),
        _mapping_row(
            "geometry",
            "final_frame_fairlead_position_m",
            _fmt3(snapshot.fairlead_position_m),
            "line end B / fairlead boundary",
            _fmt3(snapshot.fairlead_position_m),
            "matched",
        ),
        _mapping_row(
            "geometry",
            "final_frame_plough_position_m",
            _fmt3(snapshot.plough_position_m),
            "line end A / plough inlet boundary",
            _fmt3(snapshot.plough_position_m),
            "matched",
            "The plough is represented as a driven cable exit point.",
        ),
        _mapping_row(
            "boundary_motion",
            "endpoint_replay_time_window",
            endpoint_window,
            "driven fairlead/plough endpoint histories",
            endpoint_window,
            "matched" if endpoint_seed is not None else "not_available",
        ),
        _mapping_row(
            "boundary_motion",
            "endpoint_replay_initial_positions",
            (
                f"plough={_fmt3(endpoint_seed.plough_position_m)}; fairlead={_fmt3(endpoint_seed.fairlead_position_m)}"
                if endpoint_seed is not None
                else "no endpoint replay samples"
            ),
            "initial line end coordinates",
            (
                f"plough={_fmt3(endpoint_seed.plough_position_m)}; fairlead={_fmt3(endpoint_seed.fairlead_position_m)}"
                if endpoint_seed is not None
                else "none"
            ),
            "matched" if endpoint_seed is not None else "not_available",
        ),
        _mapping_row(
            "geometry",
            "initial/final suspended material length",
            f"{endpoint_seed.unstretched_length_m:.12g} / {snapshot.suspended_length_m:.12g}"
            if endpoint_seed is not None
            else f"final={snapshot.suspended_length_m:.12g}",
            "line unstretched length or winch/length time history",
            "endpoint history CSV unstretched_length_m",
            "matched" if endpoint_seed is not None else "not_available",
            "Later dynamic comparison must drive the same material length history, not silently re-initialize length.",
        ),
        _mapping_row(
            "material_transport_boundary",
            "q_f, q_p and dL_s/dt=q_f-q_p",
            (
                f"fairlead payout={getattr(endpoint_seed, 'fairlead_payout_speed_mps', None)} m/s; "
                f"plough exit={getattr(endpoint_seed, 'plough_exit_speed_mps', None)} m/s"
                if endpoint_seed is not None
                else "no endpoint material-rate samples"
            ),
            "OrcaFlex End B payout / End A haul-in",
            "positive fairlead payout and negative plough haul-in; net active length audited separately",
            "matched" if endpoint_seed is not None else "not_available",
            "Two-end line feeding transports material through the active line without using a fitted rate or a net-length proxy.",
        ),
        _mapping_row("geometry", "element_count", snapshot.element_count, "line sections / discretisation", snapshot.element_count, "matched"),
        _mapping_row("material", "diameter_m", snapshot.diameter_m, "line type outer diameter", snapshot.diameter_m, "matched"),
        _mapping_row("material", "weight_air_n_per_m", snapshot.weight_air_n_per_m, "line type mass per unit length", mass_per_m, "matched"),
        _mapping_row("material", "axial_stiffness_n", snapshot.axial_stiffness_n, "line type EA", snapshot.axial_stiffness_n, "matched"),
        _mapping_row(
            "material",
            "bending/torsional rigidity boundary",
            "no validated material EI/GJ supplied for this tension baseline",
            "line type EI / GJ",
            "0 / 0",
            "shared_model_assumption",
            "EI=GJ=0 is explicit: this is a tension-only baseline, not use of OrcaFlex default stiffness. Slackness/contact sensitivity requires real material EI/GJ in a later validation model.",
        ),
        _mapping_row(
            "material",
            "cable axial compression response",
            "cable carries tension only",
            "line type CompressionIsLimited",
            "Yes",
            "matched",
            "This is the unilateral axial behavior of a cable, not a calibration coefficient.",
        ),
        _mapping_row(
            "material",
            "submerged_weight_n_per_m",
            snapshot.submerged_weight_n_per_m,
            "mass, diameter, seawater density and gravity implied submerged weight",
            implied_submerged_weight,
            "matched",
        ),
        _mapping_row("hydrodynamics", "normal_drag_coefficient", snapshot.normal_drag_coefficient, "normal drag coefficient", snapshot.normal_drag_coefficient, "matched"),
        _mapping_row("hydrodynamics", "tangential_drag_coefficient", snapshot.tangential_drag_coefficient, "axial drag coefficient", snapshot.tangential_drag_coefficient, "matched"),
        _mapping_row(
            "hydrodynamics",
            "added-mass implementation",
            "unit-cylinder displaced-water mass added to one scalar nodal mass in x/y/z",
            "line type NormalAddedMassCoefficient / AxialAddedMassCoefficient",
            f"normal={ORCAFLEX_NORMAL_ADDED_MASS_COEFFICIENT:.12g} (both normal directions); axial={ORCAFLEX_AXIAL_ADDED_MASS_COEFFICIENT:.12g}",
            "model_gap_directional_mass",
            "The coefficient value Ca=1 is not fitted, but the project currently applies displaced-water mass isotropically; OrcaFlex applies Ca=1 only in the two normal directions and Ca=0 axially.",
        ),
        _mapping_row(
            "hydrodynamics",
            "current_speed_mps/current_direction_deg",
            f"{snapshot.current_speed_mps:.12g} m/s @ {snapshot.current_direction_deg:.12g} deg",
            "steady current vector/profile",
            f"{current_x:.12g}, {current_y:.12g}, 0",
            "matched",
            "Project convention is 0 deg +X and 90 deg +Y; OrcaFlex export uses the same horizontal components.",
        ),
        _mapping_row(
            "result_sampling",
            "same physical output time",
            "declared snapshot frame times",
            "TargetLogSampleInterval",
            f"{ORCAFLEX_DYNAMIC_LOG_INTERVAL_S:.12g} s",
            "limitation_recorded",
            "Spike logging can make tension samples at the same physical time non-comparable. This validation records the limitation and does not smooth, fit, or backfill results.",
        ),
        _mapping_row(
            "contact",
            "water_depth_m seabed plane",
            snapshot.water_depth_m,
            "flat seabed",
            snapshot.water_depth_m,
            "matched",
        ),
        _mapping_row(
            "contact",
            "seabed_friction_coefficient",
            PROJECT_SEABED_FRICTION_COEFFICIENT,
            "seabed friction coefficient",
            PROJECT_SEABED_FRICTION_COEFFICIENT,
            "shared_model_assumption",
            "Project contact projection and OrcaFlex contact are not numerically identical; contact-force comparison needs a separate sensitivity check.",
        ),
        _mapping_row(
            "out_of_scope",
            "plough body/soil/tooling",
            "not modeled by current shared comparison",
            "not modeled",
            "not modeled",
            "out_of_scope",
            "Current validation compares cable tension and endpoint reactions only.",
        ),
    ]


def _mapping_row(
    category: str,
    project_input: str,
    project_value: object,
    orcaflex_target: str,
    orcaflex_value: object,
    status: str,
    notes: str = "",
) -> dict[str, str]:
    return {
        "category": category,
        "project_input": project_input,
        "project_value": str(project_value),
        "orcaflex_target": orcaflex_target,
        "orcaflex_value": str(orcaflex_value),
        "status": status,
        "notes": notes,
    }


def _write_mapping_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORCAFLEX_INPUT_MAPPING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_endpoint_history_csv(snapshot: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORCAFLEX_ENDPOINT_HISTORY_FIELDS)
        writer.writeheader()
        for sample in snapshot.endpoint_drive_samples:
            writer.writerow(
                {
                    "time_s": _csv_number(sample.time_s),
                    "fairlead_x_m": _csv_number(sample.fairlead_position_m[0]),
                    "fairlead_y_m": _csv_number(sample.fairlead_position_m[1]),
                    "fairlead_z_m": _csv_number(sample.fairlead_position_m[2]),
                    "fairlead_vx_mps": _csv_number(sample.fairlead_velocity_mps[0]),
                    "fairlead_vy_mps": _csv_number(sample.fairlead_velocity_mps[1]),
                    "fairlead_vz_mps": _csv_number(sample.fairlead_velocity_mps[2]),
                    "plough_x_m": _csv_number(sample.plough_position_m[0]),
                    "plough_y_m": _csv_number(sample.plough_position_m[1]),
                    "plough_z_m": _csv_number(sample.plough_position_m[2]),
                    "plough_vx_mps": _csv_number(sample.plough_velocity_mps[0]),
                    "plough_vy_mps": _csv_number(sample.plough_velocity_mps[1]),
                    "plough_vz_mps": _csv_number(sample.plough_velocity_mps[2]),
                    "unstretched_length_m": _csv_number(sample.unstretched_length_m),
                    "unstretched_length_rate_mps": _csv_number(sample.unstretched_length_rate_mps),
                }
            )


def _write_probe_csv(probe: OrcaFlexProbe, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORCAFLEX_PROBE_FIELDS)
        writer.writeheader()
        for key, value in _probe_dict(probe).items():
            writer.writerow({"key": key, "value": str(value)})


def _write_probe_json(probe: OrcaFlexProbe, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_probe_dict(probe), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _probe_dict(probe: OrcaFlexProbe) -> dict[str, object]:
    return {
        "status": probe.status,
        "import_status": probe.import_status,
        "dll_version": probe.dll_version,
        "python_executable": probe.python_executable,
        "python_version": probe.python_version,
        "module_path": probe.module_path,
        "model_status": probe.model_status,
        "license_env": probe.license_env,
        "flexnet_ini_exists": probe.flexnet_ini_exists,
        "notes": probe.notes,
    }


def _write_report(
    snapshot: object,
    probe: OrcaFlexProbe,
    *,
    mapping_csv: Path,
    endpoint_history_csv: Path,
    probe_csv: Path,
    report_md: Path,
) -> None:
    lines = [
        "# OrcaFlex Validation Probe",
        "",
        f"- Case: `{snapshot.case_name}`.",
        f"- Probe status: `{probe.status}`.",
        f"- DLL version: `{probe.dll_version}`.",
        f"- Python: `{probe.python_executable}` (`{probe.python_version}`).",
        f"- FlexNet ini exists: `{probe.flexnet_ini_exists}`.",
        f"- Endpoint history CSV: `{endpoint_history_csv.name}`.",
        f"- Input mapping CSV: `{mapping_csv.name}`.",
        f"- Probe CSV: `{probe_csv.name}`.",
        "",
        "## Scope",
        "",
        "- This is a validation-layer OrcaFlex integration probe, not a production solver path.",
        "- Project coordinates are exported as OrcaFlex z-up coordinates: `X=x`, `Y=y`, `Z=-z`.",
        "- The plough is represented as a driven cable exit point; plough body, guide-slot friction, and soil reaction are out of scope for this comparison layer.",
        "- OrcaFlex results must not be written back into project solver outputs or used as correction factors.",
        "",
        "## Probe Notes",
        "",
        "```text",
        probe.notes.strip(),
        "```",
        "",
    ]
    report_md.write_text("\n".join(lines), encoding="utf-8")


def _csv_number(value: float | int | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.12g}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BACKEND_ROOT / "output" / "orcaflex_validation")
    parser.add_argument("--case")
    parser.add_argument("--points", type=int, default=7)
    parser.add_argument("--skip-model-create", action="store_true")
    parser.add_argument("--run-dynamic", action="store_true")
    parser.add_argument(
        "--element-count",
        type=int,
        default=24,
        help="Validation-only OrcaFlex cable element count; default preserves the 24-element baseline.",
    )
    parser.add_argument(
        "--time-step-s",
        type=float,
        default=ORCAFLEX_DYNAMIC_TIME_STEP_S,
        help="Validation-only implicit integration and log-sampling step in seconds; default 0.01.",
    )
    parser.add_argument(
        "--physical-output-window-s",
        type=float,
        help="Validation-only exact endpoint-history cutoff; does not interpolate or alter physical inputs.",
    )
    parser.add_argument(
        "--prehistory-duration-s",
        type=float,
        default=0.0,
        help="Optional balanced constant-speed dynamic prehistory; physical output remains 0..T.",
    )
    parser.add_argument(
        "--initial-active-length-m",
        type=float,
        help="Validation-only project and OrcaFlex initial unstretched active cable length.",
    )
    parser.add_argument("--current-speed-mps", type=float, help="Validation-only shared current speed.")
    parser.add_argument("--current-direction-deg", type=float, help="Validation-only shared current direction.")
    parser.add_argument("--plough-depth-m", type=float, help="Validation-only shared plough depth below surface.")
    parser.add_argument("--require-license", action="store_true")
    args = parser.parse_args(argv)

    if args.run_dynamic:
        case_name = args.case or ORCAFLEX_DYNAMIC_BASELINE_CASE
        report = run_dynamic_validation(
            args.output,
            case_name=case_name,
            points=args.points,
            run_model=True,
            physical_output_window_s=args.physical_output_window_s,
            prehistory_duration_s=args.prehistory_duration_s,
            element_count=args.element_count,
            time_step_s=args.time_step_s,
            initial_active_length_m=args.initial_active_length_m,
            current_speed_mps=args.current_speed_mps,
            current_direction_deg=args.current_direction_deg,
            plough_depth_m=args.plough_depth_m,
        )
        print(f"OrcaFlex dynamic status: {report['status']}")
        print(f"Dynamic input: {report['dynamic_input_csv']}")
        print(f"Fairlead motion: {report['fairlead_motion_file']}")
        print(f"Plough motion: {report['plough_motion_file']}")
        print(f"Net suspended-length history: {report['net_suspended_length_history_csv']}")
        print(f"Report: {report['dynamic_report_md']}")
        for key in ("model_dat", "model_sim", "endpoint_tension_csv", "distribution_csv"):
            if key in report:
                print(f"{key}: {report[key]}")
        if "error" in report:
            print(f"Error: {report['error']}")
        if args.require_license and report["status"] != "dynamic_completed":
            return 2
        return 0 if report["status"] == "dynamic_completed" else 1

    case_name = args.case or ORCAFLEX_STATIC_PROBE_CASE
    report = run_validation(
        args.output,
        case_name=case_name,
        points=args.points,
        create_model=not args.skip_model_create,
    )
    print(f"OrcaFlex status: {report['status']}")
    print(f"Probe: {report['probe_csv']}")
    print(f"Input mapping: {report['mapping_csv']}")
    print(f"Endpoint history: {report['endpoint_history_csv']}")
    print(f"Report: {report['report_md']}")
    if args.require_license and report["status"] != "model_created":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a MoorPy/MoorDyn validation comparison for known-plough cases.

This script is intentionally a validation-layer tool. It can backfill
MoorPy/MoorDyn reference values into diagnostic tables to locate model gaps,
but it never writes those values into the production solver outputs.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.machinery
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Sequence


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BACKEND_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
from cable_tension.dynamic_laying import (
    _initial_known_plough_state,
    _operation_case_at_time,
    _payout_speed,
    _plough_exit_material_speed,
    _plough_velocity,
    _step_dynamic_segment_tensions,
    _step_known_plough_dynamic,
    _time_history_step_limit_s,
    solve_dynamic_laying_time_history,
)


SUMMARY_FIELDS = (
    "model",
    "status",
    "fairlead_tension_n",
    "plough_tension_n",
    "fairlead_force_x_n",
    "fairlead_force_y_n",
    "fairlead_force_z_n",
    "plough_force_x_n",
    "plough_force_y_n",
    "plough_force_z_n",
    "moordyn_dt_s",
    "moordyn_duration_s",
    "moordyn_requested_duration_s",
    "moordyn_completed_duration_s",
    "moordyn_replay_coverage_percent",
    "moordyn_project_window_s",
    "moordyn_project_window_coverage_percent",
    "moordyn_last_history_time_s",
    "moordyn_ramp_duration_s",
    "moordyn_steps",
    "moordyn_init_code",
    "moordyn_init_mode",
    "moordyn_initial_fairlead_tension_n",
    "moordyn_peak_fairlead_tension_n",
    "moordyn_peak_plough_tension_n",
    "moordyn_peak_line_tension_n",
    "moordyn_peak_fairlead_time_s",
    "moordyn_peak_plough_time_s",
    "moordyn_peak_line_time_s",
    "moordyn_max_line_tension_n",
    "moordyn_history_csv",
    "moordyn_node_distribution_csv",
    "moordyn_node_count",
    "moordyn_seabed_contact_node_count",
    "moordyn_first_seabed_contact_node",
    "moordyn_last_seabed_contact_node",
    "moordyn_max_node_seabed_force_n",
    "moordyn_max_node_seabed_force_node",
    "notes",
)

MOORDYN_HISTORY_FIELDS = (
    "time_s",
    "plough_x_m",
    "plough_y_m",
    "plough_z_m",
    "fairlead_x_m",
    "fairlead_y_m",
    "fairlead_z_m",
    "line_unstretched_length_m",
    "fairlead_tension_n",
    "plough_tension_n",
    "max_line_tension_n",
    "fairlead_force_x_n",
    "fairlead_force_y_n",
    "fairlead_force_z_n",
    "plough_force_x_n",
    "plough_force_y_n",
    "plough_force_z_n",
    "step_status",
)

MOORDYN_NODE_DISTRIBUTION_FIELDS = (
    "time_s",
    "node_index",
    "node_fraction",
    "x_m",
    "y_m",
    "z_m",
    "tension_x_n",
    "tension_y_n",
    "tension_z_n",
    "tension_magnitude_n",
    "seabed_force_x_n",
    "seabed_force_y_n",
    "seabed_force_z_n",
    "seabed_force_magnitude_n",
    "net_force_x_n",
    "net_force_y_n",
    "net_force_z_n",
    "net_force_magnitude_n",
    "contact_status",
)

DISTRIBUTION_COMPARISON_FIELDS = (
    "time_s",
    "node_index",
    "node_fraction",
    "project_x_m",
    "project_y_m",
    "project_z_m",
    "project_tension_n",
    "moordyn_x_m",
    "moordyn_y_m",
    "moordyn_z_m",
    "moordyn_tension_n",
    "moordyn_minus_project_tension_n",
    "moordyn_seabed_force_magnitude_n",
    "moordyn_contact_status",
    "notes",
)

DISTRIBUTION_MOUTH_AUDIT_FIELDS = (
    "time_s",
    "moordyn_node_index",
    "moordyn_node_fraction_plough_to_fairlead",
    "project_fraction_fairlead_to_plough",
    "project_x_m",
    "project_y_m",
    "project_z_m",
    "project_segment_index",
    "project_segment_tension_n",
    "project_point_tension_n",
    "project_plough_inlet_tension_n",
    "project_plough_adjacent_segment_tension_n",
    "moordyn_x_m",
    "moordyn_y_m",
    "moordyn_z_m",
    "moordyn_node_tension_n",
    "moordyn_minus_project_segment_tension_n",
    "moordyn_seabed_force_magnitude_n",
    "moordyn_contact_status",
    "comparison_mouth",
    "direct_tension_comparison",
    "notes",
)

DISTRIBUTION_ATTRIBUTION_FIELDS = (
    "variant_id",
    "category",
    "changed_parameter",
    "status",
    "window_start_s",
    "window_end_s",
    "dynamic_history_window_s",
    "initialization_scope",
    "project_output_time_s",
    "distribution_target_time_s",
    "node_distribution_csv",
    "direct_distribution_count",
    "direct_delta_min_n",
    "direct_delta_max_n",
    "direct_delta_avg_n",
    "free_span_distribution_count",
    "free_span_delta_avg_n",
    "fairlead_delta_n",
    "contact_model_count",
    "contact_delta_max_n",
    "contact_delta_avg_n",
    "max_seabed_force_n",
    "mouth_mismatch_delta_n",
    "notes",
)

MOORDYN_SENSITIVITY_FIELDS = (
    "variant_id",
    "category",
    "changed_parameter",
    "status",
    "dt_s",
    "duration_s",
    "window_start_s",
    "window_end_s",
    "fairlead_tension_n",
    "plough_tension_n",
    "max_line_tension_n",
    "max_seabed_force_n",
    "contact_node_count",
    "delta_fairlead_from_baseline_n",
    "delta_plough_from_baseline_n",
    "delta_max_seabed_from_baseline_n",
    "input_path",
    "history_csv",
    "node_distribution_csv",
    "notes",
)

MOORDYN_DT_CONVERGENCE_FIELDS = (
    "dt_s",
    "status",
    "duration_s",
    "window_start_s",
    "window_end_s",
    "fairlead_tension_n",
    "plough_tension_n",
    "max_line_tension_n",
    "max_seabed_force_n",
    "contact_node_count",
    "reference_dt_s",
    "fairlead_delta_from_reference_n",
    "plough_delta_from_reference_n",
    "max_seabed_delta_from_reference_n",
    "input_path",
    "history_csv",
    "node_distribution_csv",
    "notes",
)

MOORDYN_DT_HISTORY_CONVERGENCE_FIELDS = (
    "dt_s",
    "status",
    "reference_dt_s",
    "history_csv",
    "reference_history_csv",
    "sample_count",
    "matched_sample_count",
    "missing_sample_count",
    "reference_only_sample_count",
    "max_abs_fairlead_delta_n",
    "rms_fairlead_delta_n",
    "max_abs_plough_delta_n",
    "rms_plough_delta_n",
    "max_abs_line_max_delta_n",
    "rms_line_max_delta_n",
    "max_abs_history_delta_time_s",
    "initial_sample_time_s",
    "post_initial_matched_sample_count",
    "post_initial_max_abs_fairlead_delta_n",
    "post_initial_rms_fairlead_delta_n",
    "post_initial_max_abs_plough_delta_n",
    "post_initial_rms_plough_delta_n",
    "post_initial_max_abs_line_max_delta_n",
    "post_initial_rms_line_max_delta_n",
    "post_initial_max_abs_history_delta_time_s",
    "notes",
)

MOORDYN_DT_NODE_CONVERGENCE_FIELDS = (
    "dt_s",
    "status",
    "reference_dt_s",
    "node_distribution_csv",
    "reference_node_distribution_csv",
    "node_sample_count",
    "matched_node_sample_count",
    "missing_node_sample_count",
    "reference_only_node_sample_count",
    "max_abs_node_tension_delta_n",
    "rms_node_tension_delta_n",
    "max_abs_seabed_force_delta_n",
    "rms_seabed_force_delta_n",
    "max_position_delta_m",
    "contact_status_mismatch_count",
    "max_abs_node_delta_time_s",
    "max_abs_node_delta_node_index",
    "initial_sample_time_s",
    "post_initial_matched_node_sample_count",
    "post_initial_max_abs_node_tension_delta_n",
    "post_initial_rms_node_tension_delta_n",
    "post_initial_max_abs_seabed_force_delta_n",
    "post_initial_rms_seabed_force_delta_n",
    "post_initial_max_position_delta_m",
    "post_initial_contact_status_mismatch_count",
    "post_initial_max_abs_node_delta_time_s",
    "post_initial_max_abs_node_delta_node_index",
    "notes",
)

MOORDYN_INITIALIZATION_ACCEPTANCE_FIELDS = (
    "dt_s",
    "status",
    "reference_dt_s",
    "initial_sample_time_s",
    "history_including_initial_max_abs_fairlead_delta_n",
    "history_including_initial_max_abs_delta_time_s",
    "history_post_initial_sample_count",
    "history_post_initial_max_abs_fairlead_delta_n",
    "history_post_initial_max_abs_line_max_delta_n",
    "history_post_initial_max_abs_delta_time_s",
    "node_including_initial_max_abs_tension_delta_n",
    "node_including_initial_max_abs_delta_time_s",
    "node_including_initial_max_abs_delta_node_index",
    "node_post_initial_sample_count",
    "node_post_initial_max_abs_tension_delta_n",
    "node_post_initial_max_position_delta_m",
    "node_post_initial_contact_status_mismatch_count",
    "t0_included_in_driven_history_acceptance",
    "driven_history_acceptance_scope",
    "initial_state_acceptance_scope",
    "classification",
    "notes",
)

MOORDYN_FAIRLEAD_ATTRIBUTION_FIELDS = (
    "variant_id",
    "category",
    "changed_input",
    "status",
    "dt_s",
    "duration_s",
    "window_start_s",
    "window_end_s",
    "project_reference_time_s",
    "project_reference_fairlead_tension_n",
    "fairlead_tension_n",
    "fairlead_minus_project_n",
    "fairlead_delta_from_baseline_n",
    "plough_tension_n",
    "max_line_tension_n",
    "max_seabed_force_n",
    "contact_node_count",
    "input_path",
    "history_csv",
    "node_distribution_csv",
    "notes",
)

INPUT_MAPPING_FIELDS = (
    "category",
    "project_input",
    "project_value",
    "moordyn_target",
    "moordyn_value",
    "status",
    "notes",
)

PROJECT_GRAVITY_MPS2 = 9.8
PROJECT_SEAWATER_DENSITY_KG_M3 = 1025.0
PROJECT_SEABED_FRICTION_COEFFICIENT = 0.6
MOORDYN_BOTTOM_STIFFNESS_PA_PER_M = 3.0e6
MOORDYN_BOTTOM_DAMPING_PA_S_PER_M = 3.0e5
MOORDYN_FRICTION_DAMPING = 200.0
MOORDYN_STATIC_DYNAMIC_FRICTION_SCALE = 1.0
MOORDYN_VALIDATION_BA_ZETA = -0.8
MOORDYN_VALIDATION_EI_N_M2 = 0.0
MOORDYN_VALIDATION_CA = 0.0
MOORDYN_VALIDATION_CA_AX = 0.0


@dataclass(frozen=True)
class MoorDynInputOptions:
    variant_id: str = "baseline"
    dt_m_s: float = 1.0e-4
    current_scale: float = 1.0
    seabed_friction_coefficient: float = PROJECT_SEABED_FRICTION_COEFFICIENT
    bottom_stiffness_pa_per_m: float = MOORDYN_BOTTOM_STIFFNESS_PA_PER_M
    bottom_damping_pa_s_per_m: float = MOORDYN_BOTTOM_DAMPING_PA_S_PER_M
    friction_damping: float = MOORDYN_FRICTION_DAMPING
    ba_zeta: float = MOORDYN_VALIDATION_BA_ZETA
    ei_n_m2: float = MOORDYN_VALIDATION_EI_N_M2
    ca: float = MOORDYN_VALIDATION_CA
    ca_ax: float = MOORDYN_VALIDATION_CA_AX


@dataclass(frozen=True)
class MoorDynSensitivityVariant:
    variant_id: str
    category: str
    changed_parameter: str
    options: MoorDynInputOptions


@dataclass(frozen=True)
class MoorDynFairleadAttributionVariant:
    variant_id: str
    category: str
    changed_input: str
    options: MoorDynInputOptions
    drive_mode: str = "baseline"


GAP_FIELDS = (
    "metric",
    "external_model",
    "project_value_n",
    "external_value_n",
    "external_minus_project_n",
    "relative_delta_percent",
    "diagnosis",
)

FRAME_SCOPE_FIELDS = (
    "scope_label",
    "model",
    "status",
    "time_s",
    "fairlead_tension_n",
    "plough_tension_n",
    "suspended_length_m",
    "span_m",
    "fairlead_x_m",
    "fairlead_y_m",
    "fairlead_z_m",
    "plough_x_m",
    "plough_y_m",
    "plough_z_m",
    "notes",
)

QUASI_STATIC_FIELDS = (
    "sample_index",
    "time_s",
    "model",
    "status",
    "project_fairlead_tension_n",
    "project_plough_tension_n",
    "moorpy_fairlead_tension_n",
    "moorpy_plough_tension_n",
    "fairlead_delta_n",
    "plough_delta_n",
    "fairlead_delta_percent",
    "plough_delta_percent",
    "suspended_length_m",
    "span_m",
    "fairlead_x_m",
    "fairlead_y_m",
    "fairlead_z_m",
    "plough_x_m",
    "plough_y_m",
    "plough_z_m",
    "notes",
)

INITIAL_STATE_STATIC_AUDIT_FIELDS = (
    "scope_label",
    "time_s",
    "status",
    "project_fairlead_tension_n",
    "project_plough_tension_n",
    "moorpy_status",
    "moorpy_fairlead_tension_n",
    "moorpy_plough_tension_n",
    "moorpy_fairlead_delta_n",
    "moorpy_plough_delta_n",
    "closed_form_status",
    "closed_form_fairlead_tension_n",
    "closed_form_plough_tension_n",
    "closed_form_fairlead_delta_n",
    "closed_form_plough_delta_n",
    "moordyn_endpoint_status",
    "moordyn_initial_fairlead_tension_n",
    "moordyn_initial_fairlead_delta_from_project_n",
    "suspended_length_m",
    "span_m",
    "static_acceptance_scope",
    "classification",
    "notes",
)


@dataclass(frozen=True)
class EndpointDriveSample:
    """One MoorDyn validation-layer coupled-endpoint drive sample in z-up coordinates."""

    time_s: float
    plough_position_m: tuple[float, float, float]
    fairlead_position_m: tuple[float, float, float]
    plough_velocity_mps: tuple[float, float, float]
    fairlead_velocity_mps: tuple[float, float, float]
    unstretched_length_m: float
    unstretched_length_rate_mps: float
    project_tdp_arc_length_m: float | None = None
    project_free_span_material_length_m: float | None = None
    project_seabed_contact_length_m: float | None = None
    project_tdp_tension_n: float | None = None
    project_seabed_normal_reaction_n: float | None = None
    project_fairlead_tension_n: float | None = None
    project_plough_boundary_tension_n: float | None = None
    project_plough_adjacent_tension_n: float | None = None
    fairlead_payout_speed_mps: float | None = None
    plough_exit_speed_mps: float | None = None


@dataclass(frozen=True)
class FrameScopeSample:
    """One project output frame used to prevent cross-time validation comparisons."""

    scope_label: str
    time_s: float
    fairlead_position_m: tuple[float, float, float]
    plough_position_m: tuple[float, float, float]
    suspended_length_m: float
    project_top_tension_n: float
    project_plough_tension_n: float
    notes: str


@dataclass(frozen=True)
class MoorPyStaticReference:
    fairlead_tension_n: float
    plough_tension_n: float
    fairlead_force_n: tuple[float, float, float]
    plough_force_n: tuple[float, float, float]


@dataclass(frozen=True)
class ClosedFormCatenaryReference:
    fairlead_tension_n: float
    plough_tension_n: float
    horizontal_tension_n: float
    catenary_parameter_m: float


@dataclass(frozen=True)
class ValidationSnapshot:
    case_name: str
    length_boundary_source: str
    water_depth_m: float
    element_count: int
    fairlead_position_m: tuple[float, float, float]
    plough_position_m: tuple[float, float, float]
    suspended_length_m: float
    span_m: float
    diameter_m: float
    weight_air_n_per_m: float
    submerged_weight_n_per_m: float
    axial_stiffness_n: float
    normal_drag_coefficient: float
    tangential_drag_coefficient: float
    current_speed_mps: float
    current_direction_deg: float
    project_top_tension_n: float
    project_plough_tension_n: float
    project_plough_endpoint_reaction_n: float
    project_load_recursive_dynamic_top_tension_n: float
    project_load_recursive_no_current_top_tension_n: float
    endpoint_drive_samples: tuple[EndpointDriveSample, ...]
    frame_scope_samples: tuple[FrameScopeSample, ...]
    quasi_static_samples: tuple[FrameScopeSample, ...]
    project_final_frame: object


def run_validation(
    output_dir: Path,
    *,
    case_name: str = "plough_straight_baseline_6min",
    points: int = 7,
    extra_pythonpath: Sequence[Path] = (),
    run_moordyn: bool = False,
    moordyn_dt_s: float = 1.0e-4,
    moordyn_duration_s: float = 1.0,
    moordyn_sample_interval_s: float = 0.01,
    moordyn_ramp_duration_s: float = 0.0,
    allow_global_optional_deps: bool = False,
    run_moordyn_sensitivity: bool = False,
    moordyn_sensitivity_duration_s: float | None = None,
    moordyn_sensitivity_start_s: float = 0.0,
    run_moordyn_dt_convergence: bool = False,
    moordyn_dt_convergence_duration_s: float | None = None,
    moordyn_dt_convergence_start_s: float = 0.0,
    moordyn_dt_convergence_values: Sequence[float] = (2.0e-4, 1.0e-4, 5.0e-5),
    run_moordyn_fairlead_attribution: bool = False,
    moordyn_fairlead_attribution_duration_s: float | None = None,
    moordyn_fairlead_attribution_start_s: float = 0.0,
) -> dict[str, str]:
    """Run project, MoorPy, and optional MoorDyn validation layers."""

    _validate_moordyn_driver_settings(
        dt_s=moordyn_dt_s,
        duration_s=moordyn_duration_s,
        sample_interval_s=moordyn_sample_interval_s,
        ramp_duration_s=moordyn_ramp_duration_s,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = _build_project_snapshot(case_name, points=points, endpoint_replay_duration_s=moordyn_duration_s)
    moordyn_input = output_dir / f"{case_name}_moordyn.txt"
    moordyn_endpoint_input = output_dir / f"{case_name}_moordyn_endpoint_history.txt"
    moordyn_current_profile = output_dir / "current_profile.txt"
    moordyn_history = output_dir / f"{case_name}_moordyn_dynamic_history.csv"
    moordyn_endpoint_history = output_dir / f"{case_name}_moordyn_endpoint_history.csv"
    moordyn_endpoint_nodes = output_dir / f"{case_name}_moordyn_endpoint_nodes.csv"
    moordyn_sensitivity_csv = output_dir / f"{case_name}_moordyn_runtime_sensitivity.csv"
    moordyn_dt_convergence_csv = output_dir / f"{case_name}_moordyn_dt_convergence.csv"
    moordyn_dt_history_convergence_csv = output_dir / f"{case_name}_moordyn_dt_history_convergence.csv"
    moordyn_dt_node_convergence_csv = output_dir / f"{case_name}_moordyn_dt_node_convergence.csv"
    moordyn_initialization_acceptance_csv = output_dir / f"{case_name}_moordyn_initialization_acceptance.csv"
    moordyn_fairlead_attribution_csv = output_dir / f"{case_name}_moordyn_fairlead_attribution.csv"
    endpoint_seed = snapshot.endpoint_drive_samples[0] if snapshot.endpoint_drive_samples else None
    base_options = MoorDynInputOptions(dt_m_s=moordyn_dt_s)
    _write_moordyn_current_profile(snapshot, moordyn_current_profile, input_options=base_options)
    _write_moordyn_input(
        snapshot,
        moordyn_input,
        coupled_fairlead=True,
        coupled_plough=False,
        input_options=base_options,
    )
    _write_moordyn_input(
        snapshot,
        moordyn_endpoint_input,
        coupled_fairlead=True,
        coupled_plough=True,
        seed_sample=endpoint_seed,
        input_options=base_options,
    )

    rows: list[dict[str, str]] = [
        _project_row(snapshot),
        _project_load_recursive_dynamic_row(snapshot),
        _project_load_recursive_no_current_row(snapshot),
        _moorpy_row(snapshot, extra_pythonpath=extra_pythonpath, allow_global=allow_global_optional_deps),
        _moordyn_row(
            snapshot,
            moordyn_input,
            extra_pythonpath=extra_pythonpath,
            run_moordyn=run_moordyn,
            dt_s=moordyn_dt_s,
            duration_s=moordyn_duration_s,
            sample_interval_s=moordyn_sample_interval_s,
            history_path=moordyn_history,
            allow_global=allow_global_optional_deps,
        ),
        _moordyn_endpoint_history_row(
            snapshot,
            moordyn_endpoint_input,
            extra_pythonpath=extra_pythonpath,
            run_moordyn=run_moordyn,
            dt_s=moordyn_dt_s,
            duration_s=moordyn_duration_s,
            sample_interval_s=moordyn_sample_interval_s,
            ramp_duration_s=moordyn_ramp_duration_s,
            history_path=moordyn_endpoint_history,
            node_distribution_path=moordyn_endpoint_nodes,
            allow_global=allow_global_optional_deps,
        ),
    ]

    geometry_csv = output_dir / f"{case_name}_geometry.csv"
    summary_csv = output_dir / f"{case_name}_validation_summary.csv"
    gaps_csv = output_dir / f"{case_name}_diagnostic_gaps.csv"
    frame_scope_csv = output_dir / f"{case_name}_frame_scope_audit.csv"
    quasi_static_csv = output_dir / f"{case_name}_quasi_static_time_history.csv"
    initial_state_static_audit_csv = output_dir / f"{case_name}_initial_state_static_audit.csv"
    input_mapping_csv = output_dir / f"{case_name}_moordyn_input_mapping.csv"
    distribution_comparison_csv = output_dir / f"{case_name}_distribution_comparison.csv"
    distribution_mouth_audit_csv = output_dir / f"{case_name}_distribution_mouth_audit.csv"
    distribution_attribution_csv = output_dir / f"{case_name}_distribution_attribution.csv"
    report_md = output_dir / f"{case_name}_validation_report.md"
    gaps = _build_gap_rows(snapshot, rows)
    frame_scope_rows = _build_frame_scope_rows(
        snapshot,
        rows,
        extra_pythonpath=extra_pythonpath,
        allow_global=allow_global_optional_deps,
    )
    quasi_static_rows = _build_quasi_static_rows(
        snapshot,
        extra_pythonpath=extra_pythonpath,
        allow_global=allow_global_optional_deps,
    )
    initial_state_static_audit_rows = _build_initial_state_static_audit_rows(
        rows,
        frame_scope_rows,
        quasi_static_rows,
    )
    sensitivity_rows = _build_moordyn_sensitivity_rows(
        snapshot,
        output_dir=output_dir,
        case_name=case_name,
        extra_pythonpath=extra_pythonpath,
        allow_global=allow_global_optional_deps,
        run_moordyn=run_moordyn and run_moordyn_sensitivity,
        dt_s=moordyn_dt_s,
        duration_s=moordyn_sensitivity_duration_s if moordyn_sensitivity_duration_s is not None else min(5.0, moordyn_duration_s),
        window_start_s=moordyn_sensitivity_start_s,
        sample_interval_s=moordyn_sample_interval_s,
        ramp_duration_s=moordyn_ramp_duration_s,
    )
    dt_convergence_rows = _build_moordyn_dt_convergence_rows(
        snapshot,
        output_dir=output_dir,
        case_name=case_name,
        extra_pythonpath=extra_pythonpath,
        allow_global=allow_global_optional_deps,
        run_moordyn=run_moordyn and run_moordyn_dt_convergence,
        duration_s=(
            moordyn_dt_convergence_duration_s
            if moordyn_dt_convergence_duration_s is not None
            else min(5.0, moordyn_duration_s)
        ),
        window_start_s=moordyn_dt_convergence_start_s,
        sample_interval_s=moordyn_sample_interval_s,
        ramp_duration_s=moordyn_ramp_duration_s,
        dt_values=moordyn_dt_convergence_values,
    )
    dt_history_convergence_rows = _build_moordyn_dt_history_convergence_rows(dt_convergence_rows)
    dt_node_convergence_rows = _build_moordyn_dt_node_convergence_rows(dt_convergence_rows)
    initialization_acceptance_rows = _build_moordyn_initialization_acceptance_rows(
        dt_history_convergence_rows,
        dt_node_convergence_rows,
    )
    fairlead_attribution_rows = _build_moordyn_fairlead_attribution_rows(
        snapshot,
        output_dir=output_dir,
        case_name=case_name,
        extra_pythonpath=extra_pythonpath,
        allow_global=allow_global_optional_deps,
        run_moordyn=run_moordyn and run_moordyn_fairlead_attribution,
        dt_s=moordyn_dt_s,
        duration_s=(
            moordyn_fairlead_attribution_duration_s
            if moordyn_fairlead_attribution_duration_s is not None
            else min(5.0, moordyn_duration_s)
        ),
        window_start_s=moordyn_fairlead_attribution_start_s,
        sample_interval_s=moordyn_sample_interval_s,
        ramp_duration_s=moordyn_ramp_duration_s,
    )
    distribution_rows = _build_distribution_comparison_rows(
        project_frame=snapshot.project_final_frame,
        moordyn_node_rows=_read_csv_rows(moordyn_endpoint_nodes),
        target_time_s=float(getattr(snapshot.project_final_frame, "time_s")),
    )
    distribution_mouth_audit_rows = _build_distribution_mouth_audit_rows(
        project_frame=snapshot.project_final_frame,
        project_plough_inlet_tension_n=snapshot.project_plough_tension_n,
        project_plough_adjacent_segment_tension_n=snapshot.project_plough_endpoint_reaction_n,
        moordyn_node_rows=_read_csv_rows(moordyn_endpoint_nodes),
        target_time_s=float(getattr(snapshot.project_final_frame, "time_s")),
    )
    distribution_attribution_rows = _build_distribution_attribution_rows(
        project_frame=snapshot.project_final_frame,
        project_plough_inlet_tension_n=snapshot.project_plough_tension_n,
        project_plough_adjacent_segment_tension_n=snapshot.project_plough_endpoint_reaction_n,
        sensitivity_rows=sensitivity_rows,
    )
    _write_geometry_csv(snapshot, geometry_csv)
    _write_summary_csv(rows, summary_csv)
    _write_gaps_csv(gaps, gaps_csv)
    _write_frame_scope_csv(frame_scope_rows, frame_scope_csv)
    _write_quasi_static_csv(quasi_static_rows, quasi_static_csv)
    _write_initial_state_static_audit_csv(initial_state_static_audit_rows, initial_state_static_audit_csv)
    _write_moordyn_sensitivity_csv(sensitivity_rows, moordyn_sensitivity_csv)
    _write_moordyn_dt_convergence_csv(dt_convergence_rows, moordyn_dt_convergence_csv)
    _write_moordyn_dt_history_convergence_csv(
        dt_history_convergence_rows,
        moordyn_dt_history_convergence_csv,
    )
    _write_moordyn_dt_node_convergence_csv(
        dt_node_convergence_rows,
        moordyn_dt_node_convergence_csv,
    )
    _write_moordyn_initialization_acceptance_csv(
        initialization_acceptance_rows,
        moordyn_initialization_acceptance_csv,
    )
    _write_moordyn_fairlead_attribution_csv(fairlead_attribution_rows, moordyn_fairlead_attribution_csv)
    _write_input_mapping_csv(_build_input_mapping_rows(snapshot), input_mapping_csv)
    _write_distribution_comparison_csv(distribution_rows, distribution_comparison_csv)
    _write_distribution_mouth_audit_csv(distribution_mouth_audit_rows, distribution_mouth_audit_csv)
    _write_distribution_attribution_csv(distribution_attribution_rows, distribution_attribution_csv)
    _write_report(
        snapshot,
        rows,
        gaps,
        moordyn_input,
        frame_scope_csv,
        quasi_static_csv,
        initial_state_static_audit_csv,
        input_mapping_csv,
        moordyn_sensitivity_csv,
        moordyn_dt_convergence_csv,
        moordyn_dt_history_convergence_csv,
        moordyn_dt_node_convergence_csv,
        moordyn_initialization_acceptance_csv,
        moordyn_fairlead_attribution_csv,
        distribution_comparison_csv,
        distribution_mouth_audit_csv,
        distribution_attribution_csv,
        report_md,
    )
    return {
        "output_dir": str(output_dir),
        "geometry_csv": str(geometry_csv),
        "summary_csv": str(summary_csv),
        "gaps_csv": str(gaps_csv),
        "frame_scope_csv": str(frame_scope_csv),
        "quasi_static_csv": str(quasi_static_csv),
        "initial_state_static_audit_csv": str(initial_state_static_audit_csv),
        "moordyn_sensitivity_csv": str(moordyn_sensitivity_csv),
        "moordyn_dt_convergence_csv": str(moordyn_dt_convergence_csv),
        "moordyn_dt_history_convergence_csv": str(moordyn_dt_history_convergence_csv),
        "moordyn_dt_node_convergence_csv": str(moordyn_dt_node_convergence_csv),
        "moordyn_initialization_acceptance_csv": str(moordyn_initialization_acceptance_csv),
        "moordyn_fairlead_attribution_csv": str(moordyn_fairlead_attribution_csv),
        "distribution_comparison_csv": str(distribution_comparison_csv),
        "distribution_mouth_audit_csv": str(distribution_mouth_audit_csv),
        "distribution_attribution_csv": str(distribution_attribution_csv),
        "input_mapping_csv": str(input_mapping_csv),
        "report_md": str(report_md),
        "moordyn_input": str(moordyn_input),
        "moordyn_endpoint_input": str(moordyn_endpoint_input),
        "moordyn_current_profile": str(moordyn_current_profile),
        "moordyn_history_csv": str(moordyn_history),
        "moordyn_endpoint_history_csv": str(moordyn_endpoint_history),
        "moordyn_endpoint_nodes_csv": str(moordyn_endpoint_nodes),
    }


def _build_project_snapshot(
    case_name: str,
    *,
    points: int,
    endpoint_replay_duration_s: float = 1.0,
    dynamic_case_override=None,
) -> ValidationSnapshot:
    dynamic_case = dynamic_case_override or get_time_history_case(case_name)
    cable = cable_parameters_from_dynamic_case(dynamic_case)
    result = solve_dynamic_laying_time_history(dynamic_case, points=points)
    final_state, final_case = _final_known_plough_state(dynamic_case, cable)
    dynamic_recursive = _step_dynamic_segment_tensions(
        final_case,
        positions=final_state.positions,
        velocities=final_state.velocities,
        rest_lengths_m=final_state.rest_lengths_m,
        payout_speed_mps=_payout_speed(dynamic_case, dynamic_case.total_duration_s),
        terminal_tension_n=0.0,
    )
    zero_velocities = tuple((0.0, 0.0, 0.0) for _ in final_state.positions)
    no_current_case = replace(
        final_case,
        current_surface_mps=0.0,
        current_bottom_mps=0.0,
        current_u_mps=0.0,
        current_v_mps=0.0,
        vessel_speed_mps=0.0,
        payout_speed_mps=0.0,
    )
    no_current_recursive = _step_dynamic_segment_tensions(
        no_current_case,
        positions=final_state.positions,
        velocities=zero_velocities,
        rest_lengths_m=final_state.rest_lengths_m,
        payout_speed_mps=0.0,
        terminal_tension_n=0.0,
    )
    frame = result.frames[-1]
    fairlead = frame.points[0]
    plough = frame.points[-1]
    fairlead_position = _to_z_up(fairlead.x_m, fairlead.y_m, fairlead.z_m)
    plough_position = _to_z_up(plough.x_m, plough.y_m, plough.z_m)
    span = _distance(fairlead_position, plough_position)
    return ValidationSnapshot(
        case_name=case_name,
        length_boundary_source=result.length_boundary_source or "",
        water_depth_m=result.water_depth_m,
        element_count=result.element_count,
        fairlead_position_m=fairlead_position,
        plough_position_m=plough_position,
        suspended_length_m=result.history[-1].suspended_length_m,
        span_m=span,
        diameter_m=result.diameter_m,
        weight_air_n_per_m=result.weight_air_n_per_m,
        submerged_weight_n_per_m=result.submerged_weight_n_per_m,
        axial_stiffness_n=result.axial_stiffness_n,
        normal_drag_coefficient=result.normal_drag_coefficient,
        tangential_drag_coefficient=result.tangential_drag_coefficient,
        current_speed_mps=result.current_speed_mps,
        current_direction_deg=result.current_direction_deg,
        project_top_tension_n=result.steady_tension_n,
        project_plough_tension_n=result.plough_boundary_tension_final_n or 0.0,
        project_plough_endpoint_reaction_n=result.plough_adjacent_segment_tension_final_n or 0.0,
        project_load_recursive_dynamic_top_tension_n=dynamic_recursive[0] if dynamic_recursive else 0.0,
        project_load_recursive_no_current_top_tension_n=no_current_recursive[0] if no_current_recursive else 0.0,
        endpoint_drive_samples=_endpoint_drive_samples_from_result(result, dynamic_case=dynamic_case),
        frame_scope_samples=_project_frame_scope_samples(
            result,
            endpoint_replay_duration_s=endpoint_replay_duration_s,
        ),
        quasi_static_samples=_project_quasi_static_samples(result),
        project_final_frame=frame,
    )


def _endpoint_drive_samples_from_result(result, *, dynamic_case=None) -> tuple[EndpointDriveSample, ...]:
    frames = tuple(result.frames)
    histories = tuple(result.history)
    if len(frames) != len(histories):
        raise ValueError("project frames and history samples must have matching lengths")
    if not frames:
        return ()

    plough_positions: list[tuple[float, float, float]] = []
    fairlead_positions: list[tuple[float, float, float]] = []
    lengths: list[float] = []
    times: list[float] = []
    for frame, point in zip(frames, histories):
        times.append(float(frame.time_s))
        fairlead_positions.append(_frame_fairlead_position_z_up(frame))
        plough_positions.append(_frame_plough_position_z_up(frame))
        lengths.append(float(point.suspended_length_m))

    samples: list[EndpointDriveSample] = []
    for index, time_s in enumerate(times):
        plough_velocity = (
            _plough_velocity(dynamic_case, time_s)
            if dynamic_case is not None
            else _finite_difference_vector(times, plough_positions, index)
        )
        plough_exit_speed = (
            _plough_exit_material_speed(dynamic_case, plough_velocity)[0]
            if dynamic_case is not None
            else None
        )
        samples.append(
            EndpointDriveSample(
                time_s=time_s,
                plough_position_m=plough_positions[index],
                fairlead_position_m=fairlead_positions[index],
                plough_velocity_mps=_finite_difference_vector(times, plough_positions, index),
                fairlead_velocity_mps=_finite_difference_vector(times, fairlead_positions, index),
                unstretched_length_m=max(0.0, lengths[index]),
                unstretched_length_rate_mps=_finite_difference_scalar(times, lengths, index),
                project_tdp_arc_length_m=getattr(histories[index], "tdp_arc_length_m", None),
                project_free_span_material_length_m=getattr(
                    histories[index], "free_span_material_length_m", None
                ),
                project_seabed_contact_length_m=getattr(
                    histories[index], "seabed_contact_length_m", None
                ),
                project_tdp_tension_n=getattr(histories[index], "plough_inlet_tension_n", None),
                project_seabed_normal_reaction_n=getattr(
                    histories[index], "seabed_normal_reaction_n", None
                ),
                project_fairlead_tension_n=getattr(histories[index], "top_tension_n", None),
                project_plough_boundary_tension_n=getattr(
                    histories[index], "plough_boundary_tension_n", None
                ),
                project_plough_adjacent_tension_n=getattr(
                    histories[index], "plough_adjacent_segment_tension_n", None
                ),
                fairlead_payout_speed_mps=(
                    _payout_speed(dynamic_case, time_s) if dynamic_case is not None else None
                ),
                plough_exit_speed_mps=plough_exit_speed,
            )
        )
    return tuple(samples)


def _project_frame_scope_samples(result, *, endpoint_replay_duration_s: float) -> tuple[FrameScopeSample, ...]:
    frames = tuple(result.frames)
    histories = tuple(result.history)
    if len(frames) != len(histories):
        raise ValueError("project frames and history samples must have matching lengths")
    if not frames:
        return ()

    endpoint_index = _nearest_history_index(histories, endpoint_replay_duration_s)
    requests = (
        (
            "project_first_frame",
            0,
            "first project output frame; same-frame comparison only",
        ),
        (
            "project_endpoint_replay_end_nearest_frame",
            endpoint_index,
            (
                "nearest sampled project frame to the MoorDyn endpoint-history replay duration "
                f"{endpoint_replay_duration_s:.12g} s; same-frame comparison only"
            ),
        ),
        (
            "project_final_frame",
            len(frames) - 1,
            (
                "final project output frame; same-frame comparison only; do not compare it "
                "against a short endpoint-history replay unless the times match"
            ),
        ),
    )
    return tuple(
        _project_frame_scope_sample(label, frames[index], histories[index], notes)
        for label, index, notes in requests
    )


def _project_quasi_static_samples(result) -> tuple[FrameScopeSample, ...]:
    frames = tuple(result.frames)
    histories = tuple(result.history)
    if len(frames) != len(histories):
        raise ValueError("project frames and history samples must have matching lengths")
    return tuple(
        _project_frame_scope_sample(
            f"project_output_frame_{index:06d}",
            frame,
            point,
            "project output frame for MoorPy quasi-static same-frame comparison; diagnostic only",
        )
        for index, (frame, point) in enumerate(zip(frames, histories))
    )


def _nearest_history_index(histories: Sequence[object], target_time_s: float) -> int:
    return min(
        range(len(histories)),
        key=lambda index: abs(float(getattr(histories[index], "time_s")) - target_time_s),
    )


def _project_frame_scope_sample(label: str, frame, point, notes: str) -> FrameScopeSample:
    fairlead_position = _frame_fairlead_position_z_up(frame)
    plough_position = _frame_plough_position_z_up(frame)
    plough_tension = getattr(point, "plough_boundary_tension_n", None)
    if plough_tension is None:
        plough_tension = getattr(point, "plough_inlet_tension_n", 0.0) or 0.0
    return FrameScopeSample(
        scope_label=label,
        time_s=float(point.time_s),
        fairlead_position_m=fairlead_position,
        plough_position_m=plough_position,
        suspended_length_m=float(point.suspended_length_m),
        project_top_tension_n=float(point.top_tension_n),
        project_plough_tension_n=float(plough_tension),
        notes=notes,
    )


def _frame_fairlead_position_z_up(frame) -> tuple[float, float, float]:
    if frame.vessel_x_m is not None and frame.vessel_y_m is not None and frame.vessel_z_m is not None:
        return _to_z_up(frame.vessel_x_m, frame.vessel_y_m, frame.vessel_z_m)
    fairlead = frame.points[0]
    return _to_z_up(fairlead.x_m, fairlead.y_m, fairlead.z_m)


def _frame_plough_position_z_up(frame) -> tuple[float, float, float]:
    if frame.plough_x_m is not None and frame.plough_y_m is not None and frame.plough_z_m is not None:
        return _to_z_up(frame.plough_x_m, frame.plough_y_m, frame.plough_z_m)
    plough = frame.points[-1]
    return _to_z_up(plough.x_m, plough.y_m, plough.z_m)


def _finite_difference_vector(
    times: Sequence[float],
    values: Sequence[tuple[float, float, float]],
    index: int,
) -> tuple[float, float, float]:
    left, right = _difference_indices(len(times), index)
    dt = times[right] - times[left]
    if abs(dt) <= 1.0e-12:
        return (0.0, 0.0, 0.0)
    return tuple((values[right][axis] - values[left][axis]) / dt for axis in range(3))  # type: ignore[return-value]


def _finite_difference_scalar(times: Sequence[float], values: Sequence[float], index: int) -> float:
    left, right = _difference_indices(len(times), index)
    dt = times[right] - times[left]
    if abs(dt) <= 1.0e-12:
        return 0.0
    return (values[right] - values[left]) / dt


def _difference_indices(count: int, index: int) -> tuple[int, int]:
    if count <= 1:
        return (0, 0)
    if index <= 0:
        return (0, 1)
    if index >= count - 1:
        return (count - 2, count - 1)
    return (index - 1, index + 1)


def _final_known_plough_state(dynamic_case, cable):
    """Replay the known-plough integrator to expose validation-only tension diagnostics."""

    state = _initial_known_plough_state(dynamic_case, cable)
    current_time = 0.0
    dt_max = min(0.05, max(dynamic_case.total_duration_s / 7200.0, 0.01))
    while current_time + 1.0e-9 < dynamic_case.total_duration_s:
        dt = min(
            _time_history_step_limit_s(dynamic_case, state, base_step_s=dt_max),
            dynamic_case.total_duration_s - current_time,
        )
        case_at_time = _operation_case_at_time(
            dynamic_case,
            cable,
            current_time,
            vessel_fixed_current=False,
        )
        state = _step_known_plough_dynamic(
            dynamic_case,
            case_at_time,
            state,
            time_s=current_time,
            dt_s=dt,
        )
        current_time += dt
    final_case = _operation_case_at_time(
        dynamic_case,
        cable,
        dynamic_case.total_duration_s,
        vessel_fixed_current=False,
    )
    return state, final_case


def _validate_moordyn_driver_settings(
    *,
    dt_s: float,
    duration_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
) -> None:
    if not math.isfinite(dt_s) or dt_s <= 0.0:
        raise ValueError("moordyn_dt_s must be a positive finite number")
    if not math.isfinite(duration_s) or duration_s < 0.0:
        raise ValueError("moordyn_duration_s must be a non-negative finite number")
    if not math.isfinite(sample_interval_s) or sample_interval_s <= 0.0:
        raise ValueError("moordyn_sample_interval_s must be a positive finite number")
    if not math.isfinite(ramp_duration_s) or ramp_duration_s < 0.0:
        raise ValueError("moordyn_ramp_duration_s must be a non-negative finite number")
    if ramp_duration_s > duration_s:
        raise ValueError("moordyn_ramp_duration_s must not exceed moordyn_duration_s")


def _project_row(snapshot: ValidationSnapshot) -> dict[str, str]:
    return _row(
        model="project_known_plough",
        status="ok",
        fairlead_tension_n=snapshot.project_top_tension_n,
        plough_tension_n=snapshot.project_plough_tension_n,
        notes=(
            "Current solver output. Plough tension is the XPBD plough-boundary constraint "
            "reaction at the prescribed inlet endpoint; TDP/contact-transition and "
            "endpoint-adjacent diagnostics are retained separately inside the production summary."
        ),
    )


def _project_load_recursive_dynamic_row(snapshot: ValidationSnapshot) -> dict[str, str]:
    return _row(
        model="project_load_recursive_dynamic",
        status="diagnostic",
        fairlead_tension_n=snapshot.project_load_recursive_dynamic_top_tension_n,
        plough_tension_n=snapshot.project_plough_tension_n,
        notes=(
            "Validation-only project diagnostic using the final production geometry with "
            "project velocities, payout, and current in a load-recursive tension pass. "
            "Not a production correction and not a fitted coefficient."
        ),
    )


def _project_load_recursive_no_current_row(snapshot: ValidationSnapshot) -> dict[str, str]:
    return _row(
        model="project_load_recursive_no_current_static",
        status="diagnostic",
        fairlead_tension_n=snapshot.project_load_recursive_no_current_top_tension_n,
        plough_tension_n=snapshot.project_plough_tension_n,
        notes=(
            "Validation-only project diagnostic using the final production geometry with "
            "zero velocity, zero payout, and zero current. This is the closest project-side "
            "static-load comparator for the MoorPy no-current static row."
        ),
    )


def _run_moorpy_static_reference(
    moorpy,
    *,
    water_depth_m: float,
    element_count: int,
    fairlead_position_m: tuple[float, float, float],
    plough_position_m: tuple[float, float, float],
    suspended_length_m: float,
    diameter_m: float,
    weight_air_n_per_m: float,
    submerged_weight_n_per_m: float,
    axial_stiffness_n: float,
    normal_drag_coefficient: float,
    tangential_drag_coefficient: float,
) -> MoorPyStaticReference:
    import numpy as np

    line_type = {
        "name": "PROJECT_CABLE",
        "d_vol": diameter_m,
        "m": weight_air_n_per_m / PROJECT_GRAVITY_MPS2,
        "w": submerged_weight_n_per_m,
        "EA": axial_stiffness_n,
        "Cd": normal_drag_coefficient,
        "CdAx": tangential_drag_coefficient,
        "Ca": 0.0,
        "CaAx": 0.0,
    }
    point_props = {
        "AnchorProps": {"fixed": {}},
        "BuoyProps": {"none": {}},
        "ConnectProps": {"none": {}},
        "DesignProps": {},
    }
    system = moorpy.System(
        depth=water_depth_m,
        rho=PROJECT_SEAWATER_DENSITY_KG_M3,
        g=PROJECT_GRAVITY_MPS2,
        lineProps={},
        pointProps=point_props,
    )
    system.lineTypes["PROJECT_CABLE"] = line_type
    plough_point = system.addPoint(1, np.array(plough_position_m, dtype=float))
    fairlead_point = system.addPoint(1, np.array(fairlead_position_m, dtype=float))
    line = system.addLine(
        suspended_length_m,
        "PROJECT_CABLE",
        nSegs=element_count,
        pointA=plough_point.number,
        pointB=fairlead_point.number,
    )
    plough_point.attachLine(line.number, 0)
    fairlead_point.attachLine(line.number, 1)
    system.initialize()
    line.staticSolve(profiles=1)
    return MoorPyStaticReference(
        fairlead_tension_n=float(line.TB),
        plough_tension_n=float(line.TA),
        fairlead_force_n=tuple(float(value) for value in line.fB),
        plough_force_n=tuple(float(value) for value in line.fA),
    )


def _moorpy_row(
    snapshot: ValidationSnapshot,
    *,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
) -> dict[str, str]:
    moorpy = _optional_import("moorpy", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moorpy is None:
        return _row(
            model="moorpy_static",
            status="dependency_missing",
            notes=(
                "Install MoorPy or pass --extra-pythonpath to run the static catenary reference. "
                "diagnostic only; not a production correction."
            ),
        )

    try:
        reference = _run_moorpy_static_reference(
            moorpy,
            water_depth_m=snapshot.water_depth_m,
            element_count=snapshot.element_count,
            fairlead_position_m=snapshot.fairlead_position_m,
            plough_position_m=snapshot.plough_position_m,
            suspended_length_m=snapshot.suspended_length_m,
            diameter_m=snapshot.diameter_m,
            weight_air_n_per_m=snapshot.weight_air_n_per_m,
            submerged_weight_n_per_m=snapshot.submerged_weight_n_per_m,
            axial_stiffness_n=snapshot.axial_stiffness_n,
            normal_drag_coefficient=snapshot.normal_drag_coefficient,
            tangential_drag_coefficient=snapshot.tangential_drag_coefficient,
        )
        return _row(
            model="moorpy_static",
            status="ok",
            fairlead_tension_n=reference.fairlead_tension_n,
            plough_tension_n=reference.plough_tension_n,
            fairlead_force=reference.fairlead_force_n,
            plough_force=reference.plough_force_n,
            notes=(
                "MoorPy fixed-end static catenary reference using the project final endpoints, "
                "suspended length, wet weight, mass, diameter, and EA. diagnostic only; "
                "not a production correction. No correction factor."
            ),
        )
    except Exception as exc:  # pragma: no cover - exercised by local dependency state
        return _row(model="moorpy_static", status="failed", notes=f"{type(exc).__name__}: {exc}")


def _moordyn_row(
    snapshot: ValidationSnapshot,
    input_path: Path,
    *,
    extra_pythonpath: Sequence[Path],
    run_moordyn: bool,
    dt_s: float,
    duration_s: float,
    sample_interval_s: float,
    history_path: Path,
    allow_global: bool,
) -> dict[str, str]:
    if not run_moordyn:
        return _row(
            model="moordyn_python",
            status="input_written",
            notes=(
                "MoorDyn v2 input file written. Python runtime readback is optional because the "
                "same fixed/coupled input needs a stable dynamic step before using runtime tension getters. "
                "diagnostic only; not a production correction."
            ),
        )
    moordyn = _optional_import("moordyn", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moordyn is None:
        return _row(
            model="moordyn_python",
            status="dependency_missing",
            notes="Install MoorDyn or pass --extra-pythonpath to run the dynamic smoke driver.",
        )
    try:
        return _run_moordyn_dynamic_smoke(
            moordyn,
            input_path=input_path,
            fairlead_position_m=snapshot.fairlead_position_m,
            dt_s=dt_s,
            duration_s=duration_s,
            sample_interval_s=sample_interval_s,
            history_path=history_path,
        )
    except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
        return _row(model="moordyn_python", status="failed", notes=f"{type(exc).__name__}: {exc}")


def _moordyn_endpoint_history_row(
    snapshot: ValidationSnapshot,
    input_path: Path,
    *,
    extra_pythonpath: Sequence[Path],
    run_moordyn: bool,
    dt_s: float,
    duration_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
    history_path: Path,
    node_distribution_path: Path,
    allow_global: bool,
) -> dict[str, str]:
    if not run_moordyn:
        return _row(
            model="moordyn_endpoint_history",
            status="input_written",
            notes=(
                "MoorDyn dual-coupled endpoint input file written. Runtime replay is optional; "
                "diagnostic only and not a production correction."
            ),
        )
    if not snapshot.endpoint_drive_samples:
        return _row(
            model="moordyn_endpoint_history",
            status="no_project_frames",
            notes="Project output did not provide endpoint frames for the MoorDyn replay.",
        )
    moordyn = _optional_import("moordyn", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moordyn is None:
        return _row(
            model="moordyn_endpoint_history",
            status="dependency_missing",
            notes="Install MoorDyn or pass --extra-pythonpath to run the endpoint history driver.",
        )
    try:
        return _run_moordyn_endpoint_history(
            moordyn,
            input_path=input_path,
            drive_samples=snapshot.endpoint_drive_samples,
            dt_s=dt_s,
            duration_s=duration_s,
            sample_interval_s=sample_interval_s,
            ramp_duration_s=ramp_duration_s,
            history_path=history_path,
            node_distribution_path=node_distribution_path,
        )
    except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
        return _row(model="moordyn_endpoint_history", status="failed", notes=f"{type(exc).__name__}: {exc}")


def _run_moordyn_dynamic_smoke(
    moordyn,
    *,
    input_path: Path,
    fairlead_position_m: tuple[float, float, float],
    dt_s: float,
    duration_s: float,
    sample_interval_s: float,
    history_path: Path,
) -> dict[str, str]:
    """Run a fixed-fairlead MoorDyn smoke step and record runtime tensions.

    This is only a runtime stability probe for the generated MoorDyn input. It
    does not replay the project vessel/plough/payout time series.
    """

    system = None
    history_rows: list[dict[str, str]] = []
    final_fairlead_tension = 0.0
    final_max_tension = 0.0
    peak_fairlead_tension = 0.0
    peak_max_tension = 0.0
    peak_fairlead_time_s = 0.0
    peak_max_time_s = 0.0
    final_force = (0.0, 0.0, 0.0)
    status = "dynamic_smoke_ok"
    step_status = "init"
    steps_completed = 0
    init_code = ""
    position = [float(item) for item in fairlead_position_m]
    velocity = [0.0, 0.0, 0.0]
    steps = max(0, int(math.ceil(duration_s / dt_s - 1.0e-12)))
    sample_every = max(1, int(round(sample_interval_s / dt_s)))

    try:
        system = moordyn.Create(str(input_path))
        if hasattr(moordyn, "SetDt"):
            moordyn.SetDt(system, dt_s)
        init_code = str(moordyn.Init(system, position, velocity))
        point = moordyn.GetPoint(system, 2)
        line = moordyn.GetLine(system, 1)

        final_fairlead_tension = float(moordyn.GetLineFairTen(line))
        final_max_tension = _moordyn_line_max_tension(moordyn, line, final_fairlead_tension)
        peak_fairlead_tension = final_fairlead_tension
        peak_max_tension = final_max_tension
        final_force = _moordyn_point_force(moordyn, point)
        initial_fairlead_tension = final_fairlead_tension
        _append_moordyn_history_row(
            history_rows,
            time_s=0.0,
            fairlead_tension=final_fairlead_tension,
            max_tension=final_max_tension,
            fairlead_force=final_force,
            step_status=step_status,
        )

        for step in range(1, steps + 1):
            time_s = (step - 1) * dt_s
            try:
                step_result = moordyn.Step(system, position, velocity, time_s, dt_s)
                step_status = str(step_result)
            except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
                status = "dynamic_smoke_diverged"
                step_status = f"{type(exc).__name__}: {exc}"
                break

            steps_completed = step
            final_fairlead_tension = float(moordyn.GetLineFairTen(line))
            final_max_tension = _moordyn_line_max_tension(moordyn, line, final_fairlead_tension)
            if final_fairlead_tension > peak_fairlead_tension:
                peak_fairlead_tension = final_fairlead_tension
                peak_fairlead_time_s = step * dt_s
            if final_max_tension > peak_max_tension:
                peak_max_tension = final_max_tension
                peak_max_time_s = step * dt_s
            final_force = _moordyn_point_force(moordyn, point)
            if not _all_finite((final_fairlead_tension, final_max_tension, *final_force)):
                status = "dynamic_smoke_diverged"
                step_status = "non_finite_runtime_value"
                break

            if step == steps or step % sample_every == 0:
                _append_moordyn_history_row(
                    history_rows,
                    time_s=step * dt_s,
                    fairlead_tension=final_fairlead_tension,
                    max_tension=final_max_tension,
                    fairlead_force=final_force,
                    step_status=step_status,
                )

        if status != "dynamic_smoke_ok" and steps_completed < steps:
            _append_moordyn_history_row(
                history_rows,
                time_s=steps_completed * dt_s,
                fairlead_tension=final_fairlead_tension,
                max_tension=final_max_tension,
                fairlead_force=final_force,
                step_status=step_status,
            )
    finally:
        if system is not None:
            try:
                moordyn.Close(system)
            except Exception:
                pass

    _write_moordyn_history_csv(history_rows, history_path)
    requested_duration = float(duration_s)
    completed_duration = steps_completed * dt_s if status == "dynamic_smoke_diverged" else steps * dt_s
    last_history_time = _last_history_time_s(history_rows)
    notes = (
        "MoorDyn fixed-fairlead dynamic smoke driver. This records runtime tension with "
        "SetDt-controlled stepping; it is diagnostic only, not a production correction and "
        "not a full vessel/plough/payout replay."
    )
    if status == "dynamic_smoke_diverged":
        notes += " The run diverged before the requested duration; inspect moordyn_history_csv."
    return _row(
        model="moordyn_python",
        status=status,
        fairlead_tension_n=final_fairlead_tension,
        fairlead_force=final_force,
        notes=notes,
        extra={
            "moordyn_dt_s": _csv_number(dt_s),
            "moordyn_duration_s": _csv_number(completed_duration),
            "moordyn_requested_duration_s": _csv_number(requested_duration),
            "moordyn_completed_duration_s": _csv_number(completed_duration),
            "moordyn_replay_coverage_percent": _csv_number(_coverage_percent(completed_duration, requested_duration)),
            "moordyn_last_history_time_s": _csv_number(last_history_time),
            "moordyn_steps": str(steps_completed if status == "dynamic_smoke_diverged" else steps),
            "moordyn_init_code": init_code,
            "moordyn_init_mode": "fixed_fairlead_static_zero_velocity",
            "moordyn_initial_fairlead_tension_n": _csv_number(initial_fairlead_tension),
            "moordyn_peak_fairlead_tension_n": _csv_number(peak_fairlead_tension),
            "moordyn_peak_line_tension_n": _csv_number(peak_max_tension),
            "moordyn_peak_fairlead_time_s": _csv_number(peak_fairlead_time_s),
            "moordyn_peak_line_time_s": _csv_number(peak_max_time_s),
            "moordyn_max_line_tension_n": _csv_number(final_max_tension),
            "moordyn_history_csv": str(history_path),
        },
    )


def _run_moordyn_endpoint_history(
    moordyn,
    *,
    input_path: Path,
    drive_samples: Sequence[EndpointDriveSample],
    dt_s: float,
    duration_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
    history_path: Path,
    node_distribution_path: Path,
) -> dict[str, str]:
    """Replay project endpoint motion into MoorDyn as validation-only coupled input."""

    system = None
    history_rows: list[dict[str, str]] = []
    node_distribution_rows: list[dict[str, str]] = []
    final_fairlead_tension = 0.0
    final_plough_tension = 0.0
    final_max_tension = 0.0
    peak_fairlead_tension = 0.0
    peak_plough_tension = 0.0
    peak_max_tension = 0.0
    peak_fairlead_time_s = 0.0
    peak_plough_time_s = 0.0
    peak_max_time_s = 0.0
    final_fairlead_force = (0.0, 0.0, 0.0)
    final_plough_force = (0.0, 0.0, 0.0)
    initial_fairlead_tension = 0.0
    node_distribution_stats = _empty_moordyn_node_distribution_stats(node_distribution_path)
    status = "endpoint_history_ok"
    step_status = "init"
    steps_completed = 0
    init_code = ""
    init_mode = "not initialized"
    line = None
    steps = max(0, int(math.ceil(duration_s / dt_s - 1.0e-12)))
    sample_every = max(1, int(round(sample_interval_s / dt_s)))

    try:
        system = moordyn.Create(str(input_path))
        if hasattr(moordyn, "SetDt"):
            moordyn.SetDt(system, dt_s)
        if hasattr(moordyn, "NCoupledDOF"):
            dof = int(moordyn.NCoupledDOF(system))
            if dof != 6:
                raise ValueError(f"endpoint history driver requires 6 coupled DOF, got {dof}")
        line = moordyn.GetLine(system, 1)
        _set_moordyn_line_length(moordyn, line, drive_samples[0].unstretched_length_m)
        _set_moordyn_line_length_rate(moordyn, line, 0.0)
        initial_drive = _interpolate_endpoint_drive(drive_samples, 0.0)
        position, velocity = _flatten_endpoint_drive(initial_drive)
        init_velocity = [0.0] * len(velocity)
        if hasattr(moordyn, "Init"):
            init_code = str(moordyn.Init(system, position, init_velocity))
            init_mode = "static_zero_velocity"
        elif hasattr(moordyn, "Init_NoIC"):
            init_code = str(moordyn.Init_NoIC(system, position, init_velocity))
            init_mode = "no_ic_zero_velocity_fallback"
        else:
            raise RuntimeError("MoorDyn runtime exposes neither Init nor Init_NoIC")
        plough_point = moordyn.GetPoint(system, 1)
        fairlead_point = moordyn.GetPoint(system, 2)

        final_fairlead_tension = float(moordyn.GetLineFairTen(line))
        initial_fairlead_tension = final_fairlead_tension
        final_plough_tension = _moordyn_line_node_tension_magnitude(moordyn, line, 0, fallback=0.0)
        final_max_tension = _moordyn_line_max_tension(moordyn, line, final_fairlead_tension)
        peak_fairlead_tension = final_fairlead_tension
        peak_plough_tension = final_plough_tension
        peak_max_tension = final_max_tension
        final_fairlead_force = _moordyn_point_force(moordyn, fairlead_point)
        final_plough_force = _moordyn_point_force(moordyn, plough_point)
        _append_moordyn_history_row(
            history_rows,
            time_s=0.0,
            drive_sample=initial_drive,
            fairlead_tension=final_fairlead_tension,
            plough_tension=final_plough_tension,
            max_tension=final_max_tension,
            fairlead_force=final_fairlead_force,
            plough_force=final_plough_force,
            step_status=step_status,
        )
        sample_node_rows, node_distribution_stats = _moordyn_line_node_distribution_rows(
            moordyn,
            line,
            time_s=0.0,
        )
        node_distribution_rows.extend(sample_node_rows)
        node_distribution_stats["moordyn_node_distribution_csv"] = str(node_distribution_path)

        for step in range(1, steps + 1):
            previous_time_s = (step - 1) * dt_s
            target_time_s = min(step * dt_s, duration_s)
            step_dt_s = max(target_time_s - previous_time_s, 0.0)
            drive = _endpoint_drive_with_ramp(drive_samples, target_time_s, ramp_duration_s=ramp_duration_s)
            position, velocity = _flatten_endpoint_drive(drive)
            _set_moordyn_line_length(moordyn, line, drive.unstretched_length_m)
            _set_moordyn_line_length_rate(moordyn, line, drive.unstretched_length_rate_mps)
            try:
                step_result = moordyn.Step(system, position, velocity, previous_time_s, step_dt_s)
                step_status = str(step_result)
            except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
                status = "endpoint_history_diverged"
                step_status = f"{type(exc).__name__}: {exc}"
                break

            steps_completed = step
            final_fairlead_tension = float(moordyn.GetLineFairTen(line))
            final_plough_tension = _moordyn_line_node_tension_magnitude(moordyn, line, 0, fallback=0.0)
            final_max_tension = _moordyn_line_max_tension(moordyn, line, final_fairlead_tension)
            if final_fairlead_tension > peak_fairlead_tension:
                peak_fairlead_tension = final_fairlead_tension
                peak_fairlead_time_s = target_time_s
            if final_plough_tension > peak_plough_tension:
                peak_plough_tension = final_plough_tension
                peak_plough_time_s = target_time_s
            if final_max_tension > peak_max_tension:
                peak_max_tension = final_max_tension
                peak_max_time_s = target_time_s
            final_fairlead_force = _moordyn_point_force(moordyn, fairlead_point)
            final_plough_force = _moordyn_point_force(moordyn, plough_point)
            if not _all_finite(
                (
                    final_fairlead_tension,
                    final_plough_tension,
                    final_max_tension,
                    *final_fairlead_force,
                    *final_plough_force,
                )
            ):
                status = "endpoint_history_diverged"
                step_status = "non_finite_runtime_value"
                break

            if step == steps or step % sample_every == 0:
                _append_moordyn_history_row(
                    history_rows,
                    time_s=target_time_s,
                    drive_sample=drive,
                    fairlead_tension=final_fairlead_tension,
                    plough_tension=final_plough_tension,
                    max_tension=final_max_tension,
                    fairlead_force=final_fairlead_force,
                    plough_force=final_plough_force,
                    step_status=step_status,
                )
                sample_node_rows, node_distribution_stats = _moordyn_line_node_distribution_rows(
                    moordyn,
                    line,
                    time_s=target_time_s,
                )
                node_distribution_rows.extend(sample_node_rows)
                node_distribution_stats["moordyn_node_distribution_csv"] = str(node_distribution_path)

        if status != "endpoint_history_ok" and steps_completed < steps:
            failed_drive = _interpolate_endpoint_drive(drive_samples, steps_completed * dt_s)
            _append_moordyn_history_row(
                history_rows,
                time_s=steps_completed * dt_s,
                drive_sample=failed_drive,
                fairlead_tension=final_fairlead_tension,
                plough_tension=final_plough_tension,
                max_tension=final_max_tension,
                fairlead_force=final_fairlead_force,
                plough_force=final_plough_force,
                step_status=step_status,
            )
            sample_node_rows, node_distribution_stats = _moordyn_line_node_distribution_rows(
                moordyn,
                line,
                time_s=steps_completed * dt_s,
            )
            node_distribution_rows.extend(sample_node_rows)
            node_distribution_stats["moordyn_node_distribution_csv"] = str(node_distribution_path)
    finally:
        if line is not None and not node_distribution_rows:
            try:
                node_time_s = steps_completed * dt_s if status == "endpoint_history_diverged" else duration_s
                node_rows, node_distribution_stats = _moordyn_line_node_distribution_rows(
                    moordyn,
                    line,
                    time_s=node_time_s,
                )
                node_distribution_stats["moordyn_node_distribution_csv"] = str(node_distribution_path)
                _write_moordyn_node_distribution_csv(node_rows, node_distribution_path)
            except Exception:
                _write_moordyn_node_distribution_csv([], node_distribution_path)
        if system is not None:
            try:
                moordyn.Close(system)
            except Exception:
                pass

    _write_moordyn_history_csv(history_rows, history_path)
    if node_distribution_rows:
        _write_moordyn_node_distribution_csv(node_distribution_rows, node_distribution_path)
    requested_duration = float(duration_s)
    completed_duration = steps_completed * dt_s if status == "endpoint_history_diverged" else duration_s
    project_window = _endpoint_drive_window_s(drive_samples)
    last_history_time = _last_history_time_s(history_rows)
    notes = (
        "MoorDyn endpoint-history driver using project vessel/plough endpoint interpolation "
        f"and validation-layer unstretched-length updates. Initialization uses {init_mode}. "
        "It is diagnostic only, not a production correction. Steady current, flat seabed "
        "contact, and seabed friction are mapped in the shared input; remaining differences "
        "are penalty contact versus XPBD hard projection and the plough-as-cable-exit abstraction."
    )
    if status == "endpoint_history_diverged":
        notes += " The run diverged before the requested duration; inspect moordyn_history_csv."
    return _row(
        model="moordyn_endpoint_history",
        status=status,
        fairlead_tension_n=final_fairlead_tension,
        plough_tension_n=final_plough_tension,
        fairlead_force=final_fairlead_force,
        plough_force=final_plough_force,
        notes=notes,
        extra={
            "moordyn_dt_s": _csv_number(dt_s),
            "moordyn_duration_s": _csv_number(completed_duration),
            "moordyn_requested_duration_s": _csv_number(requested_duration),
            "moordyn_completed_duration_s": _csv_number(completed_duration),
            "moordyn_replay_coverage_percent": _csv_number(_coverage_percent(completed_duration, requested_duration)),
            "moordyn_project_window_s": _csv_number(project_window),
            "moordyn_project_window_coverage_percent": _csv_number(
                _coverage_percent(completed_duration, project_window)
            ),
            "moordyn_last_history_time_s": _csv_number(last_history_time),
            "moordyn_ramp_duration_s": _csv_number(ramp_duration_s),
            "moordyn_steps": str(steps_completed if status == "endpoint_history_diverged" else steps),
            "moordyn_init_code": init_code,
            "moordyn_init_mode": init_mode,
            "moordyn_initial_fairlead_tension_n": _csv_number(initial_fairlead_tension),
            "moordyn_peak_fairlead_tension_n": _csv_number(peak_fairlead_tension),
            "moordyn_peak_plough_tension_n": _csv_number(peak_plough_tension),
            "moordyn_peak_line_tension_n": _csv_number(peak_max_tension),
            "moordyn_peak_fairlead_time_s": _csv_number(peak_fairlead_time_s),
            "moordyn_peak_plough_time_s": _csv_number(peak_plough_time_s),
            "moordyn_peak_line_time_s": _csv_number(peak_max_time_s),
            "moordyn_max_line_tension_n": _csv_number(final_max_tension),
            "moordyn_history_csv": str(history_path),
            **node_distribution_stats,
        },
    )


def _moordyn_line_max_tension(moordyn, line, fallback: float) -> float:
    if not hasattr(moordyn, "GetLineMaxTen"):
        return float(fallback)
    return float(moordyn.GetLineMaxTen(line))


def _moordyn_line_node_tension_magnitude(moordyn, line, index: int, *, fallback: float) -> float:
    if not hasattr(moordyn, "GetLineNodeTen"):
        return float(fallback)
    try:
        values = _vector_or_empty(moordyn.GetLineNodeTen(line, index))
    except Exception:
        return float(fallback)
    magnitude = _vector_magnitude_or_none(values)
    return float(fallback) if magnitude is None else magnitude


def _moordyn_point_force(moordyn, point) -> tuple[float, float, float]:
    return _vector_or_empty(moordyn.GetPointForce(point))  # type: ignore[return-value]


def _set_moordyn_line_length(moordyn, line, length_m: float) -> None:
    if hasattr(moordyn, "SetLineUnstretchedLength"):
        moordyn.SetLineUnstretchedLength(line, max(0.0, float(length_m)))


def _set_moordyn_line_length_rate(moordyn, line, length_rate_mps: float) -> None:
    if hasattr(moordyn, "SetLineUnstretchedLengthVel"):
        moordyn.SetLineUnstretchedLengthVel(line, float(length_rate_mps))


def _endpoint_drive_window_s(samples: Sequence[EndpointDriveSample]) -> float:
    if len(samples) < 2:
        return 0.0
    return max(0.0, float(samples[-1].time_s) - float(samples[0].time_s))


def _slice_endpoint_drive_samples(
    samples: Sequence[EndpointDriveSample],
    *,
    start_s: float,
    duration_s: float,
) -> tuple[EndpointDriveSample, ...]:
    if not samples:
        return ()
    source_start = float(samples[0].time_s)
    source_end = float(samples[-1].time_s)
    window_start = max(source_start, min(float(start_s), source_end))
    window_end = max(window_start, min(source_end, window_start + max(0.0, float(duration_s))))
    times = [window_start]
    times.extend(float(sample.time_s) for sample in samples if window_start < float(sample.time_s) < window_end)
    if window_end > window_start:
        times.append(window_end)
    unique_times = tuple(dict.fromkeys(times))
    return tuple(
        replace(_interpolate_endpoint_drive(samples, time_s), time_s=time_s - window_start)
        for time_s in unique_times
    )


def _endpoint_drive_with_ramp(
    samples: Sequence[EndpointDriveSample],
    time_s: float,
    *,
    ramp_duration_s: float,
) -> EndpointDriveSample:
    if ramp_duration_s <= 1.0e-12 or time_s <= 0.0 or time_s >= ramp_duration_s:
        return _interpolate_endpoint_drive(samples, time_s)
    fraction = max(0.0, min(1.0, float(time_s) / float(ramp_duration_s)))
    smooth = fraction * fraction * (3.0 - 2.0 * fraction)
    smooth_derivative = 6.0 * fraction * (1.0 - fraction)
    mapped_time_s = float(time_s) * smooth
    velocity_scale = smooth + float(time_s) * smooth_derivative / float(ramp_duration_s)
    drive = _interpolate_endpoint_drive(samples, mapped_time_s)
    return EndpointDriveSample(
        time_s=float(time_s),
        plough_position_m=drive.plough_position_m,
        fairlead_position_m=drive.fairlead_position_m,
        plough_velocity_mps=_scale_vector(drive.plough_velocity_mps, velocity_scale),
        fairlead_velocity_mps=_scale_vector(drive.fairlead_velocity_mps, velocity_scale),
        unstretched_length_m=drive.unstretched_length_m,
        unstretched_length_rate_mps=drive.unstretched_length_rate_mps * velocity_scale,
    )


def _coverage_percent(completed_s: float, target_s: float) -> float:
    if target_s <= 1.0e-12:
        return 100.0 if completed_s <= 1.0e-12 else 0.0
    return max(0.0, min(100.0, 100.0 * float(completed_s) / float(target_s)))


def _last_history_time_s(rows: Sequence[dict[str, str]]) -> float:
    if not rows:
        return 0.0
    try:
        return float(rows[-1].get("time_s", "") or 0.0)
    except ValueError:
        return 0.0


def _interpolate_endpoint_drive(
    samples: Sequence[EndpointDriveSample],
    time_s: float,
) -> EndpointDriveSample:
    if not samples:
        raise ValueError("at least one endpoint drive sample is required")
    if time_s <= samples[0].time_s:
        return samples[0]
    if time_s >= samples[-1].time_s:
        return samples[-1]
    for left, right in zip(samples, samples[1:]):
        if left.time_s <= time_s <= right.time_s:
            span = right.time_s - left.time_s
            fraction = 0.0 if abs(span) <= 1.0e-12 else (time_s - left.time_s) / span
            return EndpointDriveSample(
                time_s=float(time_s),
                plough_position_m=_lerp_vector(left.plough_position_m, right.plough_position_m, fraction),
                fairlead_position_m=_lerp_vector(left.fairlead_position_m, right.fairlead_position_m, fraction),
                plough_velocity_mps=_lerp_vector(left.plough_velocity_mps, right.plough_velocity_mps, fraction),
                fairlead_velocity_mps=_lerp_vector(left.fairlead_velocity_mps, right.fairlead_velocity_mps, fraction),
                unstretched_length_m=_lerp_scalar(left.unstretched_length_m, right.unstretched_length_m, fraction),
                unstretched_length_rate_mps=_lerp_scalar(
                    left.unstretched_length_rate_mps,
                    right.unstretched_length_rate_mps,
                    fraction,
                ),
            )
    return samples[-1]


def _flatten_endpoint_drive(sample: EndpointDriveSample) -> tuple[list[float], list[float]]:
    position = [*sample.plough_position_m, *sample.fairlead_position_m]
    velocity = [*sample.plough_velocity_mps, *sample.fairlead_velocity_mps]
    return [float(item) for item in position], [float(item) for item in velocity]


def _lerp_vector(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    fraction: float,
) -> tuple[float, float, float]:
    return tuple(_lerp_scalar(left[index], right[index], fraction) for index in range(3))  # type: ignore[return-value]


def _scale_vector(values: tuple[float, float, float], scale: float) -> tuple[float, float, float]:
    return tuple(float(value) * float(scale) for value in values)  # type: ignore[return-value]


def _lerp_scalar(left: float, right: float, fraction: float) -> float:
    bounded = max(0.0, min(1.0, float(fraction)))
    return float(left) + (float(right) - float(left)) * bounded


def _append_moordyn_history_row(
    rows: list[dict[str, str]],
    *,
    time_s: float,
    fairlead_tension: float,
    max_tension: float,
    fairlead_force: tuple[float | None, float | None, float | None],
    drive_sample: EndpointDriveSample | None = None,
    plough_tension: float | None = None,
    plough_force: tuple[float | None, float | None, float | None] = (None, None, None),
    step_status: str,
) -> None:
    plough_position = drive_sample.plough_position_m if drive_sample else (None, None, None)
    fairlead_position = drive_sample.fairlead_position_m if drive_sample else (None, None, None)
    rows.append(
        {
            "time_s": _csv_number(time_s),
            "plough_x_m": _csv_number(plough_position[0]),
            "plough_y_m": _csv_number(plough_position[1]),
            "plough_z_m": _csv_number(plough_position[2]),
            "fairlead_x_m": _csv_number(fairlead_position[0]),
            "fairlead_y_m": _csv_number(fairlead_position[1]),
            "fairlead_z_m": _csv_number(fairlead_position[2]),
            "line_unstretched_length_m": _csv_number(
                drive_sample.unstretched_length_m if drive_sample else None
            ),
            "fairlead_tension_n": _csv_number(fairlead_tension),
            "plough_tension_n": _csv_number(plough_tension),
            "max_line_tension_n": _csv_number(max_tension),
            "fairlead_force_x_n": _csv_number(fairlead_force[0]),
            "fairlead_force_y_n": _csv_number(fairlead_force[1]),
            "fairlead_force_z_n": _csv_number(fairlead_force[2]),
            "plough_force_x_n": _csv_number(plough_force[0]),
            "plough_force_y_n": _csv_number(plough_force[1]),
            "plough_force_z_n": _csv_number(plough_force[2]),
            "step_status": step_status,
        }
    )


def _write_moordyn_history_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _moordyn_line_node_distribution_rows(
    moordyn,
    line,
    *,
    time_s: float,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    if not hasattr(moordyn, "GetLineNumberNodes"):
        return [], _empty_moordyn_node_distribution_stats(None)
    node_count = int(moordyn.GetLineNumberNodes(line))
    rows: list[dict[str, str]] = []
    contact_indices: list[int] = []
    max_seabed_force = 0.0
    max_seabed_force_node = ""
    denominator = max(1, node_count - 1)
    for index in range(node_count):
        position = _moordyn_line_node_vector(moordyn, line, index, "GetLineNodePos")
        tension = _moordyn_line_node_vector(moordyn, line, index, "GetLineNodeTen")
        seabed_force = _moordyn_line_node_vector(moordyn, line, index, "GetLineNodeSeabedForce")
        net_force = _moordyn_line_node_vector(moordyn, line, index, "GetLineNodeForce")
        tension_magnitude = _vector_magnitude_or_none(tension)
        seabed_magnitude = _vector_magnitude_or_none(seabed_force)
        net_magnitude = _vector_magnitude_or_none(net_force)
        in_contact = seabed_magnitude is not None and seabed_magnitude > 1.0e-6
        if in_contact:
            contact_indices.append(index)
            if seabed_magnitude > max_seabed_force:
                max_seabed_force = seabed_magnitude
                max_seabed_force_node = str(index)
        rows.append(
            {
                "time_s": _csv_number(time_s),
                "node_index": str(index),
                "node_fraction": _csv_number(index / denominator),
                "x_m": _csv_number(position[0]),
                "y_m": _csv_number(position[1]),
                "z_m": _csv_number(position[2]),
                "tension_x_n": _csv_number(tension[0]),
                "tension_y_n": _csv_number(tension[1]),
                "tension_z_n": _csv_number(tension[2]),
                "tension_magnitude_n": _csv_number(tension_magnitude),
                "seabed_force_x_n": _csv_number(seabed_force[0]),
                "seabed_force_y_n": _csv_number(seabed_force[1]),
                "seabed_force_z_n": _csv_number(seabed_force[2]),
                "seabed_force_magnitude_n": _csv_number(seabed_magnitude),
                "net_force_x_n": _csv_number(net_force[0]),
                "net_force_y_n": _csv_number(net_force[1]),
                "net_force_z_n": _csv_number(net_force[2]),
                "net_force_magnitude_n": _csv_number(net_magnitude),
                "contact_status": "contact" if in_contact else "free",
            }
        )
    stats = {
        "moordyn_node_distribution_csv": "",
        "moordyn_node_count": str(node_count),
        "moordyn_seabed_contact_node_count": str(len(contact_indices)),
        "moordyn_first_seabed_contact_node": str(contact_indices[0]) if contact_indices else "",
        "moordyn_last_seabed_contact_node": str(contact_indices[-1]) if contact_indices else "",
        "moordyn_max_node_seabed_force_n": _csv_number(max_seabed_force if contact_indices else None),
        "moordyn_max_node_seabed_force_node": max_seabed_force_node,
    }
    return rows, stats


def _moordyn_line_node_vector(moordyn, line, index: int, getter_name: str) -> tuple[float | None, float | None, float | None]:
    getter = getattr(moordyn, getter_name, None)
    if getter is None:
        return (None, None, None)
    try:
        return _vector_or_empty(getter(line, index))
    except Exception:
        return (None, None, None)


def _write_moordyn_node_distribution_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_NODE_DISTRIBUTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _build_distribution_comparison_rows(
    *,
    project_frame,
    moordyn_node_rows: Sequence[dict[str, str]],
    target_time_s: float,
) -> list[dict[str, str]]:
    """Align project output and MoorDyn node rows by normalized line fraction."""

    selected_moordyn_rows = _nearest_moordyn_rows_at_time(moordyn_node_rows, target_time_s)
    if not selected_moordyn_rows:
        return []

    rows: list[dict[str, str]] = []
    for row in selected_moordyn_rows:
        fraction = _row_float(row, "node_fraction", 0.0)
        project_fraction = 1.0 - fraction
        project_point = _project_frame_point_at_fraction(project_frame, project_fraction)
        project_tension = project_point[3]
        moordyn_tension = _row_float(row, "tension_magnitude_n", 0.0)
        rows.append(
            {
                "time_s": _csv_number(target_time_s),
                "node_index": row.get("node_index", ""),
                "node_fraction": _csv_number(fraction),
                "project_x_m": _csv_number(project_point[0]),
                "project_y_m": _csv_number(project_point[1]),
                "project_z_m": _csv_number(project_point[2]),
                "project_tension_n": _csv_number(project_tension),
                "moordyn_x_m": row.get("x_m", ""),
                "moordyn_y_m": row.get("y_m", ""),
                "moordyn_z_m": row.get("z_m", ""),
                "moordyn_tension_n": _csv_number(moordyn_tension),
                "moordyn_minus_project_tension_n": _csv_number(moordyn_tension - project_tension),
                "moordyn_seabed_force_magnitude_n": row.get("seabed_force_magnitude_n", ""),
                "moordyn_contact_status": row.get("contact_status", ""),
                "notes": (
                    "Validation-only distribution row. Project z is down; MoorDyn z is up. "
                    "MoorDyn node fraction is plough-to-fairlead, so it is reversed before "
                    "aligning to the project fairlead-to-plough frame. Not used as solver feedback."
                ),
            }
        )
    return rows


def _write_distribution_comparison_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DISTRIBUTION_COMPARISON_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _build_distribution_mouth_audit_rows(
    *,
    project_frame,
    project_plough_inlet_tension_n: float,
    project_plough_adjacent_segment_tension_n: float,
    moordyn_node_rows: Sequence[dict[str, str]],
    target_time_s: float,
) -> list[dict[str, str]]:
    """Build an audit table that keeps distribution and endpoint mouths separate."""

    selected_moordyn_rows = _nearest_moordyn_rows_at_time(moordyn_node_rows, target_time_s)
    if not selected_moordyn_rows:
        return []

    rows: list[dict[str, str]] = []
    for row in selected_moordyn_rows:
        moordyn_fraction = _row_float(row, "node_fraction", 0.0)
        project_fraction = 1.0 - moordyn_fraction
        project_point = _project_frame_point_at_fraction(project_frame, project_fraction)
        project_segment_index, project_segment_tension = _project_frame_segment_tension_at_fraction(
            project_frame,
            project_fraction,
        )
        moordyn_tension = _row_float(row, "tension_magnitude_n", 0.0)
        seabed_force = _row_float(row, "seabed_force_magnitude_n", 0.0)
        contact_status = row.get("contact_status", "")
        comparison_mouth, direct_tension_comparison, notes = _distribution_mouth_classification(
            moordyn_fraction=moordyn_fraction,
            seabed_force_n=seabed_force,
            contact_status=contact_status,
        )
        rows.append(
            {
                "time_s": _csv_number(target_time_s),
                "moordyn_node_index": row.get("node_index", ""),
                "moordyn_node_fraction_plough_to_fairlead": _csv_number(moordyn_fraction),
                "project_fraction_fairlead_to_plough": _csv_number(project_fraction),
                "project_x_m": _csv_number(project_point[0]),
                "project_y_m": _csv_number(project_point[1]),
                "project_z_m": _csv_number(project_point[2]),
                "project_segment_index": "" if project_segment_index is None else str(project_segment_index),
                "project_segment_tension_n": _csv_number(project_segment_tension),
                "project_point_tension_n": _csv_number(project_point[3]),
                "project_plough_inlet_tension_n": _csv_number(project_plough_inlet_tension_n),
                "project_plough_adjacent_segment_tension_n": _csv_number(
                    project_plough_adjacent_segment_tension_n
                ),
                "moordyn_x_m": row.get("x_m", ""),
                "moordyn_y_m": row.get("y_m", ""),
                "moordyn_z_m": row.get("z_m", ""),
                "moordyn_node_tension_n": _csv_number(moordyn_tension),
                "moordyn_minus_project_segment_tension_n": _csv_number(
                    None if project_segment_tension is None else moordyn_tension - project_segment_tension
                ),
                "moordyn_seabed_force_magnitude_n": row.get("seabed_force_magnitude_n", ""),
                "moordyn_contact_status": contact_status,
                "comparison_mouth": comparison_mouth,
                "direct_tension_comparison": direct_tension_comparison,
                "notes": notes,
            }
        )
    return rows


def _distribution_mouth_classification(
    *,
    moordyn_fraction: float,
    seabed_force_n: float,
    contact_status: str,
) -> tuple[str, str, str]:
    if moordyn_fraction <= 1.0e-9:
        return (
            "plough_side_node_vs_project_tail_distribution",
            "mouth_mismatch_diagnostic",
            (
                "MoorDyn node 0 is the driven plough-side line node. Compare it as a local "
                "plough-boundary/contact diagnostic, not as a TDP contact-transition scalar."
            ),
        )
    if moordyn_fraction >= 1.0 - 1.0e-9:
        return (
            "fairlead_endpoint_distribution",
            "direct_distribution",
            (
                "Fairlead-side row aligned by normalized fraction. This is a distribution-level "
                "tension comparison, not solver feedback."
            ),
        )
    if contact_status == "contact" or seabed_force_n > 1.0e-6:
        return (
            "contact_distribution",
            "contact_model_diagnostic",
            (
                "Contact row: MoorDyn penalty contact and project XPBD seabed projection are not "
                "identical. Use for contact attribution, not as a scalar inlet proof."
            ),
        )
    return (
        "free_span_distribution",
        "direct_distribution",
        (
            "Free-span row aligned by normalized fraction. This is a distribution-level tension "
            "comparison and is validation-only."
        ),
    )


def _write_distribution_mouth_audit_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DISTRIBUTION_MOUTH_AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _build_distribution_attribution_rows(
    *,
    project_frame,
    project_plough_inlet_tension_n: float,
    project_plough_adjacent_segment_tension_n: float,
    sensitivity_rows: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Summarize MoorDyn sensitivity node distributions by comparable output mouth."""

    project_output_time_s = float(getattr(project_frame, "time_s", 0.0))
    rows: list[dict[str, str]] = []
    for sensitivity in sensitivity_rows:
        status = sensitivity.get("status", "")
        if status != "endpoint_history_ok":
            rows.append(
                _distribution_attribution_empty_row(
                    sensitivity,
                    project_output_time_s=project_output_time_s,
                    status=status or "not_available",
                    notes=(
                        sensitivity.get("notes", "")
                        or "Sensitivity variant did not produce an endpoint-history node distribution."
                    ),
                )
            )
            continue

        window_end_s = _row_float(sensitivity, "window_end_s", math.nan)
        if not math.isfinite(window_end_s) or abs(window_end_s - project_output_time_s) > 1.0e-6:
            rows.append(
                _distribution_attribution_empty_row(
                    sensitivity,
                    project_output_time_s=project_output_time_s,
                    status="window_not_matching_project_output_time",
                    notes=(
                        f"window_end_s={sensitivity.get('window_end_s', '')} is not equal to "
                        f"project output time {_csv_number(project_output_time_s)}; do not mix "
                        "a sensitivity replay window with a different physical output frame."
                    ),
                )
            )
            continue

        node_distribution_csv = sensitivity.get("node_distribution_csv", "")
        if not node_distribution_csv:
            rows.append(
                _distribution_attribution_empty_row(
                    sensitivity,
                    project_output_time_s=project_output_time_s,
                    status="missing_node_distribution_csv",
                    notes="Sensitivity row has no node_distribution_csv path.",
                )
            )
            continue

        target_time_s = _row_float(sensitivity, "duration_s", math.nan)
        if not math.isfinite(target_time_s):
            rows.append(
                _distribution_attribution_empty_row(
                    sensitivity,
                    project_output_time_s=project_output_time_s,
                    status="missing_distribution_target_time",
                    notes="Sensitivity row has no completed local duration for node-distribution lookup.",
                )
            )
            continue

        audit_rows = _build_distribution_mouth_audit_rows(
            project_frame=project_frame,
            project_plough_inlet_tension_n=project_plough_inlet_tension_n,
            project_plough_adjacent_segment_tension_n=project_plough_adjacent_segment_tension_n,
            moordyn_node_rows=_read_csv_rows(Path(node_distribution_csv)),
            target_time_s=target_time_s,
        )
        if not audit_rows:
            rows.append(
                _distribution_attribution_empty_row(
                    sensitivity,
                    project_output_time_s=project_output_time_s,
                    status="missing_node_distribution_time",
                    notes=(
                        f"Node distribution did not contain local time {_csv_number(target_time_s)}; "
                        "no mouth-aligned distribution summary was produced."
                    ),
                )
            )
            continue

        rows.append(
            _distribution_attribution_summary_row(
                sensitivity,
                project_output_time_s=project_output_time_s,
                target_time_s=target_time_s,
                audit_rows=audit_rows,
            )
        )
    return rows


def _distribution_attribution_summary_row(
    sensitivity: dict[str, str],
    *,
    project_output_time_s: float,
    target_time_s: float,
    audit_rows: Sequence[dict[str, str]],
) -> dict[str, str]:
    direct_rows = [row for row in audit_rows if row["direct_tension_comparison"] == "direct_distribution"]
    free_span_rows = [row for row in audit_rows if row["comparison_mouth"] == "free_span_distribution"]
    fairlead_rows = [row for row in audit_rows if row["comparison_mouth"] == "fairlead_endpoint_distribution"]
    contact_rows = [row for row in audit_rows if row["direct_tension_comparison"] == "contact_model_diagnostic"]
    mouth_mismatch_rows = [
        row for row in audit_rows if row["direct_tension_comparison"] == "mouth_mismatch_diagnostic"
    ]
    direct_stats = _distribution_delta_stats(direct_rows)
    free_span_stats = _distribution_delta_stats(free_span_rows)
    contact_stats = _distribution_delta_stats(contact_rows)
    max_seabed_force = _distribution_max_value(contact_rows, "moordyn_seabed_force_magnitude_n")
    fairlead_delta = _distribution_first_delta(fairlead_rows)
    mouth_mismatch_delta = _distribution_first_delta(mouth_mismatch_rows)
    return {
        "variant_id": sensitivity.get("variant_id", ""),
        "category": sensitivity.get("category", ""),
        "changed_parameter": sensitivity.get("changed_parameter", ""),
        "status": "ok",
        "window_start_s": sensitivity.get("window_start_s", ""),
        "window_end_s": sensitivity.get("window_end_s", ""),
        "dynamic_history_window_s": _sensitivity_history_window_label(sensitivity),
        "initialization_scope": "fresh_moordyn_static_zero_velocity_at_window_start",
        "project_output_time_s": _csv_number(project_output_time_s),
        "distribution_target_time_s": _csv_number(target_time_s),
        "node_distribution_csv": sensitivity.get("node_distribution_csv", ""),
        "direct_distribution_count": str(len(direct_rows)),
        "direct_delta_min_n": _csv_number(direct_stats[0]),
        "direct_delta_max_n": _csv_number(direct_stats[1]),
        "direct_delta_avg_n": _csv_number(direct_stats[2]),
        "free_span_distribution_count": str(len(free_span_rows)),
        "free_span_delta_avg_n": _csv_number(free_span_stats[2]),
        "fairlead_delta_n": _csv_number(fairlead_delta),
        "contact_model_count": str(len(contact_rows)),
        "contact_delta_max_n": _csv_number(contact_stats[1]),
        "contact_delta_avg_n": _csv_number(contact_stats[2]),
        "max_seabed_force_n": _csv_number(max_seabed_force),
        "mouth_mismatch_delta_n": _csv_number(mouth_mismatch_delta),
        "notes": (
            "Validation-only summary of the sensitivity node-distribution CSV at the local replay "
            "end time, compared to the project output frame with the same physical window end."
        ),
    }


def _distribution_attribution_empty_row(
    sensitivity: dict[str, str],
    *,
    project_output_time_s: float,
    status: str,
    notes: str,
) -> dict[str, str]:
    return {
        "variant_id": sensitivity.get("variant_id", ""),
        "category": sensitivity.get("category", ""),
        "changed_parameter": sensitivity.get("changed_parameter", ""),
        "status": status,
        "window_start_s": sensitivity.get("window_start_s", ""),
        "window_end_s": sensitivity.get("window_end_s", ""),
        "dynamic_history_window_s": _sensitivity_history_window_label(sensitivity),
        "initialization_scope": (
            "fresh_moordyn_static_zero_velocity_at_window_start"
            if sensitivity.get("status", "") == "endpoint_history_ok"
            else ""
        ),
        "project_output_time_s": _csv_number(project_output_time_s),
        "distribution_target_time_s": sensitivity.get("duration_s", ""),
        "node_distribution_csv": sensitivity.get("node_distribution_csv", ""),
        "direct_distribution_count": "",
        "direct_delta_min_n": "",
        "direct_delta_max_n": "",
        "direct_delta_avg_n": "",
        "free_span_distribution_count": "",
        "free_span_delta_avg_n": "",
        "fairlead_delta_n": "",
        "contact_model_count": "",
        "contact_delta_max_n": "",
        "contact_delta_avg_n": "",
        "max_seabed_force_n": "",
        "mouth_mismatch_delta_n": "",
        "notes": notes,
    }


def _sensitivity_history_window_label(sensitivity: dict[str, str]) -> str:
    start_s = sensitivity.get("window_start_s", "")
    end_s = sensitivity.get("window_end_s", "")
    return f"{start_s}..{end_s}" if start_s or end_s else ""


def _distribution_delta_stats(rows: Sequence[dict[str, str]]) -> tuple[float | None, float | None, float | None]:
    values = _distribution_values(rows, "moordyn_minus_project_segment_tension_n")
    if not values:
        return None, None, None
    return min(values), max(values), sum(values) / len(values)


def _distribution_first_delta(rows: Sequence[dict[str, str]]) -> float | None:
    values = _distribution_values(rows, "moordyn_minus_project_segment_tension_n")
    return values[0] if values else None


def _distribution_max_value(rows: Sequence[dict[str, str]], field: str) -> float | None:
    values = _distribution_values(rows, field)
    return max(values) if values else None


def _distribution_values(rows: Sequence[dict[str, str]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _row_float(row, field, math.nan)
        if math.isfinite(value):
            values.append(value)
    return values


def _write_distribution_attribution_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DISTRIBUTION_ATTRIBUTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _nearest_moordyn_rows_at_time(
    rows: Sequence[dict[str, str]],
    target_time_s: float,
    *,
    tolerance_s: float = 1.0e-6,
) -> list[dict[str, str]]:
    if not rows:
        return []
    times = sorted({_row_float(row, "time_s", 0.0) for row in rows})
    selected_time = min(times, key=lambda time_s: abs(time_s - target_time_s))
    if abs(selected_time - target_time_s) > tolerance_s:
        return []
    selected = [row for row in rows if abs(_row_float(row, "time_s", 0.0) - selected_time) <= 1.0e-9]
    return sorted(selected, key=lambda row: _row_float(row, "node_fraction", 0.0))


def _project_frame_point_at_fraction(project_frame, fraction: float) -> tuple[float, float, float, float]:
    points = tuple(getattr(project_frame, "points", ()))
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    if len(points) == 1:
        point = points[0]
        return (
            float(getattr(point, "x_m", 0.0)),
            float(getattr(point, "y_m", 0.0)),
            float(getattr(point, "z_m", 0.0)),
            float(getattr(point, "tension_n", 0.0)),
        )

    arc = [0.0]
    for start, end in zip(points, points[1:]):
        start_xyz = (
            float(getattr(start, "x_m", 0.0)),
            float(getattr(start, "y_m", 0.0)),
            float(getattr(start, "z_m", 0.0)),
        )
        end_xyz = (
            float(getattr(end, "x_m", 0.0)),
            float(getattr(end, "y_m", 0.0)),
            float(getattr(end, "z_m", 0.0)),
        )
        arc.append(arc[-1] + _distance(start_xyz, end_xyz))
    total = arc[-1]
    if total <= 1.0e-12:
        scaled_index = max(0.0, min(1.0, fraction)) * (len(points) - 1)
        left_index = min(int(math.floor(scaled_index)), len(points) - 2)
        local_fraction = scaled_index - left_index
    else:
        target_arc = max(0.0, min(1.0, fraction)) * total
        left_index = 0
        while left_index < len(arc) - 2 and arc[left_index + 1] < target_arc:
            left_index += 1
        span = arc[left_index + 1] - arc[left_index]
        local_fraction = 0.0 if span <= 1.0e-12 else (target_arc - arc[left_index]) / span

    left = points[left_index]
    right = points[left_index + 1]
    return (
        _lerp(float(getattr(left, "x_m", 0.0)), float(getattr(right, "x_m", 0.0)), local_fraction),
        _lerp(float(getattr(left, "y_m", 0.0)), float(getattr(right, "y_m", 0.0)), local_fraction),
        _lerp(float(getattr(left, "z_m", 0.0)), float(getattr(right, "z_m", 0.0)), local_fraction),
        _lerp(float(getattr(left, "tension_n", 0.0)), float(getattr(right, "tension_n", 0.0)), local_fraction),
    )


def _project_frame_segment_tension_at_fraction(
    project_frame,
    fraction: float,
) -> tuple[int | None, float | None]:
    points = tuple(getattr(project_frame, "points", ()))
    segment_tensions = tuple(float(tension) for tension in getattr(project_frame, "segment_tensions_n", ()))
    if not segment_tensions:
        return None, None
    if not points or len(points) < 2:
        return 0, segment_tensions[0]

    arc = [0.0]
    for start, end in zip(points, points[1:]):
        start_xyz = (
            float(getattr(start, "x_m", 0.0)),
            float(getattr(start, "y_m", 0.0)),
            float(getattr(start, "z_m", 0.0)),
        )
        end_xyz = (
            float(getattr(end, "x_m", 0.0)),
            float(getattr(end, "y_m", 0.0)),
            float(getattr(end, "z_m", 0.0)),
        )
        arc.append(arc[-1] + _distance(start_xyz, end_xyz))

    total = arc[-1]
    if total <= 1.0e-12:
        segment_index = int(math.floor(max(0.0, min(1.0, fraction)) * len(segment_tensions)))
        segment_index = min(segment_index, len(segment_tensions) - 1)
        return segment_index, segment_tensions[segment_index]

    target_arc = max(0.0, min(1.0, fraction)) * total
    segment_index = 0
    while segment_index < len(arc) - 2 and arc[segment_index + 1] <= target_arc + 1.0e-12:
        segment_index += 1
    segment_index = min(segment_index, len(segment_tensions) - 1)
    return segment_index, segment_tensions[segment_index]


def _lerp(left: float, right: float, fraction: float) -> float:
    return left + (right - left) * fraction


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _build_moordyn_sensitivity_rows(
    snapshot: ValidationSnapshot,
    *,
    output_dir: Path,
    case_name: str,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
    run_moordyn: bool,
    dt_s: float,
    duration_s: float,
    window_start_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
) -> list[dict[str, str]]:
    variants = _moordyn_sensitivity_variants(dt_s)
    if not run_moordyn:
        return [
            _moordyn_sensitivity_row(
                variant=variant,
                row=None,
                baseline=None,
                status="not_run",
                notes="Pass --run-moordyn and --run-moordyn-sensitivity to execute this runtime sensitivity case.",
            )
            for variant in variants
        ]
    if not snapshot.endpoint_drive_samples:
        return [
            _moordyn_sensitivity_row(
                variant=variant,
                row=None,
                baseline=None,
                status="no_project_frames",
                notes="Project output did not provide endpoint frames for sensitivity replay.",
            )
            for variant in variants
        ]
    moordyn = _optional_import("moordyn", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moordyn is None:
        return [
            _moordyn_sensitivity_row(
                variant=variant,
                row=None,
                baseline=None,
                status="dependency_missing",
                notes="Install MoorDyn or pass --extra-pythonpath to run sensitivity replay.",
            )
            for variant in variants
        ]

    runtime_drive_samples = _slice_endpoint_drive_samples(
        snapshot.endpoint_drive_samples,
        start_s=window_start_s,
        duration_s=duration_s,
    )
    runtime_duration_s = _endpoint_drive_window_s(runtime_drive_samples)
    rows: list[dict[str, str]] = []
    baseline_row: dict[str, str] | None = None
    for variant in variants:
        try:
            variant_row = _run_moordyn_endpoint_variant(
                moordyn,
                snapshot,
                output_dir=output_dir / "moordyn_sensitivity" / variant.variant_id,
                case_name=case_name,
                variant_id=variant.variant_id,
                input_options=variant.options,
                dt_s=dt_s,
                duration_s=runtime_duration_s,
                sample_interval_s=sample_interval_s,
                ramp_duration_s=ramp_duration_s,
                drive_samples=runtime_drive_samples,
                window_start_s=window_start_s,
            )
        except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
            rows.append(
                _moordyn_sensitivity_row(
                    variant=variant,
                    row=None,
                    baseline=baseline_row,
                    status="runtime_error",
                    notes=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if variant.variant_id == "baseline":
            baseline_row = variant_row
        rows.append(_moordyn_sensitivity_row(variant=variant, row=variant_row, baseline=baseline_row))
    return rows


def _moordyn_sensitivity_variants(dt_s: float) -> tuple[MoorDynSensitivityVariant, ...]:
    base = MoorDynInputOptions(dt_m_s=dt_s)
    return (
        MoorDynSensitivityVariant("baseline", "baseline", "none", base),
        MoorDynSensitivityVariant(
            "current_off",
            "current",
            "current_scale=0",
            replace(base, variant_id="current_off", current_scale=0.0),
        ),
        MoorDynSensitivityVariant(
            "friction_off",
            "friction",
            "FrictionCoefficient=0",
            replace(base, variant_id="friction_off", seabed_friction_coefficient=0.0),
        ),
        MoorDynSensitivityVariant(
            "contact_soft",
            "contact",
            "kBot/cBot=0.1x",
            replace(
                base,
                variant_id="contact_soft",
                bottom_stiffness_pa_per_m=MOORDYN_BOTTOM_STIFFNESS_PA_PER_M * 0.1,
                bottom_damping_pa_s_per_m=MOORDYN_BOTTOM_DAMPING_PA_S_PER_M * 0.1,
            ),
        ),
        MoorDynSensitivityVariant(
            "contact_stiff",
            "contact",
            "kBot/cBot=10x",
            replace(
                base,
                variant_id="contact_stiff",
                bottom_stiffness_pa_per_m=MOORDYN_BOTTOM_STIFFNESS_PA_PER_M * 10.0,
                bottom_damping_pa_s_per_m=MOORDYN_BOTTOM_DAMPING_PA_S_PER_M * 10.0,
            ),
        ),
        MoorDynSensitivityVariant(
            "damping_low",
            "damping",
            "BA/-zeta=-0.2",
            replace(base, variant_id="damping_low", ba_zeta=-0.2),
        ),
        MoorDynSensitivityVariant(
            "damping_high",
            "damping",
            "BA/-zeta=-1.6",
            replace(base, variant_id="damping_high", ba_zeta=-1.6),
        ),
        MoorDynSensitivityVariant(
            "added_mass_off",
            "added_mass",
            "Ca/CaAx=0",
            replace(base, variant_id="added_mass_off", ca=0.0, ca_ax=0.0),
        ),
        MoorDynSensitivityVariant(
            "added_mass_high",
            "added_mass",
            "Ca/CaAx=2",
            replace(base, variant_id="added_mass_high", ca=2.0, ca_ax=2.0),
        ),
    )


def _build_moordyn_dt_convergence_rows(
    snapshot: ValidationSnapshot,
    *,
    output_dir: Path,
    case_name: str,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
    run_moordyn: bool,
    duration_s: float,
    window_start_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
    dt_values: Sequence[float],
) -> list[dict[str, str]]:
    values = tuple(sorted({float(value) for value in dt_values}, reverse=True))
    if not values:
        return []
    if not run_moordyn:
        return [
            _moordyn_dt_convergence_row(
                dt_s=value,
                row=None,
                reference=None,
                status="not_run",
                notes="Pass --run-moordyn and --run-moordyn-dt-convergence to execute this dt convergence case.",
            )
            for value in values
        ]
    if not snapshot.endpoint_drive_samples:
        return [
            _moordyn_dt_convergence_row(
                dt_s=value,
                row=None,
                reference=None,
                status="no_project_frames",
                notes="Project output did not provide endpoint frames for dt convergence replay.",
            )
            for value in values
        ]
    moordyn = _optional_import("moordyn", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moordyn is None:
        return [
            _moordyn_dt_convergence_row(
                dt_s=value,
                row=None,
                reference=None,
                status="dependency_missing",
                notes="Install MoorDyn or pass --extra-pythonpath to run dt convergence replay.",
            )
            for value in values
        ]

    runtime_drive_samples = _slice_endpoint_drive_samples(
        snapshot.endpoint_drive_samples,
        start_s=window_start_s,
        duration_s=duration_s,
    )
    runtime_duration_s = _endpoint_drive_window_s(runtime_drive_samples)
    runtime_rows: list[tuple[float, dict[str, str]]] = []
    error_rows: list[dict[str, str]] = []
    for value in values:
        variant_id = f"dt_{_dt_label(value)}"
        try:
            runtime_rows.append(
                (
                    value,
                    _run_moordyn_endpoint_variant(
                        moordyn,
                        snapshot,
                        output_dir=output_dir / "moordyn_dt_convergence" / variant_id,
                        case_name=case_name,
                        variant_id=variant_id,
                        input_options=MoorDynInputOptions(variant_id=variant_id, dt_m_s=value),
                        dt_s=value,
                        duration_s=runtime_duration_s,
                        sample_interval_s=sample_interval_s,
                        ramp_duration_s=ramp_duration_s,
                        drive_samples=runtime_drive_samples,
                        window_start_s=window_start_s,
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
            error_rows.append(
                _moordyn_dt_convergence_row(
                    dt_s=value,
                    row=None,
                    reference=None,
                    status="runtime_error",
                    notes=f"{type(exc).__name__}: {exc}",
                )
            )
    reference = _dt_convergence_reference_row([row for _, row in runtime_rows])
    rows = [
        _moordyn_dt_convergence_row(dt_s=value, row=row, reference=reference)
        for value, row in runtime_rows
    ]
    rows.extend(error_rows)
    return rows


def _build_moordyn_fairlead_attribution_rows(
    snapshot: ValidationSnapshot,
    *,
    output_dir: Path,
    case_name: str,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
    run_moordyn: bool,
    dt_s: float,
    duration_s: float,
    window_start_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
) -> list[dict[str, str]]:
    variants = _moordyn_fairlead_attribution_variants(dt_s)
    if not run_moordyn:
        return [
            _moordyn_fairlead_attribution_row(
                variant=variant,
                row=None,
                baseline=None,
                project_reference_time_s=window_start_s + max(0.0, duration_s),
                project_reference_fairlead_tension_n=_project_fairlead_tension_at(
                    snapshot,
                    window_start_s + max(0.0, duration_s),
                ),
                status="not_run",
                notes="Pass --run-moordyn and --run-moordyn-fairlead-attribution to execute this fairlead attribution case.",
            )
            for variant in variants
        ]
    if not snapshot.endpoint_drive_samples:
        return [
            _moordyn_fairlead_attribution_row(
                variant=variant,
                row=None,
                baseline=None,
                project_reference_time_s=window_start_s + max(0.0, duration_s),
                project_reference_fairlead_tension_n=None,
                status="no_project_frames",
                notes="Project output did not provide endpoint frames for fairlead attribution replay.",
            )
            for variant in variants
        ]
    moordyn = _optional_import("moordyn", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moordyn is None:
        return [
            _moordyn_fairlead_attribution_row(
                variant=variant,
                row=None,
                baseline=None,
                project_reference_time_s=window_start_s + max(0.0, duration_s),
                project_reference_fairlead_tension_n=_project_fairlead_tension_at(
                    snapshot,
                    window_start_s + max(0.0, duration_s),
                ),
                status="dependency_missing",
                notes="Install MoorDyn or pass --extra-pythonpath to run fairlead attribution replay.",
            )
            for variant in variants
        ]

    base_drive_samples = _slice_endpoint_drive_samples(
        snapshot.endpoint_drive_samples,
        start_s=window_start_s,
        duration_s=duration_s,
    )
    runtime_duration_s = _endpoint_drive_window_s(base_drive_samples)
    project_reference_time_s = window_start_s + runtime_duration_s
    project_reference_fairlead_tension_n = _project_fairlead_tension_at(snapshot, project_reference_time_s)
    rows: list[dict[str, str]] = []
    baseline_row: dict[str, str] | None = None
    for variant in variants:
        drive_samples = _drive_samples_for_attribution_variant(base_drive_samples, variant.drive_mode)
        try:
            variant_row = _run_moordyn_endpoint_variant(
                moordyn,
                snapshot,
                output_dir=output_dir / "moordyn_fairlead_attribution" / variant.variant_id,
                case_name=case_name,
                variant_id=variant.variant_id,
                input_options=variant.options,
                dt_s=dt_s,
                duration_s=_endpoint_drive_window_s(drive_samples),
                sample_interval_s=sample_interval_s,
                ramp_duration_s=ramp_duration_s,
                drive_samples=drive_samples,
                window_start_s=window_start_s,
            )
        except Exception as exc:  # pragma: no cover - depends on local MoorDyn runtime
            rows.append(
                _moordyn_fairlead_attribution_row(
                    variant=variant,
                    row=None,
                    baseline=baseline_row,
                    project_reference_time_s=project_reference_time_s,
                    project_reference_fairlead_tension_n=project_reference_fairlead_tension_n,
                    status="runtime_error",
                    notes=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if variant.variant_id == "baseline":
            baseline_row = variant_row
        rows.append(
            _moordyn_fairlead_attribution_row(
                variant=variant,
                row=variant_row,
                baseline=baseline_row,
                project_reference_time_s=project_reference_time_s,
                project_reference_fairlead_tension_n=project_reference_fairlead_tension_n,
            )
        )
    return rows


def _moordyn_fairlead_attribution_variants(dt_s: float) -> tuple[MoorDynFairleadAttributionVariant, ...]:
    base = MoorDynInputOptions(dt_m_s=dt_s)
    return (
        MoorDynFairleadAttributionVariant("baseline", "baseline", "none", base),
        MoorDynFairleadAttributionVariant(
            "current_off",
            "current",
            "current_scale=0",
            replace(base, variant_id="current_off", current_scale=0.0),
        ),
        MoorDynFairleadAttributionVariant(
            "current_reversed",
            "current",
            "current_scale=-1",
            replace(base, variant_id="current_reversed", current_scale=-1.0),
        ),
        MoorDynFairleadAttributionVariant(
            "friction_off",
            "friction",
            "FrictionCoefficient=0",
            replace(base, variant_id="friction_off", seabed_friction_coefficient=0.0),
        ),
        MoorDynFairleadAttributionVariant(
            "contact_off",
            "contact",
            "kBot/cBot/FrictionCoefficient=0",
            replace(
                base,
                variant_id="contact_off",
                seabed_friction_coefficient=0.0,
                bottom_stiffness_pa_per_m=0.0,
                bottom_damping_pa_s_per_m=0.0,
                friction_damping=0.0,
            ),
        ),
        MoorDynFairleadAttributionVariant(
            "fixed_length",
            "payout_length",
            "constant unstretched length over replay window",
            replace(base, variant_id="fixed_length"),
            drive_mode="fixed_length",
        ),
        MoorDynFairleadAttributionVariant(
            "fixed_endpoints",
            "endpoint_motion",
            "constant fairlead/plough endpoint positions over replay window",
            replace(base, variant_id="fixed_endpoints"),
            drive_mode="fixed_endpoints",
        ),
        MoorDynFairleadAttributionVariant(
            "frozen_geometry",
            "endpoint_motion_and_length",
            "constant endpoints and unstretched length over replay window",
            replace(base, variant_id="frozen_geometry"),
            drive_mode="frozen_geometry",
        ),
    )


def _run_moordyn_endpoint_variant(
    moordyn,
    snapshot: ValidationSnapshot,
    *,
    output_dir: Path,
    case_name: str,
    variant_id: str,
    input_options: MoorDynInputOptions,
    dt_s: float,
    duration_s: float,
    sample_interval_s: float,
    ramp_duration_s: float,
    drive_samples: Sequence[EndpointDriveSample] | None = None,
    window_start_s: float = 0.0,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / f"{case_name}_{variant_id}_moordyn_endpoint_history.txt"
    history_path = output_dir / f"{case_name}_{variant_id}_moordyn_endpoint_history.csv"
    node_path = output_dir / f"{case_name}_{variant_id}_moordyn_endpoint_nodes.csv"
    current_path = output_dir / "current_profile.txt"
    runtime_drive_samples = tuple(drive_samples) if drive_samples is not None else snapshot.endpoint_drive_samples
    endpoint_seed = runtime_drive_samples[0] if runtime_drive_samples else None
    _write_moordyn_current_profile(snapshot, current_path, input_options=input_options)
    _write_moordyn_input(
        snapshot,
        input_path,
        coupled_fairlead=True,
        coupled_plough=True,
        seed_sample=endpoint_seed,
        input_options=input_options,
    )
    row = _run_moordyn_endpoint_history(
        moordyn,
        input_path=input_path,
        drive_samples=runtime_drive_samples,
        dt_s=dt_s,
        duration_s=duration_s,
        sample_interval_s=sample_interval_s,
        ramp_duration_s=ramp_duration_s,
        history_path=history_path,
        node_distribution_path=node_path,
    )
    row["moordyn_input_path"] = str(input_path)
    row["moordyn_window_start_s"] = _csv_number(window_start_s)
    row["moordyn_window_end_s"] = _csv_number(window_start_s + _endpoint_drive_window_s(runtime_drive_samples))
    return row


def _moordyn_sensitivity_row(
    *,
    variant: MoorDynSensitivityVariant,
    row: dict[str, str] | None,
    baseline: dict[str, str] | None,
    status: str | None = None,
    notes: str = "",
) -> dict[str, str]:
    status_value = status or (row["status"] if row is not None else "")
    return {
        "variant_id": variant.variant_id,
        "category": variant.category,
        "changed_parameter": variant.changed_parameter,
        "status": status_value,
        "dt_s": row.get("moordyn_dt_s", "") if row is not None else "",
        "duration_s": row.get("moordyn_completed_duration_s", "") if row is not None else "",
        "window_start_s": row.get("moordyn_window_start_s", "") if row is not None else "",
        "window_end_s": row.get("moordyn_window_end_s", "") if row is not None else "",
        "fairlead_tension_n": row.get("fairlead_tension_n", "") if row is not None else "",
        "plough_tension_n": row.get("plough_tension_n", "") if row is not None else "",
        "max_line_tension_n": row.get("moordyn_max_line_tension_n", "") if row is not None else "",
        "max_seabed_force_n": row.get("moordyn_max_node_seabed_force_n", "") if row is not None else "",
        "contact_node_count": row.get("moordyn_seabed_contact_node_count", "") if row is not None else "",
        "delta_fairlead_from_baseline_n": _delta_from_baseline(row, baseline, "fairlead_tension_n"),
        "delta_plough_from_baseline_n": _delta_from_baseline(row, baseline, "plough_tension_n"),
        "delta_max_seabed_from_baseline_n": _delta_from_baseline(
            row,
            baseline,
            "moordyn_max_node_seabed_force_n",
        ),
        "input_path": row.get("moordyn_input_path", "") if row is not None else "",
        "history_csv": row.get("moordyn_history_csv", "") if row is not None else "",
        "node_distribution_csv": row.get("moordyn_node_distribution_csv", "") if row is not None else "",
        "notes": notes or (row.get("notes", "") if row is not None else ""),
    }


def _moordyn_dt_convergence_row(
    *,
    dt_s: float,
    row: dict[str, str] | None,
    reference: dict[str, str] | None,
    status: str | None = None,
    notes: str = "",
) -> dict[str, str]:
    reference_dt = reference.get("moordyn_dt_s", "") if reference is not None else ""
    return {
        "dt_s": _csv_number(dt_s),
        "status": status or (row["status"] if row is not None else ""),
        "duration_s": row.get("moordyn_completed_duration_s", "") if row is not None else "",
        "window_start_s": row.get("moordyn_window_start_s", "") if row is not None else "",
        "window_end_s": row.get("moordyn_window_end_s", "") if row is not None else "",
        "fairlead_tension_n": row.get("fairlead_tension_n", "") if row is not None else "",
        "plough_tension_n": row.get("plough_tension_n", "") if row is not None else "",
        "max_line_tension_n": row.get("moordyn_max_line_tension_n", "") if row is not None else "",
        "max_seabed_force_n": row.get("moordyn_max_node_seabed_force_n", "") if row is not None else "",
        "contact_node_count": row.get("moordyn_seabed_contact_node_count", "") if row is not None else "",
        "reference_dt_s": reference_dt,
        "fairlead_delta_from_reference_n": _delta_from_baseline(row, reference, "fairlead_tension_n"),
        "plough_delta_from_reference_n": _delta_from_baseline(row, reference, "plough_tension_n"),
        "max_seabed_delta_from_reference_n": _delta_from_baseline(
            row,
            reference,
            "moordyn_max_node_seabed_force_n",
        ),
        "input_path": row.get("moordyn_input_path", "") if row is not None else "",
        "history_csv": row.get("moordyn_history_csv", "") if row is not None else "",
        "node_distribution_csv": row.get("moordyn_node_distribution_csv", "") if row is not None else "",
        "notes": notes or (row.get("notes", "") if row is not None else ""),
    }


def _build_moordyn_dt_history_convergence_rows(dt_rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    reference = _dt_convergence_reference_row(dt_rows)
    return [_moordyn_dt_history_convergence_row(row, reference) for row in dt_rows]


def _build_moordyn_dt_node_convergence_rows(dt_rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    reference = _dt_convergence_reference_row(dt_rows)
    return [_moordyn_dt_node_convergence_row(row, reference) for row in dt_rows]


def _build_moordyn_initialization_acceptance_rows(
    history_rows: Sequence[dict[str, str]],
    node_rows: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    node_by_dt = {row.get("dt_s", ""): row for row in node_rows}
    return [
        _moordyn_initialization_acceptance_row(history_row, node_by_dt.get(history_row.get("dt_s", ""), {}))
        for history_row in history_rows
    ]


def _dt_convergence_reference_row(dt_rows: Sequence[dict[str, str]]) -> dict[str, str] | None:
    candidates: list[tuple[float, dict[str, str]]] = []
    for row in dt_rows:
        if row.get("status") != "endpoint_history_ok":
            continue
        try:
            dt_s = float(row.get("dt_s") or row.get("moordyn_dt_s", ""))
        except (TypeError, ValueError):
            continue
        candidates.append((dt_s, row))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _moordyn_dt_history_convergence_row(
    row: dict[str, str],
    reference: dict[str, str] | None,
) -> dict[str, str]:
    status = row.get("status", "")
    reference_dt = reference.get("dt_s", "") if reference is not None else row.get("reference_dt_s", "")
    path = Path(row.get("history_csv", ""))
    reference_path = Path(reference.get("history_csv", "")) if reference is not None else Path("")
    base = {
        "dt_s": row.get("dt_s", ""),
        "status": status,
        "reference_dt_s": reference_dt,
        "history_csv": row.get("history_csv", ""),
        "reference_history_csv": reference.get("history_csv", "") if reference is not None else "",
        "sample_count": "",
        "matched_sample_count": "",
        "missing_sample_count": "",
        "reference_only_sample_count": "",
        "max_abs_fairlead_delta_n": "",
        "rms_fairlead_delta_n": "",
        "max_abs_plough_delta_n": "",
        "rms_plough_delta_n": "",
        "max_abs_line_max_delta_n": "",
        "rms_line_max_delta_n": "",
        "max_abs_history_delta_time_s": "",
        "initial_sample_time_s": "",
        "post_initial_matched_sample_count": "",
        "post_initial_max_abs_fairlead_delta_n": "",
        "post_initial_rms_fairlead_delta_n": "",
        "post_initial_max_abs_plough_delta_n": "",
        "post_initial_rms_plough_delta_n": "",
        "post_initial_max_abs_line_max_delta_n": "",
        "post_initial_rms_line_max_delta_n": "",
        "post_initial_max_abs_history_delta_time_s": "",
        "notes": "Sampled scalar-history convergence audit; complements final-scalar dt convergence.",
    }
    if status != "endpoint_history_ok":
        base["notes"] = "No scalar-history convergence comparison because the replay did not complete."
        return base
    if reference is None or not row.get("history_csv") or not reference.get("history_csv", ""):
        base["status"] = "missing_reference_history"
        base["notes"] = "No scalar-history convergence comparison because the reference history CSV is missing."
        return base

    rows_by_time = _history_rows_by_time(_read_csv_rows(path))
    reference_by_time = _history_rows_by_time(_read_csv_rows(reference_path))
    matched_times = sorted(set(rows_by_time).intersection(reference_by_time))
    missing_times = sorted(set(rows_by_time).difference(reference_by_time))
    reference_only_times = sorted(set(reference_by_time).difference(rows_by_time))
    base["sample_count"] = str(len(rows_by_time))
    base["matched_sample_count"] = str(len(matched_times))
    base["missing_sample_count"] = str(len(missing_times))
    base["reference_only_sample_count"] = str(len(reference_only_times))
    if not matched_times:
        base["status"] = "no_matched_history_samples"
        base["notes"] = "No scalar-history samples shared the same time key with the reference dt."
        return base

    initial_time = matched_times[0]
    post_initial_times = [time_s for time_s in matched_times if time_s > initial_time]
    base["initial_sample_time_s"] = _csv_number(initial_time)
    base["post_initial_matched_sample_count"] = str(len(post_initial_times))
    fairlead_deltas = _history_metric_deltas(rows_by_time, reference_by_time, matched_times, "fairlead_tension_n")
    plough_deltas = _history_metric_deltas(rows_by_time, reference_by_time, matched_times, "plough_tension_n")
    line_deltas = _history_metric_deltas(rows_by_time, reference_by_time, matched_times, "max_line_tension_n")
    base["max_abs_fairlead_delta_n"] = _csv_number(_max_abs_delta(fairlead_deltas))
    base["rms_fairlead_delta_n"] = _csv_number(_rms_delta(fairlead_deltas))
    base["max_abs_plough_delta_n"] = _csv_number(_max_abs_delta(plough_deltas))
    base["rms_plough_delta_n"] = _csv_number(_rms_delta(plough_deltas))
    base["max_abs_line_max_delta_n"] = _csv_number(_max_abs_delta(line_deltas))
    base["rms_line_max_delta_n"] = _csv_number(_rms_delta(line_deltas))
    base["max_abs_history_delta_time_s"] = _csv_number(
        _time_of_max_abs_history_delta(
            rows_by_time,
            reference_by_time,
            matched_times,
            ("fairlead_tension_n", "plough_tension_n", "max_line_tension_n"),
        )
    )
    post_initial_fairlead_deltas = _history_metric_deltas(
        rows_by_time,
        reference_by_time,
        post_initial_times,
        "fairlead_tension_n",
    )
    post_initial_plough_deltas = _history_metric_deltas(
        rows_by_time,
        reference_by_time,
        post_initial_times,
        "plough_tension_n",
    )
    post_initial_line_deltas = _history_metric_deltas(
        rows_by_time,
        reference_by_time,
        post_initial_times,
        "max_line_tension_n",
    )
    base["post_initial_max_abs_fairlead_delta_n"] = _csv_number(_max_abs_delta(post_initial_fairlead_deltas))
    base["post_initial_rms_fairlead_delta_n"] = _csv_number(_rms_delta(post_initial_fairlead_deltas))
    base["post_initial_max_abs_plough_delta_n"] = _csv_number(_max_abs_delta(post_initial_plough_deltas))
    base["post_initial_rms_plough_delta_n"] = _csv_number(_rms_delta(post_initial_plough_deltas))
    base["post_initial_max_abs_line_max_delta_n"] = _csv_number(_max_abs_delta(post_initial_line_deltas))
    base["post_initial_rms_line_max_delta_n"] = _csv_number(_rms_delta(post_initial_line_deltas))
    base["post_initial_max_abs_history_delta_time_s"] = _csv_number(
        _time_of_max_abs_history_delta(
            rows_by_time,
            reference_by_time,
            post_initial_times,
            ("fairlead_tension_n", "plough_tension_n", "max_line_tension_n"),
        )
    )
    return base


def _moordyn_dt_node_convergence_row(
    row: dict[str, str],
    reference: dict[str, str] | None,
) -> dict[str, str]:
    status = row.get("status", "")
    reference_dt = reference.get("dt_s", "") if reference is not None else row.get("reference_dt_s", "")
    path = Path(row.get("node_distribution_csv", ""))
    reference_path = Path(reference.get("node_distribution_csv", "")) if reference is not None else Path("")
    base = {
        "dt_s": row.get("dt_s", ""),
        "status": status,
        "reference_dt_s": reference_dt,
        "node_distribution_csv": row.get("node_distribution_csv", ""),
        "reference_node_distribution_csv": reference.get("node_distribution_csv", "") if reference is not None else "",
        "node_sample_count": "",
        "matched_node_sample_count": "",
        "missing_node_sample_count": "",
        "reference_only_node_sample_count": "",
        "max_abs_node_tension_delta_n": "",
        "rms_node_tension_delta_n": "",
        "max_abs_seabed_force_delta_n": "",
        "rms_seabed_force_delta_n": "",
        "max_position_delta_m": "",
        "contact_status_mismatch_count": "",
        "max_abs_node_delta_time_s": "",
        "max_abs_node_delta_node_index": "",
        "initial_sample_time_s": "",
        "post_initial_matched_node_sample_count": "",
        "post_initial_max_abs_node_tension_delta_n": "",
        "post_initial_rms_node_tension_delta_n": "",
        "post_initial_max_abs_seabed_force_delta_n": "",
        "post_initial_rms_seabed_force_delta_n": "",
        "post_initial_max_position_delta_m": "",
        "post_initial_contact_status_mismatch_count": "",
        "post_initial_max_abs_node_delta_time_s": "",
        "post_initial_max_abs_node_delta_node_index": "",
        "notes": "Node-level dt convergence audit at sampled times; complements final-scalar dt convergence.",
    }
    if status != "endpoint_history_ok":
        base["notes"] = "No node-level convergence comparison because the replay did not complete."
        return base
    if reference is None or not row.get("node_distribution_csv") or not reference.get("node_distribution_csv", ""):
        base["status"] = "missing_reference_node_distribution"
        base["notes"] = "No node-level convergence comparison because the reference node CSV is missing."
        return base

    rows_by_key = _node_rows_by_time_and_index(_read_csv_rows(path))
    reference_by_key = _node_rows_by_time_and_index(_read_csv_rows(reference_path))
    matched_keys = sorted(set(rows_by_key).intersection(reference_by_key))
    missing_keys = sorted(set(rows_by_key).difference(reference_by_key))
    reference_only_keys = sorted(set(reference_by_key).difference(rows_by_key))
    base["node_sample_count"] = str(len(rows_by_key))
    base["matched_node_sample_count"] = str(len(matched_keys))
    base["missing_node_sample_count"] = str(len(missing_keys))
    base["reference_only_node_sample_count"] = str(len(reference_only_keys))
    if not matched_keys:
        base["status"] = "no_matched_node_samples"
        base["notes"] = "No node samples shared the same time/index key with the reference dt."
        return base

    initial_time = min(key[0] for key in matched_keys)
    post_initial_keys = [key for key in matched_keys if key[0] > initial_time]
    base["initial_sample_time_s"] = _csv_number(initial_time)
    base["post_initial_matched_node_sample_count"] = str(len(post_initial_keys))
    tension_deltas = _node_metric_deltas(rows_by_key, reference_by_key, matched_keys, "tension_magnitude_n")
    seabed_deltas = _node_metric_deltas(rows_by_key, reference_by_key, matched_keys, "seabed_force_magnitude_n")
    position_deltas = _node_position_deltas(rows_by_key, reference_by_key, matched_keys)
    base["max_abs_node_tension_delta_n"] = _csv_number(_max_abs_delta(tension_deltas))
    base["rms_node_tension_delta_n"] = _csv_number(_rms_delta(tension_deltas))
    base["max_abs_seabed_force_delta_n"] = _csv_number(_max_abs_delta(seabed_deltas))
    base["rms_seabed_force_delta_n"] = _csv_number(_rms_delta(seabed_deltas))
    base["max_position_delta_m"] = _csv_number(max(position_deltas) if position_deltas else None)
    base["contact_status_mismatch_count"] = str(
        sum(1 for key in matched_keys if rows_by_key[key].get("contact_status", "") != reference_by_key[key].get("contact_status", ""))
    )
    max_key = _key_of_max_abs_node_delta(rows_by_key, reference_by_key, matched_keys)
    if max_key is not None:
        base["max_abs_node_delta_time_s"] = _csv_number(max_key[0])
        base["max_abs_node_delta_node_index"] = str(max_key[1])
    post_initial_tension_deltas = _node_metric_deltas(
        rows_by_key,
        reference_by_key,
        post_initial_keys,
        "tension_magnitude_n",
    )
    post_initial_seabed_deltas = _node_metric_deltas(
        rows_by_key,
        reference_by_key,
        post_initial_keys,
        "seabed_force_magnitude_n",
    )
    post_initial_position_deltas = _node_position_deltas(rows_by_key, reference_by_key, post_initial_keys)
    base["post_initial_max_abs_node_tension_delta_n"] = _csv_number(_max_abs_delta(post_initial_tension_deltas))
    base["post_initial_rms_node_tension_delta_n"] = _csv_number(_rms_delta(post_initial_tension_deltas))
    base["post_initial_max_abs_seabed_force_delta_n"] = _csv_number(_max_abs_delta(post_initial_seabed_deltas))
    base["post_initial_rms_seabed_force_delta_n"] = _csv_number(_rms_delta(post_initial_seabed_deltas))
    base["post_initial_max_position_delta_m"] = _csv_number(
        max(post_initial_position_deltas) if post_initial_position_deltas else None
    )
    base["post_initial_contact_status_mismatch_count"] = str(
        sum(
            1
            for key in post_initial_keys
            if rows_by_key[key].get("contact_status", "") != reference_by_key[key].get("contact_status", "")
        )
    )
    post_initial_max_key = _key_of_max_abs_node_delta(rows_by_key, reference_by_key, post_initial_keys)
    if post_initial_max_key is not None:
        base["post_initial_max_abs_node_delta_time_s"] = _csv_number(post_initial_max_key[0])
        base["post_initial_max_abs_node_delta_node_index"] = str(post_initial_max_key[1])
    return base


def _moordyn_initialization_acceptance_row(
    history_row: dict[str, str],
    node_row: dict[str, str],
) -> dict[str, str]:
    status = history_row.get("status", "") or node_row.get("status", "")
    reference_dt_s = history_row.get("reference_dt_s") or node_row.get("reference_dt_s", "")
    initial_time = history_row.get("initial_sample_time_s") or node_row.get("initial_sample_time_s", "")
    history_post_count = history_row.get("post_initial_matched_sample_count", "")
    node_post_count = node_row.get("post_initial_matched_node_sample_count", "")
    is_reference_row = _csv_numbers_equal(history_row.get("dt_s", ""), reference_dt_s)
    history_initial_dominates = _csv_numbers_equal(
        history_row.get("max_abs_history_delta_time_s", ""),
        initial_time,
    )
    node_initial_dominates = _csv_numbers_equal(
        node_row.get("max_abs_node_delta_time_s", ""),
        initial_time,
    )
    has_post_initial = _positive_int_string(history_post_count) or _positive_int_string(node_post_count)
    if status != "endpoint_history_ok":
        classification = "not_evaluated"
        notes = "Replay did not complete, so t=0 acceptance is not evaluated."
        driven_scope = "not_available"
        t0_included = ""
    elif is_reference_row:
        classification = "reference_row"
        notes = (
            "This row is the completed dt reference compared with itself. "
            "Use non-reference rows to judge t=0 acceptance; keep this row as the numerical baseline."
        )
        driven_scope = "reference_row"
        t0_included = "not_applicable"
    elif not has_post_initial:
        classification = "insufficient_post_initial_samples"
        notes = "Only the initialization sample is available; run with later shared samples before accepting driven-history convergence."
        driven_scope = "not_available"
        t0_included = "false"
    elif history_initial_dominates or node_initial_dominates:
        classification = "initialization_sample_dominates_dt_convergence"
        notes = (
            "The largest sampled dt delta occurs at the initialization sample. "
            "Audit t=0 as a separate static/initial-state mouth; use post-initial rows for driven endpoint-history convergence."
        )
        driven_scope = "post_initial_driven_history"
        t0_included = "false"
    else:
        classification = "initialization_sample_not_dominant"
        notes = (
            "The initialization sample does not dominate the sampled dt deltas, but it remains an initial-state mouth "
            "separate from driven endpoint-history convergence."
        )
        driven_scope = "post_initial_driven_history"
        t0_included = "false"
    return {
        "dt_s": history_row.get("dt_s", ""),
        "status": status,
        "reference_dt_s": reference_dt_s,
        "initial_sample_time_s": initial_time,
        "history_including_initial_max_abs_fairlead_delta_n": history_row.get("max_abs_fairlead_delta_n", ""),
        "history_including_initial_max_abs_delta_time_s": history_row.get("max_abs_history_delta_time_s", ""),
        "history_post_initial_sample_count": history_post_count,
        "history_post_initial_max_abs_fairlead_delta_n": history_row.get(
            "post_initial_max_abs_fairlead_delta_n",
            "",
        ),
        "history_post_initial_max_abs_line_max_delta_n": history_row.get(
            "post_initial_max_abs_line_max_delta_n",
            "",
        ),
        "history_post_initial_max_abs_delta_time_s": history_row.get(
            "post_initial_max_abs_history_delta_time_s",
            "",
        ),
        "node_including_initial_max_abs_tension_delta_n": node_row.get("max_abs_node_tension_delta_n", ""),
        "node_including_initial_max_abs_delta_time_s": node_row.get("max_abs_node_delta_time_s", ""),
        "node_including_initial_max_abs_delta_node_index": node_row.get("max_abs_node_delta_node_index", ""),
        "node_post_initial_sample_count": node_post_count,
        "node_post_initial_max_abs_tension_delta_n": node_row.get(
            "post_initial_max_abs_node_tension_delta_n",
            "",
        ),
        "node_post_initial_max_position_delta_m": node_row.get("post_initial_max_position_delta_m", ""),
        "node_post_initial_contact_status_mismatch_count": node_row.get(
            "post_initial_contact_status_mismatch_count",
            "",
        ),
        "t0_included_in_driven_history_acceptance": t0_included,
        "driven_history_acceptance_scope": driven_scope,
        "initial_state_acceptance_scope": "separate_static_initial_state_audit",
        "classification": classification,
        "notes": notes,
    }


def _history_rows_by_time(rows: Sequence[dict[str, str]]) -> dict[float, dict[str, str]]:
    result: dict[float, dict[str, str]] = {}
    for row in rows:
        time_s = _row_float(row, "time_s", math.nan)
        if math.isfinite(time_s):
            result[round(time_s, 9)] = row
    return result


def _node_rows_by_time_and_index(rows: Sequence[dict[str, str]]) -> dict[tuple[float, int], dict[str, str]]:
    result: dict[tuple[float, int], dict[str, str]] = {}
    for row in rows:
        time_s = _row_float(row, "time_s", math.nan)
        index_float = _row_float(row, "node_index", math.nan)
        if math.isfinite(time_s) and math.isfinite(index_float):
            result[(round(time_s, 9), int(index_float))] = row
    return result


def _history_metric_deltas(
    rows_by_time: dict[float, dict[str, str]],
    reference_by_time: dict[float, dict[str, str]],
    times: Sequence[float],
    field: str,
) -> list[float]:
    return _row_metric_deltas(rows_by_time, reference_by_time, times, field)


def _node_metric_deltas(
    rows_by_key: dict[tuple[float, int], dict[str, str]],
    reference_by_key: dict[tuple[float, int], dict[str, str]],
    keys: Sequence[tuple[float, int]],
    field: str,
) -> list[float]:
    return _row_metric_deltas(rows_by_key, reference_by_key, keys, field)


def _row_metric_deltas(
    rows_by_key,
    reference_by_key,
    keys,
    field: str,
) -> list[float]:
    deltas: list[float] = []
    for key in keys:
        value = _row_float(rows_by_key[key], field, math.nan)
        reference_value = _row_float(reference_by_key[key], field, math.nan)
        if math.isfinite(value) and math.isfinite(reference_value):
            deltas.append(value - reference_value)
    return deltas


def _node_position_deltas(
    rows_by_key: dict[tuple[float, int], dict[str, str]],
    reference_by_key: dict[tuple[float, int], dict[str, str]],
    keys: Sequence[tuple[float, int]],
) -> list[float]:
    deltas: list[float] = []
    for key in keys:
        components = []
        for field in ("x_m", "y_m", "z_m"):
            value = _row_float(rows_by_key[key], field, math.nan)
            reference_value = _row_float(reference_by_key[key], field, math.nan)
            if not math.isfinite(value) or not math.isfinite(reference_value):
                components = []
                break
            components.append(value - reference_value)
        if components:
            deltas.append(math.sqrt(sum(component * component for component in components)))
    return deltas


def _max_abs_delta(values: Sequence[float]) -> float | None:
    finite = [abs(value) for value in values if math.isfinite(value)]
    return max(finite) if finite else None


def _rms_delta(values: Sequence[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return None
    return math.sqrt(sum(value * value for value in finite) / len(finite))


def _csv_numbers_equal(left: str, right: str, *, tolerance: float = 1.0e-9) -> bool:
    if left == "" or right == "":
        return False
    try:
        return abs(float(left) - float(right)) <= tolerance
    except ValueError:
        return False


def _positive_int_string(value: str) -> bool:
    try:
        return int(value) > 0
    except ValueError:
        return False


def _time_of_max_abs_history_delta(
    rows_by_time: dict[float, dict[str, str]],
    reference_by_time: dict[float, dict[str, str]],
    times: Sequence[float],
    fields: Sequence[str],
) -> float | None:
    max_time = None
    max_delta = -1.0
    for time_s in times:
        for field in fields:
            value = _row_float(rows_by_time[time_s], field, math.nan)
            reference_value = _row_float(reference_by_time[time_s], field, math.nan)
            if math.isfinite(value) and math.isfinite(reference_value):
                delta = abs(value - reference_value)
                if delta > max_delta:
                    max_delta = delta
                    max_time = time_s
    return max_time


def _key_of_max_abs_node_delta(
    rows_by_key: dict[tuple[float, int], dict[str, str]],
    reference_by_key: dict[tuple[float, int], dict[str, str]],
    keys: Sequence[tuple[float, int]],
) -> tuple[float, int] | None:
    max_key = None
    max_delta = -1.0
    for key in keys:
        for field in ("tension_magnitude_n", "seabed_force_magnitude_n"):
            value = _row_float(rows_by_key[key], field, math.nan)
            reference_value = _row_float(reference_by_key[key], field, math.nan)
            if math.isfinite(value) and math.isfinite(reference_value):
                delta = abs(value - reference_value)
                if delta > max_delta:
                    max_delta = delta
                    max_key = key
    return max_key


def _moordyn_fairlead_attribution_row(
    *,
    variant: MoorDynFairleadAttributionVariant,
    row: dict[str, str] | None,
    baseline: dict[str, str] | None,
    project_reference_time_s: float,
    project_reference_fairlead_tension_n: float | None,
    status: str | None = None,
    notes: str = "",
) -> dict[str, str]:
    fairlead_minus_project = ""
    if row is not None and project_reference_fairlead_tension_n is not None:
        fairlead = _row_float(row, "fairlead_tension_n", math.nan)
        if math.isfinite(fairlead) and math.isfinite(project_reference_fairlead_tension_n):
            fairlead_minus_project = _csv_number(fairlead - project_reference_fairlead_tension_n)
    return {
        "variant_id": variant.variant_id,
        "category": variant.category,
        "changed_input": variant.changed_input,
        "status": status or (row["status"] if row is not None else ""),
        "dt_s": row.get("moordyn_dt_s", "") if row is not None else "",
        "duration_s": row.get("moordyn_completed_duration_s", "") if row is not None else "",
        "window_start_s": row.get("moordyn_window_start_s", "") if row is not None else "",
        "window_end_s": row.get("moordyn_window_end_s", "") if row is not None else "",
        "project_reference_time_s": _csv_number(project_reference_time_s),
        "project_reference_fairlead_tension_n": _csv_number(project_reference_fairlead_tension_n),
        "fairlead_tension_n": row.get("fairlead_tension_n", "") if row is not None else "",
        "fairlead_minus_project_n": fairlead_minus_project,
        "fairlead_delta_from_baseline_n": _delta_from_baseline(row, baseline, "fairlead_tension_n"),
        "plough_tension_n": row.get("plough_tension_n", "") if row is not None else "",
        "max_line_tension_n": row.get("moordyn_max_line_tension_n", "") if row is not None else "",
        "max_seabed_force_n": row.get("moordyn_max_node_seabed_force_n", "") if row is not None else "",
        "contact_node_count": row.get("moordyn_seabed_contact_node_count", "") if row is not None else "",
        "input_path": row.get("moordyn_input_path", "") if row is not None else "",
        "history_csv": row.get("moordyn_history_csv", "") if row is not None else "",
        "node_distribution_csv": row.get("moordyn_node_distribution_csv", "") if row is not None else "",
        "notes": notes or (row.get("notes", "") if row is not None else ""),
    }


def _delta_from_baseline(row: dict[str, str] | None, baseline: dict[str, str] | None, field: str) -> str:
    if row is None or baseline is None:
        return ""
    row_value = _row_float(row, field, math.nan)
    base_value = _row_float(baseline, field, math.nan)
    if not math.isfinite(row_value) or not math.isfinite(base_value):
        return ""
    return _csv_number(row_value - base_value)


def _dt_label(value: float) -> str:
    return f"{float(value):.12g}".replace("-", "m").replace(".", "p")


def _write_moordyn_sensitivity_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_SENSITIVITY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_moordyn_dt_convergence_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_DT_CONVERGENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_moordyn_dt_history_convergence_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_DT_HISTORY_CONVERGENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_moordyn_dt_node_convergence_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_DT_NODE_CONVERGENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_moordyn_initialization_acceptance_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_INITIALIZATION_ACCEPTANCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_moordyn_fairlead_attribution_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOORDYN_FAIRLEAD_ATTRIBUTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _project_fairlead_tension_at(snapshot: ValidationSnapshot, time_s: float) -> float | None:
    samples = tuple(sorted(snapshot.quasi_static_samples, key=lambda sample: sample.time_s))
    if not samples:
        return snapshot.project_top_tension_n
    target = float(time_s)
    if target <= samples[0].time_s:
        return samples[0].project_top_tension_n
    if target >= samples[-1].time_s:
        return samples[-1].project_top_tension_n
    for left, right in zip(samples, samples[1:]):
        if left.time_s <= target <= right.time_s:
            span = right.time_s - left.time_s
            fraction = 0.0 if abs(span) <= 1.0e-12 else (target - left.time_s) / span
            return _lerp_scalar(left.project_top_tension_n, right.project_top_tension_n, fraction)
    return samples[-1].project_top_tension_n


def _drive_samples_for_attribution_variant(
    samples: Sequence[EndpointDriveSample],
    drive_mode: str,
) -> tuple[EndpointDriveSample, ...]:
    base = tuple(samples)
    if not base:
        return ()
    if drive_mode == "baseline":
        return base
    if drive_mode == "fixed_length":
        return _constant_length_drive_samples(base)
    if drive_mode == "fixed_endpoints":
        return _fixed_endpoint_drive_samples(base)
    if drive_mode == "frozen_geometry":
        return _constant_length_drive_samples(_fixed_endpoint_drive_samples(base))
    raise ValueError(f"unknown fairlead attribution drive mode: {drive_mode}")


def _constant_length_drive_samples(samples: Sequence[EndpointDriveSample]) -> tuple[EndpointDriveSample, ...]:
    base = tuple(samples)
    if not base:
        return ()
    length_m = base[0].unstretched_length_m
    return tuple(
        replace(sample, unstretched_length_m=length_m, unstretched_length_rate_mps=0.0)
        for sample in base
    )


def _fixed_endpoint_drive_samples(samples: Sequence[EndpointDriveSample]) -> tuple[EndpointDriveSample, ...]:
    base = tuple(samples)
    if not base:
        return ()
    seed = base[0]
    zero_velocity = (0.0, 0.0, 0.0)
    return tuple(
        replace(
            sample,
            plough_position_m=seed.plough_position_m,
            fairlead_position_m=seed.fairlead_position_m,
            plough_velocity_mps=zero_velocity,
            fairlead_velocity_mps=zero_velocity,
        )
        for sample in base
    )


def _empty_moordyn_node_distribution_stats(path: Path | None) -> dict[str, str]:
    return {
        "moordyn_node_distribution_csv": str(path) if path is not None else "",
        "moordyn_node_count": "",
        "moordyn_seabed_contact_node_count": "",
        "moordyn_first_seabed_contact_node": "",
        "moordyn_last_seabed_contact_node": "",
        "moordyn_max_node_seabed_force_n": "",
        "moordyn_max_node_seabed_force_node": "",
    }


def _vector_magnitude_or_none(values: Iterable[float | None]) -> float | None:
    items = tuple(values)
    if not _all_finite(items):
        return None
    magnitude = math.hypot(*(float(value) for value in items if value is not None))
    return magnitude if math.isfinite(magnitude) else None


def _all_finite(values: Iterable[float | None]) -> bool:
    return all(value is not None and math.isfinite(float(value)) for value in values)


def _optional_import(name: str, *, extra_pythonpath: Sequence[Path], allow_global: bool):
    inserted: list[str] = []
    extra_paths = [str(Path(item).resolve()) for item in extra_pythonpath]
    importlib.invalidate_caches()
    if not allow_global:
        if not extra_paths:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, extra_paths)
        if spec is None:
            return None
    for path in reversed(extra_paths):
        if path not in sys.path:
            sys.path.insert(0, path)
            inserted.append(path)
    cached = sys.modules.get(name)
    if cached is not None and not allow_global and not _module_is_under_paths(cached, extra_paths):
        sys.modules.pop(name, None)
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _module_is_under_paths(module, paths: Sequence[str]) -> bool:
    roots = [Path(path).resolve() for path in paths]
    candidates: list[str] = []
    module_file = getattr(module, "__file__", None)
    if module_file:
        candidates.append(str(module_file))
    module_paths = getattr(module, "__path__", ())
    candidates.extend(str(path) for path in module_paths)
    for candidate in candidates:
        try:
            resolved = Path(candidate).resolve()
        except OSError:
            continue
        if any(resolved == root or resolved.is_relative_to(root) for root in roots):
            return True
    return False


def _write_moordyn_input(
    snapshot: ValidationSnapshot,
    path: Path,
    *,
    coupled_fairlead: bool,
    coupled_plough: bool,
    seed_sample: EndpointDriveSample | None = None,
    input_options: MoorDynInputOptions | None = None,
) -> None:
    options = input_options or MoorDynInputOptions()
    path.parent.mkdir(parents=True, exist_ok=True)
    fairlead_type = "COUPLED" if coupled_fairlead else "FIXED"
    plough_type = "COUPLED" if coupled_plough else "FIXED"
    plough_position = seed_sample.plough_position_m if seed_sample else snapshot.plough_position_m
    fairlead_position = seed_sample.fairlead_position_m if seed_sample else snapshot.fairlead_position_m
    unstretched_length_m = seed_sample.unstretched_length_m if seed_sample else snapshot.suspended_length_m
    mass_per_m = snapshot.weight_air_n_per_m / PROJECT_GRAVITY_MPS2
    lines = [
        "------------------------------ MoorDyn Input File ------------------------------",
        "Generated by backend/scripts/validate_moordyn_moorpy.py",
        "---------------------------------- LINE TYPES ----------------------------------",
        "Name Diam Mass/m EA BA/-zeta EI Cd Ca CdAx CaAx",
        "(name) (m) (kg/m) (N) (N-s/-) (N-m^2) (-) (-) (-) (-)",
        (
            "PROJECT_CABLE "
            f"{snapshot.diameter_m:.12g} {mass_per_m:.12g} {snapshot.axial_stiffness_n:.12g} "
            f"{options.ba_zeta:.12g} {options.ei_n_m2:.12g} "
            f"{snapshot.normal_drag_coefficient:.12g} {options.ca:.12g} "
            f"{snapshot.tangential_drag_coefficient:.12g} {options.ca_ax:.12g}"
        ),
        "------------------------------- POINT PROPERTIES -------------------------------",
        "ID Type X Y Z Mass Volume CdA Ca",
        "(#) (name) (m) (m) (m) (kg) (m^3) (m^2) (-)",
        f"1 {plough_type} {_fmt3(plough_position)} 0 0 0 0",
        f"2 {fairlead_type} {_fmt3(fairlead_position)} 0 0 0 0",
        "------------------------------------ LINES -------------------------------------",
        "ID LineType AttachA AttachB UnstrLen NumSegs Outputs",
        "(#) (name) (#) (#) (m) (-) (-)",
        f"1 PROJECT_CABLE 1 2 {unstretched_length_m:.12g} {snapshot.element_count} p",
        "----------------------------------- OPTIONS ------------------------------------",
        f"{options.dt_m_s:.12g} dtM",
        f"{PROJECT_GRAVITY_MPS2:.12g} g",
        f"{PROJECT_SEAWATER_DENSITY_KG_M3:.12g} rho",
        f"{options.bottom_stiffness_pa_per_m:.12g} kBot",
        f"{options.bottom_damping_pa_s_per_m:.12g} cBot",
        f"{snapshot.water_depth_m:.12g} WtrDpth",
        "1 Currents",
        f"{options.seabed_friction_coefficient:.12g} FrictionCoefficient",
        f"{options.friction_damping:.12g} FricDamp",
        f"{MOORDYN_STATIC_DYNAMIC_FRICTION_SCALE:.12g} StatDynFricScale",
        "5.0 TmaxIC",
        "1.0 CdScaleIC",
        "0.001 threshIC",
        "--------------------------------------------------------------------------------",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_moordyn_current_profile(
    snapshot: ValidationSnapshot,
    path: Path,
    *,
    input_options: MoorDynInputOptions | None = None,
) -> None:
    """Write MoorDyn-C steady current grid input for the shared validation model."""

    options = input_options or MoorDynInputOptions()
    current_x, current_y = _project_current_components(snapshot)
    current_x *= options.current_scale
    current_y *= options.current_scale
    lines = [
        "--------------------- MoorDyn steady currents File ---------------------",
        f"Generated from project current_speed_mps/current_direction_deg; current_scale={options.current_scale:.12g}",
        "z ux uy uz",
        f"{-snapshot.water_depth_m:.12g} {current_x:.12g} {current_y:.12g} 0",
        f"{0.0:.12g} {current_x:.12g} {current_y:.12g} 0",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _project_current_components(snapshot: ValidationSnapshot) -> tuple[float, float]:
    direction = math.radians(snapshot.current_direction_deg)
    return (
        snapshot.current_speed_mps * math.cos(direction),
        snapshot.current_speed_mps * math.sin(direction),
    )


def _build_input_mapping_rows(snapshot: ValidationSnapshot) -> list[dict[str, str]]:
    current_x, current_y = _project_current_components(snapshot)
    mass_per_m = snapshot.weight_air_n_per_m / PROJECT_GRAVITY_MPS2
    buoyancy_n_per_m = PROJECT_SEAWATER_DENSITY_KG_M3 * PROJECT_GRAVITY_MPS2 * math.pi * snapshot.diameter_m**2 / 4.0
    implied_submerged_weight = snapshot.weight_air_n_per_m - buoyancy_n_per_m
    endpoint_seed = snapshot.endpoint_drive_samples[0] if snapshot.endpoint_drive_samples else None
    endpoint_last = snapshot.endpoint_drive_samples[-1] if snapshot.endpoint_drive_samples else None
    endpoint_window = (
        f"{endpoint_seed.time_s:.12g}..{endpoint_last.time_s:.12g} s"
        if endpoint_seed is not None and endpoint_last is not None
        else "no endpoint replay samples"
    )
    rows = [
        _mapping_row("identity", "case_name", snapshot.case_name, "MoorDyn input/report prefix", snapshot.case_name, "matched"),
        _mapping_row(
            "geometry",
            "water_depth_m",
            snapshot.water_depth_m,
            "WtrDpth and current_profile z range",
            snapshot.water_depth_m,
            "matched",
            "Project z-down depth is converted to MoorDyn z-up seabed z=-WtrDpth.",
        ),
        _mapping_row(
            "geometry",
            "final_frame_fairlead_position_m",
            _fmt3(snapshot.fairlead_position_m),
            "static/smoke Point 2 X/Y/Z",
            _fmt3(snapshot.fairlead_position_m),
            "matched",
            "Final-frame z-up coordinate used by the fixed-end static/smoke MoorDyn input.",
        ),
        _mapping_row(
            "geometry",
            "final_frame_plough_position_m",
            _fmt3(snapshot.plough_position_m),
            "static/smoke Point 1 X/Y/Z",
            _fmt3(snapshot.plough_position_m),
            "matched",
            "Final-frame z-up coordinate; the plough is represented as a cable exit point.",
        ),
        _mapping_row(
            "boundary_motion",
            "endpoint_replay_initial_positions",
            (
                f"plough={_fmt3(endpoint_seed.plough_position_m)}; fairlead={_fmt3(endpoint_seed.fairlead_position_m)}"
                if endpoint_seed is not None
                else "no endpoint replay samples"
            ),
            "endpoint-history Point 1/Point 2 initial X/Y/Z",
            (
                f"plough={_fmt3(endpoint_seed.plough_position_m)}; fairlead={_fmt3(endpoint_seed.fairlead_position_m)}"
                if endpoint_seed is not None
                else "none"
            ),
            "matched" if endpoint_seed is not None else "not_available",
            "Endpoint-history input starts from the first replay sample, then Step drives project endpoint samples.",
        ),
        _mapping_row(
            "boundary_motion",
            "endpoint_replay_time_window",
            endpoint_window,
            "coupled Point 1/Point 2 Step positions and velocities",
            endpoint_window,
            "matched" if endpoint_seed is not None else "not_available",
            "This is the time-aligned dynamic comparison scope; final-frame static rows must not be mixed with replay rows.",
        ),
        _mapping_row(
            "geometry",
            "final_frame_suspended_length_m",
            snapshot.suspended_length_m,
            "static/smoke Line UnstrLen",
            snapshot.suspended_length_m,
            "matched",
        ),
        _mapping_row(
            "boundary_motion",
            "endpoint_replay_initial_unstretched_length_m",
            endpoint_seed.unstretched_length_m if endpoint_seed is not None else "no endpoint replay samples",
            "endpoint-history Line UnstrLen seed",
            endpoint_seed.unstretched_length_m if endpoint_seed is not None else "none",
            "matched" if endpoint_seed is not None else "not_available",
            "The endpoint-history driver then applies SetLineUnstretchedLength and SetLineUnstretchedLengthVel.",
        ),
        _mapping_row("geometry", "element_count", snapshot.element_count, "Line NumSegs", snapshot.element_count, "matched"),
        _mapping_row("material", "diameter_m", snapshot.diameter_m, "LineType Diam", snapshot.diameter_m, "matched"),
        _mapping_row("material", "weight_air_n_per_m", snapshot.weight_air_n_per_m, "LineType Mass/m", mass_per_m, "matched"),
        _mapping_row("material", "axial_stiffness_n", snapshot.axial_stiffness_n, "LineType EA", snapshot.axial_stiffness_n, "matched"),
        _mapping_row(
            "material",
            "submerged_weight_n_per_m",
            snapshot.submerged_weight_n_per_m,
            "Mass/m + Diam + rho + g implied submerged weight",
            implied_submerged_weight,
            "matched",
            "MoorDyn derives submerged weight from mass, diameter, water density, and gravity.",
        ),
        _mapping_row(
            "hydrodynamics",
            "normal_drag_coefficient",
            snapshot.normal_drag_coefficient,
            "LineType Cd",
            snapshot.normal_drag_coefficient,
            "matched",
        ),
        _mapping_row(
            "hydrodynamics",
            "tangential_drag_coefficient",
            snapshot.tangential_drag_coefficient,
            "LineType CdAx",
            snapshot.tangential_drag_coefficient,
            "matched",
        ),
        _mapping_row(
            "hydrodynamics",
            "current_speed_mps/current_direction_deg",
            f"{snapshot.current_speed_mps:.12g} m/s @ {snapshot.current_direction_deg:.12g} deg",
            "Currents=1 current_profile.txt ux/uy",
            f"{current_x:.12g}, {current_y:.12g}, 0",
            "matched",
            "Project convention is 0 deg +X and 90 deg +Y; vessel-speed apparent current is not added for known-plough global-current replay.",
        ),
        _mapping_row(
            "contact",
            "water_depth_m seabed plane",
            snapshot.water_depth_m,
            "WtrDpth",
            snapshot.water_depth_m,
            "matched",
            "Both models use a flat seabed for this validation case.",
        ),
        _mapping_row(
            "contact",
            "seabed_friction_coefficient",
            PROJECT_SEABED_FRICTION_COEFFICIENT,
            "FrictionCoefficient",
            PROJECT_SEABED_FRICTION_COEFFICIENT,
            "matched",
            "Project constant is currently private in dynamic_laying; mirrored here for validation traceability.",
        ),
        _mapping_row(
            "contact",
            "XPBD hard seabed projection",
            "z <= water_depth_m hard constraint",
            "kBot/cBot penalty contact",
            f"{MOORDYN_BOTTOM_STIFFNESS_PA_PER_M:.12g}, {MOORDYN_BOTTOM_DAMPING_PA_S_PER_M:.12g}",
            "shared_model_assumption",
            "MoorDyn uses finite penalty contact; project uses hard projection. This is explicit and must be sensitivity-checked before claiming contact-force equivalence.",
        ),
        _mapping_row(
            "boundary_motion",
            "vessel/plough endpoint time history",
            "project frames",
            "coupled Point 2/Point 1 Step positions and velocities",
            "endpoint_history replay",
            "matched",
        ),
        _mapping_row(
            "boundary_motion",
            "payout/suspended_length time history",
            "project suspended_length_m frames",
            "SetLineUnstretchedLength/SetLineUnstretchedLengthVel",
            "endpoint_history replay",
            "matched",
        ),
        _mapping_row(
            "moordyn_only",
            "line structural damping",
            "no project input",
            "LineType BA/-zeta",
            MOORDYN_VALIDATION_BA_ZETA,
            "validation_assumption",
            "MoorDyn numerical damping assumption; not a tuning coefficient for project outputs.",
        ),
        _mapping_row(
            "moordyn_only",
            "added-mass coefficients",
            "no project input",
            "Ca/CaAx",
            f"{MOORDYN_VALIDATION_CA:.12g}, {MOORDYN_VALIDATION_CA_AX:.12g}",
            "validation_assumption",
        ),
        _mapping_row(
            "out_of_scope",
            "plough body/soil/tooling",
            "not modeled by current project shared comparison",
            "none",
            "none",
            "out_of_scope",
            "Current shared model treats the plough as the driven cable exit point only.",
        ),
    ]
    return rows


def _mapping_row(
    category: str,
    project_input: str,
    project_value: object,
    moordyn_target: str,
    moordyn_value: object,
    status: str,
    notes: str = "",
) -> dict[str, str]:
    return {
        "category": category,
        "project_input": project_input,
        "project_value": str(project_value),
        "moordyn_target": moordyn_target,
        "moordyn_value": str(moordyn_value),
        "status": status,
        "notes": notes,
    }


def _write_input_mapping_csv(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INPUT_MAPPING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_geometry_csv(snapshot: ValidationSnapshot, path: Path) -> None:
    rows = [
        ("case_name", snapshot.case_name, "", ""),
        ("length_boundary_source", snapshot.length_boundary_source, "", ""),
        ("water_depth_m", snapshot.water_depth_m, "m", "Project z-down depth converted to z-up for MoorPy/MoorDyn."),
        ("element_count", snapshot.element_count, "-", ""),
        ("fairlead_x_m", snapshot.fairlead_position_m[0], "m", "z-up coordinate"),
        ("fairlead_y_m", snapshot.fairlead_position_m[1], "m", "z-up coordinate"),
        ("fairlead_z_m", snapshot.fairlead_position_m[2], "m", "z-up coordinate"),
        ("plough_x_m", snapshot.plough_position_m[0], "m", "z-up coordinate"),
        ("plough_y_m", snapshot.plough_position_m[1], "m", "z-up coordinate"),
        ("plough_z_m", snapshot.plough_position_m[2], "m", "z-up coordinate"),
        ("endpoint_span_m", snapshot.span_m, "m", ""),
        ("suspended_length_m", snapshot.suspended_length_m, "m", "Used as MoorPy/MoorDyn unstretched length."),
        ("diameter_m", snapshot.diameter_m, "m", ""),
        ("weight_air_n_per_m", snapshot.weight_air_n_per_m, "N/m", ""),
        ("submerged_weight_n_per_m", snapshot.submerged_weight_n_per_m, "N/m", ""),
        ("axial_stiffness_n", snapshot.axial_stiffness_n, "N", ""),
        ("normal_drag_coefficient", snapshot.normal_drag_coefficient, "-", ""),
        ("tangential_drag_coefficient", snapshot.tangential_drag_coefficient, "-", ""),
        ("current_speed_mps", snapshot.current_speed_mps, "m/s", "Documented but not applied in current MoorPy static row."),
        ("current_direction_deg", snapshot.current_direction_deg, "deg", "Project convention: 0 deg +X, 90 deg +Y."),
        (
            "project_plough_endpoint_reaction_n",
            snapshot.project_plough_endpoint_reaction_n,
            "N",
            "Endpoint-adjacent XPBD tail reaction retained for diagnostics; not compared as MoorPy plough tension.",
        ),
        (
            "project_load_recursive_dynamic_top_tension_n",
            snapshot.project_load_recursive_dynamic_top_tension_n,
            "N",
            "Validation-only final-geometry load-recursive top tension with project current, velocity, and payout.",
        ),
        (
            "project_load_recursive_no_current_top_tension_n",
            snapshot.project_load_recursive_no_current_top_tension_n,
            "N",
            "Validation-only final-geometry load-recursive top tension with zero current, velocity, and payout.",
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("field", "value", "unit", "notes"))
        writer.writerows(rows)


def _write_summary_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_gaps_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_frame_scope_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FRAME_SCOPE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_quasi_static_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUASI_STATIC_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_initial_state_static_audit_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INITIAL_STATE_STATIC_AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _build_gap_rows(snapshot: ValidationSnapshot, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    project = next(row for row in rows if row["model"] == "project_known_plough")
    external_rows = [row for row in rows if row["status"] == "ok" and row["model"] != "project_known_plough"]
    external_rows.extend(
        row
        for row in rows
        if row["model"] == "moordyn_endpoint_history"
        and row["status"] == "endpoint_history_ok"
        and _row_float(row, "moordyn_project_window_coverage_percent") >= 99.999
    )
    gaps: list[dict[str, str]] = []
    for external in external_rows:
        for metric in ("fairlead_tension_n", "plough_tension_n"):
            gaps.append(_gap_row(metric, snapshot=snapshot, project=project, external=external))
    return gaps


def _build_initial_state_static_audit_rows(
    summary_rows: list[dict[str, str]],
    frame_scope_rows: list[dict[str, str]],
    quasi_static_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    project = _find_frame_scope_row(
        frame_scope_rows,
        scope_label="project_first_frame",
        model="project_known_plough_frame",
    )
    if project is None:
        return [
            {
                "scope_label": "project_first_frame",
                "time_s": "0",
                "status": "missing_project_initial_frame",
                "project_fairlead_tension_n": "",
                "project_plough_tension_n": "",
                "moorpy_status": "",
                "moorpy_fairlead_tension_n": "",
                "moorpy_plough_tension_n": "",
                "moorpy_fairlead_delta_n": "",
                "moorpy_plough_delta_n": "",
                "closed_form_status": "",
                "closed_form_fairlead_tension_n": "",
                "closed_form_plough_tension_n": "",
                "closed_form_fairlead_delta_n": "",
                "closed_form_plough_delta_n": "",
                "moordyn_endpoint_status": "",
                "moordyn_initial_fairlead_tension_n": "",
                "moordyn_initial_fairlead_delta_from_project_n": "",
                "suspended_length_m": "",
                "span_m": "",
                "static_acceptance_scope": "separate_static_initial_state_audit",
                "classification": "initial_state_static_reference_unavailable",
                "notes": "Project first frame is missing; cannot audit t=0 static initial-state consistency.",
            }
        ]

    closed_form = _find_frame_scope_row(
        frame_scope_rows,
        scope_label="project_first_frame",
        model="closed_form_catenary_same_frame_static",
    )
    quasi_initial = _find_initial_quasi_static_row(quasi_static_rows)
    moorpy_frame = _find_frame_scope_row(
        frame_scope_rows,
        scope_label="project_first_frame",
        model="moorpy_same_frame_static",
    )
    endpoint = next((row for row in summary_rows if row["model"] == "moordyn_endpoint_history"), None)
    project_fairlead = _row_float(project, "fairlead_tension_n", math.nan)
    project_plough = _row_float(project, "plough_tension_n", math.nan)

    moorpy_status = _first_present(
        quasi_initial.get("status") if quasi_initial is not None else "",
        moorpy_frame.get("status") if moorpy_frame is not None else "",
        "not_available",
    )
    moorpy_fairlead = _first_present(
        quasi_initial.get("moorpy_fairlead_tension_n") if quasi_initial is not None else "",
        moorpy_frame.get("fairlead_tension_n") if moorpy_frame is not None else "",
    )
    moorpy_plough = _first_present(
        quasi_initial.get("moorpy_plough_tension_n") if quasi_initial is not None else "",
        moorpy_frame.get("plough_tension_n") if moorpy_frame is not None else "",
    )
    moorpy_fairlead_delta = _first_present(
        quasi_initial.get("fairlead_delta_n") if quasi_initial is not None else "",
        _delta_from_csv_value(moorpy_fairlead, project_fairlead),
    )
    moorpy_plough_delta = _first_present(
        quasi_initial.get("plough_delta_n") if quasi_initial is not None else "",
        _delta_from_csv_value(moorpy_plough, project_plough),
    )

    closed_form_status = closed_form.get("status", "not_available") if closed_form is not None else "not_available"
    closed_form_fairlead = closed_form.get("fairlead_tension_n", "") if closed_form is not None else ""
    closed_form_plough = closed_form.get("plough_tension_n", "") if closed_form is not None else ""
    moordyn_status = endpoint.get("status", "not_available") if endpoint is not None else "not_available"
    moordyn_initial_fairlead = (
        endpoint.get("moordyn_initial_fairlead_tension_n", "") if endpoint is not None else ""
    )
    has_static_reference = any(
        _is_csv_finite(value)
        for value in (moorpy_fairlead, moorpy_plough, closed_form_fairlead, closed_form_plough)
    )
    has_moordyn_initial = _is_csv_finite(moordyn_initial_fairlead)
    classification = (
        "initial_state_static_gap_measured"
        if has_static_reference or has_moordyn_initial
        else "initial_state_static_reference_unavailable"
    )
    notes = [
        "Diagnostic t=0 static initial-state audit; no production correction and no fitted coefficient.",
    ]
    if quasi_initial is not None and quasi_initial.get("notes"):
        notes.append(f"MoorPy quasi-static t=0: {quasi_initial['notes']}")
    elif moorpy_frame is None:
        notes.append("MoorPy same-frame static row is not available.")
    if closed_form is not None and closed_form.get("notes"):
        notes.append(f"Closed-form t=0: {closed_form['notes']}")
    if endpoint is None or not moordyn_initial_fairlead:
        notes.append("MoorDyn initial fairlead tension is available only after endpoint-history replay runs.")
    else:
        notes.append("MoorDyn initial fairlead tension is treated as an initialization-state clue, not driven-history convergence.")

    return [
        {
            "scope_label": "project_first_frame",
            "time_s": project.get("time_s", "0"),
            "status": "ok" if classification == "initial_state_static_gap_measured" else "reference_unavailable",
            "project_fairlead_tension_n": project.get("fairlead_tension_n", ""),
            "project_plough_tension_n": project.get("plough_tension_n", ""),
            "moorpy_status": moorpy_status,
            "moorpy_fairlead_tension_n": moorpy_fairlead,
            "moorpy_plough_tension_n": moorpy_plough,
            "moorpy_fairlead_delta_n": moorpy_fairlead_delta,
            "moorpy_plough_delta_n": moorpy_plough_delta,
            "closed_form_status": closed_form_status,
            "closed_form_fairlead_tension_n": closed_form_fairlead,
            "closed_form_plough_tension_n": closed_form_plough,
            "closed_form_fairlead_delta_n": _delta_from_csv_value(closed_form_fairlead, project_fairlead),
            "closed_form_plough_delta_n": _delta_from_csv_value(closed_form_plough, project_plough),
            "moordyn_endpoint_status": moordyn_status,
            "moordyn_initial_fairlead_tension_n": moordyn_initial_fairlead,
            "moordyn_initial_fairlead_delta_from_project_n": _delta_from_csv_value(
                moordyn_initial_fairlead,
                project_fairlead,
            ),
            "suspended_length_m": project.get("suspended_length_m", ""),
            "span_m": project.get("span_m", ""),
            "static_acceptance_scope": "separate_static_initial_state_audit",
            "classification": classification,
            "notes": "; ".join(notes),
        }
    ]


def _find_frame_scope_row(
    rows: list[dict[str, str]],
    *,
    scope_label: str,
    model: str,
) -> dict[str, str] | None:
    return next((row for row in rows if row["scope_label"] == scope_label and row["model"] == model), None)


def _find_initial_quasi_static_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    return next((row for row in rows if _row_float(row, "time_s", math.nan) == 0.0), None)


def _first_present(*values: str) -> str:
    return next((value for value in values if value != ""), "")


def _is_csv_finite(value: str) -> bool:
    try:
        return math.isfinite(float(value)) if value != "" else False
    except (TypeError, ValueError):
        return False


def _delta_from_csv_value(value: str, baseline: float) -> str:
    if not math.isfinite(baseline) or not _is_csv_finite(value):
        return ""
    return _csv_number(float(value) - baseline)


def _build_frame_scope_rows(
    snapshot: ValidationSnapshot,
    summary_rows: list[dict[str, str]],
    *,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
) -> list[dict[str, str]]:
    rows = [_project_frame_scope_row(sample) for sample in snapshot.frame_scope_samples]
    rows.extend(_closed_form_catenary_frame_scope_rows(snapshot))
    rows.extend(
        _moorpy_frame_scope_rows(
            snapshot,
            extra_pythonpath=extra_pythonpath,
            allow_global=allow_global,
        )
    )
    rows.extend(_moordyn_endpoint_scope_rows(snapshot, summary_rows))
    return rows


def _build_quasi_static_rows(
    snapshot: ValidationSnapshot,
    *,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
) -> list[dict[str, str]]:
    moorpy = _optional_import("moorpy", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moorpy is None:
        return [
            _quasi_static_row(
                sample_index=index,
                sample=sample,
                status="dependency_missing",
                notes=(
                    "Install MoorPy or pass --extra-pythonpath to compute quasi-static same-frame "
                    "references; diagnostic only; not a production correction"
                ),
            )
            for index, sample in enumerate(snapshot.quasi_static_samples)
        ]

    rows: list[dict[str, str]] = []
    for index, sample in enumerate(snapshot.quasi_static_samples):
        try:
            reference = _run_moorpy_static_reference(
                moorpy,
                water_depth_m=snapshot.water_depth_m,
                element_count=snapshot.element_count,
                fairlead_position_m=sample.fairlead_position_m,
                plough_position_m=sample.plough_position_m,
                suspended_length_m=sample.suspended_length_m,
                diameter_m=snapshot.diameter_m,
                weight_air_n_per_m=snapshot.weight_air_n_per_m,
                submerged_weight_n_per_m=snapshot.submerged_weight_n_per_m,
                axial_stiffness_n=snapshot.axial_stiffness_n,
                normal_drag_coefficient=snapshot.normal_drag_coefficient,
                tangential_drag_coefficient=snapshot.tangential_drag_coefficient,
            )
            rows.append(
                _quasi_static_row(
                    sample_index=index,
                    sample=sample,
                    status="ok",
                    moorpy_fairlead_tension_n=reference.fairlead_tension_n,
                    moorpy_plough_tension_n=reference.plough_tension_n,
                    notes=(
                        "MoorPy fixed-end no-current quasi-static reference for this exact project "
                        "output frame; diagnostic only; not a production correction"
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - depends on local MoorPy numerical state
            rows.append(
                _quasi_static_row(
                    sample_index=index,
                    sample=sample,
                    status="failed",
                    notes=f"{type(exc).__name__}: {exc}; diagnostic only",
                )
            )
    return rows


def _quasi_static_row(
    *,
    sample_index: int,
    sample: FrameScopeSample,
    status: str,
    moorpy_fairlead_tension_n: float | None = None,
    moorpy_plough_tension_n: float | None = None,
    notes: str,
) -> dict[str, str]:
    fairlead_delta = (
        moorpy_fairlead_tension_n - sample.project_top_tension_n
        if moorpy_fairlead_tension_n is not None
        else None
    )
    plough_delta = (
        moorpy_plough_tension_n - sample.project_plough_tension_n
        if moorpy_plough_tension_n is not None
        else None
    )
    span = _distance(sample.fairlead_position_m, sample.plough_position_m)
    return {
        "sample_index": str(sample_index),
        "time_s": _csv_number(sample.time_s),
        "model": "moorpy_quasi_static_same_frame",
        "status": status,
        "project_fairlead_tension_n": _csv_number(sample.project_top_tension_n),
        "project_plough_tension_n": _csv_number(sample.project_plough_tension_n),
        "moorpy_fairlead_tension_n": _csv_number(moorpy_fairlead_tension_n),
        "moorpy_plough_tension_n": _csv_number(moorpy_plough_tension_n),
        "fairlead_delta_n": _csv_number(fairlead_delta),
        "plough_delta_n": _csv_number(plough_delta),
        "fairlead_delta_percent": _relative_percent(fairlead_delta, sample.project_top_tension_n),
        "plough_delta_percent": _relative_percent(plough_delta, sample.project_plough_tension_n),
        "suspended_length_m": _csv_number(sample.suspended_length_m),
        "span_m": _csv_number(span),
        "fairlead_x_m": _csv_number(sample.fairlead_position_m[0]),
        "fairlead_y_m": _csv_number(sample.fairlead_position_m[1]),
        "fairlead_z_m": _csv_number(sample.fairlead_position_m[2]),
        "plough_x_m": _csv_number(sample.plough_position_m[0]),
        "plough_y_m": _csv_number(sample.plough_position_m[1]),
        "plough_z_m": _csv_number(sample.plough_position_m[2]),
        "notes": notes,
    }


def _relative_percent(delta: float | None, baseline: float) -> str:
    if delta is None or abs(baseline) <= 1.0e-12:
        return ""
    return f"{100.0 * delta / baseline:.12g}"


def _closed_form_catenary_frame_scope_rows(snapshot: ValidationSnapshot) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for sample in snapshot.frame_scope_samples:
        try:
            reference = _closed_form_catenary_reference(
                fairlead_position_m=sample.fairlead_position_m,
                plough_position_m=sample.plough_position_m,
                suspended_length_m=sample.suspended_length_m,
                submerged_weight_n_per_m=snapshot.submerged_weight_n_per_m,
                water_depth_m=snapshot.water_depth_m,
            )
        except ValueError as exc:
            rows.append(
                _frame_scope_row(
                    scope_label=sample.scope_label,
                    model="closed_form_catenary_same_frame_static",
                    status="unsupported",
                    time_s=sample.time_s,
                    suspended_length_m=sample.suspended_length_m,
                    fairlead_position_m=sample.fairlead_position_m,
                    plough_position_m=sample.plough_position_m,
                    notes=f"{exc}; diagnostic only",
                )
            )
            continue

        rows.append(
            _frame_scope_row(
                scope_label=sample.scope_label,
                model="closed_form_catenary_same_frame_static",
                status="ok",
                time_s=sample.time_s,
                fairlead_tension_n=reference.fairlead_tension_n,
                plough_tension_n=reference.plough_tension_n,
                suspended_length_m=sample.suspended_length_m,
                fairlead_position_m=sample.fairlead_position_m,
                plough_position_m=sample.plough_position_m,
                notes=(
                    "Closed-form inextensible fixed-end no-current catenary for this exact "
                    "project output frame; diagnostic only; no correction factor"
                ),
            )
        )
    return rows


def _closed_form_catenary_reference(
    *,
    fairlead_position_m: tuple[float, float, float],
    plough_position_m: tuple[float, float, float],
    suspended_length_m: float,
    submerged_weight_n_per_m: float,
    water_depth_m: float | None = None,
) -> ClosedFormCatenaryReference:
    if suspended_length_m <= 0.0 or not math.isfinite(suspended_length_m):
        raise ValueError("suspended length must be a positive finite value")
    if submerged_weight_n_per_m <= 0.0 or not math.isfinite(submerged_weight_n_per_m):
        raise ValueError("submerged weight must be a positive finite value")

    horizontal_span_m = math.hypot(
        fairlead_position_m[0] - plough_position_m[0],
        fairlead_position_m[1] - plough_position_m[1],
    )
    vertical_rise_m = fairlead_position_m[2] - plough_position_m[2]
    straight_span_m = math.hypot(horizontal_span_m, vertical_rise_m)
    if horizontal_span_m <= 1.0e-9:
        raise ValueError("horizontal span is too small for the closed-form catenary diagnostic")
    if suspended_length_m <= straight_span_m * (1.0 + 1.0e-12):
        raise ValueError("suspended length is not longer than the straight endpoint distance")
    if abs(vertical_rise_m) >= suspended_length_m:
        raise ValueError("vertical endpoint offset is incompatible with suspended length")

    reduced_length_m = math.sqrt(
        max(suspended_length_m * suspended_length_m - vertical_rise_m * vertical_rise_m, 0.0)
    )
    if reduced_length_m <= horizontal_span_m:
        raise ValueError("suspended length is too short for a sagging catenary")

    catenary_parameter_m = _solve_catenary_parameter(
        horizontal_span_m=horizontal_span_m,
        reduced_length_m=reduced_length_m,
    )
    half_dimensionless_span = horizontal_span_m / (2.0 * catenary_parameter_m)
    mean_dimensionless_height = math.atanh(vertical_rise_m / suspended_length_m)
    plough_argument = mean_dimensionless_height - half_dimensionless_span
    fairlead_argument = mean_dimensionless_height + half_dimensionless_span
    horizontal_tension_n = submerged_weight_n_per_m * catenary_parameter_m
    if water_depth_m is not None:
        lowest_z_m = _closed_form_catenary_lowest_z(
            plough_z_m=plough_position_m[2],
            fairlead_z_m=fairlead_position_m[2],
            catenary_parameter_m=catenary_parameter_m,
            plough_argument=plough_argument,
            fairlead_argument=fairlead_argument,
        )
        if lowest_z_m < -water_depth_m - 1.0e-6:
            raise ValueError(
                "free-span catenary would penetrate seabed; compare against a contact/static model instead"
            )
    return ClosedFormCatenaryReference(
        fairlead_tension_n=horizontal_tension_n * math.cosh(fairlead_argument),
        plough_tension_n=horizontal_tension_n * math.cosh(plough_argument),
        horizontal_tension_n=horizontal_tension_n,
        catenary_parameter_m=catenary_parameter_m,
    )


def _closed_form_catenary_lowest_z(
    *,
    plough_z_m: float,
    fairlead_z_m: float,
    catenary_parameter_m: float,
    plough_argument: float,
    fairlead_argument: float,
) -> float:
    if min(plough_argument, fairlead_argument) <= 0.0 <= max(plough_argument, fairlead_argument):
        return plough_z_m + catenary_parameter_m * (1.0 - math.cosh(plough_argument))
    return min(plough_z_m, fairlead_z_m)


def _solve_catenary_parameter(*, horizontal_span_m: float, reduced_length_m: float) -> float:
    def span_for(parameter_m: float) -> float:
        argument = horizontal_span_m / (2.0 * parameter_m)
        if argument > 700.0:
            return math.inf
        return 2.0 * parameter_m * math.sinh(argument)

    low = max(horizontal_span_m, 1.0e-9) / 1400.0
    high = max(horizontal_span_m, reduced_length_m, 1.0)
    while span_for(high) > reduced_length_m:
        high *= 2.0
        if high > 1.0e18:
            raise ValueError("failed to bracket catenary parameter")

    for _ in range(120):
        mid = 0.5 * (low + high)
        if span_for(mid) > reduced_length_m:
            low = mid
        else:
            high = mid
    return high


def _project_frame_scope_row(sample: FrameScopeSample) -> dict[str, str]:
    return _frame_scope_row(
        scope_label=sample.scope_label,
        model="project_known_plough_frame",
        status="ok",
        time_s=sample.time_s,
        fairlead_tension_n=sample.project_top_tension_n,
        plough_tension_n=sample.project_plough_tension_n,
        suspended_length_m=sample.suspended_length_m,
        fairlead_position_m=sample.fairlead_position_m,
        plough_position_m=sample.plough_position_m,
        notes=sample.notes,
    )


def _moorpy_frame_scope_rows(
    snapshot: ValidationSnapshot,
    *,
    extra_pythonpath: Sequence[Path],
    allow_global: bool,
) -> list[dict[str, str]]:
    moorpy = _optional_import("moorpy", extra_pythonpath=extra_pythonpath, allow_global=allow_global)
    if moorpy is None:
        return []

    rows: list[dict[str, str]] = []
    for sample in snapshot.frame_scope_samples:
        try:
            reference = _run_moorpy_static_reference(
                moorpy,
                water_depth_m=snapshot.water_depth_m,
                element_count=snapshot.element_count,
                fairlead_position_m=sample.fairlead_position_m,
                plough_position_m=sample.plough_position_m,
                suspended_length_m=sample.suspended_length_m,
                diameter_m=snapshot.diameter_m,
                weight_air_n_per_m=snapshot.weight_air_n_per_m,
                submerged_weight_n_per_m=snapshot.submerged_weight_n_per_m,
                axial_stiffness_n=snapshot.axial_stiffness_n,
                normal_drag_coefficient=snapshot.normal_drag_coefficient,
                tangential_drag_coefficient=snapshot.tangential_drag_coefficient,
            )
            rows.append(
                _frame_scope_row(
                    scope_label=sample.scope_label,
                    model="moorpy_same_frame_static",
                    status="ok",
                    time_s=sample.time_s,
                    fairlead_tension_n=reference.fairlead_tension_n,
                    plough_tension_n=reference.plough_tension_n,
                    suspended_length_m=sample.suspended_length_m,
                    fairlead_position_m=sample.fairlead_position_m,
                    plough_position_m=sample.plough_position_m,
                    notes=(
                        "MoorPy fixed-end no-current static reference for this exact project "
                        "output frame; diagnostic only"
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - depends on local MoorPy numerical state
            rows.append(
                _frame_scope_row(
                    scope_label=sample.scope_label,
                    model="moorpy_same_frame_static",
                    status="failed",
                    time_s=sample.time_s,
                    suspended_length_m=sample.suspended_length_m,
                    fairlead_position_m=sample.fairlead_position_m,
                    plough_position_m=sample.plough_position_m,
                    notes=f"{type(exc).__name__}: {exc}",
                )
            )
    return rows


def _moordyn_endpoint_scope_rows(
    snapshot: ValidationSnapshot,
    summary_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    endpoint = next((row for row in summary_rows if row["model"] == "moordyn_endpoint_history"), None)
    if endpoint is None or endpoint["status"] != "endpoint_history_ok":
        return []
    if not endpoint["moordyn_duration_s"]:
        return []
    time_s = float(endpoint.get("moordyn_completed_duration_s") or endpoint["moordyn_duration_s"])
    if snapshot.endpoint_drive_samples:
        drive = _interpolate_endpoint_drive(snapshot.endpoint_drive_samples, time_s)
        fairlead_position = drive.fairlead_position_m
        plough_position = drive.plough_position_m
        suspended_length = drive.unstretched_length_m
    else:
        fairlead_position = snapshot.fairlead_position_m
        plough_position = snapshot.plough_position_m
        suspended_length = snapshot.suspended_length_m
    return [
        _frame_scope_row(
            scope_label="moordyn_endpoint_history_replay_end",
            model="moordyn_endpoint_history",
            status=endpoint["status"],
            time_s=time_s,
            fairlead_tension_n=float(endpoint["fairlead_tension_n"] or 0.0),
            plough_tension_n=float(endpoint["plough_tension_n"] or 0.0),
            suspended_length_m=suspended_length,
            fairlead_position_m=fairlead_position,
            plough_position_m=plough_position,
            notes=(
                "MoorDyn endpoint-history replay end; compare only to a project frame at "
                "the same time, not to the final operation frame unless those times match"
            ),
        )
    ]


def _frame_scope_row(
    *,
    scope_label: str,
    model: str,
    status: str,
    time_s: float,
    fairlead_tension_n: float | None = None,
    plough_tension_n: float | None = None,
    suspended_length_m: float | None = None,
    fairlead_position_m: tuple[float, float, float] | None = None,
    plough_position_m: tuple[float, float, float] | None = None,
    notes: str,
) -> dict[str, str]:
    fairlead_position = fairlead_position_m or (None, None, None)
    plough_position = plough_position_m or (None, None, None)
    span = (
        _distance(fairlead_position_m, plough_position_m)
        if fairlead_position_m is not None and plough_position_m is not None
        else None
    )
    return {
        "scope_label": scope_label,
        "model": model,
        "status": status,
        "time_s": _csv_number(time_s),
        "fairlead_tension_n": _csv_number(fairlead_tension_n),
        "plough_tension_n": _csv_number(plough_tension_n),
        "suspended_length_m": _csv_number(suspended_length_m),
        "span_m": _csv_number(span),
        "fairlead_x_m": _csv_number(fairlead_position[0]),
        "fairlead_y_m": _csv_number(fairlead_position[1]),
        "fairlead_z_m": _csv_number(fairlead_position[2]),
        "plough_x_m": _csv_number(plough_position[0]),
        "plough_y_m": _csv_number(plough_position[1]),
        "plough_z_m": _csv_number(plough_position[2]),
        "notes": notes,
    }


def _gap_row(
    metric: str,
    *,
    snapshot: ValidationSnapshot,
    project: dict[str, str],
    external: dict[str, str],
) -> dict[str, str]:
    project_value = float(project[metric]) if project[metric] else 0.0
    external_value = float(external[metric]) if external[metric] else 0.0
    delta = external_value - project_value
    relative = "" if abs(project_value) <= 1.0e-12 else f"{100.0 * delta / project_value:.12g}"
    if external["model"] == "moordyn_endpoint_history" and metric == "plough_tension_n":
        diagnosis = (
            "full-window dynamic plough-boundary replay gap after matched endpoints, payout, "
            "steady current, flat seabed, and friction; inspect penalty contact, endpoint-force "
            "definition, and line-node distribution before calling this an algorithm error"
        )
    elif external["model"] == "moordyn_endpoint_history" and metric == "fairlead_tension_n":
        diagnosis = (
            "full-window dynamic replay gap after matched endpoints, payout, steady current, flat "
            "seabed, and friction; inspect damping, penalty contact, and endpoint-force definition"
        )
    elif metric == "plough_tension_n" and external["model"] == "moorpy_static":
        diagnosis = (
            "not equivalent input scope: MoorPy no-current static fixed-end tension is compared "
            "with the project dynamic plough-boundary constraint reaction; use same-frame "
            "quasi-static rows and the distribution mouth audit before judging the dynamic solve"
        )
    elif metric == "plough_tension_n":
        tolerance = max(10.0, 0.5 * max(abs(project_value), 1.0))
        if abs(delta) <= tolerance:
            diagnosis = (
                "within current diagnostic tolerance for the plough-boundary constraint reaction"
            )
        elif external_value > project_value:
            diagnosis = (
                "model-closure gap: external endpoint tension exceeds the project plough-boundary "
                "constraint reaction; check contact, friction, and active length definitions"
            )
        else:
            diagnosis = (
                "endpoint reaction gap: project plough-boundary constraint reaction exceeds "
                "external endpoint tension; check seabed contact, friction, and active length definitions"
            )
    elif (
        metric == "fairlead_tension_n"
        and external["model"] == "moorpy_static"
        and abs(snapshot.current_speed_mps) > 1.0e-12
    ):
        diagnosis = (
            "not equivalent input scope: MoorPy no-current static reference is compared with "
            "project current/dynamic production top tension; inspect project_load_recursive_* "
            "diagnostic rows before judging the dynamic algorithm"
        )
    elif metric == "fairlead_tension_n" and abs(delta) > max(10.0, 0.05 * max(abs(project_value), 1.0)):
        diagnosis = "top/fairlead tension gap: check endpoint reaction solve, length, current, and load recursion"
    else:
        diagnosis = "within current diagnostic tolerance"
    return {
        "metric": metric,
        "external_model": external["model"],
        "project_value_n": _csv_number(project_value),
        "external_value_n": _csv_number(external_value),
        "external_minus_project_n": _csv_number(delta),
        "relative_delta_percent": relative,
        "diagnosis": diagnosis,
    }


def _write_report(
    snapshot: ValidationSnapshot,
    rows: list[dict[str, str]],
    gaps: list[dict[str, str]],
    input_path: Path,
    frame_scope_path: Path,
    quasi_static_path: Path,
    initial_state_static_audit_path: Path,
    input_mapping_path: Path,
    sensitivity_path: Path,
    dt_convergence_path: Path,
    dt_history_convergence_path: Path,
    dt_node_convergence_path: Path,
    initialization_acceptance_path: Path,
    fairlead_attribution_path: Path,
    distribution_comparison_path: Path,
    distribution_mouth_audit_path: Path,
    distribution_attribution_path: Path,
    path: Path,
) -> None:
    moorpy = next(row for row in rows if row["model"] == "moorpy_static")
    moordyn = next(row for row in rows if row["model"] == "moordyn_python")
    moordyn_endpoint = next(row for row in rows if row["model"] == "moordyn_endpoint_history")
    project = next(row for row in rows if row["model"] == "project_known_plough")
    project_dynamic = next(row for row in rows if row["model"] == "project_load_recursive_dynamic")
    project_no_current = next(row for row in rows if row["model"] == "project_load_recursive_no_current_static")
    endpoint_requested_s = moordyn_endpoint.get("moordyn_requested_duration_s") or moordyn_endpoint.get(
        "moordyn_duration_s", ""
    )
    endpoint_completed_s = moordyn_endpoint.get("moordyn_completed_duration_s") or moordyn_endpoint.get(
        "moordyn_duration_s", ""
    )
    endpoint_replay_coverage = moordyn_endpoint.get("moordyn_replay_coverage_percent", "")
    endpoint_project_window_s = moordyn_endpoint.get("moordyn_project_window_s", "")
    endpoint_project_window_coverage = moordyn_endpoint.get("moordyn_project_window_coverage_percent", "")
    endpoint_last_history_s = moordyn_endpoint.get("moordyn_last_history_time_s", "")
    endpoint_ramp_duration_s = moordyn_endpoint.get("moordyn_ramp_duration_s", "")
    endpoint_init_mode = moordyn_endpoint.get("moordyn_init_mode", "")
    endpoint_peak_fairlead_time_s = moordyn_endpoint.get("moordyn_peak_fairlead_time_s", "")
    endpoint_peak_plough_time_s = moordyn_endpoint.get("moordyn_peak_plough_time_s", "")
    endpoint_peak_line_time_s = moordyn_endpoint.get("moordyn_peak_line_time_s", "")
    endpoint_node_distribution_csv = moordyn_endpoint.get("moordyn_node_distribution_csv", "")
    endpoint_node_count = moordyn_endpoint.get("moordyn_node_count", "")
    endpoint_contact_node_count = moordyn_endpoint.get("moordyn_seabed_contact_node_count", "")
    endpoint_first_contact_node = moordyn_endpoint.get("moordyn_first_seabed_contact_node", "")
    endpoint_last_contact_node = moordyn_endpoint.get("moordyn_last_seabed_contact_node", "")
    endpoint_max_seabed_force = moordyn_endpoint.get("moordyn_max_node_seabed_force_n", "")
    endpoint_max_seabed_force_node = moordyn_endpoint.get("moordyn_max_node_seabed_force_node", "")
    lines = [
        f"# MoorPy / MoorDyn Validation: {snapshot.case_name}",
        "",
        "## Scope",
        "",
        (
            "This is a validation-layer comparison for `known_plough_trajectory`. "
            "External reference values may be used as diagnostic backfill in validation tables "
            "to locate model gaps; they are not a production correction, not a fitted coefficient, "
            "and not written into solver outputs."
        ),
        "",
        "> Mature-tool values may appear in validation tables to locate gaps; they are not "
        "solver outputs, fitted coefficients, or production corrections.",
        "",
        "## Coordinate And Input Mapping",
        "",
        "- Project coordinates use z down; MoorPy/MoorDyn rows use z up.",
        "- The summary comparison uses the project final frame unless a row explicitly says otherwise.",
        "- MoorPy summary uses the project final suspended length as the unstretched line length.",
        "- The frame-scope audit CSV records first, endpoint-replay, and final project frames separately.",
        "- The current MoorPy summary row is a static no-current catenary reference; current is documented in geometry CSV.",
        "- The generated MoorDyn input uses the same endpoints, length, mass, diameter, EA, drag coefficients, steady current, flat seabed, and friction coefficient where a direct project input exists.",
        "- The endpoint-history MoorDyn input marks both plough and fairlead points as coupled and replays project endpoint samples.",
        f"- The full project-to-MoorDyn input mapping is recorded in `{input_mapping_path.name}`.",
        f"- Initial-state static audit rows are recorded in `{initial_state_static_audit_path.name}`.",
        "- MoorDyn `dtM` is written from the same runtime step size passed to the validation driver, so the standalone input file and `SetDt` call stay aligned.",
        f"- MoorDyn runtime sensitivity rows are recorded in `{sensitivity_path.name}`.",
        f"- MoorDyn time-step convergence rows are recorded in `{dt_convergence_path.name}`.",
        f"- MoorDyn sampled-history dt convergence rows, including post-initial metrics, are recorded in `{dt_history_convergence_path.name}`.",
        f"- MoorDyn sampled-node dt convergence rows, including post-initial metrics, are recorded in `{dt_node_convergence_path.name}`.",
        f"- MoorDyn t=0 initialization acceptance rows are recorded in `{initialization_acceptance_path.name}`.",
        f"- MoorDyn fairlead attribution rows are recorded in `{fairlead_attribution_path.name}`.",
        f"- Project/MoorDyn distribution comparison rows are recorded in `{distribution_comparison_path.name}`.",
        f"- Mouth-aligned distribution audit rows are recorded in `{distribution_mouth_audit_path.name}`.",
        f"- Sensitivity distribution attribution rows are recorded in `{distribution_attribution_path.name}`.",
        "",
        "## Comparison",
        "",
        "| Model | Status | Fairlead tension (N) | Plough tension (N) | Notes |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {model} | {status} | {fairlead} | {plough} | {notes} |".format(
                model=row["model"],
                status=row["status"],
                fairlead=_display_number(row["fairlead_tension_n"]),
                plough=_display_number(row["plough_tension_n"]),
                notes=row["notes"].replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Frame Scope Audit",
            "",
            f"- Frame-scope CSV: `{frame_scope_path.name}`.",
            (
                "- Use this file before judging agreement: project first frame, endpoint-history replay "
                "end frame, and project final frame are different scopes unless their `time_s` values match."
            ),
            (
                "- Closed-form catenary rows are free-span, fixed-end, no-current diagnostics; "
                "they are marked unsupported when the free catenary would penetrate the seabed."
            ),
            "- MoorPy same-frame rows are included there when the optional MoorPy dependency is available.",
            "- MoorDyn endpoint-history rows are short replay diagnostics and must not be compared to the final operation frame by default.",
            "",
            "## Initial-State Static Audit",
            "",
            f"- Initial-state static audit CSV: `{initial_state_static_audit_path.name}`.",
            (
                "- This file compares the project `t=0` frame against same-frame MoorPy static rows "
                "when available, the closed-form free-span catenary diagnostic when supported, and "
                "MoorDyn endpoint-history initialization tension when the replay has actually run."
            ),
            (
                "- Its acceptance scope is `separate_static_initial_state_audit`; it is not part of "
                "post-initial driven-history convergence and it does not feed reference values back "
                "into the project solver."
            ),
            "",
            "## Quasi-Static Time History",
            "",
            f"- Quasi-static CSV: `{quasi_static_path.name}`.",
            (
                "- This file re-solves each project output frame with MoorPy fixed-end no-current "
                "static settings when MoorPy is available, using that frame's endpoints and "
                "suspended length."
            ),
            (
                "- The rows are diagnostic only: they separate static/contact/length-scope "
                "differences from dynamic effects and are not production corrections."
            ),
            "",
        ]
    )
    lines.extend(
        [
            "",
            "## Finding",
            "",
            (
                f"- Project plough-boundary constraint reaction: {_display_number(project['plough_tension_n'])} N; "
                f"project fairlead/top tension: {_display_number(project['fairlead_tension_n'])} N."
            ),
            (
                f"- Project load-recursive dynamic diagnostic top tension: "
                f"{_display_number(project_dynamic['fairlead_tension_n'])} N; no-current static-load "
                f"diagnostic top tension: {_display_number(project_no_current['fairlead_tension_n'])} N."
            ),
            (
                "- These diagnostic rows separate static equilibrium comparison from current/dynamic "
                "production tension and XPBD constraint-reaction diagnostics; they are not MoorPy/MoorDyn "
                "backfill into the solver."
            ),
            (
                f"- Project endpoint-adjacent XPBD tail reaction remains "
                f"{_display_number(snapshot.project_plough_endpoint_reaction_n)} N and is kept as a "
                "separate diagnostic, not as the MoorPy plough-tension comparison value."
            ),
        ]
    )
    if moorpy["status"] == "ok":
        lines.append(
            (
                f"- MoorPy static catenary gives plough-end tension {_display_number(moorpy['plough_tension_n'])} N "
                f"and fairlead tension {_display_number(moorpy['fairlead_tension_n'])} N for the same endpoints and length."
            )
        )
        project_plough = float(project["plough_tension_n"]) if project["plough_tension_n"] else 0.0
        moorpy_plough = float(moorpy["plough_tension_n"]) if moorpy["plough_tension_n"] else 0.0
        if abs(moorpy_plough - project_plough) <= max(10.0, 0.5 * max(abs(project_plough), 1.0)):
            lines.append(
                "- The previous large plough-tension gap came from comparing the endpoint tail reaction with the external static line tension."
            )
        elif project_plough <= 1.0e-9 and moorpy_plough > 1.0e-9:
            lines.append(
                "- The nonzero MoorPy plough-end reaction shows the current project zero plough estimate is a model-closure gap, not a correction-factor target."
            )
        else:
            lines.append(
                "- The remaining plough-tension gap diagnoses contact, friction, active-length assumptions, and load recursion."
            )
    else:
        lines.append(f"- MoorPy did not run: {moorpy['status']} / {moorpy['notes']}")
    lines.extend(
        [
            f"- MoorDyn input file: `{input_path.name}`.",
            "- Do not interpret MoorDyn Python getter zeros before a stable dynamic step as physical line tension.",
        "",
        ]
    )
    if moordyn["status"].startswith("dynamic_smoke"):
        lines.extend(
            [
                "## MoorDyn Runtime Smoke",
                "",
                (
                    f"- Status `{moordyn['status']}` with dt `{moordyn['moordyn_dt_s']}` s, "
                    f"duration `{moordyn['moordyn_duration_s']}` s, steps `{moordyn['moordyn_steps']}`."
                ),
                (
                    f"- Init code `{moordyn['moordyn_init_code']}`; fairlead tension "
                    f"{_display_number(moordyn['moordyn_initial_fairlead_tension_n'])} N -> "
                    f"{_display_number(moordyn['fairlead_tension_n'])} N."
                ),
                (
                    f"- MoorDyn line max tension getter at the last sample: "
                    f"{_display_number(moordyn['moordyn_max_line_tension_n'])} N; peak during replay: "
                    f"{_display_number(moordyn['moordyn_peak_line_tension_n'])} N."
                ),
                f"- Runtime history CSV: `{Path(moordyn['moordyn_history_csv']).name}`.",
                "- This smoke holds the coupled fairlead position fixed; it is not a full vessel/plough/payout replay.",
                "",
            ]
        )
    if moordyn_endpoint["status"].startswith("endpoint_history"):
        lines.extend(
            [
                "## MoorDyn Endpoint History Replay",
                "",
                (
                    f"- Status `{moordyn_endpoint['status']}` with dt `{moordyn_endpoint['moordyn_dt_s']}` s, "
                    f"duration `{moordyn_endpoint['moordyn_duration_s']}` s, "
                    f"steps `{moordyn_endpoint['moordyn_steps']}`."
                ),
                (
                    f"- Replay coverage: requested `{endpoint_requested_s}` s, completed `{endpoint_completed_s}` s "
                    f"(`{endpoint_replay_coverage}`% of request); project window `{endpoint_project_window_s}` s, "
                    f"coverage `{endpoint_project_window_coverage}`%; last history sample `{endpoint_last_history_s}` s."
                ),
                f"- Endpoint drive ramp-in duration: `{endpoint_ramp_duration_s}` s.",
                (
                    f"- Init mode `{endpoint_init_mode}`, code `{moordyn_endpoint['moordyn_init_code']}`; fairlead tension "
                    f"{_display_number(moordyn_endpoint['moordyn_initial_fairlead_tension_n'])} N -> "
                    f"{_display_number(moordyn_endpoint['fairlead_tension_n'])} N."
                ),
                (
                    f"- Last plough-side node tension estimate: "
                    f"{_display_number(moordyn_endpoint['plough_tension_n'])} N; line max tension getter: "
                    f"{_display_number(moordyn_endpoint['moordyn_max_line_tension_n'])} N."
                ),
                (
                    f"- Peak replay tensions: fairlead "
                    f"{_display_number(moordyn_endpoint['moordyn_peak_fairlead_tension_n'])} N "
                    f"at `{endpoint_peak_fairlead_time_s}` s, plough "
                    f"{_display_number(moordyn_endpoint['moordyn_peak_plough_tension_n'])} N "
                    f"at `{endpoint_peak_plough_time_s}` s, line max "
                    f"{_display_number(moordyn_endpoint['moordyn_peak_line_tension_n'])} N "
                    f"at `{endpoint_peak_line_time_s}` s."
                ),
                (
                    "- The endpoint-history input is seeded from the first replay sample and initializes "
                    "MoorDyn with zero coupled-point velocity; project endpoint velocities are applied "
                    "during Step to avoid initialization-stage endpoint pre-advance."
                ),
                f"- Endpoint replay history CSV: `{Path(moordyn_endpoint['moordyn_history_csv']).name}`.",
                (
                    f"- Endpoint node tension/contact history CSV: `{Path(endpoint_node_distribution_csv).name}` "
                    f"samples every recorded replay time; the last sample has `{endpoint_node_count}` nodes, "
                    f"`{endpoint_contact_node_count}` seabed-contact nodes, "
                    f"contact node range `{endpoint_first_contact_node}`..`{endpoint_last_contact_node}`, "
                    f"and max seabed reaction `{_display_number(endpoint_max_seabed_force)}` N at node "
                    f"`{endpoint_max_seabed_force_node}`."
                    if endpoint_node_distribution_csv
                    else "- Endpoint node tension/contact history CSV was not produced by this run."
                ),
                (
                    f"- Project/MoorDyn final-frame distribution comparison CSV: "
                    f"`{distribution_comparison_path.name}`. It aligns rows by normalized line fraction and is "
                    "diagnostic only; it does not feed MoorDyn values back into the project solver."
                ),
                (
                    f"- Mouth-aligned distribution audit CSV: `{distribution_mouth_audit_path.name}`. It lists "
                    "project segment tension, project plough inlet/adjacent diagnostics, MoorDyn node tension, "
                    "and MoorDyn seabed force at the same output time, with a `comparison_mouth` column that "
                    "marks direct distribution rows separately from contact and plough-side mouth-mismatch rows."
                ),
                (
                    f"- Sensitivity distribution attribution CSV: `{distribution_attribution_path.name}`. It "
                    "summarizes each sensitivity node-distribution CSV only when `window_end_s` equals the "
                    "project output frame time, then separates direct free-span/fairlead rows from contact "
                    "and plough-side mouth-mismatch rows. The CSV records the dynamic-history window and "
                    "fresh MoorDyn static initialization scope so it is not confused with full-history continuation."
                ),
                (
                    "- This replay drives both endpoints and the validation-layer unstretched length, "
                    "and the generated input now includes steady current, flat seabed contact, and seabed "
                    "friction for the shared model. It still does not prove full equivalence because "
                    "MoorDyn penalty contact is not identical to the project's XPBD hard projection and "
                    "the plough remains a driven cable-exit point abstraction."
                ),
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## MoorDyn Sensitivity And Convergence Evidence",
            "",
            (
                f"- Runtime sensitivity CSV: `{sensitivity_path.name}`. When enabled, it runs the same endpoint replay "
                "while toggling current, seabed friction, bottom contact stiffness/damping, MoorDyn BA damping, "
                "and added-mass terms."
            ),
            (
                f"- Sensitivity distribution attribution CSV: `{distribution_attribution_path.name}`. It uses "
                "the sensitivity node histories to attribute the remaining distribution gap by output mouth; "
                "rows whose dynamic window does not end at the project output frame are marked as not comparable, "
                "and rows that do compare still carry a fresh window-start static-initialization scope."
            ),
            (
                f"- Time-step convergence CSV: `{dt_convergence_path.name}`. When enabled, it reruns the endpoint replay "
                "at the requested dt values and compares each row with the smallest completed dt as the numerical reference."
            ),
            (
                f"- Sampled-history dt convergence CSV: `{dt_history_convergence_path.name}`. It compares fairlead, "
                "plough-side, and line-max scalar histories at shared sampled times; this extends the final-scalar "
                "dt check, records post-initial metrics that exclude the first shared sample, but still does not by "
                "itself prove every unrecorded internal step."
            ),
            (
                f"- Sampled-node dt convergence CSV: `{dt_node_convergence_path.name}`. It compares same-time, "
                "same-node tension, seabed force, position, and contact-status samples against the smallest stable dt; "
                "post-initial fields separate the initialization sample from the driven-history samples."
            ),
            (
                f"- Initialization acceptance CSV: `{initialization_acceptance_path.name}`. It makes the t=0 policy "
                "machine-readable: the initialization sample is a separate static/initial-state acceptance mouth and is "
                "not included in driven endpoint-history convergence acceptance."
            ),
            (
                f"- Fairlead attribution CSV: `{fairlead_attribution_path.name}`. It keeps the same replay window "
                "and isolates current, seabed friction, seabed contact, payout-length change, endpoint motion, "
                "and frozen-geometry effects against the MoorDyn baseline."
            ),
            "- Sensitivity and convergence rows include `window_start_s`/`window_end_s`; use a contact-bearing window when auditing bottom-contact parameters.",
            (
                "- These files are runtime evidence only: a sensitive parameter does not become a fitted correction, "
                "and an insensitive parameter can be deprioritized when explaining project-vs-MoorDyn differences."
            ),
        ]
    )
    lines.extend(
        [
            "## Diagnostic Backfill Gaps",
            "",
            "| Metric | External model | Project (N) | External (N) | External - project (N) | Diagnosis |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    if gaps:
        for gap in gaps:
            lines.append(
                "| {metric} | {external_model} | {project} | {external} | {delta} | {diagnosis} |".format(
                    metric=gap["metric"],
                    external_model=gap["external_model"],
                    project=_display_number(gap["project_value_n"]),
                    external=_display_number(gap["external_value_n"]),
                    delta=_display_number(gap["external_minus_project_n"]),
                    diagnosis=gap["diagnosis"].replace("|", "/"),
                )
            )
    else:
        lines.append("| n/a | n/a |  |  |  | No external reference row completed. |")
    lines.extend(
        [
            "",
            "## Next Model Work",
            "",
            "1. Use a 100% project-window endpoint replay for final dynamic judgement; shorter runs are stability probes only.",
            "2. Audit MoorDyn penalty-contact sensitivity against the project's XPBD hard-contact projection before interpreting contact-force differences.",
            "3. Compare endpoint force, node tension, seabed/contact force, TDP position, and node coordinates over the full operation window.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(
    *,
    model: str,
    status: str,
    fairlead_tension_n: float | None = None,
    plough_tension_n: float | None = None,
    fairlead_force: Iterable[float] | None = None,
    plough_force: Iterable[float] | None = None,
    notes: str = "",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    fairlead = _vector_or_empty(fairlead_force)
    plough = _vector_or_empty(plough_force)
    row = {
        "model": model,
        "status": status,
        "fairlead_tension_n": _csv_number(fairlead_tension_n),
        "plough_tension_n": _csv_number(plough_tension_n),
        "fairlead_force_x_n": _csv_number(fairlead[0]),
        "fairlead_force_y_n": _csv_number(fairlead[1]),
        "fairlead_force_z_n": _csv_number(fairlead[2]),
        "plough_force_x_n": _csv_number(plough[0]),
        "plough_force_y_n": _csv_number(plough[1]),
        "plough_force_z_n": _csv_number(plough[2]),
        "notes": notes,
    }
    if extra:
        row.update(extra)
    return row


def _to_z_up(x: float, y: float, z_down: float) -> tuple[float, float, float]:
    return (float(x), float(y), -float(z_down))


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((aa - bb) ** 2 for aa, bb in zip(a, b)))


def _fmt3(values: tuple[float, float, float]) -> str:
    return " ".join(f"{value:.12g}" for value in values)


def _vector_or_empty(values: Iterable[float] | None) -> tuple[float | None, float | None, float | None]:
    if values is None:
        return (None, None, None)
    items = list(values)
    return (
        float(items[0]) if len(items) > 0 else None,
        float(items[1]) if len(items) > 1 else None,
        float(items[2]) if len(items) > 2 else None,
    )


def _csv_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.12g}"


def _row_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, "")
        return float(value) if value != "" else float(default)
    except (TypeError, ValueError):
        return float(default)


def _display_number(value: str) -> str:
    if not value:
        return ""
    return f"{float(value):.3f}"


def _parse_float_list(value: str) -> tuple[float, ...]:
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        raise argparse.ArgumentTypeError("expected at least one comma-separated float")
    parsed: list[float] = []
    for item in items:
        try:
            parsed.append(float(item))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid float value: {item}") from exc
    return tuple(parsed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BACKEND_ROOT / "output" / "mooring_validation")
    parser.add_argument("--case", default="plough_straight_baseline_6min")
    parser.add_argument("--points", type=int, default=7)
    parser.add_argument("--extra-pythonpath", type=Path, action="append", default=[])
    parser.add_argument("--run-moordyn", action="store_true")
    parser.add_argument("--moordyn-dt", type=float, default=1.0e-4)
    parser.add_argument("--moordyn-duration", type=float, default=1.0)
    parser.add_argument("--moordyn-sample-interval", type=float, default=0.01)
    parser.add_argument("--moordyn-ramp-duration", type=float, default=0.0)
    parser.add_argument("--run-moordyn-sensitivity", action="store_true")
    parser.add_argument("--moordyn-sensitivity-duration", type=float, default=None)
    parser.add_argument("--moordyn-sensitivity-start", type=float, default=0.0)
    parser.add_argument("--run-moordyn-dt-convergence", action="store_true")
    parser.add_argument("--moordyn-dt-convergence-duration", type=float, default=None)
    parser.add_argument("--moordyn-dt-convergence-start", type=float, default=0.0)
    parser.add_argument("--moordyn-dt-values", type=_parse_float_list, default=(2.0e-4, 1.0e-4, 5.0e-5))
    parser.add_argument("--run-moordyn-fairlead-attribution", action="store_true")
    parser.add_argument("--moordyn-fairlead-attribution-duration", type=float, default=None)
    parser.add_argument("--moordyn-fairlead-attribution-start", type=float, default=0.0)
    args = parser.parse_args(argv)
    report = run_validation(
        args.output,
        case_name=args.case,
        points=args.points,
        extra_pythonpath=tuple(args.extra_pythonpath),
        run_moordyn=args.run_moordyn,
        moordyn_dt_s=args.moordyn_dt,
        moordyn_duration_s=args.moordyn_duration,
        moordyn_sample_interval_s=args.moordyn_sample_interval,
        moordyn_ramp_duration_s=args.moordyn_ramp_duration,
        run_moordyn_sensitivity=args.run_moordyn_sensitivity,
        moordyn_sensitivity_duration_s=args.moordyn_sensitivity_duration,
        moordyn_sensitivity_start_s=args.moordyn_sensitivity_start,
        run_moordyn_dt_convergence=args.run_moordyn_dt_convergence,
        moordyn_dt_convergence_duration_s=args.moordyn_dt_convergence_duration,
        moordyn_dt_convergence_start_s=args.moordyn_dt_convergence_start,
        moordyn_dt_convergence_values=args.moordyn_dt_values,
        run_moordyn_fairlead_attribution=args.run_moordyn_fairlead_attribution,
        moordyn_fairlead_attribution_duration_s=args.moordyn_fairlead_attribution_duration,
        moordyn_fairlead_attribution_start_s=args.moordyn_fairlead_attribution_start,
        allow_global_optional_deps=True,
    )
    print(f"Validation summary: {report['summary_csv']}")
    print(f"Diagnostic gaps: {report['gaps_csv']}")
    print(f"Frame scope audit: {report['frame_scope_csv']}")
    print(f"Quasi-static time history: {report['quasi_static_csv']}")
    print(f"Initial-state static audit: {report['initial_state_static_audit_csv']}")
    print(f"MoorDyn input mapping: {report['input_mapping_csv']}")
    print(f"MoorDyn runtime sensitivity: {report['moordyn_sensitivity_csv']}")
    print(f"MoorDyn dt convergence: {report['moordyn_dt_convergence_csv']}")
    print(f"MoorDyn dt history convergence: {report['moordyn_dt_history_convergence_csv']}")
    print(f"MoorDyn dt node convergence: {report['moordyn_dt_node_convergence_csv']}")
    print(f"MoorDyn initialization acceptance: {report['moordyn_initialization_acceptance_csv']}")
    print(f"MoorDyn fairlead attribution: {report['moordyn_fairlead_attribution_csv']}")
    print(f"Distribution comparison: {report['distribution_comparison_csv']}")
    print(f"Distribution mouth audit: {report['distribution_mouth_audit_csv']}")
    print(f"Distribution attribution: {report['distribution_attribution_csv']}")
    print(f"Validation report: {report['report_md']}")
    print(f"MoorDyn input: {report['moordyn_input']}")
    print(f"MoorDyn endpoint-history input: {report['moordyn_endpoint_input']}")
    print(f"MoorDyn current profile: {report['moordyn_current_profile']}")
    print(f"MoorDyn dynamic history: {report['moordyn_history_csv']}")
    print(f"MoorDyn endpoint history: {report['moordyn_endpoint_history_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import csv
import json
import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


class OrcaFlexValidationTests(unittest.TestCase):
    def test_orcaflex_validation_writes_probe_mapping_and_endpoint_history(self):
        from scripts.validate_orcaflex import OrcaFlexProbe, run_validation

        probe = OrcaFlexProbe(
            status="license_unavailable",
            import_status="ok",
            dll_version="11.0a",
            python_executable="python",
            python_version="3.x",
            module_path="OrcFxAPI.py",
            model_status="failed",
            license_env="",
            flexnet_ini_exists=False,
            notes="Unable to obtain a FlexNet licence",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.validate_orcaflex._probe_orcaflex_api", return_value=probe):
                report = run_validation(Path(tmp), case_name="plough_straight_baseline_6min", points=7)

            self.assertEqual(report["status"], "license_unavailable")
            mapping_path = Path(report["mapping_csv"])
            endpoint_path = Path(report["endpoint_history_csv"])
            probe_json_path = Path(report["probe_json"])
            report_path = Path(report["report_md"])
            self.assertTrue(mapping_path.exists())
            self.assertTrue(endpoint_path.exists())
            self.assertTrue(probe_json_path.exists())
            self.assertTrue(report_path.exists())

            with mapping_path.open(newline="", encoding="utf-8") as handle:
                mapping_rows = list(csv.DictReader(handle))
            by_input = {row["project_input"]: row for row in mapping_rows}
            self.assertEqual(by_input["OrcFxAPI probe status"]["orcaflex_value"], "license_unavailable")
            self.assertEqual(
                by_input["project solver frame -> validation snapshot"]["orcaflex_value"],
                "X=x, Y=y, Z=z (snapshot passthrough)",
            )
            self.assertEqual(by_input["endpoint_replay_time_window"]["status"], "matched")
            self.assertEqual(by_input["initial/final suspended material length"]["status"], "matched")
            self.assertEqual(by_input["diameter_m"]["status"], "matched")
            self.assertEqual(by_input["weight_air_n_per_m"]["orcaflex_target"], "line type mass per unit length")
            self.assertEqual(by_input["axial_stiffness_n"]["orcaflex_target"], "line type EA")
            self.assertEqual(
                by_input["submerged_weight_n_per_m"]["orcaflex_target"],
                "mass, diameter, seawater density and gravity implied submerged weight",
            )
            self.assertEqual(by_input["current_speed_mps/current_direction_deg"]["status"], "matched")
            self.assertEqual(by_input["q_f, q_p and dL_s/dt=q_f-q_p"]["status"], "matched")
            self.assertIn("Two-end line feeding", by_input["q_f, q_p and dL_s/dt=q_f-q_p"]["notes"])
            self.assertEqual(by_input["bending/torsional rigidity boundary"]["orcaflex_value"], "0 / 0")
            added_mass = by_input["added-mass implementation"]
            self.assertEqual(added_mass["orcaflex_value"], "normal=1 (both normal directions); axial=0")
            self.assertEqual(added_mass["status"], "model_gap_directional_mass")
            self.assertIn("isotropically", added_mass["notes"])
            self.assertEqual(by_input["same physical output time"]["status"], "limitation_recorded")
            self.assertEqual(by_input["water_depth_m seabed plane"]["orcaflex_target"], "flat seabed")
            self.assertEqual(by_input["seabed_friction_coefficient"]["status"], "shared_model_assumption")
            self.assertEqual(by_input["plough body/soil/tooling"]["status"], "out_of_scope")
            self.assertTrue(all(row["status"] != "unmapped" for row in mapping_rows))

            with endpoint_path.open(newline="", encoding="utf-8") as handle:
                endpoint_rows = list(csv.DictReader(handle))
            self.assertEqual(len(endpoint_rows), 7)
            self.assertEqual(endpoint_rows[0]["time_s"], "0")
            self.assertIn("fairlead_z_m", endpoint_rows[0])
            self.assertIn("unstretched_length_rate_mps", endpoint_rows[0])

            probe_data = json.loads(probe_json_path.read_text(encoding="utf-8"))
            self.assertEqual(probe_data["status"], "license_unavailable")
            self.assertEqual(probe_data["dll_version"], "11.0a")
            self.assertIn("license_unavailable", report_path.read_text(encoding="utf-8"))

    def test_orcaflex_license_error_classifier_accepts_licence_and_license_spellings(self):
        from scripts.validate_orcaflex import _looks_like_license_error

        self.assertTrue(_looks_like_license_error("Unable to obtain a FlexNet licence"))
        self.assertTrue(_looks_like_license_error("Cannot find license file"))
        self.assertTrue(_looks_like_license_error("Unable to obtain a HASP dongle licence"))
        self.assertFalse(_looks_like_license_error("object property is invalid"))

    def test_dynamic_input_uses_first_frame_as_constraint_origin_and_preserves_z_up_snapshot(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import _build_orcaflex_dynamic_input

        samples = (
            EndpointDriveSample(
                time_s=0.0,
                plough_position_m=(-10.0, -2.0, -80.0),
                fairlead_position_m=(0.0, 0.0, -1.0),
                plough_velocity_mps=(0.0, 0.0, 0.0),
                fairlead_velocity_mps=(0.0, 0.0, 0.0),
                unstretched_length_m=90.0,
                unstretched_length_rate_mps=0.12,
            ),
            EndpointDriveSample(
                time_s=2.0,
                plough_position_m=(-4.0, 3.0, -75.0),
                fairlead_position_m=(8.0, 4.0, -3.0),
                plough_velocity_mps=(3.0, 2.5, 2.5),
                fairlead_velocity_mps=(4.0, 2.0, -1.0),
                unstretched_length_m=95.0,
                unstretched_length_rate_mps=0.14,
            ),
        )

        dynamic_input = _build_orcaflex_dynamic_input(samples)

        self.assertEqual(dynamic_input.times_s, (0.0, 2.0))
        self.assertEqual(dynamic_input.plough_initial_position_m, (-10.0, -2.0, -80.0))
        self.assertEqual(dynamic_input.fairlead_initial_position_m, (0.0, 0.0, -1.0))
        self.assertEqual(dynamic_input.plough_displacements_m, ((0.0, 0.0, 0.0), (6.0, 5.0, 5.0)))
        self.assertEqual(dynamic_input.fairlead_displacements_m, ((0.0, 0.0, 0.0), (8.0, 4.0, -2.0)))
        self.assertEqual(dynamic_input.suspended_length_rates_mps, (0.12, 0.14))
        self.assertEqual(dynamic_input.active_lengths_m, (90.0, 95.0))
        self.assertEqual(dynamic_input.initial_active_length_m, 90.0)
        self.assertEqual(dynamic_input.full_line_length_m, 95.0)

    def test_dynamic_history_rows_keep_relative_motion_and_net_suspended_length_rate(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import (
            _build_orcaflex_dynamic_input,
            _constraint_history_rows,
            _net_suspended_length_history_rows,
        )

        dynamic_input = _build_orcaflex_dynamic_input(
            (
                EndpointDriveSample(
                    time_s=0.0,
                    plough_position_m=(0.0, 0.0, -80.0),
                    fairlead_position_m=(0.0, 0.0, 0.0),
                    plough_velocity_mps=(0.0, 0.0, 0.0),
                    fairlead_velocity_mps=(0.0, 0.0, 0.0),
                    unstretched_length_m=90.0,
                    unstretched_length_rate_mps=0.12,
                ),
                EndpointDriveSample(
                    time_s=2.0,
                    plough_position_m=(6.0, 5.0, -75.0),
                    fairlead_position_m=(8.0, 4.0, -3.0),
                    plough_velocity_mps=(3.0, 2.5, 2.5),
                    fairlead_velocity_mps=(4.0, 2.0, -1.0),
                    unstretched_length_m=95.0,
                    unstretched_length_rate_mps=0.14,
                ),
            )
        )

        self.assertEqual(
            _constraint_history_rows(dynamic_input, endpoint="fairlead"),
            ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (2.0, 8.0, 4.0, -3.0, 0.0, 0.0, 0.0)),
        )
        self.assertEqual(_net_suspended_length_history_rows(dynamic_input), ((0.0, 0.12), (2.0, 0.14)))

    def test_two_end_material_transport_uses_positive_fairlead_payout_and_negative_plough_haul_in(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import (
            _build_orcaflex_dynamic_input,
            _endpoint_material_rate_history_rows,
            _full_line_length_for_orcaflex_feeding,
        )

        samples = tuple(
            EndpointDriveSample(
                time_s=time_s,
                plough_position_m=(-10.0 + 0.8 * time_s, 0.0, -80.0),
                fairlead_position_m=(0.8 * time_s, 0.0, 0.0),
                plough_velocity_mps=(0.8, 0.0, 0.0),
                fairlead_velocity_mps=(0.8, 0.0, 0.0),
                unstretched_length_m=96.0,
                unstretched_length_rate_mps=0.0,
                fairlead_payout_speed_mps=0.8,
                plough_exit_speed_mps=0.8,
            )
            for time_s in (0.0, 2.0)
        )
        dynamic_input = _build_orcaflex_dynamic_input(samples)

        self.assertEqual(dynamic_input.fairlead_payout_rates_mps, (0.8, 0.8))
        self.assertEqual(dynamic_input.plough_exit_rates_mps, (0.8, 0.8))
        self.assertEqual(
            _endpoint_material_rate_history_rows(dynamic_input, endpoint="fairlead"),
            ((0.0, 0.8), (2.0, 0.8)),
        )
        self.assertEqual(
            _endpoint_material_rate_history_rows(dynamic_input, endpoint="plough"),
            ((0.0, -0.8), (2.0, -0.8)),
        )
        self.assertGreater(_full_line_length_for_orcaflex_feeding(dynamic_input, element_count=12), 97.6)

    def test_physical_output_window_uses_existing_balanced_history_samples_without_rewriting_inputs(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import _slice_endpoint_drive_samples

        samples = (
            EndpointDriveSample(0.0, (0.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
            EndpointDriveSample(10.0, (8.0, 0.0, -80.0), (8.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
            EndpointDriveSample(60.0, (48.0, 0.0, -80.0), (48.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
        )

        window = _slice_endpoint_drive_samples(samples, physical_output_window_s=10.0)

        self.assertEqual(tuple(sample.time_s for sample in window), (0.0, 10.0))
        self.assertEqual(window[-1].fairlead_position_m, (8.0, 0.0, 0.0))
        self.assertEqual(window[-1].plough_position_m, (8.0, 0.0, -80.0))
        self.assertEqual(window[-1].unstretched_length_rate_mps, 0.0)
        with self.assertRaisesRegex(ValueError, "existing endpoint-history sample"):
            _slice_endpoint_drive_samples(samples, physical_output_window_s=15.0)

    def test_prehistory_extends_only_constant_balanced_endpoint_history(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import _build_orcaflex_prehistory_input

        samples = (
            EndpointDriveSample(0.0, (-10.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
            EndpointDriveSample(10.0, (-2.0, 0.0, -80.0), (8.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
        )

        dynamic_input = _build_orcaflex_prehistory_input(samples, prehistory_duration_s=30.0)

        self.assertEqual(dynamic_input.times_s[0], 0.0)
        self.assertEqual(dynamic_input.times_s[-2:], (30.0, 40.0))
        self.assertEqual(dynamic_input.physical_output_times_s, (0.0, 10.0))
        self.assertEqual(dynamic_input.physical_time_offset_s, 30.0)
        self.assertEqual(dynamic_input.plough_initial_position_m, (-30.0, 0.0, -80.0))
        self.assertEqual(dynamic_input.fairlead_initial_position_m, (-20.0, 0.0, 0.0))
        ramp_end_index = dynamic_input.times_s.index(10.0)
        physical_start_index = dynamic_input.times_s.index(30.0)
        self.assertAlmostEqual(dynamic_input.plough_displacements_m[ramp_end_index][0], 4.0)
        self.assertAlmostEqual(dynamic_input.fairlead_displacements_m[ramp_end_index][0], 4.0)
        self.assertAlmostEqual(dynamic_input.plough_displacements_m[physical_start_index][0], 20.0)
        self.assertAlmostEqual(dynamic_input.fairlead_displacements_m[physical_start_index][0], 20.0)
        self.assertTrue(all(rate == 0.0 for rate in dynamic_input.suspended_length_rates_mps))
        self.assertTrue(all(length == 100.0 for length in dynamic_input.active_lengths_m))

    def test_prehistory_rejects_nonzero_net_length_rate_and_nonconstant_first_segment(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import _build_orcaflex_prehistory_input

        nonzero_net_rate = (
            EndpointDriveSample(0.0, (0.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.01),
            EndpointDriveSample(10.0, (8.0, 0.0, -80.0), (8.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.1, 0.01),
        )
        nonconstant_speed = (
            EndpointDriveSample(0.0, (0.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.8, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
            EndpointDriveSample(10.0, (8.0, 0.0, -80.0), (8.0, 0.0, 0.0), (0.9, 0.0, 0.0), (0.9, 0.0, 0.0), 100.0, 0.0),
        )

        with self.assertRaisesRegex(ValueError, "net suspended-length rate"):
            _build_orcaflex_prehistory_input(nonzero_net_rate, prehistory_duration_s=30.0)
        with self.assertRaisesRegex(ValueError, "first endpoint velocity"):
            _build_orcaflex_prehistory_input(nonconstant_speed, prehistory_duration_s=30.0)

    def test_prehistory_rejects_different_plough_and_fairlead_translation_vectors(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import _build_orcaflex_prehistory_input

        unequal_endpoint_translation = (
            EndpointDriveSample(0.0, (-10.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.7, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
            EndpointDriveSample(10.0, (-3.0, 0.0, -80.0), (8.0, 0.0, 0.0), (0.7, 0.0, 0.0), (0.8, 0.0, 0.0), 100.0, 0.0),
        )

        with self.assertRaisesRegex(ValueError, "common endpoint translation"):
            _build_orcaflex_prehistory_input(unequal_endpoint_translation, prehistory_duration_s=30.0)

    def test_project_validation_case_replays_same_smooth_prehistory_as_orcaflex(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import (
            _payout_speed,
            _plough_position,
            _plough_velocity,
            _vessel_position,
            _vessel_velocity,
        )
        from scripts.validate_orcaflex import _build_project_prehistory_case

        baseline = get_time_history_case("plough_payout_matched_6min")
        validation_case = _build_project_prehistory_case(
            baseline,
            prehistory_duration_s=30.0,
            physical_output_window_s=10.0,
        )

        self.assertEqual(validation_case.total_duration_s, 40.0)
        self.assertEqual(validation_case.duration_s, 40.0)
        self.assertEqual(validation_case.vessel_initial_x_m, -20.0)
        self.assertEqual(validation_case.plough_initial_x_m, -75.0)
        self.assertEqual(validation_case.vessel_motion_segments, validation_case.plough_motion_segments)
        self.assertEqual(len(validation_case.vessel_motion_segments), 101)
        self.assertEqual(len(validation_case.payout_speed_segments), 101)
        self.assertEqual(validation_case.vessel_motion_segments[0].start_speed_mps, 0.0)
        self.assertEqual(validation_case.vessel_motion_segments[-1].end_speed_mps, 0.8)
        self.assertEqual(validation_case.payout_speed_segments[0].start_speed_mps, 0.0)
        self.assertEqual(validation_case.payout_speed_segments[-1].end_speed_mps, 0.8)

        def displacement_at(time_s):
            remaining = time_s
            distance = 0.0
            for segment in validation_case.vessel_motion_segments:
                used = min(remaining, segment.duration_s)
                if used <= 0.0:
                    break
                fraction = used / segment.duration_s
                end_speed = segment.start_speed_mps + fraction * (
                    segment.end_speed_mps - segment.start_speed_mps
                )
                distance += 0.5 * (segment.start_speed_mps + end_speed) * used
                remaining -= used
            return distance

        self.assertAlmostEqual(displacement_at(30.0), 20.0, places=12)
        self.assertAlmostEqual(displacement_at(40.0), 28.0, places=12)
        self.assertEqual(_vessel_position(validation_case, 0.0), (-20.0, 0.0, 0.0))
        self.assertEqual(_plough_position(validation_case, 0.0), (-75.0, 0.0, 80.0))
        self.assertEqual(_vessel_velocity(validation_case, 0.0), (0.0, 0.0, 0.0))
        self.assertEqual(_plough_velocity(validation_case, 0.0), (0.0, 0.0, 0.0))
        self.assertEqual(_payout_speed(validation_case, 0.0), 0.0)
        self.assertAlmostEqual(_vessel_position(validation_case, 30.0)[0], 0.0, places=12)
        self.assertAlmostEqual(_plough_position(validation_case, 30.0)[0], -55.0, places=12)
        self.assertAlmostEqual(_vessel_velocity(validation_case, 30.0)[0], 0.8, places=12)
        self.assertAlmostEqual(_plough_velocity(validation_case, 30.0)[0], 0.8, places=12)
        self.assertAlmostEqual(_payout_speed(validation_case, 30.0), 0.8, places=12)

    def test_project_global_axial_solver_is_grid_consistent_over_suspended_history(self):
        from dataclasses import replace

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history
        from scripts.validate_orcaflex import _build_project_prehistory_case

        baseline = get_time_history_case("plough_payout_matched_6min")
        direct_length_m = math.dist((0.0, 0.0, 0.0), (-55.0, 0.0, 70.0))
        line_tension_means_n = []
        line_tension_frames_n = []
        fairlead_tension_frames_n = []
        plough_tension_frames_n = []

        for element_count in (24, 48):
            physical_case = replace(
                baseline,
                case_name=f"suspended_grid_{element_count}",
                plough_initial_z_m=70.0,
                initial_suspended_length_m=1.005 * direct_length_m,
                current_speed_mps=0.35,
                current_direction_deg=90.0,
                element_count=element_count,
            )
            validation_case = _build_project_prehistory_case(
                physical_case,
                prehistory_duration_s=30.0,
                physical_output_window_s=10.0,
            )
            result = solve_dynamic_laying_time_history(validation_case, points=401)
            self.assertGreaterEqual(result.xpbd_iterations_per_step_min, 1)
            self.assertLessEqual(result.xpbd_iterations_per_step_max, 100)
            self.assertEqual(result.xpbd_iterations_per_step, result.xpbd_iterations_per_step_max)
            self.assertEqual(result.xpbd_iteration_limit_per_solve, 100)
            self.assertLessEqual(result.axial_constraint_residual_max_m, 1.0e-10)
            physical_frames = result.frames[300:]
            frame_means_n = []

            for frame in physical_frames:
                segment_lengths_m = [
                    math.dist(
                        (left.x_m, left.y_m, left.z_m),
                        (right.x_m, right.y_m, right.z_m),
                    )
                    for left, right in zip(frame.points, frame.points[1:])
                ]
                frame_means_n.append(
                    sum(
                        tension_n * length_m
                        for tension_n, length_m in zip(frame.segment_tensions_n, segment_lengths_m)
                    )
                    / sum(segment_lengths_m)
                )
                self.assertTrue(all(point.z_m < 80.0 for point in frame.points[1:-1]))

            line_tension_frames_n.append(frame_means_n)
            fairlead_tension_frames_n.append([frame.segment_tensions_n[0] for frame in physical_frames])
            plough_tension_frames_n.append([frame.segment_tensions_n[-1] for frame in physical_frames])

            time_step_s = physical_frames[1].time_s - physical_frames[0].time_s
            line_tension_means_n.append(
                time_step_s
                * (
                    0.5 * frame_means_n[0]
                    + sum(frame_means_n[1:-1])
                    + 0.5 * frame_means_n[-1]
                )
                / (physical_frames[-1].time_s - physical_frames[0].time_s)
            )

        relative_grid_difference = abs(line_tension_means_n[1] - line_tension_means_n[0]) / (
            0.5 * sum(line_tension_means_n)
        )
        self.assertLess(relative_grid_difference, 0.01)
        for values_by_grid in (
            line_tension_frames_n,
            fairlead_tension_frames_n,
            plough_tension_frames_n,
        ):
            self.assertEqual(len(values_by_grid[0]), len(values_by_grid[1]))
            maximum_frame_difference = max(
                abs(refined - coarse) / max(0.5 * (abs(refined) + abs(coarse)), 1.0e-12)
                for coarse, refined in zip(values_by_grid[0], values_by_grid[1])
            )
            self.assertLess(maximum_frame_difference, 0.01)

    def test_endpoint_tension_diagnostics_are_unfiltered_and_time_adjacent(self):
        from scripts.validate_orcaflex import _endpoint_tension_diagnostics

        diagnostics = _endpoint_tension_diagnostics([
            {"time_s": "0", "end_a_effective_tension_n": "5", "end_b_effective_tension_n": "6"},
            {"time_s": "1", "end_a_effective_tension_n": "10", "end_b_effective_tension_n": "3"},
            {"time_s": "2", "end_a_effective_tension_n": "-2", "end_b_effective_tension_n": "12"},
        ])

        self.assertEqual(diagnostics["endpoint_tension_max_n"], "12")
        self.assertEqual(diagnostics["endpoint_tension_median_n"], "5.5")
        self.assertEqual(diagnostics["endpoint_tension_negative_count"], "1")
        self.assertEqual(diagnostics["endpoint_tension_max_adjacent_jump_n"], "12")

    def test_logged_endpoint_tension_diagnostics_use_physical_window_with_prehistory_offset(self):
        from scripts.validate_orcaflex import OrcaFlexDynamicInput, _logged_endpoint_tension_diagnostics

        class FakeLine:
            def __init__(self):
                self.calls = []

            def TimeHistory(self, variable_name, *, period, objectExtra):
                self.calls.append((variable_name, period, objectExtra))
                return (5.0, 10.0, -2.0) if objectExtra == "A" else (6.0, 3.0, 12.0)

        api = types.SimpleNamespace(
            oeEndA="A",
            oeEndB="B",
            SpecifiedPeriod=lambda start, end: (start, end),
        )
        dynamic_input = OrcaFlexDynamicInput(
            times_s=(0.0, 30.0, 40.0),
            plough_initial_position_m=(-34.0, 0.0, -80.0),
            fairlead_initial_position_m=(-24.0, 0.0, 0.0),
            plough_displacements_m=((0.0, 0.0, 0.0), (24.0, 0.0, 0.0), (32.0, 0.0, 0.0)),
            fairlead_displacements_m=((0.0, 0.0, 0.0), (24.0, 0.0, 0.0), (32.0, 0.0, 0.0)),
            suspended_length_rates_mps=(0.0, 0.0, 0.0),
            active_lengths_m=(100.0, 100.0, 100.0),
            initial_active_length_m=100.0,
            full_line_length_m=100.0,
            physical_output_times_s=(0.0, 10.0),
            physical_time_offset_s=30.0,
            prehistory_duration_s=30.0,
        )
        line = FakeLine()

        diagnostics = _logged_endpoint_tension_diagnostics(api, line=line, dynamic_input=dynamic_input)

        self.assertEqual(line.calls, [
            ("Effective tension", (30.0, 40.0), "A"),
            ("Effective tension", (30.0, 40.0), "B"),
        ])
        self.assertEqual(diagnostics["endpoint_tension_log_sample_count"], "3")
        self.assertEqual(diagnostics["endpoint_tension_max_n"], "12")
        self.assertEqual(diagnostics["endpoint_tension_median_n"], "5.5")
        self.assertEqual(diagnostics["endpoint_tension_negative_count"], "1")
        self.assertEqual(diagnostics["endpoint_tension_max_adjacent_jump_n"], "12")

    def test_dynamic_report_records_short_window_statuses_endpoint_z_and_material_audit(self):
        from scripts.validate_orcaflex import OrcaFlexDynamicInput, _write_dynamic_report

        snapshot = types.SimpleNamespace(
            case_name="plough_payout_matched_6min",
            diameter_m=0.12,
            weight_air_n_per_m=45.0,
            submerged_weight_n_per_m=30.0,
            axial_stiffness_n=2.0e7,
            normal_drag_coefficient=1.1,
            tangential_drag_coefficient=0.04,
            water_depth_m=80.0,
        )
        dynamic_input = OrcaFlexDynamicInput(
            times_s=(0.0, 10.0),
            plough_initial_position_m=(0.0, 0.0, -80.0),
            fairlead_initial_position_m=(0.0, 0.0, 0.0),
            plough_displacements_m=((0.0, 0.0, 0.0), (8.0, 0.0, 0.0)),
            fairlead_displacements_m=((0.0, 0.0, 0.0), (8.0, 0.0, 0.0)),
            suspended_length_rates_mps=(0.0, 0.0),
            active_lengths_m=(100.0, 100.0),
            initial_active_length_m=100.0,
            full_line_length_m=100.0,
        )
        report = {
            "status": "dynamic_completed",
            "model_build_status": "completed",
            "statics_status": "completed",
            "dynamic_status": "completed",
            "extraction_status": "completed",
            "actual_output_end_time_s": "10",
            "max_endpoint_position_error_m": "0.001",
            "extracted_plough_z_m": "-80",
            "extracted_fairlead_z_m": "0",
            "tensions_finite": "yes",
            "dynamic_input_csv": "input.csv",
            "fairlead_motion_file": "fairlead.txt",
            "plough_motion_file": "plough.txt",
            "net_suspended_length_history_csv": "net_length.csv",
            "element_count": "24",
            "implicit_time_step_s": "0.01",
            "requested_physical_output_end_time_s": "10",
            "prehistory_duration_s": "30",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            _write_dynamic_report(snapshot, dynamic_input, report, path)
            text = path.read_text(encoding="utf-8")

        self.assertIn("Actual extracted output end time: `10` s", text)
        self.assertIn("Requested physical output end time: `10` s", text)
        self.assertIn("Plough endpoint Z: `-80` m", text)
        self.assertIn("Fairlead endpoint Z: `0` m", text)
        self.assertIn("Tensions finite: `yes`", text)
        self.assertIn("## Material And Environment Audit", text)
        self.assertIn("OrcaFlex model units: `m, kg, N, s`; gravity: `9.8 m/s^2`", text)
        self.assertIn("OrcaFlex uses normal `Ca=1` and axial `Ca=0`", text)
        self.assertIn("directional inertia models are not matched", text)
        implied_submerged_weight = 45.0 - 1025.0 * 9.8 * math.pi * 0.12 ** 2 / 4.0
        self.assertIn("Project submerged unit weight: `30` N/m", text)
        self.assertIn(
            f"OrcaFlex implied submerged unit weight: `{implied_submerged_weight:.12g}` N/m",
            text,
        )
        self.assertIn(
            f"Difference (OrcaFlex implied - project): `{implied_submerged_weight - 30.0:.12g}` N/m",
            text,
        )
        self.assertIn("hydrodynamic_constant is a derived quantity from weight, OD, and Cd", text)
        self.assertIn("CableParameters.total_length_m is spool/available cable length", text)
        self.assertIn("EI/GJ: `0 / 0` N m^2", text)
        self.assertIn("TargetLogSampleInterval: `0.01` s", text)
        self.assertIn("Time-alignment bound: `0.01` s", text)
        self.assertIn("first `10` s use a quintic velocity ramp from rest", text)

    def test_dynamic_failure_report_keeps_requested_end_separate_from_actual_extraction(self):
        from scripts.validate_orcaflex import OrcaFlexDynamicInput, _write_dynamic_report

        snapshot = types.SimpleNamespace(
            case_name="plough_payout_matched_6min",
            diameter_m=0.12,
            weight_air_n_per_m=45.0,
            submerged_weight_n_per_m=30.0,
            axial_stiffness_n=2.0e7,
            normal_drag_coefficient=1.1,
            tangential_drag_coefficient=0.04,
            water_depth_m=80.0,
        )
        dynamic_input = OrcaFlexDynamicInput(
            times_s=(0.0, 10.0),
            plough_initial_position_m=(0.0, 0.0, -80.0),
            fairlead_initial_position_m=(0.0, 0.0, 0.0),
            plough_displacements_m=((0.0, 0.0, 0.0), (8.0, 0.0, 0.0)),
            fairlead_displacements_m=((0.0, 0.0, 0.0), (8.0, 0.0, 0.0)),
            suspended_length_rates_mps=(0.0, 0.0),
            active_lengths_m=(100.0, 100.0),
            initial_active_length_m=100.0,
            full_line_length_m=100.0,
        )
        report = {
            "status": "dynamic_failed",
            "model_build_status": "completed",
            "statics_status": "completed",
            "dynamic_status": "failed",
            "extraction_status": "not_run",
            "dynamic_failure_time_s": "4.2",
            "requested_physical_output_end_time_s": "10",
            "dynamic_input_csv": "input.csv",
            "fairlead_motion_file": "fairlead.txt",
            "plough_motion_file": "plough.txt",
            "net_suspended_length_history_csv": "net_length.csv",
            "element_count": "24",
            "implicit_time_step_s": "0.01",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            _write_dynamic_report(snapshot, dynamic_input, report, path)
            text = path.read_text(encoding="utf-8")

        self.assertIn("Requested physical output end time: `10` s", text)
        self.assertIn("Dynamic failure time: `4.2` s", text)
        self.assertNotIn("Actual extracted output end time:", text)

    def test_dynamic_validation_writes_same_time_input_artifacts_without_running_orcaflex(self):
        from scripts.validate_orcaflex import run_dynamic_validation

        with tempfile.TemporaryDirectory() as tmp:
            report = run_dynamic_validation(
                Path(tmp),
                case_name="plough_straight_baseline_6min",
                points=7,
                run_model=False,
            )

            self.assertEqual(report["status"], "input_written")
            self.assertEqual(report["requested_physical_output_end_time_s"], "360")
            self.assertNotIn("actual_output_end_time_s", report)
            dynamic_input_path = Path(report["dynamic_input_csv"])
            fairlead_motion_path = Path(report["fairlead_motion_file"])
            plough_motion_path = Path(report["plough_motion_file"])
            net_suspended_length_history_path = Path(report["net_suspended_length_history_csv"])
            report_path = Path(report["dynamic_report_md"])
            self.assertTrue(all(path.exists() for path in (
                dynamic_input_path,
                fairlead_motion_path,
                plough_motion_path,
                net_suspended_length_history_path,
                report_path,
            )))

            with dynamic_input_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["time_s"] for row in rows], ["0", "60", "120", "180", "240", "300", "360"])
            self.assertEqual(rows[0]["active_length_m"], "99.9949123706")
            self.assertEqual(rows[-1]["active_length_m"], "146.794912371")

            fairlead_lines = fairlead_motion_path.read_text(encoding="ascii").splitlines()
            self.assertEqual(fairlead_lines[0].split("\t"), ["-1e-06", "0", "0", "0", "0", "0", "0"])
            self.assertEqual(len(fairlead_lines), 8)
            self.assertEqual(len(plough_motion_path.read_text(encoding="ascii").splitlines()), 8)
            self.assertIn("End B", report_path.read_text(encoding="utf-8"))

    def test_dynamic_validation_defaults_to_balanced_payout_case_and_labels_net_length_rate(self):
        from scripts.validate_orcaflex import run_dynamic_validation

        with tempfile.TemporaryDirectory() as tmp:
            report = run_dynamic_validation(Path(tmp), points=7, run_model=False)

            self.assertIn("plough_payout_matched_6min", report["dynamic_input_csv"])
            with Path(report["dynamic_input_csv"]).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertIn("suspended_length_rate_mps", rows[0])
            self.assertEqual({row["suspended_length_rate_mps"] for row in rows}, {"0"})
            self.assertIn("fairlead_payout_rate_mps", rows[0])
            self.assertIn("plough_exit_rate_mps", rows[0])

            report_text = Path(report["dynamic_report_md"]).read_text(encoding="utf-8")
            self.assertIn("dL_s/dt=q_f-q_p", report_text)
            self.assertIn("positive End B payout", report_text)
            self.assertIn("negative End A haul-in", report_text)
            self.assertEqual(report["element_count"], "24")
            self.assertEqual(report["implicit_time_step_s"], "0.01")

    def test_dynamic_validation_override_records_validation_discretisation_contract(self):
        from scripts.validate_orcaflex import run_dynamic_validation

        with tempfile.TemporaryDirectory() as tmp:
            report = run_dynamic_validation(
                Path(tmp),
                points=7,
                run_model=False,
                element_count=12,
                time_step_s=0.025,
                plough_depth_m=70.0,
            )
            report_text = Path(report["dynamic_report_md"]).read_text(encoding="utf-8")

        self.assertEqual(report["element_count"], "12")
        self.assertEqual(report["implicit_time_step_s"], "0.025")
        self.assertEqual(report["project_plough_depth_m"], "70")
        self.assertIn("Validation element count: `12`", report_text)
        self.assertIn("Implicit constant time step: `0.025` s", report_text)
        self.assertIn("TargetLogSampleInterval: `0.025` s", report_text)
        self.assertIn("Project plough depth: `70` m", report_text)

    def test_dynamic_validation_rejects_invalid_validation_discretisation(self):
        from scripts.validate_orcaflex import run_dynamic_validation

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "element_count"):
                run_dynamic_validation(Path(tmp), points=7, run_model=False, element_count=0)
            with self.assertRaisesRegex(ValueError, "time_step_s"):
                run_dynamic_validation(Path(tmp), points=7, run_model=False, time_step_s=0.0)

    def test_dynamic_model_uses_validation_discretisation_without_mutating_cable_material(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import _build_orcaflex_dynamic_input, _build_orcaflex_dynamic_model

        class FakeObject:
            def SetDataRowCount(self, *_args):
                return None

        class FakeModel:
            def __init__(self):
                self.general = types.SimpleNamespace()
                self.environment = types.SimpleNamespace()
                self.created = []

            def CreateObject(self, object_type):
                value = FakeObject()
                self.created.append((object_type, value))
                return value

        fake_api = types.SimpleNamespace(
            Model=FakeModel,
            otConstraint="constraint",
            otLineType="line_type",
            otPayoutRate="payout_rate",
            otLine="line",
        )
        snapshot = types.SimpleNamespace(
            water_depth_m=80.0,
            current_speed_mps=0.35,
            current_direction_deg=90.0,
            diameter_m=0.12,
            weight_air_n_per_m=45.0,
            submerged_weight_n_per_m=30.0,
            axial_stiffness_n=2.0e7,
            normal_drag_coefficient=1.1,
            tangential_drag_coefficient=0.04,
        )
        dynamic_input = _build_orcaflex_dynamic_input((
            EndpointDriveSample(0.0, (-10.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 96.0, 0.0),
            EndpointDriveSample(2.0, (-8.0, 0.0, -80.0), (2.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0), 96.0, 0.0),
        ))

        model, line = _build_orcaflex_dynamic_model(
            fake_api,
            snapshot=snapshot,
            dynamic_input=dynamic_input,
            fairlead_motion_file=Path("fairlead.txt"),
            plough_motion_file=Path("plough.txt"),
            element_count=12,
            time_step_s=0.025,
        )

        line_type = next(value for object_type, value in model.created if object_type == "line_type")
        self.assertEqual(getattr(model.general, "UnitsSystem", None), "User")
        self.assertEqual(getattr(model.general, "LengthUnits", None), "m")
        self.assertEqual(getattr(model.general, "MassUnits", None), "kg")
        self.assertEqual(getattr(model.general, "ForceUnits", None), "N")
        self.assertEqual(getattr(model.general, "g", None), 9.8)
        self.assertEqual(getattr(model.environment, "Density", None), 1025.0)
        self.assertEqual(model.general.ImplicitConstantTimeStep, 0.025)
        self.assertEqual(model.general.TargetLogSampleInterval, 0.025)
        self.assertEqual(line.TargetSegmentLength, (8.0,))
        self.assertEqual(line_type.OD, snapshot.diameter_m)
        self.assertEqual(line_type.MassPerUnitLength, snapshot.weight_air_n_per_m / 9.8)
        self.assertEqual(line_type.EA, snapshot.axial_stiffness_n)
        self.assertEqual(line_type.NormalDragCoefficient, snapshot.normal_drag_coefficient)
        self.assertEqual(line_type.AxialDragCoefficient, snapshot.tangential_drag_coefficient)
        self.assertEqual(line_type.NormalAddedMassCoefficient, 1.0)
        self.assertEqual(line_type.AxialAddedMassCoefficient, 0.0)
        self.assertEqual(line_type.EI, 0.0)
        self.assertEqual(line_type.GJ, 0.0)
        self.assertEqual(line_type.SeabedNormalFrictionCoefficient, 0.6)
        self.assertEqual(line_type.SeabedAxialFrictionCoefficient, 0.6)
        self.assertEqual(line.ConnectionPayoutRate, ("PloughHaulInRate", "FairleadPayoutRate"))

    def test_orcaflex_cli_routes_dynamic_flag_to_dynamic_runner(self):
        from scripts.validate_orcaflex import main

        dynamic_report = {
            "status": "dynamic_completed",
            "dynamic_input_csv": "input.csv",
            "fairlead_motion_file": "fairlead.txt",
            "plough_motion_file": "plough.txt",
            "net_suspended_length_history_csv": "net_length.csv",
            "dynamic_report_md": "report.md",
            "model_dat": "model.dat",
            "model_sim": "model.sim",
            "endpoint_tension_csv": "endpoint.csv",
            "distribution_csv": "distribution.csv",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.validate_orcaflex.run_dynamic_validation", return_value=dynamic_report) as runner:
                exit_code = main([
                    "--output", tmp,
                    "--case", "plough_straight_baseline_6min",
                    "--points", "7",
                    "--run-dynamic",
                    "--element-count", "12",
                    "--time-step-s", "0.025",
                    "--require-license",
                ])

        self.assertEqual(exit_code, 0)
        runner.assert_called_once_with(
            Path(tmp),
            case_name="plough_straight_baseline_6min",
            points=7,
            run_model=True,
            physical_output_window_s=None,
            prehistory_duration_s=0.0,
            element_count=12,
            time_step_s=0.025,
            initial_active_length_m=None,
            current_speed_mps=None,
            current_direction_deg=None,
            plough_depth_m=None,
        )

    def test_orcaflex_cli_uses_dynamic_default_only_when_case_is_omitted(self):
        from scripts.validate_orcaflex import main

        dynamic_report = {
            "status": "dynamic_completed",
            "dynamic_input_csv": "input.csv",
            "fairlead_motion_file": "fairlead.txt",
            "plough_motion_file": "plough.txt",
            "net_suspended_length_history_csv": "net_length.csv",
            "dynamic_report_md": "report.md",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.validate_orcaflex.run_dynamic_validation", return_value=dynamic_report) as dynamic_runner:
                self.assertEqual(main(["--output", tmp, "--run-dynamic"]), 0)
            with patch("scripts.validate_orcaflex.run_validation", return_value={
                "status": "model_created",
                "probe_csv": "probe.csv",
                "mapping_csv": "mapping.csv",
                "endpoint_history_csv": "history.csv",
                "report_md": "report.md",
            }) as static_runner:
                self.assertEqual(main(["--output", tmp]), 0)

        dynamic_runner.assert_called_once_with(
            Path(tmp),
            case_name="plough_payout_matched_6min",
            points=7,
            run_model=True,
            physical_output_window_s=None,
            prehistory_duration_s=0.0,
            element_count=24,
            time_step_s=0.01,
            initial_active_length_m=None,
            current_speed_mps=None,
            current_direction_deg=None,
            plough_depth_m=None,
        )
        static_runner.assert_called_once_with(
            Path(tmp),
            case_name="plough_straight_baseline_6min",
            points=7,
            create_model=True,
        )

    def test_dynamic_runtime_history_copy_uses_ascii_path_and_preserves_input_bytes(self):
        from scripts.validate_orcaflex import _copy_orcaflex_runtime_history

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "动态输入"
            source_dir.mkdir()
            source = source_dir / "船端运动.txt"
            source.write_bytes(b"0\t0\t0\t0\t0\t0\t0\n")
            runtime = Path(tmp) / "runtime"

            copied = _copy_orcaflex_runtime_history(source, runtime)

            self.assertTrue(str(copied).isascii())
            self.assertEqual(copied.read_bytes(), source.read_bytes())

    def test_dynamic_model_reserves_minimum_inactive_length_only_for_line_feeding_capacity(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample
        from scripts.validate_orcaflex import (
            _build_orcaflex_dynamic_input,
            _full_line_length_for_orcaflex_feeding,
        )

        dynamic_input = _build_orcaflex_dynamic_input(
            (
                EndpointDriveSample(0.0, (0.0, 0.0, -80.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 90.0, 0.12),
                EndpointDriveSample(2.0, (6.0, 5.0, -75.0), (8.0, 4.0, -3.0), (3.0, 2.5, 2.5), (4.0, 2.0, -1.0), 95.0, 0.14),
            )
        )

        self.assertEqual(_full_line_length_for_orcaflex_feeding(dynamic_input, element_count=24), 95.01)

    def test_endpoint_position_error_is_euclidean_distance(self):
        from scripts.validate_orcaflex import _position_error_m

        self.assertEqual(_position_error_m((1.0, 2.0, 3.0), (4.0, 6.0, 3.0)), 5.0)

    def test_project_cable_line_type_limits_axial_compression(self):
        from scripts.validate_orcaflex import _configure_orcaflex_project_cable_line_type

        snapshot = types.SimpleNamespace(
            diameter_m=0.12,
            weight_air_n_per_m=45.0,
            axial_stiffness_n=2.0e7,
            normal_drag_coefficient=1.1,
            tangential_drag_coefficient=0.04,
        )
        line_type = types.SimpleNamespace()

        _configure_orcaflex_project_cable_line_type(line_type, snapshot)

        self.assertEqual(line_type.name, "ProjectCable")
        self.assertEqual(line_type.CompressionIsLimited, "Yes")
        self.assertEqual(line_type.EI, 0.0)
        self.assertEqual(line_type.GJ, 0.0)
        self.assertEqual(line_type.NormalAddedMassCoefficient, 1.0)
        self.assertEqual(line_type.AxialAddedMassCoefficient, 0.0)

    def test_distribution_uses_tension_grid_and_interpolates_contact_and_coordinates(self):
        from scripts.validate_orcaflex import _distribution_rows_from_range_graphs

        tension_graph = types.SimpleNamespace(X=(0.0, 2.0, 4.0), Mean=(100.0, 200.0, 300.0))
        seabed_graph = types.SimpleNamespace(X=(0.0, 2.0), Mean=(0.0, 20.0))
        x_graph = types.SimpleNamespace(X=(0.0, 4.0), Mean=(10.0, 14.0))
        y_graph = types.SimpleNamespace(X=(0.0, 4.0), Mean=(1.0, 5.0))
        z_graph = types.SimpleNamespace(X=(0.0, 4.0), Mean=(-80.0, 0.0))

        rows = _distribution_rows_from_range_graphs(
            time_s=3.0,
            active_length_m=4.0,
            tension_graph=tension_graph,
            seabed_graph=seabed_graph,
            x_graph=x_graph,
            y_graph=y_graph,
            z_graph=z_graph,
        )

        self.assertEqual([row["arc_length_m"] for row in rows], ["0", "2", "4"])
        self.assertEqual([row["effective_tension_n"] for row in rows], ["100", "200", "300"])
        self.assertEqual(rows[1]["seabed_normal_resistance_n"], "20")
        self.assertEqual(rows[2]["seabed_normal_resistance_n"], "0")
        self.assertEqual(rows[1]["x_m"], "12")
        self.assertEqual(rows[1]["y_m"], "3")
        self.assertEqual(rows[1]["z_m"], "-40")

    def test_contact_metrics_use_native_seabed_arc_and_integrate_normal_resistance(self):
        from scripts.validate_orcaflex import _contact_metrics_from_range_graphs

        metrics = _contact_metrics_from_range_graphs(
            tension_graph=types.SimpleNamespace(X=(0.0, 4.0, 8.0), Mean=(50.0, 90.0, 130.0)),
            seabed_graph=types.SimpleNamespace(X=(0.0, 2.0, 4.0), Mean=(10.0, 20.0, 0.0)),
            active_length_m=10.0,
        )

        self.assertEqual(metrics["orcaflex_seabed_contact_length_m"], "3")
        self.assertEqual(metrics["orcaflex_tdp_arc_length_m"], "7")
        self.assertEqual(metrics["orcaflex_tdp_effective_tension_n"], "80")
        self.assertEqual(metrics["orcaflex_seabed_normal_resultant_n"], "50")

    def test_contact_metrics_report_no_contact_without_inventing_tension(self):
        from scripts.validate_orcaflex import _contact_metrics_from_range_graphs

        metrics = _contact_metrics_from_range_graphs(
            tension_graph=types.SimpleNamespace(X=(0.0, 2.0), Mean=(50.0, 70.0)),
            seabed_graph=types.SimpleNamespace(X=(0.0, 2.0), Mean=(0.0, 0.0)),
            active_length_m=2.0,
        )

        self.assertEqual(metrics["orcaflex_seabed_contact_length_m"], "0")
        self.assertEqual(metrics["orcaflex_tdp_arc_length_m"], "2")
        self.assertEqual(metrics["orcaflex_tdp_effective_tension_n"], "")
        self.assertEqual(metrics["orcaflex_seabed_normal_resultant_n"], "0")

    def test_dynamic_stage_failure_records_the_failing_stage(self):
        from scripts.validate_orcaflex import _record_dynamic_stage_failure

        report = {}
        _record_dynamic_stage_failure(report, "statics", RuntimeError("static equilibrium did not converge"))

        self.assertEqual(report["status"], "statics_failed")
        self.assertEqual(report["statics_status"], "failed")
        self.assertEqual(report["error_stage"], "statics")
        self.assertIn("RuntimeError", report["error"])

    def test_orcaflex_probe_classifies_model_license_failure(self):
        from scripts.validate_orcaflex import _probe_orcaflex_api

        def raise_license_error():
            raise RuntimeError("Cannot find license file from FlexNet")

        fake_api = types.SimpleNamespace(
            __file__="C:\\fake\\OrcFxAPI.py",
            DLLVersion=lambda: "11.0a",
            Model=raise_license_error,
        )
        with patch.dict(sys.modules, {"OrcFxAPI": fake_api}):
            probe = _probe_orcaflex_api(create_model=True)

        self.assertEqual(probe.status, "license_unavailable")
        self.assertEqual(probe.import_status, "ok")
        self.assertEqual(probe.dll_version, "11.0a")
        self.assertEqual(probe.model_status, "failed")
        self.assertIn("FlexNet", probe.notes)

    def test_orcaflex_runtime_override_uses_gui_lib64_when_api_dependency_differs(self):
        from scripts.validate_orcaflex import _prepare_orcaflex_runtime_override

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "OrcaFlex" / "11.0"
            api_win64 = root / "OrcFxAPI" / "Win64"
            api_lib64 = api_win64 / "lib64"
            gui_lib64 = root / "lib64"
            api_lib64.mkdir(parents=True)
            gui_lib64.mkdir(parents=True)
            (api_win64 / "OrcFxAPI.dll").write_text("api dll", encoding="utf-8")
            (api_lib64 / "hasp.dll").write_text("hasp", encoding="utf-8")
            (api_lib64 / "comptran.dll").write_text("old api comptran", encoding="utf-8")
            (gui_lib64 / "comptran.dll").write_text("new gui comptran", encoding="utf-8")

            fake_config = types.SimpleNamespace(getLibPath=lambda: str(api_win64 / "OrcFxAPI.dll"))
            with patch.dict(sys.modules, {"OrcFxAPIConfig": fake_config}):
                sys.modules.pop("OrcFxAPI", None)
                with patch.dict(os.environ, {}, clear=False):
                    note = _prepare_orcaflex_runtime_override(Path(tmp) / "runtime")
                    override = Path(os.environ["_OrcFxAPIlib"])
                    override_comptran = (override.parent / "lib64" / "comptran.dll").read_text(encoding="utf-8")

            self.assertIn("runtime override applied", note)
            self.assertEqual(override.name, "OrcFxAPI.dll")
            self.assertEqual(override_comptran, "new gui comptran")


if __name__ == "__main__":
    unittest.main()

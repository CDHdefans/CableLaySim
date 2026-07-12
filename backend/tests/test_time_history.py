import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(ROOT / "src"))

from reference_tables import TABLE_4_1_DYNAMIC


def _time_at_extreme(result):
    target = result.extreme_tension_n
    point = min(result.history, key=lambda item: abs(item.top_tension_n - target))
    return point.time_s


def _percent_error(computed, reference):
    return abs(computed - reference) / max(abs(reference), 1.0e-12) * 100.0


class TimeHistoryTests(unittest.TestCase):
    def test_dynamic_module_does_not_keep_fitted_angle_control_path(self):
        import cable_tension.dynamic as dynamic

        for forbidden in (
            "_TABLE_4_1",
            "_dynamic_tension_scalars",
            "_modal_tension_target",
            "_hydrodynamic_lift_tension",
            "_DYNAMIC_RELAXATION_TIME_S",
            "_dynamic_target_tension",
            "_rk4_tension_step",
            "_target_angles",
            "_restoring_angular_accel",
            "_angular_accel_from_forces",
            "_ANGLE_RESPONSE_TIME_S",
            "_ANGLE_DAMPING_RATIO",
        ):
            self.assertFalse(hasattr(dynamic, forbidden))

    def test_dynamic_module_exposes_multi_element_angle_terms(self):
        import cable_tension.dynamic as dynamic

        self.assertTrue(hasattr(dynamic, "_solve_finite_difference_angle_time_history"))
        self.assertTrue(hasattr(dynamic, "_integrate_angle_motion"))
        self.assertTrue(hasattr(dynamic, "_finite_difference_tensions"))
        self.assertTrue(hasattr(dynamic, "_angle_accelerations"))
        self.assertTrue(hasattr(dynamic, "_AngleState"))
        self.assertTrue(hasattr(dynamic, "_straight_line_state"))
        self.assertTrue(hasattr(dynamic, "_relative_current_components"))
        self.assertTrue(hasattr(dynamic, "_vessel_speed"))

    def test_finite_difference_angle_response_stays_in_physical_scale(self):
        from cable_tension.dynamic import solve_time_history

        for case_name in TABLE_4_1_DYNAMIC:
            result = solve_time_history(case_name, points=31)

            self.assertGreater(result.initial_tension_n, 900.0)
            self.assertLess(result.initial_tension_n, 1300.0)
            self.assertGreater(result.steady_tension_n, 900.0)
            self.assertLess(result.steady_tension_n, 1300.0)

    def test_dynamic_extreme_uses_angle_motion_without_reference_fit(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.dynamic import solve_time_history

        self.assertTrue(hasattr(dynamic, "_speed_acceleration_mps2"))
        self.assertTrue(hasattr(dynamic, "_rk4_angle_step"))

        accel = solve_time_history("la_dynamic_accel_current_1p50", points=361)
        decel = solve_time_history("la_dynamic_decel_current_1p50", points=361)

        self.assertLess(accel.extreme_tension_n, accel.steady_tension_n)
        self.assertLess(accel.steady_tension_n, accel.initial_tension_n)
        self.assertLess(decel.initial_tension_n, decel.steady_tension_n)
        self.assertLess(decel.steady_tension_n, decel.extreme_tension_n)
        self.assertLessEqual(_time_at_extreme(accel), 90.0)
        self.assertLessEqual(_time_at_extreme(decel), 90.0)

    def test_dynamic_solver_stays_inside_documented_table_4_1_diagnostic_envelope(self):
        from cable_tension.dynamic import solve_time_history

        max_percent_error = 0.0
        for case_name, paper in TABLE_4_1_DYNAMIC.items():
            result = solve_time_history(case_name, points=31)
            computed = (
                result.initial_tension_n,
                result.extreme_tension_n,
                result.steady_tension_n,
            )
            reference = (
                paper["initial_tension_n"],
                paper["extreme_tension_n"],
                paper["steady_tension_n"],
            )
            max_percent_error = max(
                max_percent_error,
                *(_percent_error(a, b) for a, b in zip(computed, reference)),
            )

        self.assertLess(max_percent_error, 5.0)

    def test_dynamic_solver_exposes_multi_element_angle_evidence(self):
        from cable_tension.dynamic import solve_time_history

        result = solve_time_history("la_dynamic_accel_current_1p00", points=31)
        point = result.history[0]

        self.assertEqual(
            result.evidence_level,
            "LA finite-difference angle motion with straight-line length boundary; Table 4-1 is diagnostic, not full Eq. 3.5.5 N/B iteration",
        )
        self.assertGreater(result.element_count, 8)
        self.assertGreaterEqual(point.suspended_length_m, result.water_depth_m)
        self.assertGreater(point.tdp_x_m, 0.0)
        self.assertGreater(point.tdp_y_m, 0.0)
        self.assertGreater(max(point.iterations for point in result.history), result.element_count)

    def test_dynamic_solver_outputs_3d_frames_from_angle_state(self):
        from cable_tension.dynamic import solve_time_history

        result = solve_time_history("la_dynamic_accel_current_1p50", points=7)
        first_frame = result.frames[0]
        last_point = first_frame.points[-1]

        self.assertEqual(len(result.frames), len(result.history))
        self.assertEqual(first_frame.time_s, result.history[0].time_s)
        self.assertEqual(len(first_frame.points), result.element_count + 1)
        self.assertEqual(first_frame.points[0].index, 0)
        self.assertAlmostEqual(first_frame.points[0].x_m, 0.0)
        self.assertAlmostEqual(first_frame.points[0].y_m, 0.0)
        self.assertAlmostEqual(first_frame.points[0].z_m, 0.0)
        self.assertAlmostEqual(first_frame.points[0].tension_n, result.history[0].top_tension_n)
        self.assertAlmostEqual(last_point.x_m, result.history[0].tdp_x_m)
        self.assertAlmostEqual(last_point.y_m, result.history[0].tdp_y_m)
        self.assertAlmostEqual(last_point.z_m, result.water_depth_m)
        self.assertAlmostEqual(last_point.tension_n, 0.0)
        self.assertGreater(
            abs(result.frames[1].points[-1].x_m - result.frames[-1].points[-1].x_m)
            + abs(result.frames[1].points[-1].y_m - result.frames[-1].points[-1].y_m),
            1.0e-6,
        )

    def test_dynamic_frame_pairs_top_to_bottom_geometry_with_tensions(self):
        import cable_tension.dynamic as dynamic

        sample = dynamic._AngleSample(
            time_s=0.0,
            tension_n=30.0,
            tdp_x_m=0.0,
            tdp_y_m=0.0,
            suspended_length_m=20.0,
            angles_rad=(math.radians(30.0), math.radians(60.0)),
            psis_rad=(0.0, math.radians(90.0)),
            tensions_n=(0.0, 10.0, 30.0),
            integration_steps=2,
        )

        frame = dynamic._frame_at_time(sample)
        first_segment = dynamic._tangent_components(math.radians(60.0), math.radians(90.0))

        self.assertAlmostEqual(frame.points[0].tension_n, 30.0)
        self.assertAlmostEqual(frame.points[1].x_m, 10.0 * first_segment[0])
        self.assertAlmostEqual(frame.points[1].y_m, 10.0 * first_segment[1])
        self.assertAlmostEqual(frame.points[1].z_m, 10.0 * first_segment[2])
        self.assertAlmostEqual(frame.points[1].tension_n, 10.0)
        self.assertAlmostEqual(frame.points[2].tension_n, 0.0)

    def test_angle_motion_keeps_distinct_element_angles(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        samples = dynamic._integrate_angle_motion(case, [0.0, case.duration_s, 90.0])

        self.assertEqual(len(samples), 3)
        self.assertEqual(len(samples[-1].angles_rad), case.element_count)
        self.assertGreater(max(samples[-1].angles_rad) - min(samples[-1].angles_rad), 1.0e-5)

    def test_dynamic_solver_tracks_per_element_azimuth_motion(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_decel_current_1p50"]
        samples = dynamic._integrate_angle_motion(case, [0.0, case.duration_s, 90.0])

        self.assertEqual(len(samples[-1].psis_rad), case.element_count)
        self.assertGreater(max(samples[-1].psis_rad) - min(samples[-1].psis_rad), 1.0e-5)

    def test_tension_recurrence_has_no_stepwise_axial_inertia_jump(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_decel_current_1p50"]
        sample = dynamic._integrate_angle_motion(case, [case.duration_s])[0]

        before = dynamic._finite_difference_tensions(
            case,
            case.duration_s - 1.0e-6,
            sample.angles_rad,
            sample.psis_rad,
        )[-1]
        after = dynamic._finite_difference_tensions(
            case,
            case.duration_s + 1.0e-6,
            sample.angles_rad,
            sample.psis_rad,
        )[-1]

        self.assertLess(abs(after - before), 1.0)

    def test_tension_recurrence_uses_local_tangential_acceleration_sign(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_decel_current_1p50"]
        sample = dynamic._integrate_angle_motion(case, [case.duration_s])[0]
        base = dynamic._finite_difference_tensions(case, case.duration_s, sample.angles_rad, sample.psis_rad)[-1]
        positive = dynamic._finite_difference_tensions(
            case,
            case.duration_s,
            sample.angles_rad,
            sample.psis_rad,
            tangential_accelerations_mps2=tuple(0.02 for _ in sample.angles_rad),
        )[-1]
        negative = dynamic._finite_difference_tensions(
            case,
            case.duration_s,
            sample.angles_rad,
            sample.psis_rad,
            tangential_accelerations_mps2=tuple(-0.02 for _ in sample.angles_rad),
        )[-1]

        self.assertLess(positive, base)
        self.assertGreater(negative, base)

    def test_dynamic_tdp_projection_matches_global_orientation_vectors(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.kinematics import orientation_vectors

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        state = dynamic._AngleState(
            angles_rad=(math.radians(20.0), math.radians(35.0)),
            psis_rad=(math.radians(15.0), math.radians(65.0)),
            angular_rates_radps=(0.0, 0.0),
            azimuth_rates_radps=(0.0, 0.0),
        )

        sample = dynamic._angle_sample(case, 10.0, state, integration_steps=2)
        ds = dynamic._angle_element_length_m(case, state.angles_rad)
        expected_x = sum(
            ds * float(orientation_vectors(theta, psi)["t"][0])
            for theta, psi in zip(state.angles_rad, state.psis_rad)
        )
        expected_y = sum(
            ds * float(orientation_vectors(theta, psi)["t"][1])
            for theta, psi in zip(state.angles_rad, state.psis_rad)
        )

        self.assertAlmostEqual(sample.tdp_x_m, expected_x)
        self.assertAlmostEqual(sample.tdp_y_m, expected_y)

    def test_angle_state_carries_suspended_length_instead_of_recomputing_from_depth(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        state = dynamic._AngleState(
            angles_rad=(math.radians(20.0), math.radians(30.0)),
            psis_rad=(math.radians(10.0), math.radians(20.0)),
            angular_rates_radps=(0.0, 0.0),
            azimuth_rates_radps=(0.0, 0.0),
            suspended_length_m=150.0,
        )

        sample = dynamic._angle_sample(case, 10.0, state, integration_steps=2)
        element_length = dynamic._angle_element_length_m(case, state)
        depth_projection_length = case.water_depth_m / (
            math.sin(state.angles_rad[0]) + math.sin(state.angles_rad[1])
        )

        self.assertAlmostEqual(sample.suspended_length_m, 150.0)
        self.assertAlmostEqual(element_length, 75.0)
        self.assertNotAlmostEqual(element_length, depth_projection_length)

    def test_angle_motion_main_path_does_not_infer_length_from_depth_projection(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]

        with patch.object(dynamic, "_inferred_suspended_length_m", side_effect=AssertionError):
            samples = dynamic._integrate_angle_motion(case, [0.0, 0.2])

        self.assertEqual(len(samples), 2)
        self.assertGreater(samples[-1].suspended_length_m, 0.0)

    def test_dynamic_act_projection_matches_global_orientation_vectors(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.kinematics import orientation_vectors

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        state = dynamic._AngleState(
            angles_rad=(math.radians(25.0),),
            psis_rad=(math.radians(35.0),),
            angular_rates_radps=(0.0,),
            azimuth_rates_radps=(0.0,),
        )

        actual = dynamic._element_tangential_accelerations(case, 10.0, state)[0]
        expected = dynamic._speed_acceleration_mps2(case, 10.0) * float(
            orientation_vectors(state.angles_rad[0], state.psis_rad[0])["t"][1]
        )

        self.assertAlmostEqual(actual, expected)

    def test_angle_acceleration_uses_free_bottom_boundary_not_initial_straight_line_angle(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        initial = dynamic._straight_line_state(case, case.initial_speed_mps)
        state = dynamic._AngleState(
            angles_rad=(math.radians(20.0), math.radians(30.0), math.radians(40.0)),
            psis_rad=(math.radians(15.0), math.radians(35.0), math.radians(55.0)),
            angular_rates_radps=(0.0, 0.0, 0.0),
            azimuth_rates_radps=(0.0, 0.0, 0.0),
            suspended_length_m=initial.suspended_length_m,
        )
        original = dynamic._straight_line_state
        observed_speeds: list[float] = []

        def spy(case_arg, speed_arg):
            observed_speeds.append(speed_arg)
            return original(case_arg, speed_arg)

        with patch.object(dynamic, "_straight_line_state", side_effect=spy):
            dynamic._angle_accelerations(case, 10.0, state)

        self.assertNotIn(case.initial_speed_mps, observed_speeds[1:])

    def test_dynamic_damping_ratio_uses_drag_anisotropy_without_empirical_amplification(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.cases import get_cable

        cable = get_cable("LA")
        expected = cable.tangential_drag_coefficient / cable.normal_drag_coefficient

        self.assertAlmostEqual(dynamic._angle_damping_ratio(dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]), expected)

    def test_dynamic_act_ignores_unsupported_angular_velocity_products(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.kinematics import orientation_vectors

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        state = dynamic._AngleState(
            angles_rad=(math.radians(25.0), math.radians(30.0)),
            psis_rad=(math.radians(35.0), math.radians(45.0)),
            angular_rates_radps=(0.01, 0.02),
            azimuth_rates_radps=(0.03, 0.04),
        )

        actual = dynamic._element_tangential_accelerations(case, 10.0, state)
        expected = []
        for theta, psi in zip(state.angles_rad, state.psis_rad):
            tangent = orientation_vectors(theta, psi)["t"]
            expected.append(dynamic._speed_acceleration_mps2(case, 10.0) * float(tangent[1]))

        self.assertEqual(len(actual), len(expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value)

    def test_dynamic_tangential_drag_projection_matches_global_orientation_vectors(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.kinematics import orientation_vectors

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        theta = math.radians(30.0)
        psi = math.radians(55.0)
        speed = 0.8
        current = dynamic._relative_current_components(case, speed)
        tangent = orientation_vectors(theta, psi)["t"]
        relative_t = current[0] * float(tangent[0]) + current[1] * float(tangent[1]) - speed
        cable = dynamic.get_cable("LA")
        expected = (
            -0.5
            * math.pi
            * dynamic._SEAWATER_DENSITY_KG_M3
            * cable.tangential_drag_coefficient
            * cable.diameter_m
            * relative_t
            * abs(relative_t)
        )

        actual = dynamic._tangential_drag_for_angle(case, speed, theta, psi)

        self.assertAlmostEqual(actual, expected)

    def test_angle_acceleration_uses_local_act_in_stage_tensions(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p50"]
        state = dynamic._AngleState(
            angles_rad=(math.radians(20.0), math.radians(30.0), math.radians(40.0)),
            psis_rad=(math.radians(15.0), math.radians(35.0), math.radians(55.0)),
            angular_rates_radps=(0.0, 0.0, 0.0),
            azimuth_rates_radps=(0.0, 0.0, 0.0),
        )
        original = dynamic._finite_difference_tensions
        observed: list[tuple[float, ...] | None] = []

        def spy(*args, **kwargs):
            observed.append(kwargs.get("tangential_accelerations_mps2"))
            return original(*args, **kwargs)

        with patch.object(dynamic, "_finite_difference_tensions", side_effect=spy):
            dynamic._angle_accelerations(case, 10.0, state)

        self.assertTrue(
            any(
                values is not None and any(abs(value) > 0.0 for value in values)
                for values in observed
            )
        )

    def test_tension_recurrence_rejects_mismatched_dynamic_terms(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_decel_current_1p50"]
        sample = dynamic._integrate_angle_motion(case, [case.duration_s])[0]

        with self.assertRaises(ValueError):
            dynamic._finite_difference_tensions(
                case,
                case.duration_s,
                sample.angles_rad,
                sample.psis_rad[:-1],
            )

        with self.assertRaises(ValueError):
            dynamic._finite_difference_tensions(
                case,
                case.duration_s,
                sample.angles_rad,
                sample.psis_rad,
                tangential_accelerations_mps2=tuple(0.0 for _ in sample.angles_rad[:-1]),
            )

    def test_dynamic_inertia_includes_cylinder_added_mass(self):
        import cable_tension.dynamic as dynamic
        from cable_tension.cases import get_cable

        cable = get_cable("LA")
        structural_mass = cable.weight_air_n_per_m / dynamic._GRAVITY_MPS2
        dynamic_mass = dynamic._dynamic_mass_per_meter(cable)

        self.assertGreater(dynamic_mass, structural_mass)

    def test_dynamic_apparent_current_uses_direction_and_vessel_speed(self):
        import cable_tension.dynamic as dynamic

        case = dynamic._DYNAMIC_CASES["la_dynamic_accel_current_1p00"]
        x_90, y_90 = dynamic._apparent_current_components(case, vessel_speed_mps=0.5)
        x_270, y_270 = dynamic._apparent_current_components(
            dynamic.DynamicCaseInput(
                case_name="custom",
                current_speed_mps=1.0,
                speed_change="accel",
                initial_speed_mps=0.5,
                final_speed_mps=1.5,
                duration_s=30.0,
                water_depth_m=100.0,
                current_direction_deg=270.0,
            ),
            vessel_speed_mps=0.5,
        )

        self.assertGreater(x_90, 0.0)
        self.assertAlmostEqual(x_90, x_270)
        self.assertGreater(y_90, 0.0)
        self.assertLess(y_270, 0.0)

    def test_la_acceleration_time_history_is_input_driven_not_table_fitted(self):
        from cable_tension.dynamic import solve_time_history

        result = solve_time_history("la_dynamic_accel_current_1p50", points=31)

        self.assertEqual(len(result.history), 31)
        self.assertGreater(result.initial_tension_n, result.steady_tension_n)
        self.assertLess(result.extreme_tension_n, result.steady_tension_n)

    def test_la_deceleration_time_history_is_input_driven_not_table_fitted(self):
        from cable_tension.dynamic import solve_time_history

        result = solve_time_history("la_dynamic_decel_current_1p50", points=31)

        self.assertLess(result.initial_tension_n, result.steady_tension_n)
        self.assertGreater(result.extreme_tension_n, result.steady_tension_n)

    def test_time_history_samples_keep_start_speed_change_and_total_duration_endpoints(self):
        from cable_tension.dynamic import DynamicCaseInput, solve_time_history_input

        result = solve_time_history_input(
            DynamicCaseInput(
                case_name="endpoint_check",
                current_speed_mps=1.0,
                speed_change="accel",
                initial_speed_mps=0.5,
                final_speed_mps=1.5,
                duration_s=95.0,
                water_depth_m=100.0,
                element_count=8,
                total_duration_s=100.0,
                current_direction_deg=90.0,
                touchdown_tension_n=0.0,
            ),
            points=3,
        )

        sample_times = [point.time_s for point in result.history]

        self.assertEqual(sample_times[0], 0.0)
        self.assertIn(95.0, sample_times)
        self.assertEqual(sample_times[-1], 100.0)
        self.assertAlmostEqual(result.steady_tension_n, result.history[-1].top_tension_n)

    def test_speed_change_label_must_match_speed_direction(self):
        from cable_tension.dynamic import DynamicCaseInput, solve_time_history_input

        with self.assertRaises(ValueError):
            solve_time_history_input(
                DynamicCaseInput(
                    case_name="bad_accel",
                    current_speed_mps=1.0,
                    speed_change="accel",
                    initial_speed_mps=1.5,
                    final_speed_mps=0.5,
                    duration_s=30.0,
                    water_depth_m=100.0,
                    element_count=8,
                    total_duration_s=100.0,
                    current_direction_deg=90.0,
                    touchdown_tension_n=0.0,
                ),
                points=5,
            )

    def test_dynamic_speed_change_requires_positive_duration(self):
        from cable_tension.dynamic import DynamicCaseInput, solve_time_history_input

        with self.assertRaises(ValueError):
            solve_time_history_input(
                DynamicCaseInput(
                    case_name="zero_duration_accel",
                    current_speed_mps=1.0,
                    speed_change="accel",
                    initial_speed_mps=0.5,
                    final_speed_mps=1.5,
                    duration_s=0.0,
                    water_depth_m=100.0,
                    element_count=8,
                    total_duration_s=100.0,
                    current_direction_deg=90.0,
                    touchdown_tension_n=0.0,
                ),
                points=5,
            )

        with self.assertRaises(ValueError):
            solve_time_history_input(
                DynamicCaseInput(
                    case_name="bad_decel",
                    current_speed_mps=1.0,
                    speed_change="decel",
                    initial_speed_mps=0.5,
                    final_speed_mps=1.5,
                    duration_s=30.0,
                    water_depth_m=100.0,
                    element_count=8,
                    total_duration_s=100.0,
                    current_direction_deg=90.0,
                    touchdown_tension_n=0.0,
                ),
                points=5,
            )

    def test_la_dynamic_top_tension_uses_axial_tension_not_normal_drag_norm(self):
        from cable_tension.cases import get_cable
        from cable_tension.dynamic import solve_time_history

        cable = get_cable("LA")
        weight_only_tension = cable.submerged_weight_n_per_m * 100.0
        result = solve_time_history("la_dynamic_accel_current_1p50", points=31)

        self.assertLess(result.steady_tension_n, weight_only_tension * 1.5)

    def test_write_time_history_outputs_csv_and_svg(self):
        from cable_tension.dynamic import solve_time_history
        from cable_tension.io import write_time_history

        with tempfile.TemporaryDirectory() as tmp:
            result = solve_time_history("la_dynamic_accel_current_1p00", points=31)
            written = write_time_history(result, Path(tmp))

            self.assertTrue(written.summary_csv.exists())
            self.assertTrue(written.history_csv.exists())
            self.assertTrue(written.history_svg.exists())
            with written.summary_csv.open(newline="", encoding="utf-8") as handle:
                summary_reader = csv.DictReader(handle)
                self.assertEqual(
                    summary_reader.fieldnames,
                    [
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
                summary_row = next(summary_reader)
                self.assertEqual(summary_row["plough_exit_speed_mps"], "")
                self.assertEqual(summary_row["plough_exit_speed_source"], "not_applicable")
            with written.history_csv.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    reader.fieldnames,
                    [
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
                rows = list(reader)
            self.assertEqual(len(rows), 31)
            self.assertEqual(rows[0]["time_s"], "0.000000")

    def test_reproduce_paper_writes_table_4_1_and_dynamic_figures(self):
        from cable_tension.paper import reproduce_paper

        with tempfile.TemporaryDirectory() as tmp:
            reproduce_paper(Path(tmp), points=41)

            table_path = Path(tmp) / "tables" / "table_4_1_dynamic_la.csv"
            self.assertTrue(table_path.exists())
            self.assertTrue((Path(tmp) / "figures" / "fig_4_1_la_acceleration.svg").exists())
            self.assertTrue((Path(tmp) / "figures" / "fig_4_2_la_deceleration.svg").exists())
            with table_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            max_percent_error = 0.0
            for row in rows:
                reference = TABLE_4_1_DYNAMIC[row["case_name"]]
                for field in ("initial_tension_n", "extreme_tension_n", "steady_tension_n"):
                    max_percent_error = max(
                        max_percent_error,
                        _percent_error(float(row[field]), reference[field]),
                    )
            self.assertLess(max_percent_error, 5.0)


if __name__ == "__main__":
    unittest.main()

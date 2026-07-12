import dataclasses
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _closed_form_catenary_endpoint_tensions_z_down(
    *,
    top,
    bottom,
    length_m,
    submerged_weight_n_per_m,
):
    horizontal_span_m = math.hypot(top[0] - bottom[0], top[1] - bottom[1])
    vertical_drop_m = bottom[2] - top[2]
    straight_span_m = math.hypot(horizontal_span_m, vertical_drop_m)
    if length_m <= straight_span_m:
        raise AssertionError("test catenary length must exceed endpoint distance")
    reduced_length_m = math.sqrt(max(length_m * length_m - vertical_drop_m * vertical_drop_m, 0.0))
    if reduced_length_m <= horizontal_span_m:
        raise AssertionError("test catenary length is too short for sagging catenary")

    def span_for(parameter_m):
        argument = horizontal_span_m / (2.0 * parameter_m)
        return math.inf if argument > 700.0 else 2.0 * parameter_m * math.sinh(argument)

    low = max(horizontal_span_m, 1.0e-9) / 1400.0
    high = max(horizontal_span_m, reduced_length_m, 1.0)
    while span_for(high) > reduced_length_m:
        high *= 2.0
    for _ in range(120):
        mid = 0.5 * (low + high)
        if span_for(mid) > reduced_length_m:
            low = mid
        else:
            high = mid
    parameter_m = high
    half_dimensionless_span = horizontal_span_m / (2.0 * parameter_m)
    mean_dimensionless_height = math.atanh(vertical_drop_m / length_m)
    bottom_argument = mean_dimensionless_height - half_dimensionless_span
    top_argument = mean_dimensionless_height + half_dimensionless_span
    horizontal_tension_n = submerged_weight_n_per_m * parameter_m
    return (
        horizontal_tension_n * math.cosh(top_argument),
        horizontal_tension_n * math.cosh(bottom_argument),
    )


def _frame_polyline_length(frame) -> float:
    return sum(
        math.dist(
            (left.x_m, left.y_m, left.z_m),
            (right.x_m, right.y_m, right.z_m),
        )
        for left, right in zip(frame.points, frame.points[1:])
    )


class LayingArchitectureTests(unittest.TestCase):
    def test_geometry_keeps_node_coordinates_primary_and_angles_as_outputs(self):
        from cable_tension.geometry import interpolate_tdp, segment_angles, segment_vectors

        nodes = ((0.0, 0.0, 0.0), (3.0, 4.0, 0.0), (3.0, 4.0, 12.0))

        vectors = segment_vectors(nodes)
        angles = segment_angles(nodes)
        tdp = interpolate_tdp(nodes, seabed_depth_m=10.0)

        self.assertEqual(vectors[0].delta, (3.0, 4.0, 0.0))
        self.assertAlmostEqual(vectors[0].length_m, 5.0)
        self.assertAlmostEqual(vectors[0].tangent[0], 0.6)
        self.assertAlmostEqual(vectors[0].tangent[1], 0.8)
        self.assertAlmostEqual(angles[0].theta_rad, 0.0)
        self.assertAlmostEqual(angles[0].psi_rad, math.atan2(4.0, 3.0))
        self.assertAlmostEqual(angles[1].theta_rad, math.pi / 2.0)
        self.assertEqual(tdp.segment_index, 1)
        self.assertAlmostEqual(tdp.point[2], 10.0)
        self.assertAlmostEqual(tdp.fraction, 10.0 / 12.0)

    def test_heading_angle_and_geometry_azimuth_use_documented_zero_axes(self):
        from cable_tension.dynamic_laying import _heading_unit
        from cable_tension.geometry import segment_angles

        self.assertEqual(_heading_unit(0.0), (1.0, 0.0, 0.0))
        self.assertAlmostEqual(_heading_unit(90.0)[0], 0.0, places=12)
        self.assertAlmostEqual(_heading_unit(90.0)[1], 1.0)

        angles = segment_angles(((0.0, 0.0, 0.0), (0.0, 10.0, 0.0)))
        self.assertAlmostEqual(angles[0].psi_rad, math.pi / 2.0)

    def test_measured_motion_segment_velocity_components_override_heading_fallback(self):
        from cable_tension.dynamic import MotionSegment
        from cable_tension.dynamic_laying import _motion_displacement, _motion_velocity

        segment = MotionSegment(
            duration_s=10.0,
            start_speed_mps=99.0,
            end_speed_mps=99.0,
            heading_deg=180.0,
            start_velocity_x_mps=1.0,
            start_velocity_y_mps=2.0,
            end_velocity_x_mps=3.0,
            end_velocity_y_mps=4.0,
        )

        self.assertEqual(_motion_velocity((segment,), 5.0), (2.0, 3.0, 0.0))
        self.assertEqual(_motion_displacement((segment,), 5.0), (7.5, 12.5, 0.0))

    def test_hydrodynamics_uses_one_current_and_morison_entrypoint(self):
        from cable_tension.hydrodynamics import current_at, morison_drag

        current = current_at(
            depth_m=50.0,
            water_depth_m=100.0,
            current_surface_mps=2.0,
            current_bottom_mps=1.0,
            current_direction_deg=0.0,
            vessel_speed_mps=0.25,
        )
        drag = morison_drag(
            seawater_density=1025.0,
            diameter_m=0.0264,
            segment_length_m=2.0,
            tangent=(1.0, 0.0, 0.0),
            relative_velocity=(1.2, -0.5, 0.0),
            tangential_coefficient=0.01,
            normal_coefficient=2.12,
        )

        self.assertAlmostEqual(current[0], 1.75)
        self.assertAlmostEqual(current[1], 0.0)
        self.assertLess(drag[0], 0.0)
        self.assertGreater(drag[1], 0.0)
        self.assertAlmostEqual(drag[2], 0.0)
        self.assertLess(drag[0] * 1.2 + drag[1] * -0.5, 0.0)

    def test_contact_projects_nodes_to_seabed_and_defines_tdp_from_contact(self):
        from cable_tension.contact import detect_tdp, project_to_seabed, seabed_friction

        projected = project_to_seabed(
            point=(1.0, 2.0, 12.0),
            velocity=(0.3, -0.4, 1.2),
            seabed_depth_m=10.0,
        )
        tdp = detect_tdp(
            nodes=((0.0, 0.0, 0.0), (1.0, 0.0, 8.0), (2.0, 0.0, 10.0), (3.0, 0.0, 10.0)),
            seabed_depth_m=10.0,
        )
        friction = seabed_friction(
            normal_force_n=100.0,
            tangential_velocity=(3.0, 4.0, 0.0),
            friction_coefficient=0.5,
        )

        self.assertTrue(projected.in_contact)
        self.assertEqual(projected.point, (1.0, 2.0, 10.0))
        self.assertEqual(projected.velocity, (0.3, -0.4, 0.0))
        self.assertEqual(tdp.node_index, 2)
        self.assertEqual(tdp.point, (2.0, 0.0, 10.0))
        self.assertAlmostEqual(friction[0], -30.0)
        self.assertAlmostEqual(friction[1], -40.0)
        self.assertAlmostEqual(friction[2], 0.0)

    def test_dynamic_laying_state_updates_paid_length_and_seabed_contact(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 5.0), (0.0, 0.0, 10.5)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.8)),
            rest_lengths_m=(5.0, 5.0),
            paid_length_m=10.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
        )

        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=0.5,
            payout_speed_mps=1.2,
            seabed_depth_m=10.0,
        )

        self.assertAlmostEqual(updated.time_s, 0.5)
        self.assertAlmostEqual(updated.paid_length_m, 10.6)
        self.assertGreaterEqual(updated.laid_length_m, state.laid_length_m)
        self.assertAlmostEqual(updated.suspended_length_m, updated.paid_length_m - updated.laid_length_m)
        self.assertTrue(updated.contact_flags[-1])
        self.assertAlmostEqual(updated.positions[-1][2], 10.0)
        self.assertLessEqual(updated.velocities[-1][2], 0.0)

    def test_dynamic_laying_segment_tension_comes_from_axial_extension(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, compute_forces

        case = get_case("la_accel_200m")
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (5.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(4.0,),
            paid_length_m=4.0,
            laid_length_m=0.0,
            contact_flags=(False, False),
        )

        forces = compute_forces(case, state)
        expected = case.cable.axial_stiffness_n * (5.0 - 4.0) / 4.0

        self.assertAlmostEqual(forces[0][0], expected)
        self.assertAlmostEqual(forces[1][0], -expected)

    def test_dynamic_laying_payout_inserts_node_instead_of_uniform_rest_length(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 4.0), (0.0, 0.0, 8.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(4.0, 4.0),
            paid_length_m=8.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
        )

        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=1.0,
            payout_speed_mps=1.0,
            seabed_depth_m=100.0,
            target_segment_length_m=0.5,
        )

        self.assertAlmostEqual(updated.paid_length_m, 9.0)
        self.assertAlmostEqual(updated.laid_length_m, 0.0)
        self.assertAlmostEqual(updated.suspended_length_m, 9.0)
        self.assertGreater(len(updated.positions), len(state.positions))
        self.assertLess(updated.payout_buffer_m, 0.5)
        self.assertIn(0.5, updated.rest_lengths_m)
        self.assertNotEqual(updated.rest_lengths_m, tuple(9.0 / len(updated.rest_lengths_m) for _ in updated.rest_lengths_m))

    def test_dynamic_laying_xpbd_length_constraint_keeps_multiplier_audit(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (5.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(4.0,),
            paid_length_m=4.0,
            laid_length_m=0.0,
            contact_flags=(False, False),
        )

        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=0.1,
            payout_speed_mps=0.0,
            seabed_depth_m=100.0,
            xpbd_iterations=12,
        )

        length = math.dist(updated.positions[0], updated.positions[1])
        self.assertLess(length, 5.0)
        self.assertGreater(updated.length_lambdas_n_s2[0] / 0.1**2, 0.0)
        self.assertGreater(updated.segment_tensions_n[0], 0.0)
        self.assertNotAlmostEqual(updated.segment_tensions_n[0], updated.length_lambdas_n_s2[0] / 0.1**2)

    def test_dynamic_laying_contact_constraint_outputs_normal_reaction(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 10.5)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(10.5,),
            paid_length_m=10.5,
            laid_length_m=0.0,
            contact_flags=(False, False),
        )

        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=0.1,
            payout_speed_mps=0.0,
            seabed_depth_m=10.0,
            xpbd_iterations=8,
        )

        self.assertAlmostEqual(updated.positions[-1][2], 10.0)
        self.assertTrue(updated.contact_flags[-1])
        self.assertGreater(updated.contact_normal_reactions_n[-1], 0.0)
        self.assertAlmostEqual(updated.contact_normal_reactions_n[-1], updated.contact_lambdas_n_s2[-1] / 0.1**2)

    def test_dynamic_laying_contact_friction_uses_constraint_normal_reaction(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        base_case = get_case("la_accel_200m")
        cable_without_drag = replace(
            base_case.cable,
            tangential_drag_coefficient=0.0,
            normal_drag_coefficient=0.0,
        )
        case = replace(base_case, cable=cable_without_drag)
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 10.5)),
            velocities=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
            rest_lengths_m=(10.5,),
            paid_length_m=10.5,
            laid_length_m=0.0,
            contact_flags=(False, False),
        )

        updated = step_dynamic(
            case,
            state,
            dt_s=0.1,
            payout_speed_mps=0.0,
            seabed_depth_m=10.0,
            seabed_friction_coefficient=0.6,
            xpbd_iterations=8,
        )

        self.assertGreater(updated.contact_normal_reactions_n[-1], 0.0)
        self.assertLess(abs(updated.velocities[-1][0]), abs(state.velocities[-1][0]))

    def test_dynamic_laying_payout_speed_changes_morison_relative_velocity(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, compute_forces

        case = get_case("la_accel_200m")
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(10.0,),
            paid_length_m=10.0,
            laid_length_m=0.0,
            contact_flags=(False, False),
        )

        no_payout = compute_forces(case, state, payout_speed_mps=0.0)
        with_payout = compute_forces(case, state, payout_speed_mps=1.0)

        self.assertAlmostEqual(no_payout[0][0], 0.0)
        self.assertLess(with_payout[0][0], no_payout[0][0])
        self.assertLess(with_payout[1][0], no_payout[1][0])

    def test_plough_exit_speed_tapers_morison_material_velocity(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, compute_forces

        case = dataclasses.replace(
            get_case("la_accel_200m"),
            current_u_mps=0.0,
            current_v_mps=0.0,
            current_surface_mps=0.0,
            current_bottom_mps=0.0,
            current_direction_deg=0.0,
        )
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0),) * 3,
            rest_lengths_m=(10.0, 10.0),
            paid_length_m=20.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
        )

        uniform = compute_forces(
            case,
            state,
            payout_speed_mps=2.0,
            plough_exit_speed_mps=2.0,
        )
        tapered = compute_forces(
            case,
            state,
            payout_speed_mps=2.0,
            plough_exit_speed_mps=0.0,
        )

        self.assertLess(uniform[-1][0], 0.0)
        self.assertGreater(tapered[-1][0], uniform[-1][0])

    def test_dynamic_laying_contact_friction_reduces_horizontal_sliding(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, compute_forces

        base_case = get_case("la_accel_200m")
        cable_without_drag = replace(
            base_case.cable,
            tangential_drag_coefficient=0.0,
            normal_drag_coefficient=0.0,
        )
        case = replace(base_case, cable=cable_without_drag)
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
            rest_lengths_m=(10.0,),
            paid_length_m=10.0,
            laid_length_m=0.0,
            contact_flags=(False, True),
        )

        forces = compute_forces(
            case,
            state,
            seabed_depth_m=10.0,
            seabed_friction_coefficient=0.5,
        )

        self.assertLess(forces[1][0], 0.0)
        self.assertAlmostEqual(forces[1][2], 0.0)

    def test_dynamic_laying_contact_friction_uses_payout_material_speed(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, compute_forces

        base_case = get_case("la_accel_200m")
        cable_without_drag = replace(
            base_case.cable,
            tangential_drag_coefficient=0.0,
            normal_drag_coefficient=0.0,
        )
        case = replace(base_case, cable=cable_without_drag)
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 10.0), (10.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(10.0,),
            paid_length_m=10.0,
            laid_length_m=0.0,
            contact_flags=(True, True),
        )

        no_payout = compute_forces(
            case,
            state,
            seabed_depth_m=10.0,
            payout_speed_mps=0.0,
            seabed_friction_coefficient=0.5,
        )
        with_payout = compute_forces(
            case,
            state,
            seabed_depth_m=10.0,
            payout_speed_mps=2.0,
            seabed_friction_coefficient=0.5,
        )

        self.assertAlmostEqual(no_payout[0][0], 0.0)
        self.assertLess(with_payout[0][0], 0.0)
        self.assertLess(with_payout[1][0], 0.0)

    def test_plough_exit_speed_tapers_contact_material_velocity(self):
        from cable_tension.dynamic_laying import _apply_contact_friction

        positions = ((0.0, 0.0, 10.0), (1.0, 0.0, 10.0), (2.0, 0.0, 10.0))
        _, velocities = _apply_contact_friction(
            positions=positions,
            previous_positions=positions,
            velocities=((0.0, 0.0, 0.0),) * 3,
            contact_flags=(False, True, True),
            contact_normal_reactions_n=(0.0, 10.0, 10.0),
            masses=(1.0, 1.0, 1.0),
            rest_lengths_m=(1.0, 1.0),
            payout_speed_mps=2.0,
            plough_exit_speed_mps=0.0,
            dt_s=0.1,
            friction_coefficient=0.5,
            update_positions=False,
        )

        self.assertLess(velocities[1][0], 0.0)
        self.assertAlmostEqual(velocities[2][0], 0.0)

    def test_plough_exit_speed_changes_load_recursive_tension(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import _step_dynamic_segment_tensions

        case = dataclasses.replace(
            get_case("la_accel_200m"),
            current_u_mps=2.0,
            current_v_mps=0.0,
            current_surface_mps=None,
            current_bottom_mps=None,
            current_direction_deg=None,
        )
        kwargs = dict(
            positions=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0),) * 3,
            rest_lengths_m=(10.0, 10.0),
            payout_speed_mps=0.0,
            terminal_tension_n=0.0,
        )

        uniform = _step_dynamic_segment_tensions(case, plough_exit_speed_mps=0.0, **kwargs)
        tapered = _step_dynamic_segment_tensions(case, plough_exit_speed_mps=1.0, **kwargs)

        self.assertGreater(uniform[-1], tapered[-1])

    def test_dynamic_laying_segment_tensions_are_available_for_force_audit(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, _segment_tensions_from_state

        case = get_case("la_accel_200m")
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (9.0, 0.0, 0.0), (15.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(4.0, 4.0, 4.0),
            paid_length_m=12.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False, False),
        )

        tensions = _segment_tensions_from_state(case, state)
        segment_0 = case.cable.axial_stiffness_n * (5.0 - 4.0) / 4.0
        segment_1 = 0.0
        segment_2 = case.cable.axial_stiffness_n * (6.0 - 4.0) / 4.0

        self.assertAlmostEqual(tensions[0], segment_0)
        self.assertAlmostEqual(tensions[1], segment_1)
        self.assertAlmostEqual(tensions[2], segment_2)

    def test_dynamic_laying_time_history_runs_as_engineering_prototype(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            get_time_history_case("la_dynamic_accel_current_1p50"),
            points=11,
        )

        self.assertEqual(len(result.history), 11)
        self.assertEqual(result.length_boundary_source, "xpbd_node_dynamics_contact_remesh")
        self.assertIn("XPBD", result.evidence_level)
        self.assertGreater(result.initial_tension_n, 0.0)
        self.assertGreater(result.steady_tension_n, 0.0)
        self.assertAlmostEqual(result.frames[0].points[0].z_m, 0.0)
        self.assertGreaterEqual(result.frames[0].points[-1].z_m, result.water_depth_m - 1.0e-6)

    def test_known_plough_trajectory_pins_vessel_and_plough_endpoints(self):
        from cable_tension.dynamic import DynamicCaseInput
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            DynamicCaseInput(
                case_name="known_plough_boundary",
                current_speed_mps=0.4,
                current_direction_deg=90.0,
                speed_change="accel",
                initial_speed_mps=0.8,
                final_speed_mps=1.0,
                payout_initial_speed_mps=1.05,
                payout_final_speed_mps=1.15,
                length_boundary_source="known_plough_trajectory",
                duration_s=10.0,
                total_duration_s=20.0,
                water_depth_m=80.0,
                element_count=10,
                touchdown_tension_n=200.0,
                vessel_initial_x_m=0.0,
                vessel_initial_y_m=0.0,
                vessel_heading_deg=0.0,
                plough_initial_x_m=-55.0,
                plough_initial_y_m=0.0,
                plough_initial_z_m=78.0,
                plough_speed_mps=0.75,
                plough_heading_deg=0.0,
                initial_suspended_length_m=100.0,
            ),
            points=5,
        )

        self.assertEqual(result.length_boundary_source, "known_plough_trajectory")
        self.assertIn("known plough trajectory", result.evidence_level)
        self.assertEqual(len(result.history), 5)
        self.assertAlmostEqual(result.frames[0].vessel_x_m, 0.0)
        self.assertAlmostEqual(result.frames[0].plough_x_m, -55.0)
        self.assertAlmostEqual(result.frames[-1].vessel_x_m, 19.0)
        self.assertAlmostEqual(result.frames[-1].plough_x_m, -40.0)
        self.assertAlmostEqual(result.frames[-1].points[0].x_m, result.frames[-1].vessel_x_m)
        self.assertAlmostEqual(result.frames[-1].points[-1].x_m, result.frames[-1].plough_x_m)
        self.assertAlmostEqual(result.frames[-1].points[-1].z_m, 78.0)
        self.assertGreater(result.history[-1].plough_inlet_tension_n, 0.0)
        self.assertGreater(result.history[-1].minimum_bend_radius_m, 0.0)
        self.assertGreater(result.plough_inlet_tension_final_n, 0.0)

    def test_known_plough_current_uses_global_environment_frame(self):
        from unittest.mock import patch

        from cable_tension.dynamic import DynamicCaseInput
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history
        from cable_tension.hydrodynamics import current_at

        seen_vessel_speed_terms: list[float] = []

        def recording_current_at(**kwargs):
            seen_vessel_speed_terms.append(kwargs["vessel_speed_mps"])
            return current_at(**kwargs)

        with patch("cable_tension.dynamic_laying.current_at", side_effect=recording_current_at):
            solve_dynamic_laying_time_history(
                DynamicCaseInput(
                    case_name="known_plough_global_current",
                    current_speed_mps=0.95,
                    current_direction_deg=90.0,
                    speed_change="steady",
                    initial_speed_mps=0.8,
                    final_speed_mps=0.8,
                    payout_initial_speed_mps=0.88,
                    payout_final_speed_mps=0.88,
                    length_boundary_source="known_plough_trajectory",
                    duration_s=0.1,
                    total_duration_s=0.1,
                    water_depth_m=80.0,
                    element_count=8,
                    touchdown_tension_n=200.0,
                    vessel_initial_x_m=0.0,
                    vessel_initial_y_m=0.0,
                    vessel_heading_deg=0.0,
                    plough_initial_x_m=-55.0,
                    plough_initial_y_m=0.0,
                    plough_initial_z_m=78.0,
                    plough_speed_mps=0.75,
                    plough_heading_deg=0.0,
                    initial_suspended_length_m=100.0,
                ),
                points=3,
            )

        self.assertTrue(seen_vessel_speed_terms)
        self.assertEqual(set(seen_vessel_speed_terms), {0.0})

    def test_known_plough_step_applies_contact_friction_after_constraint_reaction(self):
        from unittest.mock import patch

        from cable_tension.dynamic import DynamicCaseInput, cable_parameters_from_dynamic_case
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _operation_case_at_time,
            _step_known_plough_dynamic,
        )

        dynamic_case = DynamicCaseInput(
            case_name="known_plough_contact_friction",
            current_speed_mps=0.35,
            current_direction_deg=90.0,
            speed_change="steady",
            initial_speed_mps=0.8,
            final_speed_mps=0.8,
            payout_initial_speed_mps=0.88,
            payout_final_speed_mps=0.88,
            length_boundary_source="known_plough_trajectory",
            duration_s=0.1,
            total_duration_s=0.1,
            water_depth_m=20.0,
            element_count=4,
            touchdown_tension_n=20.0,
            vessel_initial_x_m=0.0,
            vessel_initial_y_m=0.0,
            vessel_heading_deg=0.0,
            plough_initial_x_m=-18.0,
            plough_initial_y_m=0.0,
            plough_initial_z_m=20.0,
            plough_speed_mps=0.6,
            plough_heading_deg=0.0,
            initial_suspended_length_m=30.0,
        )
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (-9.0, 0.0, 20.5), (-18.0, 0.0, 20.0)),
            velocities=((0.8, 0.0, 0.0), (1.5, 0.0, 0.0), (0.6, 0.0, 0.0)),
            rest_lengths_m=(22.0, 9.5),
            paid_length_m=31.5,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
        )
        case = _operation_case_at_time(dynamic_case, cable, 0.0, vessel_fixed_current=False)
        seen_kwargs = []
        seen_friction_reactions = []
        seen_friction_kwargs = []

        def recording_compute_forces(case_arg, state_arg, **kwargs):
            seen_kwargs.append(kwargs)
            return tuple((0.0, 0.0, 0.0) for _ in state_arg.positions)

        def recording_apply_contact_friction(**kwargs):
            seen_friction_kwargs.append(kwargs)
            seen_friction_reactions.append(kwargs["contact_normal_reactions_n"])
            return kwargs["positions"], kwargs["velocities"]

        with patch("cable_tension.dynamic_laying.compute_forces", side_effect=recording_compute_forces):
            with patch("cable_tension.dynamic_laying._apply_contact_friction", side_effect=recording_apply_contact_friction):
                _step_known_plough_dynamic(
                    dynamic_case,
                    case,
                    state,
                    time_s=0.0,
                    dt_s=0.05,
                    seabed_friction_coefficient=0.6,
                )

        self.assertTrue(seen_kwargs)
        self.assertIsNone(seen_kwargs[0]["seabed_depth_m"])
        self.assertNotIn("seabed_friction_coefficient", seen_kwargs[0])
        self.assertAlmostEqual(seen_kwargs[0]["payout_speed_mps"], 0.88)
        self.assertAlmostEqual(seen_kwargs[0]["plough_exit_speed_mps"], 0.6)
        self.assertTrue(seen_friction_reactions)
        self.assertTrue(any(reaction > 0.0 for reaction in seen_friction_reactions[0]))
        self.assertAlmostEqual(seen_friction_kwargs[0]["payout_speed_mps"], 0.88)
        self.assertAlmostEqual(seen_friction_kwargs[0]["plough_exit_speed_mps"], 0.6)

    def test_operation_case_keeps_vessel_fixed_current_for_non_plough_path(self):
        from cable_tension.cases import get_cable
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import _operation_case_at_time

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p00")
        cable = get_cable("LA")

        vessel_fixed = _operation_case_at_time(dynamic_case, cable, 5.0)
        global_current = _operation_case_at_time(
            dynamic_case,
            cable,
            5.0,
            vessel_fixed_current=False,
        )

        self.assertGreater(vessel_fixed.vessel_speed_mps, 0.0)
        self.assertEqual(global_current.vessel_speed_mps, 0.0)
        self.assertEqual(vessel_fixed.payout_speed_mps, global_current.payout_speed_mps)

    def test_known_plough_tdp_is_contact_transition_or_plough_inlet_without_contact(self):
        import math

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            get_time_history_case("plough_cross_current_0p95_90deg_6min"),
            points=11,
        )

        final_point = result.history[-1]
        final_frame = result.frames[-1]
        plough_endpoint = final_frame.points[-1]
        tdp_to_plough = math.hypot(
            final_point.tdp_x_m - plough_endpoint.x_m,
            final_point.tdp_y_m - plough_endpoint.y_m,
        )

        self.assertAlmostEqual(plough_endpoint.x_m, final_frame.plough_x_m)
        self.assertAlmostEqual(plough_endpoint.y_m, final_frame.plough_y_m)
        if (final_point.seabed_contact_length_m or 0.0) > 0.0:
            self.assertGreater(tdp_to_plough, 0.5)
        else:
            self.assertAlmostEqual(tdp_to_plough, 0.0, places=8)

    def test_known_plough_current_direction_changes_tdp_footprint(self):
        import math

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        cross_current = solve_dynamic_laying_time_history(
            get_time_history_case("plough_cross_current_0p95_90deg_6min"),
            points=11,
        )
        following_current = solve_dynamic_laying_time_history(
            get_time_history_case("plough_cross_current_0p95_0deg_6min"),
            points=11,
        )

        cross_shape_y = max(abs(point.y_m) for point in cross_current.frames[-1].points[1:-1])
        following_shape_y = max(abs(point.y_m) for point in following_current.frames[-1].points[1:-1])
        tdp_delta = math.hypot(
            cross_current.history[-1].tdp_x_m - following_current.history[-1].tdp_x_m,
            cross_current.history[-1].tdp_y_m - following_current.history[-1].tdp_y_m,
        )

        self.assertGreater(cross_shape_y, following_shape_y + 5.0)
        self.assertGreater(tdp_delta, 1.0)

    def test_known_plough_tdp_falls_back_to_plough_inlet_section_without_contact(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _known_plough_tdp,
            _operation_case_at_time,
            _plough_inlet_tension_from_dynamic_state,
        )

        state = DynamicLayingState(
            time_s=0.0,
            positions=(
                (0.0, 0.0, 0.0),
                (5.0, 0.0, 55.0),
                (12.0, 3.0, 78.0),
                (16.0, 4.0, 76.0),
                (20.0, 0.0, 77.0),
            ),
            velocities=tuple((0.0, 0.0, 0.0) for _ in range(5)),
            rest_lengths_m=(55.3, 24.2, 4.5, 5.7),
            paid_length_m=89.7,
            laid_length_m=0.0,
            contact_flags=(False, False, False, False, False),
            segment_tensions_n=(500.0, 400.0, 300.0, 10.0),
            length_constraint_reactions_n=(500.0, 400.0, 300.0, 10.0),
        )

        self.assertEqual(_known_plough_tdp(state, seabed_depth_m=80.0), state.positions[-1])
        dynamic_case = get_time_history_case("plough_straight_baseline_6min")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        case = _operation_case_at_time(dynamic_case, cable, 0.0, vessel_fixed_current=False)
        self.assertEqual(
            _plough_inlet_tension_from_dynamic_state(
                dynamic_case,
                case,
                state,
                0.0,
                endpoint_segment_tensions=state.length_constraint_reactions_n,
            ),
            10.0,
        )

    def test_known_plough_touchdown_tension_is_not_external_boundary_force(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        base_case = get_time_history_case("plough_straight_baseline_6min")
        zero_estimate = solve_dynamic_laying_time_history(
            dataclasses.replace(
                base_case,
                case_name="known_plough_zero_tdp_estimate",
                touchdown_tension_n=0.0,
            ),
            points=7,
        )
        high_estimate = solve_dynamic_laying_time_history(
            dataclasses.replace(
                base_case,
                case_name="known_plough_high_tdp_estimate",
                touchdown_tension_n=400.0,
            ),
            points=7,
        )

        self.assertAlmostEqual(zero_estimate.steady_tension_n, high_estimate.steady_tension_n)
        self.assertAlmostEqual(
            zero_estimate.plough_adjacent_segment_tension_final_n,
            high_estimate.plough_adjacent_segment_tension_final_n,
        )
        self.assertAlmostEqual(
            zero_estimate.plough_boundary_tension_final_n,
            high_estimate.plough_boundary_tension_final_n,
        )
        self.assertAlmostEqual(
            high_estimate.plough_boundary_tension_final_n,
            high_estimate.plough_adjacent_segment_tension_final_n,
        )
        self.assertLess(
            high_estimate.plough_inlet_tension_final_n,
            high_estimate.plough_boundary_tension_final_n,
        )
        self.assertGreater(
            abs(high_estimate.plough_boundary_tension_final_n - 400.0),
            50.0,
        )
        for zero_point, high_point in zip(zero_estimate.frames[-1].points, high_estimate.frames[-1].points):
            self.assertAlmostEqual(zero_point.x_m, high_point.x_m)
            self.assertAlmostEqual(zero_point.y_m, high_point.y_m)
            self.assertAlmostEqual(zero_point.z_m, high_point.z_m)
            self.assertAlmostEqual(zero_point.tension_n, high_point.tension_n)
        self.assertAlmostEqual(
            high_estimate.history[-1].plough_boundary_tension_n,
            high_estimate.history[-1].plough_adjacent_segment_tension_n,
        )

    def test_known_plough_initial_state_uses_fixed_end_static_reaction(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_endpoint_catenary_profile,
            _initial_known_plough_state,
        )

        dynamic_case = dataclasses.replace(
            get_time_history_case("plough_straight_baseline_6min"),
            current_speed_mps=0.0,
            initial_speed_mps=0.0,
            final_speed_mps=0.0,
            payout_initial_speed_mps=0.0,
            payout_final_speed_mps=0.0,
            plough_speed_mps=0.0,
            plough_exit_speed_mps=0.55,
        )
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_known_plough_state(dynamic_case, cable)
        expected_profile = _initial_endpoint_catenary_profile(
            state.positions[0],
            state.positions[-1],
            element_count=dynamic_case.element_count,
            suspended_length_m=state.suspended_length_m,
            submerged_weight_n_per_m=cable.submerged_weight_n_per_m,
            water_depth_m=dynamic_case.water_depth_m,
        )
        self.assertIsNotNone(expected_profile)
        expected_positions, _ = expected_profile
        expected_top, expected_plough = _closed_form_catenary_endpoint_tensions_z_down(
            top=state.positions[0],
            bottom=state.positions[-1],
            length_m=state.suspended_length_m,
            submerged_weight_n_per_m=cable.submerged_weight_n_per_m,
        )

        self.assertAlmostEqual(sum(state.rest_lengths_m), state.suspended_length_m)
        for actual, expected in zip(state.positions, expected_positions):
            self.assertAlmostEqual(actual[0], expected[0])
            self.assertAlmostEqual(actual[1], expected[1])
            self.assertAlmostEqual(actual[2], expected[2])
        self.assertAlmostEqual(state.segment_tensions_n[0], expected_top, delta=0.02 * expected_top)
        self.assertAlmostEqual(state.segment_tensions_n[-1], expected_plough, delta=0.02 * expected_plough)
        self.assertLess(state.segment_tensions_n[-1], state.segment_tensions_n[0])

    def test_known_plough_material_flow_updates_end_lengths_without_global_scaling(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _step_known_plough_dynamic,
        )

        dynamic_case = dataclasses.replace(
            get_time_history_case("plough_straight_baseline_6min"),
            current_speed_mps=0.0,
            initial_speed_mps=0.0,
            final_speed_mps=0.0,
            payout_initial_speed_mps=0.5,
            payout_final_speed_mps=0.5,
            plough_speed_mps=0.0,
        )
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_known_plough_state(dynamic_case, cable)
        case = _operation_case_at_time(dynamic_case, cable, 0.0, vessel_fixed_current=False)

        updated = _step_known_plough_dynamic(dynamic_case, case, state, time_s=0.0, dt_s=0.1)

        self.assertGreater(updated.rest_lengths_m[0], state.rest_lengths_m[0])
        self.assertAlmostEqual(updated.rest_lengths_m[-1], state.rest_lengths_m[-1])
        uniform_scaled = tuple(
            sum(updated.rest_lengths_m) / len(updated.rest_lengths_m)
            for _ in updated.rest_lengths_m
        )
        self.assertNotEqual(updated.rest_lengths_m, uniform_scaled)
        self.assertAlmostEqual(
            sum(updated.rest_lengths_m),
            sum(state.rest_lengths_m) + 0.5 * 0.1,
        )

    def test_payout_remesh_split_preserves_first_segment_geometry_and_strain(self):
        from cable_tension.dynamic_laying import DynamicLayingState, _insert_payout_nodes

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
            rest_lengths_m=(1.4, 1.0),
            paid_length_m=2.4,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
            length_lambdas_n_s2=(0.06, 0.04),
            segment_tensions_n=(600.0, 400.0),
            length_constraint_reactions_n=(600.0, 400.0),
        )

        updated = _insert_payout_nodes(
            state,
            payout_increment_m=0.2,
            target_segment_length_m=1.0,
        )

        original_curve_length = sum(
            math.dist(left, right)
            for left, right in zip(state.positions, state.positions[1:])
        )
        original_reaction_integral = 600.0 * 1.6 + 400.0 * 1.0
        self.assertEqual(len(updated.positions), len(state.positions) + 1)
        self.assertEqual(updated.positions[0], state.positions[0])
        self.assertEqual(updated.positions[-1], state.positions[-1])
        self.assertAlmostEqual(sum(updated.rest_lengths_m), 2.6, places=12)
        self.assertAlmostEqual(
            sum(
                math.dist(left, right)
                for left, right in zip(updated.positions, updated.positions[1:])
            ),
            original_curve_length,
            places=10,
        )
        stretch_ratios = [
            math.dist(left, right) / rest_length
            for left, right, rest_length in zip(
                updated.positions,
                updated.positions[1:],
                updated.rest_lengths_m,
            )
        ]
        self.assertGreaterEqual(min(stretch_ratios), 1.0 - 1.0e-12)
        self.assertLessEqual(max(stretch_ratios), 1.25 + 1.0e-12)
        self.assertAlmostEqual(
            sum(
                reaction * rest_length
                for reaction, rest_length in zip(
                    updated.length_constraint_reactions_n,
                    updated.rest_lengths_m,
                )
            ),
            original_reaction_integral,
            places=10,
        )

    def test_known_plough_tail_withdrawal_defers_remesh_while_material_cfl_is_satisfied(self):
        from cable_tension.dynamic_laying import DynamicLayingState, _advance_known_plough_material_flow

        positions = tuple((float(index), 0.0, 0.0) for index in range(7))
        state = DynamicLayingState(
            time_s=0.0,
            positions=positions,
            velocities=tuple((0.0, 0.0, 0.0) for _ in positions),
            rest_lengths_m=(1.0, 1.0, 1.0, 1.0, 1.0, 0.23),
            paid_length_m=5.23,
            laid_length_m=0.0,
            contact_flags=tuple(False for _ in positions),
        )

        updated = _advance_known_plough_material_flow(
            state,
            payout_increment_m=0.0,
            laydown_increment_m=0.01,
            target_segment_length_m=1.0,
        )

        self.assertEqual(len(updated.positions), len(state.positions))
        self.assertEqual(updated.positions, state.positions)
        self.assertAlmostEqual(updated.rest_lengths_m[-1], 0.22, places=12)

    def test_matched_two_end_material_flow_keeps_the_computational_mesh_unchanged(self):
        from cable_tension.dynamic_laying import DynamicLayingState, _advance_known_plough_material_flow

        positions = tuple((float(index), 0.0, 0.0) for index in range(7))
        state = DynamicLayingState(
            time_s=0.0,
            positions=positions,
            velocities=tuple((0.1 * index, 0.0, 0.0) for index in range(7)),
            rest_lengths_m=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
            paid_length_m=6.0,
            laid_length_m=0.0,
            contact_flags=tuple(False for _ in positions),
            length_lambdas_n_s2=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
            segment_tensions_n=(10.0, 20.0, 30.0, 40.0, 50.0, 60.0),
            length_constraint_reactions_n=(10.0, 20.0, 30.0, 40.0, 50.0, 60.0),
        )

        updated = _advance_known_plough_material_flow(
            state,
            payout_increment_m=0.1,
            laydown_increment_m=0.1,
            target_segment_length_m=1.0,
        )

        self.assertEqual(updated, state)

    def test_known_plough_scheduled_tail_remesh_receives_seabed_depth(self):
        from unittest.mock import patch

        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _advance_known_plough_material_flow,
            _remesh_known_plough_tail_window,
        )

        positions = (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 2.0),
            (2.0, 0.0, 4.0),
            (3.0, 0.0, 6.0),
            (4.0, 0.0, 8.0),
            (5.0, 0.0, 10.0),
            (5.1, 0.0, 10.0),
        )
        state = DynamicLayingState(
            time_s=0.0,
            positions=positions,
            velocities=tuple((0.0, 0.0, 0.0) for _ in positions),
            rest_lengths_m=(2.2, 2.2, 2.2, 2.2, 2.0, 0.1),
            paid_length_m=10.9,
            laid_length_m=0.0,
            contact_flags=(False, False, False, False, False, True, False),
        )

        with patch(
            "cable_tension.dynamic_laying._remesh_known_plough_tail_window",
            wraps=_remesh_known_plough_tail_window,
        ) as remesh:
            _advance_known_plough_material_flow(
                state,
                payout_increment_m=0.0,
                laydown_increment_m=0.05,
                target_segment_length_m=2.0,
                seabed_depth_m=10.0,
            )

        self.assertEqual(remesh.call_args.kwargs["seabed_depth_m"], 10.0)

    def test_known_plough_tail_remesh_preserves_deformed_curve_and_tension_integral(self):
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _withdraw_known_plough_tail_length,
        )

        positions = (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.1, 0.0),
            (3.0, 0.3, 0.0),
            (4.0, 0.6, 0.0),
            (5.0, 1.0, 0.0),
            (5.5, 1.3, 0.0),
        )
        rest_lengths = (0.95, 0.95, 0.95, 0.95, 0.95, 0.55)
        tensions = (600.0, 550.0, 500.0, 450.0, 400.0, 350.0)
        lambdas = tuple(tension * 0.01**2 for tension in tensions)
        state = DynamicLayingState(
            time_s=1.0,
            positions=positions,
            velocities=tuple((0.2 + 0.01 * index, 0.0, 0.0) for index in range(len(positions))),
            rest_lengths_m=rest_lengths,
            paid_length_m=sum(rest_lengths),
            laid_length_m=0.0,
            contact_flags=tuple(False for _ in positions),
            length_lambdas_n_s2=lambdas,
            segment_tensions_n=tensions,
            length_constraint_reactions_n=tensions,
            contact_lambdas_n_s2=tuple(0.0 for _ in positions),
            contact_normal_reactions_n=tuple(0.0 for _ in positions),
        )
        laydown_increment_m = 0.05
        initial_curve_length_m = sum(math.dist(left, right) for left, right in zip(positions, positions[1:]))
        expected_tension_integral_n_m = (
            sum(tension * length for tension, length in zip(tensions, rest_lengths))
            - tensions[-1] * laydown_increment_m
        )

        initial_max_velocity_mps = max(math.sqrt(sum(component**2 for component in velocity)) for velocity in state.velocities)

        updated = _withdraw_known_plough_tail_length(
            state,
            laydown_increment_m=laydown_increment_m,
            minimum_segment_length_m=0.5,
        )

        updated_curve_length_m = sum(
            math.dist(left, right)
            for left, right in zip(updated.positions, updated.positions[1:])
        )
        updated_tension_integral_n_m = sum(
            tension * length
            for tension, length in zip(updated.segment_tensions_n, updated.rest_lengths_m)
        )
        updated_max_velocity_mps = max(
            math.sqrt(sum(component**2 for component in velocity))
            for velocity in updated.velocities
        )
        self.assertEqual(len(updated.positions), len(positions) - 1)
        self.assertEqual(updated.positions[0], positions[0])
        self.assertEqual(updated.positions[-1], positions[-1])
        self.assertAlmostEqual(
            sum(updated.rest_lengths_m),
            sum(rest_lengths) - laydown_increment_m,
            places=12,
        )
        self.assertAlmostEqual(updated_curve_length_m, initial_curve_length_m, places=8)
        self.assertAlmostEqual(
            updated_tension_integral_n_m,
            expected_tension_integral_n_m,
            places=8,
        )
        self.assertEqual(updated.velocities[0], state.velocities[0])
        self.assertEqual(updated.velocities[-1], state.velocities[-1])
        self.assertLessEqual(updated_max_velocity_mps, initial_max_velocity_mps + 1.0e-12)

    def test_tail_remesh_projection_preserves_near_taut_bend_side(self):
        from cable_tension.dynamic_laying import _project_open_chain_segment_lengths

        positions = [
            (0.0, 0.0, 0.0),
            (3.39, 0.02, 0.0),
            (6.79, 0.03, 0.0),
            (10.19, 0.03, 0.0),
            (13.59, 0.02, 0.0),
            (16.995, 0.0, 0.0),
        ]
        target_lengths = [3.41494, 3.41408, 3.41406, 3.41427, 3.42968]

        projected = _project_open_chain_segment_lengths(positions, target_lengths)

        self.assertIsNotNone(projected)
        assert projected is not None
        self.assertEqual(projected[0], positions[0])
        self.assertEqual(projected[-1], positions[-1])
        self.assertTrue(all(position[1] >= -1.0e-12 for position in projected))
        for left, right, target in zip(projected, projected[1:], target_lengths):
            self.assertAlmostEqual(math.dist(left, right), target, places=8)

    def test_known_plough_tail_remesh_failure_is_not_silently_advanced(self):
        from unittest.mock import patch

        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _withdraw_known_plough_tail_length,
        )

        state = DynamicLayingState(
            time_s=0.0,
            positions=(
                (0.0, 0.0, 0.0),
                (1.0, 0.1, 0.0),
                (2.0, 0.2, 0.0),
                (3.0, 0.3, 0.0),
            ),
            velocities=tuple((0.0, 0.0, 0.0) for _ in range(4)),
            rest_lengths_m=(1.0, 1.0, 0.55),
            paid_length_m=2.55,
            laid_length_m=0.0,
            contact_flags=(False, False, False, False),
        )

        with patch("cable_tension.dynamic_laying._remesh_known_plough_tail_window", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "tail remesh projection failed"):
                _withdraw_known_plough_tail_length(
                    state,
                    laydown_increment_m=0.05,
                    minimum_segment_length_m=0.5,
                )

    def test_known_plough_step_preserves_prescribed_endpoint_velocities(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _plough_velocity,
            _step_known_plough_dynamic,
            _vessel_velocity,
        )

        dynamic_case = get_time_history_case("plough_straight_baseline_6min")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_known_plough_state(dynamic_case, cable)
        case = _operation_case_at_time(dynamic_case, cable, 0.0, vessel_fixed_current=False)

        updated = _step_known_plough_dynamic(dynamic_case, case, state, time_s=0.0, dt_s=0.05)

        self.assertEqual(updated.velocities[0], _vessel_velocity(dynamic_case, 0.05))
        self.assertEqual(updated.velocities[-1], _plough_velocity(dynamic_case, 0.05))

    def test_known_plough_laydown_uses_route_projection_not_transverse_speed(self):
        from cable_tension.dynamic import MotionSegment, cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _step_known_plough_dynamic,
        )

        base_case = get_time_history_case("plough_straight_baseline_6min")
        transverse_plough = dataclasses.replace(
            base_case,
            current_speed_mps=0.0,
            initial_speed_mps=0.0,
            final_speed_mps=0.0,
            payout_initial_speed_mps=0.0,
            payout_final_speed_mps=0.0,
            plough_speed_mps=0.0,
            plough_exit_speed_mps=0.55,
            plough_motion_segments=(
                MotionSegment(
                    duration_s=1.0,
                    start_speed_mps=1.0,
                    end_speed_mps=1.0,
                    heading_deg=90.0,
                    start_velocity_x_mps=0.0,
                    start_velocity_y_mps=1.0,
                    end_velocity_x_mps=0.0,
                    end_velocity_y_mps=1.0,
                ),
            ),
        )
        forward_plough = dataclasses.replace(
            transverse_plough,
            plough_exit_speed_mps=None,
            plough_motion_segments=(
                MotionSegment(
                    duration_s=1.0,
                    start_speed_mps=1.0,
                    end_speed_mps=1.0,
                    heading_deg=0.0,
                    start_velocity_x_mps=1.0,
                    start_velocity_y_mps=0.0,
                    end_velocity_x_mps=1.0,
                    end_velocity_y_mps=0.0,
                ),
            ),
        )

        for dynamic_case, expected_delta in ((transverse_plough, -0.055), (forward_plough, -0.1)):
            cable = cable_parameters_from_dynamic_case(dynamic_case)
            state = _initial_known_plough_state(dynamic_case, cable)
            case = _operation_case_at_time(dynamic_case, cable, 0.0, vessel_fixed_current=False)
            updated = _step_known_plough_dynamic(dynamic_case, case, state, time_s=0.0, dt_s=0.1)

            self.assertAlmostEqual(
                updated.material_suspended_length_m,
                state.material_suspended_length_m + expected_delta,
            )

    def test_known_plough_final_geometry_keeps_material_length_residual_bounded(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            get_time_history_case("plough_straight_baseline_6min"),
            points=7,
        )

        final_length = _frame_polyline_length(result.frames[-1])
        length_residual = final_length - result.history[-1].suspended_length_m
        tolerance = max(0.25, 0.002 * result.history[-1].suspended_length_m)

        self.assertLess(
            abs(length_residual),
            tolerance,
            "known-plough geometry should stay close to the material suspended length",
        )
        self.assertIsNotNone(result.history[-1].material_suspended_length_m)
        self.assertAlmostEqual(
            result.history[-1].material_suspended_length_m,
            result.history[-1].suspended_length_m,
        )
        self.assertAlmostEqual(result.geometric_length_deficit_final_m or 0.0, 0.0)

    def test_known_plough_reports_configured_minimum_bend_radius_margin(self):
        from cable_tension.dynamic import DynamicCaseInput
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        case = DynamicCaseInput(
            case_name="known_plough_bend_radius_limit",
            current_speed_mps=0.35,
            current_direction_deg=90.0,
            speed_change="steady",
            initial_speed_mps=0.8,
            final_speed_mps=0.8,
            payout_initial_speed_mps=0.88,
            payout_final_speed_mps=0.88,
            length_boundary_source="known_plough_trajectory",
            duration_s=12.0,
            total_duration_s=12.0,
            water_depth_m=80.0,
            element_count=10,
            touchdown_tension_n=200.0,
            vessel_initial_x_m=0.0,
            vessel_initial_y_m=0.0,
            vessel_heading_deg=0.0,
            plough_initial_x_m=-55.0,
            plough_initial_y_m=0.0,
            plough_initial_z_m=78.0,
            plough_speed_mps=0.75,
            plough_heading_deg=0.0,
            initial_suspended_length_m=100.0,
            min_bending_radius_m=8.0,
        )
        result = solve_dynamic_laying_time_history(case, points=5)

        self.assertEqual(result.minimum_bend_radius_limit_m, 8.0)
        self.assertIsNotNone(result.minimum_bend_radius_min_m)
        self.assertAlmostEqual(
            result.minimum_bend_radius_margin_m,
            result.minimum_bend_radius_min_m - 8.0,
        )
        self.assertGreaterEqual(result.minimum_bend_radius_min_m, 8.0)
        self.assertEqual(result.minimum_bend_radius_status, "ok")

        impossible_limit = solve_dynamic_laying_time_history(
            dataclasses.replace(case, min_bending_radius_m=10_000.0),
            points=5,
        )

        self.assertEqual(impossible_limit.minimum_bend_radius_limit_m, 10_000.0)
        self.assertLess(impossible_limit.minimum_bend_radius_margin_m, 0.0)
        self.assertEqual(impossible_limit.minimum_bend_radius_status, "below_limit")

    def test_known_plough_bend_projection_rejects_infeasible_radius(self):
        from cable_tension.dynamic_laying import _feasible_bend_projection_radius_m

        arguments = {
            "rest_lengths_m": (50.0, 50.0),
            "top_position": (0.0, 0.0, 0.0),
            "bottom_position": (55.0, 0.0, 78.0),
        }
        self.assertEqual(
            _feasible_bend_projection_radius_m(requested_radius_m=8.0, **arguments),
            8.0,
        )
        self.assertIsNone(
            _feasible_bend_projection_radius_m(requested_radius_m=10_000.0, **arguments)
        )
        self.assertEqual(
            _feasible_bend_projection_radius_m(
                requested_radius_m=10_000.0,
                rest_lengths_m=(5.0,),
                top_position=(0.0, 0.0, 0.0),
                bottom_position=(5.0, 0.0, 0.0),
            ),
            10_000.0,
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            _feasible_bend_projection_radius_m(requested_radius_m=math.nan, **arguments)

    def test_known_plough_reports_tdp_inlet_separately_from_endpoint_tail_reaction(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            get_time_history_case("plough_straight_baseline_6min"),
            points=7,
        )

        self.assertIsNotNone(result.plough_boundary_tension_final_n)
        self.assertGreater(result.plough_boundary_tension_final_n, 10.0)
        self.assertLess(
            result.plough_inlet_tension_final_n,
            result.plough_boundary_tension_final_n,
        )
        self.assertAlmostEqual(
            result.plough_boundary_tension_final_n,
            result.plough_adjacent_segment_tension_final_n,
        )
        self.assertEqual(result.plough_tension_status, "carried")
        final_point = result.history[-1]
        self.assertAlmostEqual(
            final_point.plough_boundary_tension_n,
            final_point.plough_adjacent_segment_tension_n,
        )
        self.assertAlmostEqual(
            result.frames[-1].points[-1].tension_n,
            result.plough_adjacent_segment_tension_final_n,
        )
        self.assertAlmostEqual(
            result.frames[-1].segment_tensions_n[-1],
            result.plough_adjacent_segment_tension_final_n,
        )
        self.assertAlmostEqual(result.history[-1].top_tension_n, result.frames[-1].segment_tensions_n[0])
        self.assertGreater(result.history[-1].top_tension_n, 0.0)
        self.assertAlmostEqual(result.geometric_length_deficit_final_m or 0.0, 0.0)

    def test_known_plough_internal_step_is_not_report_sampling_step(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        case = get_time_history_case("plough_material_power_500kv_6min")
        coarse_output = solve_dynamic_laying_time_history(case, points=7)
        dense_output = solve_dynamic_laying_time_history(case, points=61)

        self.assertAlmostEqual(coarse_output.integration_time_step_max_s, 0.05)
        self.assertAlmostEqual(dense_output.integration_time_step_max_s, 0.05)
        self.assertLess(coarse_output.integration_time_step_max_s, coarse_output.total_duration_s / 6)
        self.assertLess(dense_output.integration_time_step_max_s, dense_output.total_duration_s / 60)
        self.assertIsNotNone(coarse_output.spatial_step_min_m)
        self.assertGreater(coarse_output.spatial_step_min_m, 0.0)
        self.assertGreaterEqual(coarse_output.xpbd_iterations_per_step, 20)
        self.assertLessEqual(coarse_output.xpbd_iterations_per_step, 100)
        self.assertEqual(
            coarse_output.xpbd_iterations_per_step,
            coarse_output.xpbd_iterations_per_step_max,
        )
        self.assertGreaterEqual(coarse_output.xpbd_iterations_per_step_min, 1)
        self.assertEqual(
            coarse_output.xpbd_iterations_per_step_min,
            dense_output.xpbd_iterations_per_step_min,
        )
        self.assertEqual(
            coarse_output.xpbd_iterations_per_step_max,
            dense_output.xpbd_iterations_per_step_max,
        )
        self.assertEqual(coarse_output.xpbd_iteration_limit_per_solve, 100)
        self.assertLessEqual(coarse_output.axial_constraint_residual_max_m, 1.0e-10)
        self.assertAlmostEqual(
            coarse_output.history[-1].top_tension_n,
            dense_output.history[-1].top_tension_n,
            delta=max(0.01, 1.0e-6 * abs(dense_output.history[-1].top_tension_n)),
        )
        self.assertAlmostEqual(
            coarse_output.history[-1].plough_adjacent_segment_tension_n,
            dense_output.history[-1].plough_adjacent_segment_tension_n,
            delta=max(0.01, 1.0e-6 * abs(dense_output.history[-1].plough_adjacent_segment_tension_n)),
        )

    def test_known_plough_bend_radius_uses_internal_steps_not_output_sampling(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        case = get_time_history_case("plough_straight_baseline_6min")
        sparse_output = solve_dynamic_laying_time_history(case, points=7)
        dense_output = solve_dynamic_laying_time_history(case, points=61)

        self.assertAlmostEqual(
            sparse_output.minimum_bend_radius_min_m,
            dense_output.minimum_bend_radius_min_m,
            delta=1.0e-6,
        )

    def test_known_plough_reports_minimum_bend_radius_diagnostics(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            get_time_history_case("plough_straight_baseline_6min"),
            points=7,
        )

        self.assertIsNotNone(result.minimum_bend_radius_min_m)
        self.assertIsNotNone(result.minimum_bend_radius_time_s)
        self.assertIsNotNone(result.minimum_bend_radius_node_index)
        self.assertIsNotNone(result.minimum_bend_radius_left_segment_m)
        self.assertIsNotNone(result.minimum_bend_radius_right_segment_m)
        self.assertIsNotNone(result.minimum_bend_radius_turn_angle_deg)
        self.assertIsNotNone(result.minimum_bend_radius_node_depth_m)
        self.assertIsNotNone(result.minimum_bend_radius_near_seabed)
        self.assertEqual(result.minimum_bend_radius_excluded_tail_nodes, 2)
        self.assertIsNotNone(result.minimum_bend_radius_raw_m)
        self.assertIsNotNone(result.minimum_bend_radius_raw_time_s)
        self.assertIsNotNone(result.minimum_bend_radius_raw_node_index)
        self.assertIsNotNone(result.minimum_bend_radius_raw_left_segment_m)
        self.assertIsNotNone(result.minimum_bend_radius_raw_right_segment_m)
        self.assertIsNotNone(result.minimum_bend_radius_raw_turn_angle_deg)
        self.assertIsNotNone(result.minimum_bend_radius_raw_node_depth_m)
        self.assertIsNotNone(result.minimum_bend_radius_raw_near_seabed)
        self.assertGreaterEqual(result.minimum_bend_radius_time_s, 0.0)
        self.assertLessEqual(result.minimum_bend_radius_time_s, result.total_duration_s)
        self.assertGreaterEqual(result.minimum_bend_radius_raw_time_s, 0.0)
        self.assertLessEqual(result.minimum_bend_radius_raw_time_s, result.total_duration_s)
        max_frame_node_count = max(len(frame.points) for frame in result.frames)
        self.assertGreater(result.minimum_bend_radius_node_index, 0)
        self.assertLess(result.minimum_bend_radius_node_index, max_frame_node_count - 1)
        self.assertGreater(result.minimum_bend_radius_raw_node_index, 0)
        self.assertLess(result.minimum_bend_radius_raw_node_index, max_frame_node_count - 1)
        self.assertLessEqual(result.minimum_bend_radius_raw_m, result.minimum_bend_radius_min_m)
        self.assertGreater(result.minimum_bend_radius_left_segment_m, 0.0)
        self.assertGreater(result.minimum_bend_radius_right_segment_m, 0.0)
        self.assertGreater(result.minimum_bend_radius_turn_angle_deg, 0.0)
        self.assertGreaterEqual(result.minimum_bend_radius_node_depth_m, 0.0)
        self.assertLessEqual(result.minimum_bend_radius_node_depth_m, result.water_depth_m + 1.0e-6)
        self.assertIsInstance(result.minimum_bend_radius_near_seabed, bool)
        self.assertIsInstance(result.minimum_bend_radius_raw_near_seabed, bool)
        self.assertEqual(result.history[-1].minimum_bend_radius_excluded_tail_nodes, 2)
        self.assertLessEqual(
            result.history[-1].minimum_bend_radius_raw_m,
            result.history[-1].minimum_bend_radius_m,
        )
        self.assertIsNotNone(result.frames[-1].minimum_bend_radius_left_segment_m)
        self.assertIsNotNone(result.frames[-1].minimum_bend_radius_right_segment_m)
        self.assertIsNotNone(result.frames[-1].minimum_bend_radius_node_depth_m)
        self.assertIsInstance(result.frames[-1].minimum_bend_radius_near_seabed, bool)
        self.assertEqual(result.frames[-1].minimum_bend_radius_excluded_tail_nodes, 2)

    def test_known_plough_refinement_does_not_create_numerical_kinks(self):
        from dataclasses import replace

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        case = get_time_history_case("plough_straight_baseline_6min")

        for element_count in (24, 48):
            result = solve_dynamic_laying_time_history(
                replace(case, element_count=element_count),
                points=9,
            )
            self.assertIsNotNone(result.minimum_bend_radius_min_m)
            self.assertIsNotNone(result.spatial_step_min_m)
            self.assertGreater(
                result.minimum_bend_radius_min_m,
                0.1 * result.spatial_step_min_m,
                f"{element_count} elements should not create a local kink smaller than 10% of segment length",
            )

    def test_known_plough_tail_cluster_merge_does_not_consume_free_span_bend(self):
        from cable_tension.dynamic_laying import _merge_known_plough_tail_contact_cluster

        positions = (
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 4.0),
            (2.0, 2.0, 7.0),
            (1.0, 3.0, 8.0),
            (0.5, 4.0, 8.2),
        )
        velocities = tuple((0.0, 0.0, 0.0) for _ in positions)
        rest_lengths = (3.0, 3.0, 3.0, 3.0)

        merged_positions, _, merged_lengths, *_ = _merge_known_plough_tail_contact_cluster(
            positions=positions,
            velocities=velocities,
            rest_lengths_m=rest_lengths,
            contact_flags=(False, False, False, False, False),
            length_lambdas_n_s2=(0.0, 0.0, 0.0, 0.0),
            contact_lambdas_n_s2=(0.0, 0.0, 0.0, 0.0, 0.0),
            contact_normal_reactions_n=(0.0, 0.0, 0.0, 0.0, 0.0),
            seabed_depth_m=10.0,
        )

        self.assertEqual(merged_positions, positions)
        self.assertEqual(merged_lengths, rest_lengths)

    def test_known_plough_tail_cluster_merge_removes_folded_seabed_remnant(self):
        from cable_tension.dynamic_laying import _merge_known_plough_tail_contact_cluster

        positions = (
            (0.0, 0.0, 0.0),
            (0.0, -2.0, 6.0),
            (0.2, -3.0, 10.0),
            (0.4, -3.2, 10.0),
            (0.0, -3.1, 10.0),
        )
        velocities = tuple((0.0, 0.0, 0.0) for _ in positions)

        merged_positions, _, merged_lengths, *_ = _merge_known_plough_tail_contact_cluster(
            positions=positions,
            velocities=velocities,
            rest_lengths_m=(3.0, 3.0, 3.0, 3.0),
            contact_flags=(False, False, True, True, True),
            length_lambdas_n_s2=(0.0, 0.0, 0.0, 0.0),
            contact_lambdas_n_s2=(0.0, 0.0, 0.0, 0.0, 0.0),
            contact_normal_reactions_n=(0.0, 0.0, 0.0, 0.0, 0.0),
            seabed_depth_m=10.0,
        )

        self.assertLess(len(merged_positions), len(positions))
        self.assertEqual(merged_positions[-1], positions[-1])
        self.assertAlmostEqual(sum(merged_lengths), 12.0)

    def test_known_plough_tail_cluster_keeps_forward_subgrid_segment_above_material_cfl_limit(self):
        from cable_tension.dynamic_laying import _merge_known_plough_tail_contact_cluster

        positions = (
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 8.0),
            (1.0, 0.0, 10.0),
            (2.0, 0.0, 10.0),
            (2.4, 0.0, 10.0),
        )
        velocities = tuple((0.0, 0.0, 0.0) for _ in positions)

        merged_positions, _, merged_lengths, *_ = _merge_known_plough_tail_contact_cluster(
            positions=positions,
            velocities=velocities,
            rest_lengths_m=(2.0, 1.0, 1.0, 0.4),
            contact_flags=(False, False, True, True, True),
            length_lambdas_n_s2=(0.0, 0.0, 0.0, 0.0),
            contact_lambdas_n_s2=(0.0, 0.0, 0.0, 0.0, 0.0),
            contact_normal_reactions_n=(0.0, 0.0, 0.0, 0.0, 0.0),
            seabed_depth_m=10.0,
        )

        self.assertEqual(merged_positions, positions)
        self.assertEqual(merged_lengths, (2.0, 1.0, 1.0, 0.4))

    def test_minimum_bend_radius_counts_regular_free_span_bend(self):
        from cable_tension.dynamic_laying import _minimum_bend_radius

        radius = _minimum_bend_radius(
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
            )
        )

        self.assertAlmostEqual(radius, 2.0 / math.pi)

    def test_known_plough_bend_radius_can_exclude_prescribed_plough_inlet_fixture(self):
        from cable_tension.dynamic_laying import _minimum_bend_radius_diagnostic

        positions = (
            (0.0, 0.0, 0.0),
            (0.0, 6.0, 25.0),
            (0.0, 12.0, 50.0),
            (0.0, 18.0, 76.0),
            (0.0, 19.0, 79.4),
            (0.0, 18.2, 80.0),
        )

        unfiltered = _minimum_bend_radius_diagnostic(positions)
        filtered = _minimum_bend_radius_diagnostic(positions, exclude_tail_nodes=2)

        self.assertIn(unfiltered.node_index, {3, 4})
        self.assertNotIn(filtered.node_index, {3, 4})
        self.assertGreater(filtered.radius_m, unfiltered.radius_m)

    def test_known_plough_internal_step_shrinks_for_short_fast_segments(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import _initial_known_plough_state, _time_history_step_limit_s

        case = dataclasses.replace(
            get_time_history_case("plough_straight_baseline_6min"),
            element_count=300,
            initial_speed_mps=12.0,
            final_speed_mps=12.0,
            payout_initial_speed_mps=12.0,
            payout_final_speed_mps=12.0,
            plough_speed_mps=12.0,
            current_speed_mps=2.0,
        )
        state = _initial_known_plough_state(case)

        self.assertLess(_time_history_step_limit_s(case, state, base_step_s=0.05), 0.05)

    def test_dynamic_time_history_does_not_project_back_to_straight_line_state(self):
        import inspect

        from cable_tension.dynamic import get_time_history_case
        import cable_tension.dynamic_laying as dynamic_laying
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        source = inspect.getsource(dynamic_laying)
        self.assertNotIn("_project_to_speed_continuity_boundary", source)
        self.assertNotIn("_boundary_projection_velocities", source)
        result = solve_dynamic_laying_time_history(
            get_time_history_case("la_dynamic_accel_current_1p00"),
            points=5,
        )

        self.assertEqual(result.length_boundary_source, "xpbd_node_dynamics_contact_remesh")
        self.assertIn("XPBD/load-recursive segment tension diagnostics", result.evidence_level)

    def test_dynamic_time_history_does_not_use_legacy_force_balance_for_top_tension(self):
        from unittest.mock import patch

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        with patch(
            "cable_tension.dynamic_laying._top_tension_from_node_state",
            side_effect=AssertionError("top tension must come from the node-dynamic state"),
        ):
            result = solve_dynamic_laying_time_history(
                get_time_history_case("la_dynamic_decel_current_1p00"),
                points=5,
            )

        self.assertGreater(result.initial_tension_n, 0.0)
        self.assertGreater(result.steady_tension_n, 0.0)

    def test_dynamic_time_history_does_not_use_posthoc_force_balance_tensions(self):
        from unittest.mock import patch

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        with patch(
            "cable_tension.dynamic_laying._node_state_force_balance_tensions",
            side_effect=AssertionError("time-history tension must come from XPBD/axial state"),
        ):
            result = solve_dynamic_laying_time_history(
                get_time_history_case("la_dynamic_accel_current_1p00"),
                points=5,
            )

        self.assertGreater(result.initial_tension_n, 0.0)
        self.assertGreater(result.steady_tension_n, 0.0)

    def test_dynamic_time_history_frame_arc_matches_suspended_length(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        for case_name in (
            "la_dynamic_accel_current_1p00",
            "la_dynamic_accel_current_1p50",
            "la_dynamic_decel_current_1p00",
            "la_dynamic_decel_current_1p50",
        ):
            result = solve_dynamic_laying_time_history(
                get_time_history_case(case_name),
                points=13,
            )
            for history_point, frame in zip(result.history, result.frames):
                coordinates = [(point.x_m, point.y_m, point.z_m) for point in frame.points]
                frame_arc = sum(
                    math.dist(start, end)
                    for start, end in zip(coordinates, coordinates[1:])
                )

                self.assertAlmostEqual(
                    frame_arc,
                    history_point.suspended_length_m,
                    delta=1.0,
                    msg=f"{case_name} at {history_point.time_s:.1f}s",
                )

    def test_dynamic_time_history_tdp_is_on_frame_seabed_intersection(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        for case_name in (
            "la_dynamic_accel_current_1p00",
            "la_dynamic_accel_current_1p50",
            "la_dynamic_decel_current_1p00",
            "la_dynamic_decel_current_1p50",
        ):
            result = solve_dynamic_laying_time_history(
                get_time_history_case(case_name),
                points=31,
            )
            for history_point, frame in zip(result.history, result.frames):
                coordinates = [(point.x_m, point.y_m, point.z_m) for point in frame.points]
                frame_tdp = None
                for start, end in zip(coordinates, coordinates[1:]):
                    if end[2] >= result.water_depth_m - 1.0e-6:
                        # A projected contact node represents a nodal control
                        # volume, so the unresolved transition is reconstructed
                        # at the adjacent segment midpoint.
                        fraction = 0.5
                        frame_tdp = (
                            start[0] + (end[0] - start[0]) * fraction,
                            start[1] + (end[1] - start[1]) * fraction,
                            result.water_depth_m,
                        )
                        break

                self.assertIsNotNone(frame_tdp, f"{case_name} at {history_point.time_s:.1f}s")
                self.assertAlmostEqual(frame_tdp[2], result.water_depth_m, delta=1.0e-6)
                self.assertAlmostEqual(frame_tdp[0], history_point.tdp_x_m, delta=1.0e-6)
                self.assertAlmostEqual(frame_tdp[1], history_point.tdp_y_m, delta=1.0e-6)

    def test_dynamic_time_history_frames_stay_between_surface_and_seabed(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        for case_name in (
            "la_dynamic_accel_current_1p00",
            "la_dynamic_accel_current_1p50",
            "la_dynamic_decel_current_1p00",
            "la_dynamic_decel_current_1p50",
        ):
            result = solve_dynamic_laying_time_history(
                get_time_history_case(case_name),
                points=31,
            )
            for frame in result.frames:
                for point in frame.points:
                    self.assertGreaterEqual(point.z_m, -1.0e-6, case_name)
                    self.assertLessEqual(point.z_m, result.water_depth_m + 1.0e-6, case_name)

    def test_dynamic_time_history_suspended_frames_do_not_fold_upward(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        result = solve_dynamic_laying_time_history(
            get_time_history_case("la_dynamic_accel_current_1p50"),
            points=13,
        )

        for frame in result.frames:
            depths = [point.z_m for point in frame.points]
            for previous, current in zip(depths, depths[1:]):
                self.assertGreaterEqual(current + 1.0e-6, previous, frame.time_s)

    def test_dynamic_laying_frame_tensions_are_not_linear_placeholders(self):
        from cable_tension.cases import get_cable
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _operation_case_at_time,
            _point_tensions_from_state,
            _top_tension_from_node_state,
        )

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p00")
        case = _operation_case_at_time(dynamic_case, get_cable("LA"), 45.0)
        state = DynamicLayingState(
            time_s=45.0,
            positions=((0.0, 0.0, 0.0), (8.0, 2.0, 25.0), (20.0, 11.0, 63.0), (45.0, 31.0, 100.0)),
            velocities=((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(
                math.dist((0.0, 0.0, 0.0), (8.0, 2.0, 25.0)),
                math.dist((8.0, 2.0, 25.0), (20.0, 11.0, 63.0)),
                math.dist((20.0, 11.0, 63.0), (45.0, 31.0, 100.0)),
            ),
            paid_length_m=130.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False, True),
            segment_tensions_n=(1200.0, 800.0, 500.0),
        )
        point_tensions = _point_tensions_from_state(dynamic_case, case, state, 45.0)
        top_tension = _top_tension_from_node_state(dynamic_case, case, state, 45.0)
        placeholder = [
            top_tension * (1.0 - index / (len(point_tensions) - 1))
            for index in range(len(point_tensions))
        ]

        self.assertFalse(
            all(
                math.isclose(tension, expected, rel_tol=1.0e-12, abs_tol=1.0e-9)
                for tension, expected in zip(point_tensions, placeholder)
            )
        )
        self.assertAlmostEqual(point_tensions[0], top_tension)
        self.assertLess(
            max(point_tensions),
            top_tension * 2.0,
        )

    def test_dynamic_laying_dynamic_segment_tensions_prefer_constraint_state(self):
        from cable_tension.cases import get_cable
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _dynamic_segment_tensions,
            _operation_case_at_time,
        )

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p00")
        case = _operation_case_at_time(dynamic_case, get_cable("LA"), 30.0)
        state = DynamicLayingState(
            time_s=30.0,
            positions=((0.0, 0.0, 0.0), (3.0, 0.0, 4.0), (6.0, 0.0, 8.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(5.0, 5.0),
            paid_length_m=10.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
            length_lambdas_n_s2=(1.25, 0.75),
            segment_tensions_n=(125.0, 75.0),
        )

        self.assertEqual(
            _dynamic_segment_tensions(dynamic_case, case, state, 30.0),
            (125.0, 75.0),
        )

    def test_known_plough_output_tensions_use_constraint_reactions_for_distribution(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _known_plough_output_segment_tensions,
            _operation_case_at_time,
        )

        dynamic_case = get_time_history_case("plough_straight_baseline_6min")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        case = _operation_case_at_time(dynamic_case, cable, 360.0)
        state = DynamicLayingState(
            time_s=360.0,
            positions=(
                (0.0, 0.0, 0.0),
                (8.0, 0.0, 20.0),
                (20.0, 0.0, 50.0),
                (35.0, 0.0, 80.0),
                (45.0, 0.0, 80.0),
            ),
            velocities=tuple((0.0, 0.0, 0.0) for _ in range(5)),
            rest_lengths_m=(21.540659, 32.310989, 33.541020, 10.0),
            paid_length_m=97.392668,
            laid_length_m=0.0,
            contact_flags=(False, False, False, True, True),
            segment_tensions_n=(80.0, 55.0, 15.0, 0.0),
            length_constraint_reactions_n=(180.0, 150.0, 120.0, 600.0),
        )

        self.assertEqual(
            _known_plough_output_segment_tensions(dynamic_case, case, state, 360.0),
            (180.0, 150.0, 120.0, 600.0),
        )

    def test_known_plough_keeps_upstream_constraint_reactions_when_tail_segment_is_slack(self):
        from cable_tension.dynamic_laying import _segment_tensions_from_length_constraints

        tensions = _segment_tensions_from_length_constraints(
            (1.8, 1.2, 0.4, 0.0),
            dt_s=0.1,
            expected_count=4,
        )

        self.assertEqual(len(tensions), 4)
        for actual, expected in zip(tensions, (180.0, 120.0, 40.0, 0.0)):
            self.assertAlmostEqual(actual, expected)

    def test_known_plough_keeps_valid_all_slack_constraint_reaction_field(self):
        from cable_tension.dynamic_laying import _segment_tensions_from_length_constraints

        tensions = _segment_tensions_from_length_constraints(
            (0.0, 0.0, 0.0, 0.0),
            dt_s=0.1,
            expected_count=4,
        )

        self.assertEqual(tensions, (0.0, 0.0, 0.0, 0.0))

    def test_known_plough_endpoint_constraints_use_global_uniform_tension_solve(self):
        from dataclasses import replace

        from cable_tension.cases import get_cable
        from cable_tension.dynamic_laying import _solve_xpbd_endpoint_constraints
        from cable_tension.parameters import OperationCase

        cable = replace(get_cable("LA"), axial_stiffness_n=1000.0)
        case = OperationCase(
            name="global_uniform_tension",
            cable=cable,
            initial_speed_mps=0.0,
            final_speed_mps=0.0,
            duration_s=1.0,
            current_u_mps=0.0,
            current_v_mps=0.0,
            water_depth_m=100.0,
            touchdown_tension_n=0.0,
            vessel_speed_mps=0.0,
            payout_speed_mps=0.0,
        )
        positions = (
            (0.0, 0.0, 0.0),
            (1.01, 0.0, 0.0),
            (2.02, 0.0, 0.0),
            (3.03, 0.0, 0.0),
            (4.04, 0.0, 0.0),
        )

        solved, lambdas, contacts, iterations, residual_m = _solve_xpbd_endpoint_constraints(
            case,
            positions=positions,
            rest_lengths_m=(1.0, 1.0, 1.0, 1.0),
            inverse_masses=(0.0, 1.0, 1.0, 1.0, 0.0),
            seabed_depth_m=100.0,
            dt_s=0.1,
            iterations=1,
            top_position=positions[0],
            bottom_position=positions[-1],
        )

        self.assertEqual(contacts, (0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(iterations, 1)
        self.assertLess(residual_m, 1.0e-12)
        for actual, expected in zip(solved, positions):
            self.assertLess(math.dist(actual, expected), 1.0e-12)
        for lambda_value in lambdas:
            self.assertAlmostEqual(lambda_value / 0.1**2, 10.0, places=9)

    def test_known_plough_endpoint_constraints_reject_nonconverged_global_tension(self):
        from dataclasses import replace

        from cable_tension.cases import get_cable
        from cable_tension.dynamic_laying import _solve_xpbd_endpoint_constraints
        from cable_tension.parameters import OperationCase

        cable = replace(get_cable("LA"), axial_stiffness_n=1000.0)
        case = OperationCase(
            name="nonconverged_global_tension",
            cable=cable,
            initial_speed_mps=0.0,
            final_speed_mps=0.0,
            duration_s=1.0,
            current_u_mps=0.0,
            current_v_mps=0.0,
            water_depth_m=100.0,
            touchdown_tension_n=0.0,
            vessel_speed_mps=0.0,
            payout_speed_mps=0.0,
        )
        positions = (
            (0.0, 0.0, 0.0),
            (1.2, 0.0, 0.0),
            (2.0, 0.5, 0.0),
            (3.0, 0.0, 0.0),
        )

        with self.assertRaisesRegex(RuntimeError, "global axial constraints did not converge"):
            _solve_xpbd_endpoint_constraints(
                case,
                positions=positions,
                rest_lengths_m=(1.0, 1.0, 1.0),
                inverse_masses=(0.0, 1.0, 1.0, 0.0),
                seabed_depth_m=100.0,
                dt_s=0.1,
                iterations=1,
                top_position=positions[0],
                bottom_position=positions[-1],
            )

    def test_known_plough_tdp_inlet_uses_same_constraint_tension_mouth(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            DynamicLayingState,
            _known_plough_output_segment_tensions,
            _operation_case_at_time,
            _plough_inlet_tension_from_dynamic_state,
        )

        dynamic_case = get_time_history_case("plough_straight_baseline_6min")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        case = _operation_case_at_time(dynamic_case, cable, 360.0)
        state = DynamicLayingState(
            time_s=360.0,
            positions=(
                (0.0, 0.0, 0.0),
                (8.0, 0.0, 20.0),
                (20.0, 0.0, 50.0),
                (35.0, 0.0, 80.0),
                (45.0, 0.0, 80.0),
            ),
            velocities=tuple((0.0, 0.0, 0.0) for _ in range(5)),
            rest_lengths_m=(21.540659, 32.310989, 33.541020, 10.0),
            paid_length_m=97.392668,
            laid_length_m=0.0,
            contact_flags=(False, False, False, True, True),
            segment_tensions_n=(80.0, 55.0, 15.0, 0.0),
            length_constraint_reactions_n=(180.0, 150.0, 120.0, 600.0),
        )

        output_tensions = _known_plough_output_segment_tensions(dynamic_case, case, state, 360.0)
        inlet_tension = _plough_inlet_tension_from_dynamic_state(
            dynamic_case,
            case,
            state,
            360.0,
            endpoint_segment_tensions=state.length_constraint_reactions_n,
        )

        self.assertEqual(output_tensions, (180.0, 150.0, 120.0, 600.0))
        self.assertEqual(inlet_tension, 120.0)

    def test_dynamic_laying_tdp_interpolates_contact_transition(self):
        from cable_tension.dynamic_laying import DynamicLayingState, _state_tdp

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (2.0, 0.0, 8.0), (4.0, 0.0, 10.0), (6.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(8.0, math.sqrt(8.0), 2.0),
            paid_length_m=12.0,
            laid_length_m=0.0,
            contact_flags=(False, False, True, True),
        )

        tdp = _state_tdp(state, seabed_depth_m=10.0)

        self.assertEqual(tdp, (3.0, 0.0, 10.0))

    def test_dynamic_laying_removes_stable_bottom_segment_into_laid_length(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 5.0), (1.0, 0.0, 10.0), (3.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(5.0, math.sqrt(26.0), 2.0),
            paid_length_m=12.1,
            laid_length_m=0.0,
            contact_flags=(False, False, True, True),
            contact_normal_reactions_n=(0.0, 0.0, 1.0, 1.0),
            laydown_buffer_m=2.0,
        )

        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=0.1,
            payout_speed_mps=0.0,
            seabed_depth_m=10.0,
            remove_laid_segments=True,
        )

        self.assertLess(len(updated.positions), len(state.positions))
        self.assertAlmostEqual(updated.laid_length_m, 2.0)
        self.assertEqual(updated.laid_segment_lengths_m, (2.0,))

    def test_dynamic_laying_vessel_advance_drives_bottom_remesh(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        case = replace(get_case("la_accel_200m"), vessel_speed_mps=2.0)
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 8.0), (2.0, 0.0, 10.0), (5.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(8.0, math.sqrt(8.0), 3.0),
            paid_length_m=13.82842712474619,
            laid_length_m=0.0,
            contact_flags=(False, False, True, True),
        )

        updated = step_dynamic(
            case,
            state,
            dt_s=2.0,
            payout_speed_mps=0.0,
            seabed_depth_m=10.0,
            remove_laid_segments=True,
        )

        self.assertGreater(updated.laid_length_m, 0.0)
        self.assertLess(len(updated.positions), len(state.positions))
        self.assertTrue(updated.contact_flags[-1])
        self.assertAlmostEqual(updated.positions[-1][2], 10.0)
        self.assertLess(updated.laydown_buffer_m, state.rest_lengths_m[-1])

    def test_dynamic_laying_does_not_lay_tdp_segment_without_stable_tail_contact(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        case = replace(get_case("la_accel_200m"), vessel_speed_mps=1.0)
        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 8.0), (2.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(8.0, math.sqrt(8.0)),
            paid_length_m=10.82842712474619,
            laid_length_m=0.0,
            contact_flags=(False, False, True),
            laydown_buffer_m=1.0,
        )

        updated = step_dynamic(
            case,
            state,
            dt_s=0.5,
            payout_speed_mps=0.0,
            seabed_depth_m=10.0,
            remove_laid_segments=True,
        )

        self.assertAlmostEqual(updated.laid_length_m, 0.0)
        self.assertAlmostEqual(updated.rest_lengths_m[-1], state.rest_lengths_m[-1])
        self.assertAlmostEqual(updated.laydown_buffer_m, 0.0)
        self.assertAlmostEqual(updated.suspended_length_m, updated.paid_length_m - updated.laid_length_m)
        self.assertTrue(updated.contact_flags[-1])

    def test_dynamic_laying_tension_diagnostics_use_explicit_current_components(self):
        from dataclasses import replace

        from cable_tension.cases import get_cable
        from cable_tension.dynamic_laying import _step_dynamic_segment_tensions
        from cable_tension.parameters import OperationCase

        cable = get_cable("LA")
        case = OperationCase(
            name="explicit_current",
            cable=cable,
            initial_speed_mps=0.0,
            final_speed_mps=0.0,
            duration_s=1.0,
            water_depth_m=10.0,
            current_u_mps=2.0,
            current_v_mps=0.0,
            vessel_speed_mps=0.0,
            payout_speed_mps=0.0,
        )
        no_current_case = replace(case, current_u_mps=0.0)
        with_current = _step_dynamic_segment_tensions(
            case,
            positions=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(10.0,),
            payout_speed_mps=0.0,
        )
        without_current = _step_dynamic_segment_tensions(
            no_current_case,
            positions=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            rest_lengths_m=(10.0,),
            payout_speed_mps=0.0,
        )

        self.assertGreater(with_current[0], without_current[0])

    def test_dynamic_laying_initial_tension_matches_paper_straight_line_balance(self):
        from cable_tension.cases import get_cable
        from cable_tension.dynamic import get_time_history_case, _straight_line_state
        from cable_tension.dynamic_laying import (
            _initial_laying_state,
            _operation_case_at_time,
            _top_tension_from_node_state,
        )

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p50")
        paper_state = _straight_line_state(dynamic_case, dynamic_case.initial_speed_mps)
        node_state = _initial_laying_state(dynamic_case)
        operation_case = _operation_case_at_time(dynamic_case, get_cable("LA"), 0.0)

        self.assertAlmostEqual(
            _top_tension_from_node_state(dynamic_case, operation_case, node_state, 0.0),
            paper_state.top_tension_n,
            delta=1.0e-9,
        )

    def test_dynamic_laying_top_tension_uses_state_tension_field(self):
        from dataclasses import replace

        from cable_tension.cases import get_cable
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_laying_state,
            _operation_case_at_time,
            _top_tension_from_node_state,
        )

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p50")
        state = _initial_laying_state(dynamic_case)
        state = replace(
            state,
            length_lambdas_n_s2=tuple(0.1 for _ in state.rest_lengths_m),
            segment_tensions_n=tuple(1.0 for _ in state.rest_lengths_m),
        )
        operation_case = _operation_case_at_time(dynamic_case, get_cable("LA"), 0.1)

        top_tension = _top_tension_from_node_state(dynamic_case, operation_case, state, 0.1)

        self.assertAlmostEqual(top_tension, 1.0)

    def test_dynamic_laying_existing_contact_node_stays_on_seabed(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 5.0), (1.0, 0.0, 10.0)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, -2.0)),
            rest_lengths_m=(5.0, math.sqrt(26.0)),
            paid_length_m=10.1,
            laid_length_m=0.0,
            contact_flags=(False, False, True),
        )

        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=0.1,
            payout_speed_mps=0.0,
            seabed_depth_m=10.0,
            remove_laid_segments=False,
        )

        self.assertTrue(updated.contact_flags[-1])
        self.assertAlmostEqual(updated.positions[-1][2], 10.0)
        self.assertAlmostEqual(updated.velocities[-1][2], 0.0)

    def test_dynamic_laying_length_state_does_not_collapse_when_bottom_nodes_contact(self):
        from cable_tension.cases import get_cable
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_laying_state,
            _operation_case_at_time,
            _payout_speed,
            step_dynamic,
        )

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p50")
        cable = get_cable("LA")
        state = _initial_laying_state(dynamic_case)
        target_time_s = 10.0
        while state.time_s + 1.0e-9 < target_time_s:
            dt_s = min(0.1, target_time_s - state.time_s)
            state = step_dynamic(
                _operation_case_at_time(dynamic_case, cable, state.time_s),
                state,
                dt_s=dt_s,
                payout_speed_mps=_payout_speed(dynamic_case, state.time_s),
                seabed_depth_m=dynamic_case.water_depth_m,
            )

        self.assertGreater(state.suspended_length_m, dynamic_case.water_depth_m)
        self.assertLess(state.laid_length_m, state.paid_length_m - dynamic_case.water_depth_m)

    def test_dynamic_laying_suspended_length_and_tdp_follow_speed_change_boundary(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        accel_case = get_time_history_case("la_dynamic_accel_current_1p00")
        accel_high_current_case = get_time_history_case("la_dynamic_accel_current_1p50")
        decel_case = get_time_history_case("la_dynamic_decel_current_1p50")

        accel = solve_dynamic_laying_time_history(accel_case, points=13)
        accel_high_current = solve_dynamic_laying_time_history(accel_high_current_case, points=13)
        decel = solve_dynamic_laying_time_history(decel_case, points=13)

        accel_lengths = [point.suspended_length_m for point in accel.history]
        decel_lengths = [point.suspended_length_m for point in decel.history]
        accel_tdp_x = [point.tdp_x_m for point in accel.history]
        accel_high_current_tdp = accel_high_current.history

        self.assertGreater(accel_lengths[-1], accel_lengths[0] + 60.0)
        self.assertLess(decel_lengths[-1], decel_lengths[0] - 50.0)
        self.assertGreater(accel_tdp_x[-1], accel_tdp_x[0] + 40.0)
        self.assertGreater(accel_high_current_tdp[-1].tdp_x_m, 200.0)
        self.assertGreater(accel_high_current_tdp[-1].tdp_y_m, 180.0)

    def test_dynamic_laying_time_history_tension_stays_finite_and_positive(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        for case_name in (
            "la_dynamic_accel_current_1p00",
            "la_dynamic_accel_current_1p50",
            "la_dynamic_decel_current_1p00",
            "la_dynamic_decel_current_1p50",
        ):
            result = solve_dynamic_laying_time_history(
                get_time_history_case(case_name),
                points=31,
            )
            tensions = [point.top_tension_n for point in result.history]

            self.assertGreater(min(tensions), 100.0, case_name)
            self.assertLess(max(tensions), 2000.0, case_name)

    def test_dynamic_laying_time_history_uses_node_geometry_after_ramp(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        accel = solve_dynamic_laying_time_history(
            get_time_history_case("la_dynamic_accel_current_1p00"),
            points=13,
        )
        first_frame = accel.frames[0]
        final_frame = accel.frames[-1]

        self.assertGreater(len(final_frame.points), len(first_frame.points))
        self.assertNotAlmostEqual(final_frame.points[-1].x_m, first_frame.points[-1].x_m)
        self.assertNotAlmostEqual(final_frame.points[-1].y_m, first_frame.points[-1].y_m)

    def test_dynamic_laying_projection_updates_velocity_from_corrected_positions(self):
        from cable_tension.cases import get_case
        from cable_tension.dynamic_laying import DynamicLayingState, step_dynamic

        state = DynamicLayingState(
            time_s=0.0,
            positions=((0.0, 0.0, 0.0), (0.0, 0.0, 5.0), (0.0, 0.0, 10.5)),
            velocities=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.8)),
            rest_lengths_m=(5.0, 5.0),
            paid_length_m=10.0,
            laid_length_m=0.0,
            contact_flags=(False, False, False),
        )

        dt_s = 0.5
        updated = step_dynamic(
            get_case("la_accel_200m"),
            state,
            dt_s=dt_s,
            payout_speed_mps=1.2,
            seabed_depth_m=10.0,
        )

        for previous, position, velocity in zip(state.positions, updated.positions, updated.velocities):
            self.assertAlmostEqual(velocity[0], (position[0] - previous[0]) / dt_s)
            self.assertAlmostEqual(velocity[1], (position[1] - previous[1]) / dt_s)
            expected_z = (position[2] - previous[2]) / dt_s
            if position[2] >= 10.0:
                expected_z = min(expected_z, 0.0)
            self.assertAlmostEqual(velocity[2], expected_z)

    def test_legacy_dynamic_preserves_current_angle_diagnostic_entrypoint(self):
        from cable_tension.dynamic import solve_time_history as current_solve
        from cable_tension.legacy_dynamic import solve_time_history as legacy_solve

        current = current_solve("la_dynamic_accel_current_1p00", points=7)
        legacy = legacy_solve("la_dynamic_accel_current_1p00", points=7)

        self.assertEqual(legacy.evidence_level, current.evidence_level)
        self.assertEqual(len(legacy.history), len(current.history))


if __name__ == "__main__":
    unittest.main()

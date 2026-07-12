import math
import unittest


class SegmentContactProfileTests(unittest.TestCase):
    def test_exact_plane_crossing_sets_fraction_and_material_lengths(self):
        from cable_tension.contact import build_segment_contact_profile

        profile = build_segment_contact_profile(
            nodes=((0.0, 0.0, 8.0), (4.0, 0.0, 12.0)),
            rest_lengths_m=(6.0,),
            contact_flags=(False, True),
            contact_normal_reactions_n=(0.0, 25.0),
            seabed_depth_m=10.0,
        )

        self.assertEqual(profile.tdp_segment_index, 0)
        self.assertAlmostEqual(profile.tdp_segment_fraction, 0.5)
        self.assertEqual(profile.tdp_point, (2.0, 0.0, 10.0))
        self.assertEqual(profile.segment_contact_fractions, (0.5,))
        self.assertAlmostEqual(profile.tdp_arc_length_m, 3.0)
        self.assertAlmostEqual(profile.suspended_length_m, 3.0)
        self.assertAlmostEqual(profile.contact_length_m, 3.0)
        self.assertAlmostEqual(profile.normal_resultant_n, 25.0)

    def test_projected_transition_uses_first_contact_node_control_volume(self):
        from cable_tension.contact import build_segment_contact_profile

        profile = build_segment_contact_profile(
            nodes=((0.0, 0.0, 6.0), (4.0, 0.0, 10.0), (8.0, 0.0, 10.0)),
            rest_lengths_m=(6.0, 4.0),
            contact_flags=(False, True, True),
            contact_normal_reactions_n=(0.0, 12.0, 8.0),
            seabed_depth_m=10.0,
        )

        self.assertEqual(profile.tdp_segment_index, 0)
        self.assertAlmostEqual(profile.tdp_segment_fraction, 0.5)
        self.assertEqual(profile.tdp_point, (2.0, 0.0, 10.0))
        self.assertEqual(profile.segment_contact_fractions, (0.5, 1.0))
        self.assertAlmostEqual(profile.tdp_arc_length_m, 3.0)
        self.assertAlmostEqual(profile.contact_length_m, 7.0)
        self.assertAlmostEqual(profile.suspended_length_m + profile.contact_length_m, 10.0)
        self.assertAlmostEqual(profile.normal_resultant_n, 20.0)

    def test_reaction_activates_contact_when_boolean_flag_is_missing(self):
        from cable_tension.contact import build_segment_contact_profile

        profile = build_segment_contact_profile(
            nodes=((0.0, 0.0, 8.0), (2.0, 0.0, 10.0), (4.0, 0.0, 10.0)),
            rest_lengths_m=(3.0, 2.0),
            contact_flags=(False, False, False),
            contact_normal_reactions_n=(0.0, 5.0, 4.0),
            seabed_depth_m=10.0,
        )

        self.assertTrue(profile.has_contact)
        self.assertAlmostEqual(profile.contact_length_m, 3.5)

    def test_active_tail_uses_solver_contact_set_within_projection_tolerance(self):
        from cable_tension.contact import build_segment_contact_profile

        profile = build_segment_contact_profile(
            nodes=(
                (0.0, 0.0, 8.0),
                (2.0, 0.0, 9.99995),
                (4.0, 0.0, 9.99995),
                (6.0, 0.0, 10.0),
            ),
            rest_lengths_m=(3.0, 2.0, 2.0),
            contact_flags=(False, True, True, False),
            contact_normal_reactions_n=(0.0, 1.0, 1.0, 0.0),
            seabed_depth_m=10.0,
        )

        self.assertEqual(profile.segment_contact_fractions, (0.5, 1.0, 1.0))
        self.assertAlmostEqual(profile.contact_length_m, 5.5)
        self.assertAlmostEqual(profile.suspended_length_m, profile.tdp_arc_length_m)

    def test_half_cell_reconstruction_converges_under_refinement(self):
        from cable_tension.contact import build_segment_contact_profile

        coarse = self._flat_tail_profile(element_count=4, analytical_tdp_arc_m=5.0)
        fine = self._flat_tail_profile(element_count=8, analytical_tdp_arc_m=5.0)

        coarse_error = abs(coarse.tdp_arc_length_m - 5.0)
        fine_error = abs(fine.tdp_arc_length_m - 5.0)
        self.assertLess(fine_error, coarse_error)
        self.assertLessEqual(fine_error, 10.0 / 8.0 / 2.0 + 1.0e-12)

    def test_no_contact_returns_full_suspended_material_length(self):
        from cable_tension.contact import build_segment_contact_profile

        profile = build_segment_contact_profile(
            nodes=((0.0, 0.0, 0.0), (1.0, 0.0, 3.0), (2.0, 0.0, 7.0)),
            rest_lengths_m=(4.0, 5.0),
            contact_flags=(False, False, False),
            contact_normal_reactions_n=(0.0, 0.0, 0.0),
            seabed_depth_m=10.0,
        )

        self.assertFalse(profile.has_contact)
        self.assertEqual(profile.segment_contact_fractions, (0.0, 0.0))
        self.assertAlmostEqual(profile.suspended_length_m, 9.0)
        self.assertAlmostEqual(profile.contact_length_m, 0.0)
        self.assertAlmostEqual(profile.tdp_arc_length_m, 9.0)

    def test_invalid_dimensions_are_rejected(self):
        from cable_tension.contact import build_segment_contact_profile

        with self.assertRaisesRegex(ValueError, "one entry per segment"):
            build_segment_contact_profile(
                nodes=((0.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
                rest_lengths_m=(),
                contact_flags=(False, False),
                contact_normal_reactions_n=(0.0, 0.0),
                seabed_depth_m=10.0,
            )
        with self.assertRaisesRegex(ValueError, "one entry per node"):
            build_segment_contact_profile(
                nodes=((0.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
                rest_lengths_m=(1.0,),
                contact_flags=(False,),
                contact_normal_reactions_n=(0.0, 0.0),
                seabed_depth_m=10.0,
            )

    @staticmethod
    def _flat_tail_profile(*, element_count: int, analytical_tdp_arc_m: float):
        from cable_tension.contact import build_segment_contact_profile

        ds = 10.0 / element_count
        nodes = []
        flags = []
        reactions = []
        first_active_station = analytical_tdp_arc_m + 0.5 * ds
        for index in range(element_count + 1):
            station = index * ds
            active = station >= first_active_station - 1.0e-12
            nodes.append((station, 0.0, 10.0 if active else 10.0 - max(0.1, analytical_tdp_arc_m - station)))
            flags.append(active)
            reactions.append(1.0 if active else 0.0)
        return build_segment_contact_profile(
            nodes=tuple(nodes),
            rest_lengths_m=tuple(ds for _ in range(element_count)),
            contact_flags=tuple(flags),
            contact_normal_reactions_n=tuple(reactions),
            seabed_depth_m=10.0,
        )


class ContactTransitionTensionTests(unittest.TestCase):
    def test_transition_tension_interpolates_segment_center_values(self):
        from cable_tension.dynamic_laying import _segment_field_at_material_station

        value = _segment_field_at_material_station(
            values=(100.0, 60.0, 20.0),
            rest_lengths_m=(4.0, 4.0, 4.0),
            material_station_m=6.0,
        )

        self.assertAlmostEqual(value, 60.0)

    def test_transition_tension_interpolates_between_adjacent_centers(self):
        from cable_tension.dynamic_laying import _segment_field_at_material_station

        value = _segment_field_at_material_station(
            values=(100.0, 60.0, 20.0),
            rest_lengths_m=(4.0, 4.0, 4.0),
            material_station_m=4.0,
        )

        self.assertAlmostEqual(value, 80.0)


class ContactAwareInitialStateTests(unittest.TestCase):
    def test_slack_known_plough_initialises_as_catenary_plus_laid_tail(self):
        from dataclasses import replace

        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import _initial_known_plough_state, _state_contact_profile

        dynamic_case = replace(
            get_time_history_case("plough_payout_matched_6min"),
            initial_suspended_length_m=105.0,
            element_count=48,
        )
        state = _initial_known_plough_state(
            dynamic_case,
            cable_parameters_from_dynamic_case(dynamic_case),
        )
        profile = _state_contact_profile(state, dynamic_case.water_depth_m)

        self.assertAlmostEqual(sum(state.rest_lengths_m), 105.0, places=12)
        self.assertTrue(all(position[2] <= dynamic_case.water_depth_m + 1.0e-12 for position in state.positions))
        self.assertTrue(any(state.contact_flags[1:-1]))
        self.assertTrue(profile.has_contact)
        self.assertGreater(profile.contact_length_m, 0.0)
        self.assertAlmostEqual(profile.suspended_length_m + profile.contact_length_m, 105.0, places=12)
        self.assertTrue(all(tension >= 0.0 for tension in state.segment_tensions_n))

    def test_taut_known_plough_initial_state_remains_free_of_interior_contact(self):
        from dataclasses import replace

        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import _initial_known_plough_state, _state_contact_profile

        dynamic_case = replace(
            get_time_history_case("plough_payout_matched_6min"),
            initial_suspended_length_m=100.0,
            element_count=24,
        )
        state = _initial_known_plough_state(
            dynamic_case,
            cable_parameters_from_dynamic_case(dynamic_case),
        )
        profile = _state_contact_profile(state, dynamic_case.water_depth_m)

        self.assertFalse(any(state.contact_flags[1:-1]))
        self.assertFalse(profile.has_contact)


class SeabedAwareRemeshTests(unittest.TestCase):
    def test_segment_length_projection_does_not_penetrate_seabed(self):
        from cable_tension.dynamic_laying import _project_open_chain_segment_lengths_with_seabed

        projected = _project_open_chain_segment_lengths_with_seabed(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 1.1), (2.0, 0.0, 1.0)],
            [1.2, 1.2],
            seabed_depth_m=1.0,
        )

        self.assertIsNotNone(projected)
        assert projected is not None
        self.assertLessEqual(max(position[2] for position in projected), 1.0)
        for left, right in zip(projected, projected[1:]):
            self.assertAlmostEqual(math.dist(left, right), 1.2, places=9)

    def test_known_plough_cfl_excludes_consumable_tail_but_keeps_interior_limit(self):
        from dataclasses import replace

        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import _initial_known_plough_state, _time_history_step_limit_s

        dynamic_case = get_time_history_case("plough_straight_baseline_6min")
        state = _initial_known_plough_state(
            dynamic_case,
            cable_parameters_from_dynamic_case(dynamic_case),
        )
        short_tail = replace(
            state,
            rest_lengths_m=state.rest_lengths_m[:-1] + (1.0e-4,),
        )
        short_interior_lengths = list(state.rest_lengths_m)
        short_interior_lengths[-2] = 1.0e-4
        short_interior = replace(
            state,
            rest_lengths_m=tuple(short_interior_lengths),
        )

        self.assertAlmostEqual(
            _time_history_step_limit_s(dynamic_case, short_tail, base_step_s=0.05),
            0.05,
        )
        self.assertLess(
            _time_history_step_limit_s(dynamic_case, short_interior, base_step_s=0.05),
            0.05,
        )

    def test_scheduled_tail_window_can_reflect_bend_away_from_seabed(self):
        from cable_tension.dynamic_laying import _remesh_known_plough_tail_window

        positions = [
            (37.803904074787155, 0.0, 79.40465521043667),
            (34.48976564121207, 0.0, 79.96567297869116),
            (30.481927366214776, 0.0, 79.99960206276639),
            (26.473945378044228, 0.0, 79.99999932248487),
            (22.465963245259417, 0.0, 79.99999999945815),
            (18.4579809875379, 0.0, 79.99999999999952),
            (18.274999999997448, 0.0, 80.0),
        ]
        rest_lengths = [
            3.361286821447478,
            4.007980924089516,
            4.007980924089516,
            4.007980924089516,
            4.007980924089516,
            0.15,
        ]

        remeshed = _remesh_known_plough_tail_window(
            positions=positions,
            velocities=[(0.0, 0.0, 0.0) for _ in positions],
            rest_lengths_m=rest_lengths,
            contact_flags=[False, True, True, True, True, True, False],
            length_lambdas_n_s2=[0.0 for _ in rest_lengths],
            segment_tensions_n=[0.0 for _ in rest_lengths],
            length_constraint_reactions_n=[0.0 for _ in rest_lengths],
            contact_lambdas_n_s2=[0.0 for _ in positions],
            contact_normal_reactions_n=[0.0 for _ in positions],
            seabed_depth_m=80.0,
        )

        self.assertIsNotNone(remeshed)
        assert remeshed is not None
        self.assertLessEqual(max(position[2] for position in remeshed[0]), 80.0)
        first_contact_index = next(
            index
            for index, position in enumerate(remeshed[0][1:-1], start=1)
            if abs(position[2] - 80.0) <= 1.0e-9
        )
        self.assertLess(first_contact_index, len(remeshed[0]) - 1)
        for position in remeshed[0][first_contact_index:]:
            self.assertAlmostEqual(position[2], 80.0, places=9)


class DynamicLayingLongRunStabilityTests(unittest.TestCase):
    def test_known_plough_axial_solver_can_exit_before_twenty_iterations(self):
        from dataclasses import replace

        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import solve_dynamic_laying_time_history

        case = replace(
            get_time_history_case("plough_straight_baseline_6min"),
            duration_s=1.0,
            total_duration_s=1.0,
        )

        result = solve_dynamic_laying_time_history(case, points=3)

        self.assertLess(result.xpbd_iterations_per_step_min, 20)
        self.assertLessEqual(result.axial_constraint_residual_max_m, 1.0e-10)

    def test_following_current_known_plough_does_not_enter_tail_cfl_zeno_loop(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _step_known_plough_dynamic,
            _time_history_step_limit_s,
        )

        dynamic_case = get_time_history_case("plough_cross_current_0p95_0deg_6min")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_known_plough_state(dynamic_case, cable)
        current_time = 0.0
        step_count = 0
        minimum_step_s = math.inf
        maximum_speed_mps = 0.0
        while current_time < 120.0 - 1.0e-9 and step_count <= 5000:
            dt_s = min(
                _time_history_step_limit_s(dynamic_case, state, base_step_s=0.05),
                120.0 - current_time,
            )
            minimum_step_s = min(minimum_step_s, dt_s)
            state = _step_known_plough_dynamic(
                dynamic_case,
                _operation_case_at_time(
                    dynamic_case,
                    cable,
                    current_time,
                    vessel_fixed_current=False,
                ),
                state,
                time_s=current_time,
                dt_s=dt_s,
            )
            current_time += dt_s
            step_count += 1
            maximum_speed_mps = max(
                maximum_speed_mps,
                max(math.sqrt(sum(component * component for component in velocity)) for velocity in state.velocities),
            )

        self.assertAlmostEqual(current_time, 120.0, places=8)
        self.assertLessEqual(step_count, 3000)
        self.assertGreaterEqual(minimum_step_s, 0.01)
        self.assertLess(maximum_speed_mps, 10.0)

    def test_material_node_laying_path_does_not_collapse_cfl_step_after_220_seconds(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_laying_state,
            _operation_case_at_time,
            _payout_speed,
            _time_history_step_limit_s,
            _time_history_target_segment_length,
            step_dynamic,
        )

        dynamic_case = get_time_history_case("la_dynamic_accel_current_1p00")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_laying_state(dynamic_case)
        target_segment_length = _time_history_target_segment_length(state)
        minimum_step_s = math.inf
        maximum_speed_mps = 0.0

        while state.time_s < 223.0 - 1.0e-9 and maximum_speed_mps < 20.0:
            dt_s = min(
                _time_history_step_limit_s(dynamic_case, state, base_step_s=0.1),
                223.0 - state.time_s,
            )
            minimum_step_s = min(minimum_step_s, dt_s)
            state = step_dynamic(
                _operation_case_at_time(dynamic_case, cable, state.time_s),
                state,
                dt_s=dt_s,
                payout_speed_mps=_payout_speed(dynamic_case, state.time_s),
                seabed_depth_m=dynamic_case.water_depth_m,
                xpbd_iterations=8,
                target_segment_length_m=target_segment_length,
                enforce_chain_lengths=True,
            )
            maximum_speed_mps = max(
                math.sqrt(sum(component * component for component in velocity))
                for velocity in state.velocities
            )

        self.assertAlmostEqual(state.time_s, 223.0, places=8)
        self.assertGreaterEqual(minimum_step_s, 0.05)
        self.assertLess(maximum_speed_mps, 20.0)

    def test_matched_two_end_flow_preserves_topology_and_positive_endpoint_reactions(self):
        from dataclasses import replace

        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _step_known_plough_dynamic,
            _time_history_step_limit_s,
        )
        from scripts.validate_orcaflex import _build_project_prehistory_case

        for element_count in (24, 48):
            base_case = replace(
                get_time_history_case("plough_payout_matched_6min"),
                initial_suspended_length_m=110.0,
                element_count=element_count,
                current_speed_mps=0.35,
                current_direction_deg=90.0,
            )
            dynamic_case = _build_project_prehistory_case(
                base_case,
                prehistory_duration_s=60.0,
                physical_output_window_s=10.0,
            )
            cable = cable_parameters_from_dynamic_case(dynamic_case)
            state = _initial_known_plough_state(dynamic_case, cable)
            current_time = 0.0
            topology_changes = 0
            minimum_top_reaction = math.inf
            minimum_plough_reaction = math.inf
            while current_time < dynamic_case.total_duration_s - 1.0e-9:
                previous_state = state
                dt_s = min(
                    _time_history_step_limit_s(dynamic_case, state, base_step_s=0.01),
                    dynamic_case.total_duration_s - current_time,
                )
                state = _step_known_plough_dynamic(
                    dynamic_case,
                    _operation_case_at_time(
                        dynamic_case,
                        cable,
                        current_time,
                        vessel_fixed_current=False,
                    ),
                    state,
                    time_s=current_time,
                    dt_s=dt_s,
                )
                current_time += dt_s
                if current_time < 60.0:
                    continue
                topology_changes += len(state.positions) != len(previous_state.positions)
                minimum_top_reaction = min(
                    minimum_top_reaction,
                    state.length_constraint_reactions_n[0],
                )
                minimum_plough_reaction = min(
                    minimum_plough_reaction,
                    state.length_constraint_reactions_n[-1],
                )

            self.assertEqual(topology_changes, 0, element_count)
            self.assertGreater(minimum_top_reaction, 0.0, element_count)
            self.assertGreater(minimum_plough_reaction, 0.0, element_count)

    def test_fast_payout_post_startup_insertions_keep_endpoint_reactions_physical(self):
        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _step_known_plough_dynamic,
            _time_history_step_limit_s,
        )

        dynamic_case = get_time_history_case("plough_payout_fast_1p25_6min")
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_known_plough_state(dynamic_case, cable)
        current_time = 0.0
        insertion_events = 0
        minimum_top_reaction = math.inf
        minimum_plough_reaction = math.inf
        zero_plough_reaction_segments = []
        while current_time < 40.0 - 1.0e-9:
            previous_state = state
            dt_s = min(
                _time_history_step_limit_s(dynamic_case, state, base_step_s=0.05),
                40.0 - current_time,
            )
            state = _step_known_plough_dynamic(
                dynamic_case,
                _operation_case_at_time(
                    dynamic_case,
                    cable,
                    current_time,
                    vessel_fixed_current=False,
                ),
                state,
                time_s=current_time,
                dt_s=dt_s,
            )
            current_time += dt_s
            if current_time < 5.0:
                continue
            minimum_top_reaction = min(
                minimum_top_reaction,
                state.length_constraint_reactions_n[0],
            )
            minimum_plough_reaction = min(
                minimum_plough_reaction,
                state.length_constraint_reactions_n[-1],
            )
            if state.length_constraint_reactions_n[-1] == 0.0:
                zero_plough_reaction_segments.append(
                    (
                        math.dist(state.positions[-2], state.positions[-1]),
                        state.rest_lengths_m[-1],
                    )
                )
            if len(state.positions) > len(previous_state.positions):
                insertion_events += 1
                self.assertGreater(state.length_constraint_reactions_n[0], 0.0)
            self.assertGreaterEqual(len(state.positions), len(previous_state.positions))

        self.assertGreater(insertion_events, 0)
        self.assertGreater(minimum_top_reaction, 0.0)
        self.assertGreaterEqual(minimum_plough_reaction, 0.0)
        self.assertGreater(len(zero_plough_reaction_segments), 0)
        for segment_length, rest_length in zero_plough_reaction_segments:
            self.assertLessEqual(segment_length, rest_length + 1.0e-9)

    def test_net_tail_withdrawal_events_keep_endpoint_reactions_continuous(self):
        from dataclasses import replace

        from cable_tension.dynamic import cable_parameters_from_dynamic_case, get_time_history_case
        from cable_tension.dynamic_laying import (
            _initial_known_plough_state,
            _operation_case_at_time,
            _step_known_plough_dynamic,
            _time_history_step_limit_s,
        )

        dynamic_case = replace(
            get_time_history_case("plough_straight_baseline_6min"),
            plough_initial_z_m=70.0,
            initial_suspended_length_m=1.1 * math.dist((0.0, 0.0, 0.0), (-55.0, 0.0, 70.0)),
            payout_initial_speed_mps=0.6,
            payout_final_speed_mps=0.6,
        )
        cable = cable_parameters_from_dynamic_case(dynamic_case)
        state = _initial_known_plough_state(dynamic_case, cable)
        current_time = 0.0
        withdrawal_events = 0
        while current_time < 30.0 - 1.0e-9:
            previous_state = state
            dt_s = min(
                _time_history_step_limit_s(dynamic_case, state, base_step_s=0.05),
                30.0 - current_time,
            )
            state = _step_known_plough_dynamic(
                dynamic_case,
                _operation_case_at_time(
                    dynamic_case,
                    cable,
                    current_time,
                    vessel_fixed_current=False,
                ),
                state,
                time_s=current_time,
                dt_s=dt_s,
            )
            current_time += dt_s
            self.assertLessEqual(len(state.positions), len(previous_state.positions))
            if len(state.positions) == len(previous_state.positions):
                continue
            withdrawal_events += 1
            self.assertGreater(
                state.length_constraint_reactions_n[0],
                0.25 * previous_state.length_constraint_reactions_n[0],
            )
            self.assertGreaterEqual(state.length_constraint_reactions_n[-1], 0.0)

        self.assertGreater(withdrawal_events, 0)


if __name__ == "__main__":
    unittest.main()

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


class KnownPloughRuntimeTests(unittest.TestCase):
    def test_runtime_diagnostics_remain_constant_size(self):
        from cable_tension.dynamic import get_time_history_case
        from cable_tension.dynamic_laying import advance_known_plough_runtime, initialize_known_plough_runtime

        case = replace(get_time_history_case("plough_payout_matched_6min"), element_count=24)
        runtime = initialize_known_plough_runtime(case)
        advance_known_plough_runtime(runtime, case, target_time_s=5.0)

        self.assertFalse(hasattr(runtime, "used_dts"))
        self.assertFalse(hasattr(runtime, "axial_iteration_counts"))
        self.assertFalse(hasattr(runtime, "axial_constraint_residuals"))
        self.assertGreaterEqual(runtime.steps, 100)
        self.assertGreater(runtime.integration_time_step_min_s, 0.0)
        self.assertGreaterEqual(runtime.integration_time_step_max_s, runtime.integration_time_step_min_s)
        self.assertGreaterEqual(runtime.axial_constraint_residual_max_m, 0.0)

    def test_two_incremental_steps_match_two_second_batch_result(self):
        from cable_tension.dynamic import MotionSample, SpeedSegment, get_time_history_case
        from cable_tension.dynamic_laying import (
            advance_known_plough_runtime,
            initialize_known_plough_runtime,
            sample_known_plough_runtime,
            solve_dynamic_laying_time_history,
        )

        base = get_time_history_case("plough_payout_matched_6min")
        times = (0.0, 1.0, 2.0)
        case = replace(
            base,
            total_duration_s=2.0,
            duration_s=2.0,
            element_count=24,
            plough_exit_speed_mps=0.8,
            vessel_motion_samples=tuple(
                MotionSample(t, 0.8 * t, 0.0, 0.0, 0.8, 0.0, 0.0) for t in times
            ),
            plough_motion_samples=tuple(
                MotionSample(t, -55.0 + 0.8 * t, 0.0, 80.0, 0.8, 0.0, 0.0)
                for t in times
            ),
            payout_speed_segments=(SpeedSegment(2.0, 0.8, 0.8),),
        )

        batch = solve_dynamic_laying_time_history(case, points=3)
        runtime = initialize_known_plough_runtime(case)
        advance_known_plough_runtime(runtime, case, target_time_s=1.0)
        first = sample_known_plough_runtime(runtime, case)
        advance_known_plough_runtime(runtime, case, target_time_s=2.0)
        second = sample_known_plough_runtime(runtime, case)

        self.assertAlmostEqual(first.point.time_s, 1.0)
        self.assertAlmostEqual(second.point.time_s, 2.0)
        self.assertEqual(len(second.frame.points), len(batch.frames[-1].points))
        for actual, expected in zip(second.frame.points, batch.frames[-1].points):
            self.assertAlmostEqual(actual.x_m, expected.x_m, delta=1.0e-9)
            self.assertAlmostEqual(actual.y_m, expected.y_m, delta=1.0e-9)
            self.assertAlmostEqual(actual.z_m, expected.z_m, delta=1.0e-9)
            self.assertAlmostEqual(actual.tension_n, expected.tension_n, delta=1.0e-6)
        self.assertTrue(math.isfinite(second.point.top_tension_n))


class RealtimeSimulationSessionTests(unittest.TestCase):
    def _case(self):
        from cable_tension.dynamic import get_time_history_case

        return replace(
            get_time_history_case("plough_payout_matched_6min"),
            element_count=24,
            plough_exit_speed_mps=0.8,
        )

    def _packet(self, sequence: int, time_s: float, **overrides):
        from cable_tension.realtime import RealtimeSensorPacket, SynchronizedEndpointSample

        values = {
            "sequence": sequence,
            "time_s": time_s,
            "observed_at_unix_s": 1_000.0 + time_s,
            "quality": "valid",
            "vessel": SynchronizedEndpointSample(0.8 * time_s, 0.0, 0.0, 0.8, 0.0, 0.0),
            "plough": SynchronizedEndpointSample(-55.0 + 0.8 * time_s, 0.0, 80.0, 0.8, 0.0, 0.0),
            "payout_speed_mps": 0.8,
            "plough_exit_speed_mps": 0.8,
            "current_velocity_x_mps": 0.0,
            "current_velocity_y_mps": 0.35,
        }
        values.update(overrides)
        return RealtimeSensorPacket(**values)

    def _session(self):
        from cable_tension.realtime import RealtimeSimulationSession

        return RealtimeSimulationSession(
            session_id="test-session",
            base_case=self._case(),
            initial_packet=self._packet(0, 0.0),
            max_sensor_gap_s=1.1,
            max_data_age_s=1.0,
            clock=lambda: 1_001.0,
        )

    def test_session_advances_one_state_and_returns_latest_frame(self):
        session = self._session()

        result = session.advance(self._packet(1, 1.0))

        self.assertEqual(result.session_id, "test-session")
        self.assertEqual(result.sequence, 1)
        self.assertAlmostEqual(result.time_s, 1.0)
        self.assertGreater(result.compute_wall_s, 0.0)
        self.assertEqual(result.input_status, "valid")
        self.assertEqual(len(result.frame.points), 25)
        self.assertTrue(math.isfinite(result.point.top_tension_n))
        self.assertEqual(session.current_sequence, 1)
        self.assertAlmostEqual(session.current_time_s, 1.0)

    def test_rejected_packet_does_not_mutate_session_state(self):
        from cable_tension.realtime import RealtimeSessionError

        session = self._session()
        baseline = session.latest
        invalid_packets = (
            self._packet(2, 1.0),
            self._packet(1, 0.0),
            self._packet(1, 2.0),
            self._packet(1, 1.0, quality="invalid"),
            self._packet(1, 1.0, observed_at_unix_s=900.0),
        )
        expected_codes = (
            "sequence_conflict",
            "non_monotonic_time",
            "sensor_gap",
            "invalid_quality",
            "stale_sample",
        )

        for packet, expected_code in zip(invalid_packets, expected_codes):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(RealtimeSessionError) as raised:
                    session.advance(packet)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertIs(session.latest, baseline)
                self.assertEqual(session.current_sequence, 0)
                self.assertAlmostEqual(session.current_time_s, 0.0)

    def test_time_varying_sensor_channels_change_next_frame(self):
        baseline = self._session().advance(self._packet(1, 1.0))
        current_changed = self._session().advance(
            self._packet(
                1,
                1.0,
                current_velocity_x_mps=0.5,
                current_velocity_y_mps=0.0,
            )
        )
        payout_changed = self._session().advance(self._packet(1, 1.0, payout_speed_mps=1.2))
        exit_changed = self._session().advance(self._packet(1, 1.0, plough_exit_speed_mps=0.6))

        self.assertNotAlmostEqual(
            payout_changed.point.material_suspended_length_m,
            baseline.point.material_suspended_length_m,
        )
        self.assertNotAlmostEqual(
            exit_changed.point.material_suspended_length_m,
            baseline.point.material_suspended_length_m,
        )
        self.assertNotAlmostEqual(current_changed.point.top_tension_n, baseline.point.top_tension_n)


if __name__ == "__main__":
    unittest.main()

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class LumpedMassDynamicTests(unittest.TestCase):
    def test_lumped_mass_solver_outputs_dynamic_frames_without_table_targets(self):
        from cable_tension.dynamic import DynamicCaseInput
        from cable_tension.lumped_mass_dynamic import solve_lumped_mass_time_history

        result = solve_lumped_mass_time_history(
            DynamicCaseInput(
                case_name="lumped_demo",
                current_speed_mps=1.2,
                speed_change="accel",
                initial_speed_mps=0.4,
                final_speed_mps=1.1,
                duration_s=20.0,
                water_depth_m=80.0,
                element_count=12,
                total_duration_s=60.0,
                current_direction_deg=75.0,
                touchdown_tension_n=80.0,
            ),
            points=13,
        )

        self.assertEqual(result.evidence_level, "experimental lumped-mass dynamic line; no paper target fitting")
        self.assertEqual(len(result.history), 13)
        self.assertEqual(len(result.frames), 13)
        self.assertEqual(result.history[0].time_s, 0.0)
        self.assertIn(20.0, [point.time_s for point in result.history])
        self.assertEqual(result.history[-1].time_s, 60.0)
        self.assertGreater(min(point.top_tension_n for point in result.history), 0.0)
        self.assertGreater(result.history[-1].suspended_length_m, result.water_depth_m)

        first_frame = result.frames[0]
        last_frame = result.frames[-1]
        self.assertEqual(len(first_frame.points), result.element_count + 1)
        self.assertAlmostEqual(first_frame.points[0].z_m, 0.0)
        self.assertAlmostEqual(first_frame.points[-1].z_m, result.water_depth_m)
        self.assertGreater(
            abs(last_frame.points[-1].x_m - first_frame.points[-1].x_m)
            + abs(last_frame.points[-1].y_m - first_frame.points[-1].y_m),
            1.0e-4,
        )

    def test_lumped_mass_solver_reacts_to_current_direction(self):
        from dataclasses import replace

        from cable_tension.dynamic import DynamicCaseInput
        from cable_tension.lumped_mass_dynamic import solve_lumped_mass_time_history

        base = DynamicCaseInput(
            case_name="direction_a",
            current_speed_mps=1.0,
            speed_change="accel",
            initial_speed_mps=0.5,
            final_speed_mps=1.0,
            duration_s=20.0,
            water_depth_m=80.0,
            element_count=10,
            total_duration_s=50.0,
            current_direction_deg=90.0,
            touchdown_tension_n=50.0,
        )
        transverse = solve_lumped_mass_time_history(base, points=11)
        inline = solve_lumped_mass_time_history(
            replace(base, case_name="direction_b", current_direction_deg=0.0),
            points=11,
        )

        self.assertNotAlmostEqual(transverse.history[-1].tdp_x_m, inline.history[-1].tdp_x_m)
        self.assertNotAlmostEqual(transverse.history[-1].tdp_y_m, inline.history[-1].tdp_y_m)

    def test_lumped_mass_solver_source_has_no_paper_target_path(self):
        import cable_tension.lumped_mass_dynamic as lumped

        source = Path(lumped.__file__).read_text(encoding="utf-8")
        for forbidden in ("TABLE_4_1", "reference target", "fitting coefficient"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

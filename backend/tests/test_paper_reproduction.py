import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class PaperReproductionTests(unittest.TestCase):
    def test_table_4_2_power_cable_parameters_are_available(self):
        from cable_tension.cases import get_cable

        cable = get_cable("POWER_500KV")

        self.assertAlmostEqual(cable.diameter_m, 0.139)
        self.assertAlmostEqual(cable.weight_air_n_per_m, 48.0 * 9.8)
        self.assertAlmostEqual(cable.submerged_weight_n_per_m, 32.0 * 9.8)
        self.assertAlmostEqual(cable.normal_drag_coefficient, 1.0)
        self.assertAlmostEqual(cable.tangential_drag_coefficient, 0.0)
        self.assertAlmostEqual(cable.max_water_depth_m, 100.0)
        self.assertAlmostEqual(cable.max_allowable_tension_n, 87_500.0)
        self.assertAlmostEqual(cable.min_bending_radius_m, 5.0)

    def test_table_4_3_current_speed_case_returns_algorithmic_values(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        result = solve_case(get_case("power_current_speed_1p50"), points=81)
        tdp = result.profile[-1]

        self.assertGreater(result.top_tension_final_n, 30_000.0)
        self.assertLess(result.top_tension_final_n, 40_000.0)
        self.assertGreater(tdp.x_m, 0.0)
        self.assertGreater(tdp.y_m, 0.0)
        self.assertAlmostEqual(tdp.z_m, 100.0, places=6)

    def test_table_4_4_current_direction_case_returns_algorithmic_values(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        result = solve_case(get_case("power_current_direction_0"), points=81)
        tdp = result.profile[-1]

        self.assertGreater(result.top_tension_final_n, 30_000.0)
        self.assertLess(result.top_tension_final_n, 40_000.0)
        self.assertGreater(tdp.x_m, 30.0)
        self.assertGreater(tdp.y_m, 15.0)

    def test_table_4_5_pretension_case_returns_algorithmic_values(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        result = solve_case(get_case("power_pretension_4000"), points=81)
        tdp = result.profile[-1]

        self.assertGreater(result.top_tension_final_n, 34_000.0)
        self.assertLess(result.top_tension_final_n, 37_000.0)
        self.assertGreater(tdp.x_m, 8.0)
        self.assertGreater(tdp.y_m, 45.0)

    def test_reproduce_paper_writes_expected_tables_and_inputs(self):
        from cable_tension.paper import reproduce_paper

        with tempfile.TemporaryDirectory() as tmp:
            result = reproduce_paper(Path(tmp), points=41)

            self.assertTrue((Path(tmp) / "inputs" / "cases.csv").exists())
            self.assertTrue((Path(tmp) / "tables" / "table_4_3_current_speed.csv").exists())
            self.assertTrue((Path(tmp) / "tables" / "table_4_4_current_direction.csv").exists())
            self.assertTrue((Path(tmp) / "tables" / "table_4_5_pretension.csv").exists())
            self.assertTrue((Path(tmp) / "figures" / "fig_4_11_current_speed.svg").exists())
            self.assertTrue((Path(tmp) / "INPUT_OUTPUT.md").exists())

            profile_svg = (Path(tmp) / "figures" / "fig_4_11_current_speed.svg").read_text(
                encoding="utf-8",
            )
            time_svg = (Path(tmp) / "figures" / "fig_4_1_la_acceleration.svg").read_text(
                encoding="utf-8",
            )
            self.assertIn("X distance (m)", profile_svg)
            self.assertIn("Depth z (m)", profile_svg)
            self.assertIn("axis-tick", profile_svg)
            self.assertIn("Time t (s)", time_svg)
            self.assertIn("Top tension T (N)", time_svg)
            self.assertIn("axis-tick", time_svg)

            with (Path(tmp) / "tables" / "table_4_3_current_speed.csv").open(
                newline="",
                encoding="utf-8",
            ) as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    reader.fieldnames,
                    [
                        "case_name",
                        "current_surface_mps",
                        "top_tension_n",
                        "tdp_x_m",
                        "tdp_y_m",
                    ],
                )
                self.assertFalse(
                    any(
                        "paper" in field or "reference" in field or "error" in field
                        for field in reader.fieldnames or []
                    )
                )
                rows = list(reader)
            self.assertEqual(len(rows), 4)
            with (Path(tmp) / "inputs" / "time_history_cases.csv").open(
                newline="",
                encoding="utf-8",
            ) as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    reader.fieldnames,
                    [
                        "case_name",
                        "cable",
                        "current_speed_mps",
                        "current_direction_deg",
                        "speed_change",
                        "initial_speed_mps",
                        "final_speed_mps",
                        "payout_initial_speed_mps",
                        "payout_final_speed_mps",
                        "length_boundary_source",
                        "duration_s",
                        "water_depth_m",
                        "touchdown_tension_n",
                        "total_duration_s",
                        "element_count",
                    ],
                )
                self.assertFalse(
                    any(
                        field
                        in {
                            "initial_tension_n",
                            "extreme_tension_n",
                            "steady_tension_n",
                        }
                        for field in reader.fieldnames or []
                    )
                )
            with (Path(tmp) / "tables" / "table_4_1_dynamic_la.csv").open(
                newline="",
                encoding="utf-8",
            ) as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    reader.fieldnames,
                    [
                        "case_name",
                        "speed_change",
                        "current_speed_mps",
                        "initial_tension_n",
                        "extreme_tension_n",
                        "steady_tension_n",
                    ],
                )
            self.assertEqual(result.case_count, 20)


if __name__ == "__main__":
    unittest.main()

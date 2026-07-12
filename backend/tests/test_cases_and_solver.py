import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CaseAndSolverTests(unittest.TestCase):
    def test_table_3_1_cable_parameters_are_available(self):
        from cable_tension.cases import get_cable

        la = get_cable("LA")
        ha = get_cable("HA")

        self.assertAlmostEqual(la.diameter_m, 0.0264)
        self.assertAlmostEqual(la.weight_air_n_per_m, 16.09)
        self.assertAlmostEqual(la.submerged_weight_n_per_m, 10.59)
        self.assertAlmostEqual(la.hydrodynamic_constant, 0.6173)
        self.assertAlmostEqual(la.tangential_drag_coefficient, 0.01)
        self.assertAlmostEqual(la.normal_drag_coefficient, 2.12)
        self.assertAlmostEqual(la.total_length_m, 350.0)

        self.assertAlmostEqual(ha.diameter_m, 0.0332)
        self.assertAlmostEqual(ha.weight_air_n_per_m, 26.50)
        self.assertAlmostEqual(ha.submerged_weight_n_per_m, 17.80)
        self.assertAlmostEqual(ha.hydrodynamic_constant, 0.7974)
        self.assertAlmostEqual(ha.tangential_drag_coefficient, 0.01)
        self.assertAlmostEqual(ha.normal_drag_coefficient, 1.64)
        self.assertAlmostEqual(ha.total_length_m, 300.0)

    def test_table_3_4_operation_cases_are_available(self):
        from cable_tension.cases import get_case

        case = get_case("la_accel_200m")

        self.assertEqual(case.name, "la_accel_200m")
        self.assertEqual(case.cable.name, "LA")
        self.assertAlmostEqual(case.initial_speed_mps, 0.5)
        self.assertAlmostEqual(case.final_speed_mps, 1.5)
        self.assertAlmostEqual(case.duration_s, 30.0)
        self.assertAlmostEqual(case.water_depth_m, 200.0)

    def test_solver_uses_vertical_equilibrium_for_la_static_case(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        case = get_case("la_accel_200m")
        result = solve_case(case, points=101)
        expected = case.cable.submerged_weight_n_per_m * case.water_depth_m

        self.assertEqual(len(result.profile), 101)
        self.assertAlmostEqual(result.top_tension_final_n, expected, places=6)
        self.assertAlmostEqual(result.top_tension_final_n, result.profile[0].tension_n)
        self.assertGreater(result.profile[0].tension_n, result.profile[-1].tension_n)
        self.assertAlmostEqual(result.profile[-1].z_m, 200.0, places=6)

    def test_solver_uses_vertical_equilibrium_for_ha_static_case(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        case = get_case("ha_accel_200m")
        result = solve_case(case, points=101)
        expected = case.cable.submerged_weight_n_per_m * case.water_depth_m

        self.assertAlmostEqual(result.top_tension_final_n, expected, places=6)
        self.assertAlmostEqual(result.profile[-1].z_m, 200.0, places=6)
        self.assertGreater(result.profile[0].tension_n, result.profile[-1].tension_n)


if __name__ == "__main__":
    unittest.main()

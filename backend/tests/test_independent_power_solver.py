import sys
import unittest
from dataclasses import replace
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(ROOT / "src"))

from reference_tables import CHAPTER_4_STATIC


def _percent_error(computed, reference):
    return abs(computed - reference) / max(abs(reference), 1.0e-12) * 100.0


class IndependentPowerSolverTests(unittest.TestCase):
    def test_solver_module_does_not_store_chapter_4_output_targets(self):
        import cable_tension.solver as solver

        self.assertFalse(hasattr(solver, "_CURRENT_SPEED_TARGETS"))
        self.assertFalse(hasattr(solver, "_CURRENT_DIRECTION_TARGETS"))
        self.assertFalse(hasattr(solver, "_PRETENSION_TARGETS"))
        source = Path(solver.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "_power" + "_top_tension",
            "_power" + "_tdp_coordinates",
            "current_alignment",
            "0.00638",
            "u**1.65",
            "1.08",
        ):
            self.assertNotIn(forbidden, source)

    def test_chapter_4_reference_comparison_lives_in_tests(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        max_top_tension_percent_error = 0.0
        for case_name, paper in CHAPTER_4_STATIC.items():
            case = get_case(case_name)
            result = solve_case(case, points=81)
            tdp = result.profile[-1]
            max_top_tension_percent_error = max(
                max_top_tension_percent_error,
                _percent_error(result.top_tension_final_n, paper["top_tension_n"]),
            )
            self.assertTrue(math.isfinite(tdp.x_m))
            self.assertTrue(math.isfinite(tdp.y_m))
            self.assertAlmostEqual(tdp.z_m, case.water_depth_m, places=6)

        self.assertLess(max_top_tension_percent_error, 1.0)

    def test_power_solver_rejects_cable_too_short_to_reach_surface(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        case = get_case("power_current_speed_1p50")
        short_cable = replace(
            case,
            cable=replace(
                case.cable,
                total_length_m=50.0,
            )
        )

        with self.assertRaises(ValueError):
            solve_case(short_cable, points=81)

    def test_power_solver_depends_on_physical_inputs_not_case_name(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        base_case = get_case("power_current_speed_1p50")
        baseline = solve_case(base_case, points=81)
        baseline_tdp = baseline.profile[-1]

        for synthetic_name in (
            "power_current_direction_90",
            "power_pretension_1500",
            "power_custom_same_inputs",
        ):
            renamed = solve_case(replace(base_case, name=synthetic_name), points=81)
            renamed_tdp = renamed.profile[-1]

            self.assertAlmostEqual(
                renamed.top_tension_final_n,
                baseline.top_tension_final_n,
                places=9,
            )
            self.assertAlmostEqual(renamed_tdp.x_m, baseline_tdp.x_m, places=9)
            self.assertAlmostEqual(renamed_tdp.y_m, baseline_tdp.y_m, places=9)

    def test_power_solver_preserves_signed_3d_current_direction(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        base_case = replace(get_case("power_current_direction_90"), current_direction_deg=0.0, vessel_speed_mps=0.0)
        positive = solve_case(base_case, points=81)
        negative = solve_case(
            replace(base_case, name="power_current_direction_180", current_direction_deg=180.0),
            points=81,
        )
        positive_tdp = positive.profile[-1]
        negative_tdp = negative.profile[-1]
        positive_top = positive.profile[0]
        negative_top = negative.profile[0]

        self.assertGreater(positive_tdp.x_m, 0.0)
        self.assertLess(negative_tdp.x_m, 0.0)
        self.assertAlmostEqual(abs(positive_tdp.x_m), abs(negative_tdp.x_m), places=6)
        self.assertAlmostEqual(positive_tdp.y_m, negative_tdp.y_m, places=6)
        self.assertGreater(positive_top.drag_x_n_per_m, 0.0)
        self.assertLess(negative_top.drag_x_n_per_m, 0.0)
        self.assertNotAlmostEqual(positive_top.psi_rad, negative_top.psi_rad)

    def test_power_profile_exposes_3d_audit_terms(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        result = solve_case(get_case("power_current_speed_1p50"), points=81)
        top = result.profile[0]

        self.assertGreater(abs(top.tangent_x) + abs(top.tangent_y) + abs(top.tangent_z), 0.0)
        self.assertGreater(abs(top.current_x_mps) + abs(top.current_y_mps), 0.0)
        self.assertGreater(abs(top.drag_x_n_per_m) + abs(top.drag_y_n_per_m), 0.0)
        self.assertGreaterEqual(top.psi_rad, -3.2)
        self.assertLessEqual(top.psi_rad, 3.2)

    def test_steady_power_case_reports_top_tension_min_as_top_tension(self):
        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        result = solve_case(get_case("power_current_speed_1p50"), points=81)

        self.assertAlmostEqual(result.top_tension_min_n, result.top_tension_final_n)

    def test_power_top_tension_does_not_treat_normal_drag_as_axial_tension(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        base_case = get_case("power_current_speed_1p50")
        still_water = solve_case(
            replace(base_case, current_surface_mps=0.0, current_bottom_mps=0.0),
            points=81,
        )
        transverse_current = solve_case(base_case, points=81)

        self.assertAlmostEqual(
            transverse_current.top_tension_final_n,
            still_water.top_tension_final_n,
            places=6,
        )

    def test_power_vessel_speed_contributes_to_relative_current_shape(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        base_case = get_case("power_current_direction_90")
        without_vessel_speed = solve_case(replace(base_case, vessel_speed_mps=0.0), points=81)
        with_vessel_speed = solve_case(base_case, points=81)

        self.assertGreater(
            with_vessel_speed.profile[-1].x_m,
            without_vessel_speed.profile[-1].x_m,
        )

    def test_explicit_current_components_include_vessel_speed(self):
        from dataclasses import replace

        import cable_tension.solver as solver
        from cable_tension.cases import get_case

        case = replace(
            get_case("power_current_speed_1p50"),
            current_surface_mps=None,
            current_bottom_mps=None,
            current_direction_deg=None,
            current_u_mps=0.2,
            current_v_mps=0.3,
            vessel_speed_mps=0.5,
        )

        current = solver._current_vector_at_depth(case, 20.0)

        self.assertAlmostEqual(current[0], 0.7)
        self.assertAlmostEqual(current[1], 0.3)
        self.assertAlmostEqual(current[2], 0.0)

    def test_power_profile_geometry_responds_to_axial_stiffness(self):
        from dataclasses import replace

        from cable_tension.cases import get_case
        from cable_tension.solver import solve_case

        base_case = get_case("power_current_speed_1p50")
        stiff = replace(base_case, cable=replace(base_case.cable, axial_stiffness_n=1.0e12))
        soft = replace(base_case, cable=replace(base_case.cable, axial_stiffness_n=5.0e4))

        stiff_result = solve_case(stiff, points=81)
        soft_result = solve_case(soft, points=81)

        self.assertGreater(abs(soft_result.profile[-1].y_m - stiff_result.profile[-1].y_m), 1.0e-4)


if __name__ == "__main__":
    unittest.main()

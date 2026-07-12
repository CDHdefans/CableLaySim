import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class GlobalAxialConstraintTests(unittest.TestCase):
    def test_uniform_straight_chain_recovers_ea_strain_tension(self):
        from cable_tension.axial_constraints import solve_global_axial_constraint_step

        step = solve_global_axial_constraint_step(
            positions=((0.0, 0.0, 0.0), (1.01, 0.0, 0.0), (2.02, 0.0, 0.0), (3.03, 0.0, 0.0), (4.04, 0.0, 0.0)),
            rest_lengths_m=(1.0, 1.0, 1.0, 1.0),
            inverse_masses_per_kg=(0.0, 1.0, 1.0, 1.0, 0.0),
            axial_stiffness_n=1000.0,
            dt_s=0.1,
        )

        tensions = tuple(value / 0.1**2 for value in step.lambdas_n_s2)
        for tension in tensions:
            self.assertAlmostEqual(tension, 10.0, places=9)
        expected_positions = (
            (0.0, 0.0, 0.0),
            (1.01, 0.0, 0.0),
            (2.02, 0.0, 0.0),
            (3.03, 0.0, 0.0),
            (4.04, 0.0, 0.0),
        )
        for actual, expected in zip(step.positions, expected_positions):
            self.assertLess(math.dist(actual, expected), 1.0e-12)
        self.assertLess(step.max_residual_m, 1.0e-12)

    def test_uniform_tension_is_grid_independent(self):
        from cable_tension.axial_constraints import solve_global_axial_constraint_step

        def tensions(element_count: int) -> tuple[float, ...]:
            stretched_length = 4.04 / element_count
            rest_length = 4.0 / element_count
            step = solve_global_axial_constraint_step(
                positions=tuple((stretched_length * index, 0.0, 0.0) for index in range(element_count + 1)),
                rest_lengths_m=tuple(rest_length for _ in range(element_count)),
                inverse_masses_per_kg=(0.0, *(1.0 for _ in range(element_count - 1)), 0.0),
                axial_stiffness_n=1000.0,
                dt_s=0.1,
            )
            return tuple(value / 0.1**2 for value in step.lambdas_n_s2)

        coarse = tensions(4)
        fine = tensions(8)

        for tension in (*coarse, *fine):
            self.assertAlmostEqual(tension, 10.0, places=8)

    def test_slack_segments_keep_zero_reaction(self):
        from cable_tension.axial_constraints import solve_global_axial_constraint_step

        positions = ((0.0, 0.0, 0.0), (0.9, 0.0, 0.0), (1.8, 0.0, 0.0))
        step = solve_global_axial_constraint_step(
            positions=positions,
            rest_lengths_m=(1.0, 1.0),
            inverse_masses_per_kg=(0.0, 1.0, 0.0),
            axial_stiffness_n=1000.0,
            dt_s=0.1,
        )

        self.assertEqual(step.positions, positions)
        self.assertEqual(step.lambdas_n_s2, (0.0, 0.0))

    def test_adjacent_segment_reactivates_after_global_correction(self):
        from cable_tension.axial_constraints import solve_global_axial_constraint_step

        first = solve_global_axial_constraint_step(
            positions=((0.0, 0.0, 0.0), (1.2, 0.0, 0.0), (2.05, 0.0, 0.0)),
            rest_lengths_m=(1.0, 1.0),
            inverse_masses_per_kg=(0.0, 1.0, 0.0),
            axial_stiffness_n=1000.0,
            dt_s=0.1,
        )
        second = solve_global_axial_constraint_step(
            positions=first.positions,
            rest_lengths_m=(1.0, 1.0),
            inverse_masses_per_kg=(0.0, 1.0, 0.0),
            axial_stiffness_n=1000.0,
            dt_s=0.1,
            lambdas_n_s2=first.lambdas_n_s2,
        )

        self.assertEqual(first.lambdas_n_s2[1], 0.0)
        self.assertGreater(second.lambdas_n_s2[1], 0.0)
        self.assertLess(second.max_residual_m, 1.0e-12)

    def test_tension_is_invariant_to_time_step_scaling(self):
        from cable_tension.axial_constraints import solve_global_axial_constraint_step

        tensions = []
        for dt_s in (0.05, 0.1):
            step = solve_global_axial_constraint_step(
                positions=((0.0, 0.0, 0.0), (1.01, 0.0, 0.0), (2.02, 0.0, 0.0)),
                rest_lengths_m=(1.0, 1.0),
                inverse_masses_per_kg=(0.0, 1.0, 0.0),
                axial_stiffness_n=1000.0,
                dt_s=dt_s,
            )
            tensions.append(tuple(value / dt_s**2 for value in step.lambdas_n_s2))

        for tension in (*tensions[0], *tensions[1]):
            self.assertAlmostEqual(tension, 10.0, places=8)

    def test_residual_rejects_nonfinite_state(self):
        from cable_tension.axial_constraints import axial_constraint_residual_m

        with self.assertRaisesRegex(ValueError, "finite"):
            axial_constraint_residual_m(
                positions=((0.0, 0.0, 0.0), (math.nan, 0.0, 0.0)),
                rest_lengths_m=(1.0,),
                lambdas_n_s2=(0.0,),
                axial_stiffness_n=1000.0,
                dt_s=0.1,
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            axial_constraint_residual_m(
                positions=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                rest_lengths_m=(1.0,),
                lambdas_n_s2=(math.nan,),
                axial_stiffness_n=1000.0,
                dt_s=0.1,
            )

    def test_rejects_dimension_mismatch(self):
        from cable_tension.axial_constraints import solve_global_axial_constraint_step

        with self.assertRaisesRegex(ValueError, "one more entry"):
            solve_global_axial_constraint_step(
                positions=((0.0, 0.0, 0.0), (1.1, 0.0, 0.0)),
                rest_lengths_m=(1.0, 1.0),
                inverse_masses_per_kg=(0.0, 0.0),
                axial_stiffness_n=1000.0,
                dt_s=0.1,
            )


if __name__ == "__main__":
    unittest.main()

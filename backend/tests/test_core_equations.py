import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CoreEquationTests(unittest.TestCase):
    def test_orientation_vectors_are_orthonormal(self):
        from cable_tension.kinematics import orientation_vectors

        theta = math.radians(18.0)
        psi = math.radians(37.0)

        basis = orientation_vectors(theta, psi)

        for name in ("t", "n", "b"):
            self.assertAlmostEqual(float(basis[name] @ basis[name]), 1.0, places=12)

        self.assertAlmostEqual(float(basis["t"] @ basis["n"]), 0.0, places=12)
        self.assertAlmostEqual(float(basis["t"] @ basis["b"]), 0.0, places=12)
        self.assertAlmostEqual(float(basis["n"] @ basis["b"]), 0.0, places=12)

    def test_zero_angle_orientation_matches_thesis_axes(self):
        from cable_tension.kinematics import orientation_vectors

        basis = orientation_vectors(0.0, 0.0)

        self.assertEqual(tuple(basis["t"].round(12)), (1.0, 0.0, 0.0))
        self.assertEqual(tuple(basis["n"].round(12)), (0.0, 0.0, 1.0))
        self.assertEqual(tuple(basis["b"].round(12)), (0.0, -1.0, 0.0))

    def test_axial_strain_and_stretched_step(self):
        from cable_tension.kinematics import axial_strain, stretched_step_components

        strain = axial_strain(tension=2_000.0, axial_stiffness=1_000_000.0)
        dx, dy, dz = stretched_step_components(
            ds=10.0,
            theta=math.radians(30.0),
            psi=0.0,
            strain=strain,
        )

        self.assertAlmostEqual(strain, 0.002)
        self.assertAlmostEqual(dx, 10.0 * 1.002 * math.cos(math.radians(30.0)))
        self.assertAlmostEqual(dy, 0.0)
        self.assertAlmostEqual(dz, 10.0 * 1.002 * math.sin(math.radians(30.0)))

    def test_reynolds_and_tangential_drag_coefficient(self):
        from cable_tension.loads import reynolds_number, tangential_drag_coefficient

        re = reynolds_number(speed=1.5, diameter=0.0264, kinematic_viscosity=1.0e-6)

        self.assertAlmostEqual(re, 39_600.0)
        self.assertAlmostEqual(
            tangential_drag_coefficient(re),
            0.055 / (39_600.0**0.14),
        )

    def test_morison_drag_components_oppose_relative_motion(self):
        from cable_tension.loads import morison_drag_components

        drag = morison_drag_components(
            seawater_density=1025.0,
            diameter=0.0264,
            strain=0.0,
            relative_t=1.2,
            relative_n=-0.5,
            relative_b=0.0,
            tangential_coefficient=0.01,
            normal_coefficient=2.12,
        )

        self.assertLess(drag.tangential, 0.0)
        self.assertGreater(drag.normal, 0.0)
        self.assertAlmostEqual(drag.binormal, 0.0)


if __name__ == "__main__":
    unittest.main()

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CliOutputTests(unittest.TestCase):
    def test_write_result_outputs_summary_profile_and_svg(self):
        from cable_tension.cases import get_case
        from cable_tension.io import write_result
        from cable_tension.solver import solve_case

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            result = solve_case(get_case("la_accel_200m"), points=11)
            written = write_result(result, out_dir)

            self.assertTrue(written.summary_csv.exists())
            self.assertTrue(written.profile_csv.exists())
            self.assertTrue(written.profile_svg.exists())

            with written.summary_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["case_name"], "la_accel_200m")
            self.assertAlmostEqual(float(rows[0]["top_tension_final_n"]), result.top_tension_final_n)

            with written.profile_csv.open(newline="", encoding="utf-8") as handle:
                profile_rows = list(csv.DictReader(handle))
            self.assertEqual(len(profile_rows), 11)
            self.assertEqual(profile_rows[0]["index"], "0")

            self.assertIn("<svg", written.profile_svg.read_text(encoding="utf-8"))

    def test_run_case_cli_writes_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_case.py"),
                    "--case",
                    "ha_accel_200m",
                    "--points",
                    "17",
                    "--output",
                    tmp,
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("ha_accel_200m", completed.stdout)
            self.assertTrue((Path(tmp) / "summary.csv").exists())
            self.assertTrue((Path(tmp) / "profile.csv").exists())
            self.assertTrue((Path(tmp) / "profile.svg").exists())

    def test_run_case_cli_lists_cases_without_case_argument(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_case.py"),
                "--list",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("la_accel_200m", completed.stdout)
        self.assertIn("power_current_speed_1p50", completed.stdout)


if __name__ == "__main__":
    unittest.main()

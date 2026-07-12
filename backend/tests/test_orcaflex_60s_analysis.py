import csv
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


class OrcaFlex60SecondAnalysisTests(unittest.TestCase):
    def test_tdp_rows_include_only_frames_where_both_solvers_have_contact(self):
        from scripts.analyze_orcaflex_60s_validation import _both_contact_rows

        rows = [
            {"time_s": "0", "project_seabed_contact_length_m": "2", "orcaflex_seabed_contact_length_m": "1"},
            {"time_s": "1", "project_seabed_contact_length_m": "0", "orcaflex_seabed_contact_length_m": "1"},
            {"time_s": "2", "project_seabed_contact_length_m": "1", "orcaflex_seabed_contact_length_m": "0"},
            {"time_s": "3", "project_seabed_contact_length_m": "0", "orcaflex_seabed_contact_length_m": "0"},
        ]

        selected, counts = _both_contact_rows(rows)

        self.assertEqual([row["time_s"] for row in selected], ["0"])
        self.assertEqual(counts, {
            "both_contact": 1,
            "project_only": 1,
            "orcaflex_only": 1,
            "neither": 1,
        })

    def test_output_times_must_cover_every_integer_second(self):
        from scripts.analyze_orcaflex_60s_validation import _validate_output_times

        rows = [{"time_s": str(value)} for value in range(61) if value != 17]

        with self.assertRaisesRegex(ValueError, "0..60"):
            _validate_output_times(rows)

    def test_single_matching_file_rejects_ambiguous_artifacts(self):
        from scripts.analyze_orcaflex_60s_validation import _single_matching_file

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a_orcaflex_endpoint_tension.csv").touch()
            (directory / "b_orcaflex_endpoint_tension.csv").touch()

            with self.assertRaisesRegex(ValueError, "exactly one"):
                _single_matching_file(directory, "*_orcaflex_endpoint_tension.csv")

    def test_artifact_contract_rejects_wrong_current_direction(self):
        from scripts.analyze_orcaflex_60s_validation import _validate_artifact_contract

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            report = directory / "case_orcaflex_dynamic_report.md"
            report.write_text(
                "\n".join((
                    "- Status: `dynamic_completed`.",
                    "- Physical output window: `0` to `60` s.",
                    "- Project plough depth: `70` m.",
                    "- Validation element count: `48`.",
                    "- Implicit constant time step: `0.01` s.",
                    "- Prehistory dynamic interval: physical `-60` to `0` s maps to OrcaFlex model time `0` to `60` s; physical output remains `0..60` s.",
                )),
                encoding="utf-8",
            )
            model = directory / "case_orcaflex_dynamic.dat"
            model.write_text("RefCurrentSpeed: 0.35\nRefCurrentDirection: 0\n", encoding="utf-8")
            dynamic_input = directory / "case_orcaflex_dynamic_input.csv"
            dynamic_input.write_text(
                "physical_time_s,fairlead_payout_rate_mps,plough_exit_rate_mps,active_length_m\n"
                "-60,0,0,95.9866666667\n"
                "0,0.8,0.8,95.9866666667\n"
                "60,0.8,0.8,95.9866666667\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "current direction"):
                _validate_artifact_contract(
                    directory,
                    expected_plough_depth_m=70.0,
                    expected_active_length_m=96.0,
                )

    def test_artifact_contract_rejects_prehistory_flux_mismatch(self):
        from scripts.analyze_orcaflex_60s_validation import _validate_artifact_contract

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "case_orcaflex_dynamic_report.md").write_text(
                "\n".join((
                    "- Status: `dynamic_completed`.",
                    "- Physical output window: `0` to `60` s.",
                    "- Project plough depth: `70` m.",
                    "- Validation element count: `48`.",
                    "- Implicit constant time step: `0.01` s.",
                    "- Prehistory dynamic interval: physical `-60` to `0` s maps to OrcaFlex model time `0` to `60` s; physical output remains `0..60` s.",
                )),
                encoding="utf-8",
            )
            (directory / "case_orcaflex_dynamic.dat").write_text(
                "RefCurrentSpeed: 0.35\nRefCurrentDirection: 90\n",
                encoding="utf-8",
            )
            (directory / "case_orcaflex_dynamic_input.csv").write_text(
                "physical_time_s,suspended_length_rate_mps,fairlead_payout_rate_mps,plough_exit_rate_mps,active_length_m\n"
                "-60,0.1,0.2,0.1,95.9866666667\n"
                "0,0,0.8,0.8,95.9866666667\n"
                "60,0,0.8,0.8,95.9866666667\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "matched two-end material flow"):
                _validate_artifact_contract(
                    directory,
                    expected_plough_depth_m=70.0,
                    expected_active_length_m=96.0,
                )

    def test_artifact_contract_accepts_explicit_120_second_prehistory(self):
        from scripts.analyze_orcaflex_60s_validation import _validate_artifact_contract

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "case_orcaflex_dynamic_report.md").write_text(
                "\n".join((
                    "- Status: `dynamic_completed`.",
                    "- Physical output window: `0` to `60` s.",
                    "- Project plough depth: `70` m.",
                    "- Validation element count: `48`.",
                    "- Implicit constant time step: `0.01` s.",
                    "- Prehistory dynamic interval: physical `-120` to `0` s maps to OrcaFlex model time `0` to `120` s; physical output remains `0..60` s.",
                )),
                encoding="utf-8",
            )
            (directory / "case_orcaflex_dynamic.dat").write_text(
                "RefCurrentSpeed: 0.35\nRefCurrentDirection: 90\n",
                encoding="utf-8",
            )
            fields = (
                "physical_time_s",
                "suspended_length_rate_mps",
                "fairlead_payout_rate_mps",
                "plough_exit_rate_mps",
                "active_length_m",
                "fairlead_dx_m",
                "fairlead_dy_m",
                "fairlead_dz_m",
                "plough_dx_m",
                "plough_dy_m",
                "plough_dz_m",
            )
            with (directory / "case_orcaflex_dynamic_input.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for time_s, rate, x_m in ((-120, 0.0, 0.0), (0, 0.8, 92.0), (60, 0.8, 140.0)):
                    writer.writerow({
                        "physical_time_s": time_s,
                        "suspended_length_rate_mps": 0.0,
                        "fairlead_payout_rate_mps": rate,
                        "plough_exit_rate_mps": rate,
                        "active_length_m": 95.98,
                        "fairlead_dx_m": x_m,
                        "fairlead_dy_m": 0.0,
                        "fairlead_dz_m": 0.0,
                        "plough_dx_m": x_m,
                        "plough_dy_m": 0.0,
                        "plough_dz_m": 0.0,
                    })

            _validate_artifact_contract(
                directory,
                expected_plough_depth_m=70.0,
                expected_active_length_m=96.0,
                expected_prehistory_duration_s=120.0,
            )

            input_path = directory / "case_orcaflex_dynamic_input.csv"
            with input_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["fairlead_dx_m"] = "1"
            rows[0]["plough_dx_m"] = "1"
            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "Prehistory endpoint trajectory"):
                _validate_artifact_contract(
                    directory,
                    expected_plough_depth_m=70.0,
                    expected_active_length_m=96.0,
                    expected_prehistory_duration_s=120.0,
                )

    def test_gap_diagnosis_main_uses_independent_scenario_contract(self):
        from scripts import diagnose_orcaflex_suspended_gap as diagnosis

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            endpoint = directory / "case_orcaflex_endpoint_tension.csv"
            output = directory / "diagnosis.json"
            fields = (
                "time_s",
                "active_length_m",
                "end_b_effective_tension_n",
                "end_a_effective_tension_n",
            )
            with endpoint.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for time_s in range(61):
                    writer.writerow({
                        "time_s": time_s,
                        "active_length_m": 95.98,
                        "end_b_effective_tension_n": 1000.0,
                        "end_a_effective_tension_n": 300.0,
                    })
            fake_variant = {
                "variant": "fake",
                "fairlead": {},
                "plough": {},
                "runtime": {},
                "samples": [],
                "windows": {},
            }
            argv = (
                "diagnose_orcaflex_suspended_gap.py",
                "--endpoint-csv", str(endpoint),
                "--output", str(output),
                "--prehistory-duration-s", "120",
                "--expected-active-length-m", "96",
                "--expected-plough-depth-m", "70",
            )
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                diagnosis, "_validate_artifact_contract"
            ) as contract, mock.patch.object(
                diagnosis, "_run_variant", return_value=fake_variant
            ):
                self.assertEqual(diagnosis.main(), 0)

            contract.assert_called_once()
            kwargs = contract.call_args.kwargs
            self.assertEqual(kwargs["expected_prehistory_duration_s"], 120.0)
            self.assertEqual(kwargs["expected_active_length_m"], 96.0)
            self.assertEqual(kwargs["expected_plough_depth_m"], 70.0)
            self.assertAlmostEqual(kwargs["expected_diameter_m"], 0.0264)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["reference_contract"]["expected_active_length_m"], 96.0)
            self.assertEqual(payload["reference_contract"]["observed_active_length_m"], 95.98)

    def test_project_replay_rejects_endpoint_artifact_version_mismatch(self):
        from scripts.analyze_orcaflex_60s_validation import _validate_project_replay

        endpoint_rows = [{
            "time_s": "0",
            "project_fairlead_tension_n": "101",
            "project_plough_boundary_tension_n": "20",
            "project_tdp_tension_n": "19",
            "project_seabed_contact_length_m": "2",
            "active_length_m": "96",
        }]
        result = types.SimpleNamespace(history=[types.SimpleNamespace(
            time_s=60.0,
            top_tension_n=100.0,
            plough_boundary_tension_n=20.0,
            plough_inlet_tension_n=19.0,
            seabed_contact_length_m=2.0,
            free_span_material_length_m=94.0,
        )])

        with self.assertRaisesRegex(ValueError, "project_fairlead_tension_n"):
            _validate_project_replay(endpoint_rows, result, prehistory_duration_s=60.0)

    def test_curve_metrics_use_actual_time_spacing(self):
        from scripts.analyze_orcaflex_60s_validation import _curve_metrics

        row = _curve_metrics(
            "baseline",
            "fairlead",
            [0.0, 10.0, 10.0],
            [10.0, 10.0, 10.0],
            [0.0, 1.0, 3.0],
        )

        self.assertAlmostEqual(float(row["project_mean_n"]), 25.0 / 3.0)

    def test_curve_metrics_use_the_complete_uniform_time_window(self):
        from scripts.analyze_orcaflex_60s_validation import _curve_metrics

        row = _curve_metrics(
            "baseline",
            "fairlead",
            [10.0, 20.0, 30.0],
            [20.0, 20.0, 20.0],
            [0.0, 1.0, 2.0],
        )

        self.assertEqual(row["sample_count"], 3)
        self.assertEqual(row["project_mean_n"], "20")
        self.assertEqual(row["orcaflex_mean_n"], "20")
        self.assertEqual(row["mean_error_pct"], "0")
        self.assertEqual(row["project_peak_time_s"], "2")

    def test_no_contact_marks_tdp_as_not_applicable(self):
        from scripts.analyze_orcaflex_60s_validation import _not_applicable_curve_row

        row = _not_applicable_curve_row("suspended_no_contact", "tdp", 61)

        self.assertEqual(row["status"], "not_applicable_no_contact")
        self.assertEqual(row["sample_count"], 61)
        self.assertEqual(row["project_mean_n"], "")
        self.assertEqual(row["orcaflex_mean_n"], "")

    def test_orcaflex_distribution_is_reoriented_from_fairlead_to_plough(self):
        from scripts.analyze_orcaflex_60s_validation import _orcaflex_distribution

        stations, tensions = _orcaflex_distribution(
            [
                {"time_s": "10", "normalized_active_arc": "0", "effective_tension_n": "100"},
                {"time_s": "10", "normalized_active_arc": "0.5", "effective_tension_n": "200"},
                {"time_s": "10", "normalized_active_arc": "1", "effective_tension_n": "300"},
            ],
            10.0,
        )

        self.assertEqual(stations, [0.0, 0.5, 1.0])
        self.assertEqual(tensions, [300.0, 200.0, 100.0])

    def test_project_distribution_uses_segment_centres_on_geometric_arc(self):
        from scripts.analyze_orcaflex_60s_validation import _project_distribution

        frame = types.SimpleNamespace(
            points=(
                types.SimpleNamespace(x_m=0.0, y_m=0.0, z_m=0.0),
                types.SimpleNamespace(x_m=1.0, y_m=0.0, z_m=0.0),
                types.SimpleNamespace(x_m=3.0, y_m=0.0, z_m=0.0),
            ),
            segment_tensions_n=(10.0, 20.0),
        )

        stations, tensions = _project_distribution(frame)

        self.assertAlmostEqual(stations[0], 1.0 / 6.0)
        self.assertAlmostEqual(stations[1], 2.0 / 3.0)
        self.assertEqual(tensions, [10.0, 20.0])


if __name__ == "__main__":
    unittest.main()

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


class MooringValidationTests(unittest.TestCase):
    def test_moordyn_ramp_duration_cannot_exceed_replay_duration(self):
        from scripts.validate_moordyn_moorpy import _validate_moordyn_driver_settings

        with self.assertRaisesRegex(ValueError, "must not exceed"):
            _validate_moordyn_driver_settings(
                dt_s=0.01,
                duration_s=1.0,
                sample_interval_s=0.1,
                ramp_duration_s=2.0,
            )

    def test_validation_writes_project_baseline_and_moordyn_input_without_optional_dependencies(self):
        from scripts.validate_moordyn_moorpy import _build_project_snapshot, _fmt3, run_validation

        with tempfile.TemporaryDirectory() as tmp:
            report = run_validation(
                Path(tmp),
                case_name="plough_straight_baseline_6min",
                points=7,
                extra_pythonpath=(),
                run_moordyn=False,
                moordyn_dt_s=0.0001,
            )

            summary_path = Path(report["summary_csv"])
            gaps_path = Path(report["gaps_csv"])
            frame_scope_path = Path(report["frame_scope_csv"])
            quasi_static_path = Path(report["quasi_static_csv"])
            initial_static_path = Path(report["initial_state_static_audit_csv"])
            input_mapping_path = Path(report["input_mapping_csv"])
            distribution_path = Path(report["distribution_comparison_csv"])
            moordyn_input_path = Path(report["moordyn_input"])
            moordyn_endpoint_input_path = Path(report["moordyn_endpoint_input"])
            current_profile_path = Path(report["moordyn_current_profile"])
            self.assertTrue(summary_path.exists())
            self.assertTrue(gaps_path.exists())
            self.assertTrue(frame_scope_path.exists())
            self.assertTrue(quasi_static_path.exists())
            self.assertTrue(initial_static_path.exists())
            self.assertTrue(input_mapping_path.exists())
            self.assertTrue(distribution_path.exists())
            self.assertTrue(moordyn_input_path.exists())
            self.assertTrue(moordyn_endpoint_input_path.exists())
            self.assertTrue(current_profile_path.exists())
            snapshot = _build_project_snapshot("plough_straight_baseline_6min", points=7)
            endpoint_seed = snapshot.endpoint_drive_samples[0]
            endpoint_input_text = moordyn_endpoint_input_path.read_text(encoding="utf-8")
            self.assertIn(
                f"1 COUPLED {_fmt3(endpoint_seed.plough_position_m)} 0 0 0 0",
                endpoint_input_text,
            )
            self.assertIn(
                f"2 COUPLED {_fmt3(endpoint_seed.fairlead_position_m)} 0 0 0 0",
                endpoint_input_text,
            )
            self.assertIn(
                f"1 PROJECT_CABLE 1 2 {endpoint_seed.unstretched_length_m:.12g}",
                endpoint_input_text,
            )
            self.assertIn("1 Currents", endpoint_input_text)
            self.assertIn("0.0001 dtM", endpoint_input_text)
            self.assertNotIn("0.001 dtM", endpoint_input_text)
            self.assertIn("3000000 kBot", endpoint_input_text)
            self.assertIn("300000 cBot", endpoint_input_text)
            self.assertIn("0.6 FrictionCoefficient", endpoint_input_text)
            current_profile_text = current_profile_path.read_text(encoding="utf-8")
            current_rows = [
                line.split()
                for line in current_profile_text.splitlines()
                if line.startswith("-80 ") or line.startswith("0 ")
            ]
            self.assertEqual(len(current_rows), 2)
            for row in current_rows:
                self.assertAlmostEqual(float(row[1]), 0.0)
                self.assertAlmostEqual(float(row[2]), 0.35)
                self.assertAlmostEqual(float(row[3]), 0.0)
            with input_mapping_path.open(newline="", encoding="utf-8") as handle:
                mapping_rows = list(csv.DictReader(handle))
            mapping_by_input = {row["project_input"]: row for row in mapping_rows}
            self.assertEqual(mapping_by_input["current_speed_mps/current_direction_deg"]["status"], "matched")
            self.assertIn("current_profile.txt", mapping_by_input["current_speed_mps/current_direction_deg"]["moordyn_target"])
            self.assertEqual(mapping_by_input["seabed_friction_coefficient"]["moordyn_value"], "0.6")
            self.assertEqual(mapping_by_input["XPBD hard seabed projection"]["status"], "shared_model_assumption")
            self.assertTrue(all(row["status"] != "unmapped" for row in mapping_rows))
            report_text = Path(report["report_md"]).read_text(encoding="utf-8")
            self.assertIn("known_plough_trajectory", report_text)
            self.assertIn("diagnostic backfill", report_text)
            self.assertIn("not a production correction", report_text)
            self.assertIn("Frame Scope Audit", report_text)
            self.assertIn("Initial-State Static Audit", report_text)
            self.assertIn("Quasi-Static Time History", report_text)
            self.assertIn("distribution comparison", report_text.lower())
            self.assertIn("input mapping", report_text.lower())

            with summary_path.open(newline="", encoding="utf-8") as handle:
                rows = {row["model"]: row for row in csv.DictReader(handle)}
            self.assertEqual(rows["project_known_plough"]["status"], "ok")
            self.assertEqual(rows["moorpy_static"]["status"], "dependency_missing")
            self.assertEqual(rows["moordyn_endpoint_history"]["status"], "input_written")
            self.assertIn("diagnostic only", rows["moorpy_static"]["notes"])
            self.assertGreater(float(rows["project_known_plough"]["fairlead_tension_n"]), 0.0)
            self.assertGreater(float(rows["project_known_plough"]["plough_tension_n"]), 10.0)

            with frame_scope_path.open(newline="", encoding="utf-8") as handle:
                frame_rows = list(csv.DictReader(handle))
            labels = {row["scope_label"] for row in frame_rows}
            self.assertIn("project_first_frame", labels)
            self.assertIn("project_endpoint_replay_end_nearest_frame", labels)
            self.assertIn("project_final_frame", labels)
            first_frame = next(row for row in frame_rows if row["scope_label"] == "project_first_frame")
            endpoint_end = next(
                row
                for row in frame_rows
                if row["scope_label"] == "project_endpoint_replay_end_nearest_frame"
            )
            final_frame = next(row for row in frame_rows if row["scope_label"] == "project_final_frame")
            closed_form_first = next(
                row
                for row in frame_rows
                if row["scope_label"] == "project_first_frame"
                and row["model"] == "closed_form_catenary_same_frame_static"
            )
            closed_form_final = next(
                row
                for row in frame_rows
                if row["scope_label"] == "project_final_frame"
                and row["model"] == "closed_form_catenary_same_frame_static"
            )
            self.assertEqual(first_frame["model"], "project_known_plough_frame")
            self.assertEqual(first_frame["time_s"], "0")
            self.assertEqual(closed_form_first["status"], "ok")
            self.assertIn("diagnostic only", closed_form_first["notes"])
            self.assertEqual(closed_form_final["status"], "unsupported")
            self.assertIn("penetrate seabed", closed_form_final["notes"])
            self.assertAlmostEqual(
                float(closed_form_first["fairlead_tension_n"]),
                float(first_frame["fairlead_tension_n"]),
                delta=1.0e-6,
            )
            self.assertAlmostEqual(
                float(closed_form_first["plough_tension_n"]),
                float(first_frame["plough_tension_n"]),
                delta=1.0e-6,
            )
            self.assertNotEqual(endpoint_end["time_s"], final_frame["time_s"])
            self.assertIn("same-frame comparison only", final_frame["notes"])

            with quasi_static_path.open(newline="", encoding="utf-8") as handle:
                quasi_static_rows = list(csv.DictReader(handle))
            self.assertEqual(len(quasi_static_rows), 7)
            self.assertEqual(quasi_static_rows[0]["time_s"], "0")
            self.assertEqual(quasi_static_rows[-1]["time_s"], "360")
            self.assertTrue(all(row["status"] == "dependency_missing" for row in quasi_static_rows))
            self.assertGreater(float(quasi_static_rows[0]["project_fairlead_tension_n"]), 0.0)
            self.assertGreater(float(quasi_static_rows[0]["project_plough_tension_n"]), 0.0)
            self.assertEqual(quasi_static_rows[0]["moorpy_fairlead_tension_n"], "")
            self.assertIn("diagnostic only", quasi_static_rows[0]["notes"])

            with initial_static_path.open(newline="", encoding="utf-8") as handle:
                initial_static_rows = list(csv.DictReader(handle))
            self.assertEqual(len(initial_static_rows), 1)
            initial_static = initial_static_rows[0]
            self.assertEqual(initial_static["scope_label"], "project_first_frame")
            self.assertEqual(initial_static["time_s"], "0")
            self.assertEqual(initial_static["status"], "ok")
            self.assertEqual(initial_static["moorpy_status"], "dependency_missing")
            self.assertEqual(initial_static["closed_form_status"], "ok")
            self.assertEqual(initial_static["moordyn_endpoint_status"], "input_written")
            self.assertEqual(
                initial_static["static_acceptance_scope"],
                "separate_static_initial_state_audit",
            )
            self.assertEqual(initial_static["classification"], "initial_state_static_gap_measured")
            self.assertLess(abs(float(initial_static["closed_form_fairlead_delta_n"])), 1.0e-6)
            self.assertLess(abs(float(initial_static["closed_form_plough_delta_n"])), 1.0e-6)
            self.assertEqual(initial_static["moordyn_initial_fairlead_tension_n"], "")
            self.assertIn("no production correction", initial_static["notes"])

    def test_optional_import_uses_explicit_path_when_global_dependencies_are_disallowed(self):
        from scripts.validate_moordyn_moorpy import _optional_import

        module_name = "mooring_validation_fake_optional_dep"
        sys.modules.pop(module_name, None)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.assertIsNone(
                _optional_import("json", extra_pythonpath=(tmp_path,), allow_global=False)
            )

            package = tmp_path / module_name
            package.mkdir()
            (package / "__init__.py").write_text("VALUE = 'from-extra-path'\n", encoding="utf-8")
            module = _optional_import(module_name, extra_pythonpath=(tmp_path,), allow_global=False)
            self.assertIsNotNone(module)
            self.assertEqual(module.VALUE, "from-extra-path")
        sys.modules.pop(module_name, None)

    def test_frame_scope_records_moordyn_endpoint_replay_only_when_completed(self):
        from scripts.validate_moordyn_moorpy import _row, run_validation

        def fake_endpoint_row(*args, **kwargs):
            return _row(
                model="moordyn_endpoint_history",
                status="endpoint_history_ok",
                fairlead_tension_n=12.0,
                plough_tension_n=3.0,
                extra={
                    "moordyn_dt_s": "0.1",
                    "moordyn_duration_s": "1",
                    "moordyn_steps": "10",
                    "moordyn_init_code": "fake",
                    "moordyn_initial_fairlead_tension_n": "0",
                    "moordyn_peak_fairlead_tension_n": "12",
                    "moordyn_peak_plough_tension_n": "3",
                    "moordyn_peak_line_tension_n": "12",
                    "moordyn_max_line_tension_n": "12",
                    "moordyn_history_csv": "fake_endpoint_history.csv",
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.validate_moordyn_moorpy._moordyn_endpoint_history_row", fake_endpoint_row):
                report = run_validation(
                    Path(tmp),
                    case_name="plough_straight_baseline_6min",
                    points=7,
                    extra_pythonpath=(),
                    run_moordyn=False,
                )

            with Path(report["frame_scope_csv"]).open(newline="", encoding="utf-8") as handle:
                frame_rows = list(csv.DictReader(handle))
            self.assertTrue(
                any(
                    row["scope_label"] == "moordyn_endpoint_history_replay_end"
                    and row["model"] == "moordyn_endpoint_history"
                    and row["status"] == "endpoint_history_ok"
                    for row in frame_rows
                )
            )

        def fake_diverged_endpoint_row(*args, **kwargs):
            return _row(
                model="moordyn_endpoint_history",
                status="endpoint_history_diverged",
                fairlead_tension_n=12.0,
                plough_tension_n=3.0,
                extra={
                    "moordyn_dt_s": "0.1",
                    "moordyn_duration_s": "0.5",
                    "moordyn_steps": "5",
                    "moordyn_init_code": "fake",
                    "moordyn_initial_fairlead_tension_n": "0",
                    "moordyn_peak_fairlead_tension_n": "12",
                    "moordyn_peak_plough_tension_n": "3",
                    "moordyn_peak_line_tension_n": "12",
                    "moordyn_max_line_tension_n": "12",
                    "moordyn_history_csv": "fake_endpoint_history.csv",
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.validate_moordyn_moorpy._moordyn_endpoint_history_row", fake_diverged_endpoint_row):
                report = run_validation(
                    Path(tmp),
                    case_name="plough_straight_baseline_6min",
                    points=7,
                    extra_pythonpath=(),
                    run_moordyn=False,
                )

            with Path(report["frame_scope_csv"]).open(newline="", encoding="utf-8") as handle:
                frame_rows = list(csv.DictReader(handle))
            self.assertFalse(
                any(row["scope_label"] == "moordyn_endpoint_history_replay_end" for row in frame_rows)
            )

    def test_endpoint_history_row_passes_ramp_duration_to_runtime_driver(self):
        from scripts.validate_moordyn_moorpy import (
            _build_project_snapshot,
            _moordyn_endpoint_history_row,
            _row,
        )

        captured = {}

        def fake_run(moordyn, **kwargs):
            captured.update(kwargs)
            return _row(
                model="moordyn_endpoint_history",
                status="endpoint_history_ok",
                extra={
                    "moordyn_dt_s": "0.1",
                    "moordyn_duration_s": "1",
                    "moordyn_requested_duration_s": "1",
                    "moordyn_completed_duration_s": "1",
                    "moordyn_replay_coverage_percent": "100",
                    "moordyn_project_window_s": "360",
                    "moordyn_project_window_coverage_percent": "0.277777777778",
                    "moordyn_last_history_time_s": "1",
                    "moordyn_ramp_duration_s": "0.5",
                    "moordyn_steps": "10",
                    "moordyn_init_code": "fake",
                    "moordyn_init_mode": "static_zero_velocity",
                    "moordyn_initial_fairlead_tension_n": "10",
                    "moordyn_peak_fairlead_tension_n": "12",
                    "moordyn_peak_plough_tension_n": "3",
                    "moordyn_peak_line_tension_n": "12",
                    "moordyn_peak_fairlead_time_s": "0.1",
                    "moordyn_peak_plough_time_s": "0.1",
                    "moordyn_peak_line_time_s": "0.1",
                    "moordyn_max_line_tension_n": "12",
                    "moordyn_history_csv": "fake_endpoint_history.csv",
                    "moordyn_node_distribution_csv": "fake_endpoint_nodes.csv",
                },
            )

        snapshot = _build_project_snapshot("plough_straight_baseline_6min", points=7)
        with patch("scripts.validate_moordyn_moorpy._optional_import", return_value=object()):
            with patch("scripts.validate_moordyn_moorpy._run_moordyn_endpoint_history", fake_run):
                row = _moordyn_endpoint_history_row(
                    snapshot,
                    Path("fake_moordyn_endpoint_history.txt"),
                    extra_pythonpath=(),
                    run_moordyn=True,
                    dt_s=0.1,
                    duration_s=1.0,
                    sample_interval_s=0.1,
                    ramp_duration_s=0.5,
                    history_path=Path("fake_endpoint_history.csv"),
                    node_distribution_path=Path("fake_endpoint_nodes.csv"),
                    allow_global=False,
                )

        self.assertEqual(row["status"], "endpoint_history_ok")
        self.assertEqual(captured["ramp_duration_s"], 0.5)
        self.assertEqual(captured["node_distribution_path"], Path("fake_endpoint_nodes.csv"))

    def test_validation_runs_moorpy_static_when_dependency_path_is_available(self):
        from scripts.validate_moordyn_moorpy import run_validation

        deps = Path("tmp/mooring_validation_pydeps")
        if not (deps / "moorpy").exists():
            self.skipTest("MoorPy optional validation dependency is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            report = run_validation(
                Path(tmp),
                case_name="plough_straight_baseline_6min",
                points=7,
                extra_pythonpath=(deps,),
                run_moordyn=False,
            )

            with Path(report["summary_csv"]).open(newline="", encoding="utf-8") as handle:
                rows = {row["model"]: row for row in csv.DictReader(handle)}
            with Path(report["gaps_csv"]).open(newline="", encoding="utf-8") as handle:
                gaps = {row["metric"]: row for row in csv.DictReader(handle)}
            with Path(report["frame_scope_csv"]).open(newline="", encoding="utf-8") as handle:
                frame_scope_rows = list(csv.DictReader(handle))
            with Path(report["quasi_static_csv"]).open(newline="", encoding="utf-8") as handle:
                quasi_static_rows = list(csv.DictReader(handle))
            self.assertEqual(rows["moorpy_static"]["status"], "ok")
            self.assertIn("diagnostic only", rows["moorpy_static"]["notes"])
            self.assertTrue(
                any(
                    row["model"] == "moorpy_same_frame_static"
                    and row["scope_label"] == "project_final_frame"
                    for row in frame_scope_rows
                )
            )
            by_scope_model = {
                (row["scope_label"], row["model"]): row
                for row in frame_scope_rows
            }
            first_moorpy = by_scope_model[("project_first_frame", "moorpy_same_frame_static")]
            first_closed_form = by_scope_model[
                ("project_first_frame", "closed_form_catenary_same_frame_static")
            ]
            self.assertEqual(first_closed_form["status"], "ok")
            self.assertLess(
                abs(
                    float(first_moorpy["fairlead_tension_n"])
                    - float(first_closed_form["fairlead_tension_n"])
                ),
                5.0,
            )
            self.assertLess(
                abs(
                    float(first_moorpy["plough_tension_n"])
                    - float(first_closed_form["plough_tension_n"])
                ),
                5.0,
            )
            final_closed_form = by_scope_model[
                ("project_final_frame", "closed_form_catenary_same_frame_static")
            ]
            self.assertEqual(final_closed_form["status"], "unsupported")
            self.assertIn("penetrate seabed", final_closed_form["notes"])
            self.assertEqual(len(quasi_static_rows), 7)
            self.assertTrue(all(row["status"] == "ok" for row in quasi_static_rows))
            first_quasi = quasi_static_rows[0]
            final_quasi = quasi_static_rows[-1]
            self.assertEqual(first_quasi["time_s"], "0")
            self.assertEqual(final_quasi["time_s"], "360")
            self.assertLess(
                abs(
                    float(first_quasi["moorpy_fairlead_tension_n"])
                    - float(first_moorpy["fairlead_tension_n"])
                ),
                5.0,
            )
            self.assertLess(abs(float(first_quasi["fairlead_delta_n"])), 5.0)
            self.assertLess(abs(float(first_quasi["plough_delta_n"])), 5.0)
            self.assertGreater(float(final_quasi["moorpy_fairlead_tension_n"]), 850.0)
            self.assertIn("diagnostic only", first_quasi["notes"])
            self.assertEqual(rows["project_load_recursive_dynamic"]["status"], "diagnostic")
            self.assertEqual(rows["project_load_recursive_no_current_static"]["status"], "diagnostic")
            self.assertGreater(float(rows["moorpy_static"]["fairlead_tension_n"]), 850.0)
            self.assertGreater(float(rows["moorpy_static"]["plough_tension_n"]), 10.0)
            self.assertGreater(float(rows["project_known_plough"]["plough_tension_n"]), 10.0)
            production_gap = abs(
                float(rows["moorpy_static"]["fairlead_tension_n"])
                - float(rows["project_known_plough"]["fairlead_tension_n"])
            )
            no_current_gap = abs(
                float(rows["moorpy_static"]["fairlead_tension_n"])
                - float(rows["project_load_recursive_no_current_static"]["fairlead_tension_n"])
            )
            self.assertLess(no_current_gap, production_gap)
            self.assertEqual(gaps["plough_tension_n"]["external_model"], "moorpy_static")
            self.assertNotEqual(
                float(gaps["plough_tension_n"]["external_minus_project_n"]),
                0.0,
            )
            self.assertIn("not equivalent input scope", gaps["plough_tension_n"]["diagnosis"])
            self.assertIn("plough-boundary constraint reaction", gaps["plough_tension_n"]["diagnosis"])
            self.assertIn("MoorPy no-current static", gaps["fairlead_tension_n"]["diagnosis"])

    def test_moordyn_dynamic_smoke_driver_records_runtime_tension_history(self):
        from scripts.validate_moordyn_moorpy import _run_moordyn_dynamic_smoke

        class FakeLine:
            def __init__(self):
                self.fairlead_tension = 100.0
                self.max_tension = 120.0

        class FakePoint:
            def __init__(self, line):
                self.line = line

        class FakeMoorDyn:
            def __init__(self):
                self.line = FakeLine()
                self.point = FakePoint(self.line)
                self.dt_s = None
                self.step_count = 0
                self.closed = False

            def Create(self, input_path):
                self.input_path = str(input_path)
                return object()

            def SetDt(self, system, dt_s):
                self.dt_s = dt_s

            def Init(self, system, position, velocity):
                self.init_position = tuple(position)
                self.init_velocity = tuple(velocity)
                return 0

            def GetLine(self, system, line_id):
                return self.line

            def GetPoint(self, system, point_id):
                return self.point

            def GetLineFairTen(self, line):
                return line.fairlead_tension

            def GetLineMaxTen(self, line):
                return line.max_tension

            def GetPointForce(self, point):
                return (0.0, -point.line.fairlead_tension, -10.0)

            def Step(self, system, position, velocity, time_s, dt_s):
                self.step_count += 1
                self.line.fairlead_tension += 5.0
                self.line.max_tension += 5.0
                return 0

            def Close(self, system):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "moordyn_history.csv"
            fake = FakeMoorDyn()
            row = _run_moordyn_dynamic_smoke(
                fake,
                input_path=Path(tmp) / "case_moordyn.txt",
                fairlead_position_m=(0.0, 288.0, 0.0),
                dt_s=0.01,
                duration_s=0.03,
                sample_interval_s=0.01,
                history_path=history_path,
            )

            self.assertEqual(row["status"], "dynamic_smoke_ok")
            self.assertEqual(row["model"], "moordyn_python")
            self.assertEqual(row["moordyn_dt_s"], "0.01")
            self.assertEqual(row["moordyn_steps"], "3")
            self.assertEqual(row["moordyn_init_code"], "0")
            self.assertEqual(row["fairlead_tension_n"], "115")
            self.assertEqual(row["moordyn_initial_fairlead_tension_n"], "100")
            self.assertEqual(row["moordyn_peak_fairlead_tension_n"], "115")
            self.assertEqual(row["moordyn_peak_line_tension_n"], "135")
            self.assertEqual(row["moordyn_peak_fairlead_time_s"], "0.03")
            self.assertEqual(row["moordyn_peak_line_time_s"], "0.03")
            self.assertEqual(row["moordyn_max_line_tension_n"], "135")
            self.assertTrue(fake.closed)
            self.assertTrue(history_path.exists())
            with history_path.open(newline="", encoding="utf-8") as handle:
                history = list(csv.DictReader(handle))
            self.assertEqual([item["time_s"] for item in history], ["0", "0.01", "0.02", "0.03"])
            self.assertEqual(history[-1]["fairlead_tension_n"], "115")

    def test_moordyn_row_keeps_ramp_duration_out_of_static_smoke_driver(self):
        from scripts.validate_moordyn_moorpy import _build_project_snapshot, _moordyn_row

        snapshot = _build_project_snapshot("plough_straight_baseline_6min", points=7)
        captured = {}

        def fake_run_moordyn_dynamic_smoke(
            moordyn,
            *,
            input_path,
            fairlead_position_m,
            dt_s,
            duration_s,
            sample_interval_s,
            history_path,
        ):
            captured["input_path"] = input_path
            captured["fairlead_position_m"] = fairlead_position_m
            captured["dt_s"] = dt_s
            captured["duration_s"] = duration_s
            captured["sample_interval_s"] = sample_interval_s
            captured["history_path"] = history_path
            return {
                "model": "moordyn_python",
                "status": "dynamic_smoke_ok",
                "notes": "fake smoke row",
            }

        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "moordyn_history.csv"
            with patch("scripts.validate_moordyn_moorpy._optional_import", return_value=object()):
                with patch(
                    "scripts.validate_moordyn_moorpy._run_moordyn_dynamic_smoke",
                    fake_run_moordyn_dynamic_smoke,
                ):
                    row = _moordyn_row(
                        snapshot,
                        Path(tmp) / "case_moordyn.txt",
                        extra_pythonpath=(),
                        run_moordyn=True,
                        dt_s=0.01,
                        duration_s=0.02,
                        sample_interval_s=0.01,
                        history_path=history_path,
                        allow_global=True,
                    )

        self.assertEqual(row["status"], "dynamic_smoke_ok")
        self.assertEqual(captured["history_path"], history_path)
        self.assertEqual(captured["duration_s"], 0.02)

    def test_moordyn_endpoint_history_driver_moves_coupled_endpoints_and_line_length(self):
        from scripts.validate_moordyn_moorpy import EndpointDriveSample, _run_moordyn_endpoint_history

        class FakeLine:
            def __init__(self):
                self.fairlead_tension = 100.0
                self.max_tension = 120.0
                self.lengths = []
                self.length_rates = []

        class FakePoint:
            def __init__(self, line, force_sign):
                self.line = line
                self.force_sign = force_sign

        class FakeMoorDyn:
            def __init__(self):
                self.line = FakeLine()
                self.plough = FakePoint(self.line, -1.0)
                self.fairlead = FakePoint(self.line, 1.0)
                self.step_positions = []
                self.step_velocities = []
                self.closed = False

            def Create(self, input_path):
                return object()

            def SetDt(self, system, dt_s):
                self.dt_s = dt_s

            def NCoupledDOF(self, system):
                return 6

            def Init(self, system, position, velocity):
                self.init_position = tuple(position)
                self.init_velocity = tuple(velocity)
                self.init_mode = "Init"
                return 0

            def Init_NoIC(self, system, position, velocity):
                self.init_mode = "Init_NoIC"
                raise AssertionError("endpoint history should prefer static Init with zero velocity")

            def GetLine(self, system, line_id):
                return self.line

            def GetPoint(self, system, point_id):
                return self.plough if point_id == 1 else self.fairlead

            def GetLineFairTen(self, line):
                return line.fairlead_tension

            def GetLineMaxTen(self, line):
                return line.max_tension

            def GetPointForce(self, point):
                return (0.0, point.force_sign * point.line.fairlead_tension, -10.0)

            def GetLineNumberNodes(self, line):
                return 3

            def GetLineNodePos(self, line, index):
                return (
                    (0.0, 0.0, -80.0),
                    (0.0, 2.0, -80.0),
                    (0.0, 4.0, 0.0),
                )[index]

            def GetLineNodeTen(self, line, index):
                return (
                    (0.0, 10.0, 0.0),
                    (0.0, 20.0, 0.0),
                    (0.0, 30.0, 0.0),
                )[index]

            def GetLineNodeSeabedForce(self, line, index):
                return (
                    (0.0, 0.0, 5.0),
                    (0.0, 0.0, 2.0),
                    (0.0, 0.0, 0.0),
                )[index]

            def GetLineNodeForce(self, line, index):
                return (
                    (0.0, 1.0, 0.0),
                    (0.0, 2.0, 0.0),
                    (0.0, 3.0, 0.0),
                )[index]

            def SetLineUnstretchedLength(self, line, length):
                line.lengths.append(float(length))

            def SetLineUnstretchedLengthVel(self, line, length_rate):
                line.length_rates.append(float(length_rate))

            def Step(self, system, position, velocity, time_s, dt_s):
                if len(position) != 6 or len(velocity) != 6:
                    raise AssertionError("endpoint history must drive both coupled endpoints")
                self.step_positions.append(tuple(position))
                self.step_velocities.append(tuple(velocity))
                self.line.fairlead_tension += 5.0
                self.line.max_tension += 5.0
                return 0

            def Close(self, system):
                self.closed = True

        samples = (
            EndpointDriveSample(
                time_s=0.0,
                plough_position_m=(0.0, 0.0, -80.0),
                fairlead_position_m=(0.0, 0.0, 0.0),
                plough_velocity_mps=(100.0, 0.0, 0.0),
                fairlead_velocity_mps=(0.0, 200.0, 0.0),
                unstretched_length_m=100.0,
                unstretched_length_rate_mps=100.0,
            ),
            EndpointDriveSample(
                time_s=0.02,
                plough_position_m=(2.0, 0.0, -80.0),
                fairlead_position_m=(0.0, 4.0, 0.0),
                plough_velocity_mps=(100.0, 0.0, 0.0),
                fairlead_velocity_mps=(0.0, 200.0, 0.0),
                unstretched_length_m=102.0,
                unstretched_length_rate_mps=100.0,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "endpoint_history.csv"
            node_path = Path(tmp) / "endpoint_nodes.csv"
            fake = FakeMoorDyn()
            row = _run_moordyn_endpoint_history(
                fake,
                input_path=Path(tmp) / "case_moordyn_endpoint_history.txt",
                drive_samples=samples,
                dt_s=0.01,
                duration_s=0.02,
                sample_interval_s=0.01,
                history_path=history_path,
                node_distribution_path=node_path,
                ramp_duration_s=0.02,
            )

            self.assertEqual(row["model"], "moordyn_endpoint_history")
            self.assertEqual(row["status"], "endpoint_history_ok")
            self.assertEqual(row["moordyn_steps"], "2")
            self.assertEqual(row["moordyn_requested_duration_s"], "0.02")
            self.assertEqual(row["moordyn_completed_duration_s"], "0.02")
            self.assertEqual(row["moordyn_replay_coverage_percent"], "100")
            self.assertEqual(row["moordyn_project_window_s"], "0.02")
            self.assertEqual(row["moordyn_project_window_coverage_percent"], "100")
            self.assertEqual(row["moordyn_last_history_time_s"], "0.02")
            self.assertEqual(row["moordyn_init_mode"], "static_zero_velocity")
            self.assertEqual(fake.init_position, (0.0, 0.0, -80.0, 0.0, 0.0, 0.0))
            self.assertEqual(fake.init_velocity, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            self.assertEqual(fake.init_mode, "Init")
            self.assertEqual(fake.step_positions[-1], (2.0, 0.0, -80.0, 0.0, 4.0, 0.0))
            self.assertEqual(fake.step_velocities[-1], (100.0, 0.0, 0.0, 0.0, 200.0, 0.0))
            self.assertEqual(fake.line.length_rates[0], 0.0)
            self.assertEqual(fake.line.lengths[-1], 102.0)
            self.assertEqual(fake.line.length_rates[-1], 100.0)
            self.assertEqual(row["fairlead_tension_n"], "110")
            self.assertEqual(row["moordyn_initial_fairlead_tension_n"], "100")
            self.assertEqual(row["moordyn_peak_fairlead_tension_n"], "110")
            self.assertEqual(row["moordyn_peak_plough_tension_n"], "10")
            self.assertEqual(row["moordyn_peak_line_tension_n"], "130")
            self.assertEqual(row["moordyn_peak_fairlead_time_s"], "0.02")
            self.assertEqual(row["moordyn_peak_plough_time_s"], "0")
            self.assertEqual(row["moordyn_peak_line_time_s"], "0.02")
            self.assertEqual(row["moordyn_ramp_duration_s"], "0.02")
            self.assertEqual(row["moordyn_node_distribution_csv"], str(node_path))
            self.assertEqual(row["moordyn_node_count"], "3")
            self.assertEqual(row["moordyn_seabed_contact_node_count"], "2")
            self.assertEqual(row["moordyn_first_seabed_contact_node"], "0")
            self.assertEqual(row["moordyn_last_seabed_contact_node"], "1")
            self.assertEqual(row["moordyn_max_node_seabed_force_n"], "5")
            self.assertEqual(row["moordyn_max_node_seabed_force_node"], "0")
            self.assertTrue(fake.closed)
            with history_path.open(newline="", encoding="utf-8") as handle:
                history = list(csv.DictReader(handle))
            with node_path.open(newline="", encoding="utf-8") as handle:
                nodes = list(csv.DictReader(handle))
            node_times = {row["time_s"] for row in nodes}
            self.assertEqual(fake.step_positions[0], (0.5, 0.0, -80.0, 0.0, 1.0, 0.0))
            self.assertEqual(fake.step_velocities[0], (125.0, 0.0, 0.0, 0.0, 250.0, 0.0))
            self.assertEqual(history[-1]["time_s"], "0.02")
            self.assertEqual(history[-1]["plough_x_m"], "2")
            self.assertEqual(history[-1]["fairlead_y_m"], "4")
            self.assertEqual(history[-1]["line_unstretched_length_m"], "102")
            self.assertEqual(node_times, {"0", "0.01", "0.02"})
            self.assertEqual(len(nodes), 9)
            self.assertEqual(nodes[0]["contact_status"], "contact")
            self.assertEqual(nodes[0]["tension_magnitude_n"], "10")
            self.assertEqual(nodes[2]["contact_status"], "free")

    def test_distribution_comparison_rows_align_project_and_moordyn_by_fraction(self):
        from scripts.validate_moordyn_moorpy import (
            _build_distribution_comparison_rows,
            _write_distribution_comparison_csv,
        )

        class Point:
            def __init__(self, x_m, y_m, z_m, tension_n):
                self.x_m = x_m
                self.y_m = y_m
                self.z_m = z_m
                self.tension_n = tension_n

        class Frame:
            time_s = 10.0
            points = (
                Point(0.0, 0.0, 0.0, 100.0),
                Point(10.0, 0.0, 5.0, 80.0),
                Point(20.0, 0.0, 10.0, 60.0),
            )

        moordyn_rows = [
            {
                "time_s": "0",
                "node_index": "0",
                "node_fraction": "0",
                "tension_magnitude_n": "1",
                "seabed_force_magnitude_n": "0",
                "contact_status": "free",
            },
            {
                "time_s": "10",
                "node_index": "0",
                "node_fraction": "0",
                "tension_magnitude_n": "110",
                "seabed_force_magnitude_n": "0",
                "contact_status": "free",
            },
            {
                "time_s": "10",
                "node_index": "1",
                "node_fraction": "0.5",
                "tension_magnitude_n": "90",
                "seabed_force_magnitude_n": "5",
                "contact_status": "contact",
            },
            {
                "time_s": "10",
                "node_index": "2",
                "node_fraction": "1",
                "tension_magnitude_n": "70",
                "seabed_force_magnitude_n": "0",
                "contact_status": "free",
            },
        ]

        rows = _build_distribution_comparison_rows(
            project_frame=Frame(),
            moordyn_node_rows=moordyn_rows,
            target_time_s=10.0,
        )

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["project_tension_n"], "60")
        self.assertEqual(rows[1]["project_tension_n"], "80")
        self.assertEqual(rows[1]["moordyn_tension_n"], "90")
        self.assertEqual(rows[1]["moordyn_minus_project_tension_n"], "10")
        self.assertEqual(rows[1]["moordyn_seabed_force_magnitude_n"], "5")
        self.assertEqual(rows[1]["moordyn_contact_status"], "contact")
        self.assertEqual(rows[2]["project_tension_n"], "100")

        missing_time_rows = _build_distribution_comparison_rows(
            project_frame=Frame(),
            moordyn_node_rows=moordyn_rows,
            target_time_s=10.5,
        )
        self.assertEqual(missing_time_rows, [])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "distribution.csv"
            _write_distribution_comparison_csv(rows, path)
            with path.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))
        self.assertEqual(written[1]["moordyn_minus_project_tension_n"], "10")

    def test_distribution_mouth_audit_rows_separate_contact_and_endpoint_mouths(self):
        from scripts.validate_moordyn_moorpy import (
            _build_distribution_mouth_audit_rows,
            _write_distribution_mouth_audit_csv,
        )

        class Point:
            def __init__(self, x_m, y_m, z_m, tension_n):
                self.x_m = x_m
                self.y_m = y_m
                self.z_m = z_m
                self.tension_n = tension_n

        class Frame:
            time_s = 10.0
            points = (
                Point(0.0, 0.0, 0.0, 100.0),
                Point(10.0, 0.0, 5.0, 80.0),
                Point(20.0, 0.0, 10.0, 60.0),
            )
            segment_tensions_n = (95.0, 65.0)

        moordyn_rows = [
            {
                "time_s": "10",
                "node_index": "0",
                "node_fraction": "0",
                "tension_magnitude_n": "110",
                "seabed_force_magnitude_n": "0",
                "contact_status": "free",
            },
            {
                "time_s": "10",
                "node_index": "1",
                "node_fraction": "0.5",
                "tension_magnitude_n": "90",
                "seabed_force_magnitude_n": "5",
                "contact_status": "contact",
            },
            {
                "time_s": "10",
                "node_index": "2",
                "node_fraction": "1",
                "tension_magnitude_n": "70",
                "seabed_force_magnitude_n": "0",
                "contact_status": "free",
            },
        ]

        rows = _build_distribution_mouth_audit_rows(
            project_frame=Frame(),
            project_plough_inlet_tension_n=14.0,
            project_plough_adjacent_segment_tension_n=65.0,
            moordyn_node_rows=moordyn_rows,
            target_time_s=10.0,
        )

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["project_fraction_fairlead_to_plough"], "1")
        self.assertEqual(rows[0]["project_segment_index"], "1")
        self.assertEqual(rows[0]["project_segment_tension_n"], "65")
        self.assertEqual(rows[0]["project_plough_inlet_tension_n"], "14")
        self.assertEqual(rows[0]["project_plough_adjacent_segment_tension_n"], "65")
        self.assertEqual(rows[0]["comparison_mouth"], "plough_side_node_vs_project_tail_distribution")
        self.assertEqual(rows[0]["direct_tension_comparison"], "mouth_mismatch_diagnostic")
        self.assertEqual(rows[1]["comparison_mouth"], "contact_distribution")
        self.assertEqual(rows[1]["direct_tension_comparison"], "contact_model_diagnostic")
        self.assertEqual(rows[1]["moordyn_minus_project_segment_tension_n"], "25")
        self.assertEqual(rows[2]["comparison_mouth"], "fairlead_endpoint_distribution")
        self.assertEqual(rows[2]["direct_tension_comparison"], "direct_distribution")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "distribution_mouth_audit.csv"
            _write_distribution_mouth_audit_csv(rows, path)
            with path.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))
        self.assertEqual(written[0]["comparison_mouth"], "plough_side_node_vs_project_tail_distribution")

    def test_distribution_attribution_rows_summarize_final_window_sensitivity_nodes(self):
        from scripts.validate_moordyn_moorpy import (
            _build_distribution_attribution_rows,
            _write_distribution_attribution_csv,
        )

        class Point:
            def __init__(self, x_m, y_m, z_m, tension_n):
                self.x_m = x_m
                self.y_m = y_m
                self.z_m = z_m
                self.tension_n = tension_n

        class Frame:
            time_s = 10.0
            points = (
                Point(0.0, 0.0, 0.0, 100.0),
                Point(10.0, 0.0, 5.0, 80.0),
                Point(20.0, 0.0, 10.0, 60.0),
            )
            segment_tensions_n = (95.0, 65.0)

        with tempfile.TemporaryDirectory() as tmp:
            node_path = Path(tmp) / "baseline_nodes.csv"
            with node_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "time_s",
                        "node_index",
                        "node_fraction",
                        "x_m",
                        "y_m",
                        "z_m",
                        "tension_magnitude_n",
                        "seabed_force_magnitude_n",
                        "contact_status",
                    ),
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "time_s": "2",
                            "node_index": "0",
                            "node_fraction": "0",
                            "tension_magnitude_n": "110",
                            "seabed_force_magnitude_n": "0",
                            "contact_status": "free",
                        },
                        {
                            "time_s": "2",
                            "node_index": "1",
                            "node_fraction": "0.5",
                            "tension_magnitude_n": "90",
                            "seabed_force_magnitude_n": "5",
                            "contact_status": "contact",
                        },
                        {
                            "time_s": "2",
                            "node_index": "2",
                            "node_fraction": "1",
                            "tension_magnitude_n": "70",
                            "seabed_force_magnitude_n": "0",
                            "contact_status": "free",
                        },
                    ]
                )

            sensitivity_rows = [
                {
                    "variant_id": "baseline",
                    "category": "baseline",
                    "changed_parameter": "none",
                    "status": "endpoint_history_ok",
                    "duration_s": "2",
                    "window_start_s": "8",
                    "window_end_s": "10",
                    "node_distribution_csv": str(node_path),
                },
                {
                    "variant_id": "early_window",
                    "category": "window_guard",
                    "changed_parameter": "window_end_s",
                    "status": "endpoint_history_ok",
                    "duration_s": "2",
                    "window_start_s": "4",
                    "window_end_s": "6",
                    "node_distribution_csv": str(node_path),
                },
            ]

            rows = _build_distribution_attribution_rows(
                project_frame=Frame(),
                project_plough_inlet_tension_n=14.0,
                project_plough_adjacent_segment_tension_n=65.0,
                sensitivity_rows=sensitivity_rows,
            )

            self.assertEqual(rows[0]["variant_id"], "baseline")
            self.assertEqual(rows[0]["status"], "ok")
            self.assertEqual(rows[0]["dynamic_history_window_s"], "8..10")
            self.assertEqual(rows[0]["initialization_scope"], "fresh_moordyn_static_zero_velocity_at_window_start")
            self.assertEqual(rows[0]["distribution_target_time_s"], "2")
            self.assertEqual(rows[0]["direct_distribution_count"], "1")
            self.assertEqual(rows[0]["direct_delta_avg_n"], "-25")
            self.assertEqual(rows[0]["fairlead_delta_n"], "-25")
            self.assertEqual(rows[0]["contact_model_count"], "1")
            self.assertEqual(rows[0]["contact_delta_avg_n"], "25")
            self.assertEqual(rows[0]["max_seabed_force_n"], "5")
            self.assertEqual(rows[0]["mouth_mismatch_delta_n"], "45")
            self.assertEqual(rows[1]["status"], "window_not_matching_project_output_time")
            self.assertIn("not equal", rows[1]["notes"])

            path = Path(tmp) / "distribution_attribution.csv"
            _write_distribution_attribution_csv(rows, path)
            with path.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))
            self.assertEqual(written[0]["variant_id"], "baseline")

    def test_validation_writes_runtime_sensitivity_and_dt_convergence_artifacts_when_enabled(self):
        import scripts.validate_moordyn_moorpy as validation

        def fake_endpoint_history(moordyn, **kwargs):
            input_path = Path(kwargs["input_path"])
            input_text = input_path.read_text(encoding="utf-8")
            current_profile_text = (input_path.parent / "current_profile.txt").read_text(encoding="utf-8")
            dt_s = float(kwargs["dt_s"])
            history_path = Path(kwargs["history_path"])
            node_path = Path(kwargs["node_distribution_path"])
            current_factor = 0.0 if "current_scale=0" in current_profile_text else 1.0
            friction_factor = 0.0 if "0 FrictionCoefficient" in input_text else 1.0
            with history_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "time_s",
                        "fairlead_tension_n",
                        "plough_tension_n",
                        "max_line_tension_n",
                    ],
                )
                writer.writeheader()
                for time_s in (0.0, 0.01, 0.02):
                    writer.writerow(
                        {
                            "time_s": f"{time_s:.2f}".rstrip("0").rstrip(".") or "0",
                            "fairlead_tension_n": f"{1000.0 + time_s * 100.0 + dt_s:.12g}",
                            "plough_tension_n": f"{200.0 + time_s * 10.0 + dt_s:.12g}",
                            "max_line_tension_n": f"{1005.0 + time_s * 50.0 + dt_s:.12g}",
                        }
                    )
            with node_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "time_s",
                        "node_index",
                        "node_fraction",
                        "x_m",
                        "y_m",
                        "z_m",
                        "tension_magnitude_n",
                        "seabed_force_magnitude_n",
                        "contact_status",
                    ],
                )
                writer.writeheader()
                for time_s in (0.0, 0.01, 0.02):
                    for node_index in (0, 1):
                        writer.writerow(
                            {
                                "time_s": f"{time_s:.2f}".rstrip("0").rstrip(".") or "0",
                                "node_index": str(node_index),
                                "node_fraction": f"{0.5 * node_index:.12g}",
                                "x_m": f"{node_index + time_s + dt_s:.12g}",
                                "y_m": f"{2.0 * node_index + time_s:.12g}",
                                "z_m": f"{-180.0 + node_index - dt_s:.12g}",
                                "tension_magnitude_n": f"{50.0 + node_index + time_s * 10.0 + dt_s:.12g}",
                                "seabed_force_magnitude_n": f"{5.0 * node_index + dt_s:.12g}",
                                "contact_status": "contact" if node_index == 1 else "free",
                            }
                        )
            return validation._row(
                model="moordyn_endpoint_history",
                status="endpoint_history_ok",
                fairlead_tension_n=1000.0 + 10.0 * current_factor + 5.0 * friction_factor + dt_s,
                plough_tension_n=200.0 + current_factor,
                notes="fake endpoint replay",
                extra={
                    "moordyn_dt_s": f"{dt_s:.12g}",
                    "moordyn_duration_s": "0.02",
                    "moordyn_requested_duration_s": "0.02",
                    "moordyn_completed_duration_s": "0.02",
                    "moordyn_replay_coverage_percent": "100",
                    "moordyn_project_window_s": "360",
                    "moordyn_project_window_coverage_percent": "0.00555555555556",
                    "moordyn_last_history_time_s": "0.02",
                    "moordyn_ramp_duration_s": "0.0",
                    "moordyn_steps": "2",
                    "moordyn_init_code": "0",
                    "moordyn_init_mode": "static_zero_velocity",
                    "moordyn_initial_fairlead_tension_n": "900",
                    "moordyn_peak_fairlead_tension_n": "1010",
                    "moordyn_peak_plough_tension_n": "201",
                    "moordyn_peak_line_tension_n": "1005",
                    "moordyn_peak_fairlead_time_s": "0.01",
                    "moordyn_peak_plough_time_s": "0.01",
                    "moordyn_peak_line_time_s": "0.01",
                    "moordyn_max_line_tension_n": "1005",
                    "moordyn_history_csv": str(kwargs["history_path"]),
                    "moordyn_node_distribution_csv": str(kwargs["node_distribution_path"]),
                    "moordyn_node_count": "3",
                    "moordyn_seabed_contact_node_count": "2",
                    "moordyn_first_seabed_contact_node": "1",
                    "moordyn_last_seabed_contact_node": "2",
                    "moordyn_max_node_seabed_force_n": "75",
                    "moordyn_max_node_seabed_force_node": "2",
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(validation, "_optional_import", return_value=object()):
                with patch.object(validation, "_run_moordyn_endpoint_history", fake_endpoint_history):
                    report = validation.run_validation(
                        Path(tmp),
                        case_name="plough_straight_baseline_6min",
                        points=7,
                        extra_pythonpath=(),
                        run_moordyn=True,
                        moordyn_dt_s=0.0001,
                        moordyn_duration_s=0.02,
                        moordyn_sample_interval_s=0.01,
                        run_moordyn_sensitivity=True,
                        moordyn_sensitivity_duration_s=0.02,
                        moordyn_sensitivity_start_s=180.0,
                        run_moordyn_dt_convergence=True,
                        moordyn_dt_convergence_duration_s=0.02,
                        moordyn_dt_convergence_start_s=180.0,
                    )

            sensitivity_path = Path(report["moordyn_sensitivity_csv"])
            convergence_path = Path(report["moordyn_dt_convergence_csv"])
            history_convergence_path = Path(report["moordyn_dt_history_convergence_csv"])
            node_convergence_path = Path(report["moordyn_dt_node_convergence_csv"])
            initialization_acceptance_path = Path(report["moordyn_initialization_acceptance_csv"])
            initial_static_path = Path(report["initial_state_static_audit_csv"])
            self.assertTrue(sensitivity_path.exists())
            self.assertTrue(convergence_path.exists())
            self.assertTrue(history_convergence_path.exists())
            self.assertTrue(node_convergence_path.exists())
            self.assertTrue(initialization_acceptance_path.exists())
            self.assertTrue(initial_static_path.exists())
            with sensitivity_path.open(newline="", encoding="utf-8") as handle:
                sensitivity = {row["variant_id"]: row for row in csv.DictReader(handle)}
            self.assertIn("baseline", sensitivity)
            self.assertIn("current_off", sensitivity)
            self.assertIn("friction_off", sensitivity)
            self.assertIn("added_mass_off", sensitivity)
            self.assertIn("added_mass_high", sensitivity)
            self.assertEqual(sensitivity["baseline"]["window_start_s"], "180", sensitivity["baseline"])
            self.assertEqual(sensitivity["baseline"]["window_end_s"], "180.02", sensitivity["baseline"])
            self.assertNotEqual(
                sensitivity["baseline"]["fairlead_tension_n"],
                sensitivity["current_off"]["fairlead_tension_n"],
            )
            with convergence_path.open(newline="", encoding="utf-8") as handle:
                convergence = list(csv.DictReader(handle))
            self.assertEqual({row["dt_s"] for row in convergence}, {"0.0002", "0.0001", "5e-05"})
            self.assertTrue(all(row["reference_dt_s"] == "5e-05" for row in convergence))
            self.assertTrue(all(row["window_start_s"] == "180" for row in convergence))
            self.assertTrue(all(row["window_end_s"] == "180.02" for row in convergence))
            with history_convergence_path.open(newline="", encoding="utf-8") as handle:
                history_convergence = {row["dt_s"]: row for row in csv.DictReader(handle)}
            self.assertEqual(history_convergence["0.0001"]["reference_dt_s"], "5e-05")
            self.assertEqual(history_convergence["0.0001"]["matched_sample_count"], "3")
            self.assertEqual(history_convergence["0.0001"]["missing_sample_count"], "0")
            self.assertIn("final-scalar", history_convergence["0.0001"]["notes"])
            self.assertIn("Sampled", history_convergence["0.0001"]["notes"])
            self.assertNotEqual(history_convergence["0.0001"]["max_abs_fairlead_delta_n"], "")
            self.assertNotEqual(history_convergence["0.0001"]["rms_fairlead_delta_n"], "")
            self.assertEqual(history_convergence["0.0001"]["initial_sample_time_s"], "0")
            self.assertEqual(history_convergence["0.0001"]["post_initial_matched_sample_count"], "2")
            self.assertNotEqual(history_convergence["0.0001"]["post_initial_max_abs_fairlead_delta_n"], "")
            self.assertNotEqual(history_convergence["0.0001"]["post_initial_rms_fairlead_delta_n"], "")
            with node_convergence_path.open(newline="", encoding="utf-8") as handle:
                node_convergence = {row["dt_s"]: row for row in csv.DictReader(handle)}
            self.assertEqual(node_convergence["0.0001"]["reference_dt_s"], "5e-05")
            self.assertEqual(node_convergence["0.0001"]["matched_node_sample_count"], "6")
            self.assertEqual(node_convergence["0.0001"]["missing_node_sample_count"], "0")
            self.assertEqual(node_convergence["0.0001"]["contact_status_mismatch_count"], "0")
            self.assertNotEqual(node_convergence["0.0001"]["max_abs_node_tension_delta_n"], "")
            self.assertNotEqual(node_convergence["0.0001"]["rms_node_tension_delta_n"], "")
            self.assertNotEqual(node_convergence["0.0001"]["max_position_delta_m"], "")
            self.assertEqual(node_convergence["0.0001"]["initial_sample_time_s"], "0")
            self.assertEqual(node_convergence["0.0001"]["post_initial_matched_node_sample_count"], "4")
            self.assertNotEqual(node_convergence["0.0001"]["post_initial_max_abs_node_tension_delta_n"], "")
            self.assertNotEqual(node_convergence["0.0001"]["post_initial_max_position_delta_m"], "")
            self.assertEqual(node_convergence["0.0001"]["post_initial_contact_status_mismatch_count"], "0")
            with initialization_acceptance_path.open(newline="", encoding="utf-8") as handle:
                initialization_acceptance = {row["dt_s"]: row for row in csv.DictReader(handle)}
            self.assertEqual(initialization_acceptance["0.0001"]["reference_dt_s"], "5e-05")
            self.assertEqual(initialization_acceptance["0.0001"]["initial_sample_time_s"], "0")
            self.assertEqual(
                initialization_acceptance["0.0001"]["classification"],
                "initialization_sample_dominates_dt_convergence",
            )
            self.assertEqual(
                initialization_acceptance["0.0001"]["t0_included_in_driven_history_acceptance"],
                "false",
            )
            self.assertEqual(
                initialization_acceptance["0.0001"]["driven_history_acceptance_scope"],
                "post_initial_driven_history",
            )
            self.assertEqual(
                initialization_acceptance["0.0001"]["initial_state_acceptance_scope"],
                "separate_static_initial_state_audit",
            )
            self.assertEqual(initialization_acceptance["5e-05"]["classification"], "reference_row")
            self.assertEqual(
                initialization_acceptance["5e-05"]["t0_included_in_driven_history_acceptance"],
                "not_applicable",
            )
            self.assertEqual(initialization_acceptance["5e-05"]["driven_history_acceptance_scope"], "reference_row")
            with initial_static_path.open(newline="", encoding="utf-8") as handle:
                initial_static = next(csv.DictReader(handle))
            self.assertEqual(initial_static["moordyn_endpoint_status"], "endpoint_history_ok")
            self.assertEqual(initial_static["moordyn_initial_fairlead_tension_n"], "900")
            self.assertEqual(
                initial_static["static_acceptance_scope"],
                "separate_static_initial_state_audit",
            )
            project_fairlead = float(initial_static["project_fairlead_tension_n"])
            self.assertAlmostEqual(
                float(initial_static["moordyn_initial_fairlead_delta_from_project_n"]),
                900.0 - project_fairlead,
            )

    def test_dt_convergence_reference_uses_smallest_completed_replay(self):
        from scripts.validate_moordyn_moorpy import _dt_convergence_reference_row

        reference = _dt_convergence_reference_row(
            [
                {"dt_s": "0.0002", "status": "endpoint_history_ok", "reference_dt_s": "5e-05"},
                {"dt_s": "0.0001", "status": "endpoint_history_ok", "reference_dt_s": "5e-05"},
                {"dt_s": "5e-05", "status": "endpoint_history_diverged", "reference_dt_s": "5e-05"},
            ]
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference["dt_s"], "0.0001")

        runtime_reference = _dt_convergence_reference_row(
            [
                {"moordyn_dt_s": "0.0002", "status": "endpoint_history_ok"},
                {"moordyn_dt_s": "0.0001", "status": "endpoint_history_ok"},
                {"moordyn_dt_s": "5e-05", "status": "endpoint_history_diverged"},
            ]
        )

        self.assertIsNotNone(runtime_reference)
        self.assertEqual(runtime_reference["moordyn_dt_s"], "0.0001")

    def test_dt_convergence_builder_uses_smallest_completed_replay_reference(self):
        import scripts.validate_moordyn_moorpy as validation

        def fake_endpoint_variant(moordyn, snapshot, **kwargs):
            dt_s = float(kwargs["dt_s"])
            status = "endpoint_history_diverged" if abs(dt_s - 5.0e-5) < 1.0e-12 else "endpoint_history_ok"
            return validation._row(
                model="moordyn_endpoint_history",
                status=status,
                fairlead_tension_n=1000.0 + dt_s,
                plough_tension_n=200.0 + dt_s,
                notes="fake dt replay",
                extra={
                    "moordyn_dt_s": f"{dt_s:.12g}",
                    "moordyn_completed_duration_s": "0.02",
                    "moordyn_window_start_s": "180",
                    "moordyn_window_end_s": "180.02",
                    "moordyn_max_line_tension_n": f"{1005.0 + dt_s:.12g}",
                    "moordyn_max_node_seabed_force_n": f"{75.0 + dt_s:.12g}",
                },
            )

        snapshot = validation._build_project_snapshot(
            "plough_straight_baseline_6min",
            points=7,
            endpoint_replay_duration_s=0.02,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(validation, "_optional_import", return_value=object()):
                with patch.object(validation, "_run_moordyn_endpoint_variant", fake_endpoint_variant):
                    rows = validation._build_moordyn_dt_convergence_rows(
                        snapshot,
                        output_dir=Path(tmp),
                        case_name="plough_straight_baseline_6min",
                        extra_pythonpath=(),
                        allow_global=False,
                        run_moordyn=True,
                        duration_s=0.02,
                        window_start_s=180.0,
                        sample_interval_s=0.01,
                        ramp_duration_s=0.0,
                        dt_values=(0.0002, 0.0001, 0.00005),
                    )

        rows_by_dt = {row["dt_s"]: row for row in rows}
        self.assertEqual(rows_by_dt["0.0002"]["reference_dt_s"], "0.0001")
        self.assertEqual(rows_by_dt["0.0001"]["reference_dt_s"], "0.0001")
        self.assertEqual(rows_by_dt["5e-05"]["status"], "endpoint_history_diverged")
        self.assertEqual(rows_by_dt["5e-05"]["reference_dt_s"], "0.0001")

    def test_validation_writes_fairlead_attribution_artifacts_when_enabled(self):
        from scripts.validate_moordyn_moorpy import _row, run_validation

        def fake_endpoint_history(moordyn, **kwargs):
            input_path = Path(kwargs["input_path"])
            input_text = input_path.read_text(encoding="utf-8")
            current_profile_text = (input_path.parent / "current_profile.txt").read_text(encoding="utf-8")
            drive_samples = tuple(kwargs["drive_samples"])
            current_factor = (
                -1.0
                if "current_scale=-1" in current_profile_text
                else 0.0
                if "current_scale=0" in current_profile_text
                else 1.0
            )
            friction_factor = 0.0 if "0 FrictionCoefficient" in input_text else 1.0
            contact_factor = 0.0 if "0 kBot" in input_text else 1.0
            length_delta = abs(drive_samples[-1].unstretched_length_m - drive_samples[0].unstretched_length_m)
            return _row(
                model="moordyn_endpoint_history",
                status="endpoint_history_ok",
                fairlead_tension_n=900.0 + 30.0 * current_factor + 20.0 * friction_factor + 10.0 * contact_factor + length_delta,
                plough_tension_n=100.0 + length_delta,
                notes="fake fairlead attribution replay",
                extra={
                    "moordyn_dt_s": f"{float(kwargs['dt_s']):.12g}",
                    "moordyn_duration_s": "0.02",
                    "moordyn_requested_duration_s": "0.02",
                    "moordyn_completed_duration_s": "0.02",
                    "moordyn_replay_coverage_percent": "100",
                    "moordyn_project_window_s": "360",
                    "moordyn_project_window_coverage_percent": "0.00555555555556",
                    "moordyn_last_history_time_s": "0.02",
                    "moordyn_ramp_duration_s": "0.0",
                    "moordyn_steps": "2",
                    "moordyn_init_code": "0",
                    "moordyn_init_mode": "static_zero_velocity",
                    "moordyn_initial_fairlead_tension_n": "900",
                    "moordyn_peak_fairlead_tension_n": "960",
                    "moordyn_peak_plough_tension_n": "110",
                    "moordyn_peak_line_tension_n": "950",
                    "moordyn_peak_fairlead_time_s": "0.01",
                    "moordyn_peak_plough_time_s": "0.01",
                    "moordyn_peak_line_time_s": "0.01",
                    "moordyn_max_line_tension_n": "950",
                    "moordyn_history_csv": str(kwargs["history_path"]),
                    "moordyn_node_distribution_csv": str(kwargs["node_distribution_path"]),
                    "moordyn_node_count": "3",
                    "moordyn_seabed_contact_node_count": "1",
                    "moordyn_first_seabed_contact_node": "1",
                    "moordyn_last_seabed_contact_node": "1",
                    "moordyn_max_node_seabed_force_n": "12",
                    "moordyn_max_node_seabed_force_node": "1",
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.validate_moordyn_moorpy._optional_import", return_value=object()):
                with patch("scripts.validate_moordyn_moorpy._run_moordyn_endpoint_history", fake_endpoint_history):
                    report = run_validation(
                        Path(tmp),
                        case_name="plough_straight_baseline_6min",
                        points=7,
                        extra_pythonpath=(),
                        run_moordyn=True,
                        moordyn_dt_s=0.0001,
                        moordyn_duration_s=0.02,
                        moordyn_sample_interval_s=0.01,
                        run_moordyn_fairlead_attribution=True,
                        moordyn_fairlead_attribution_duration_s=0.02,
                        moordyn_fairlead_attribution_start_s=180.0,
                    )

            attribution_path = Path(report["moordyn_fairlead_attribution_csv"])
            self.assertTrue(attribution_path.exists())
            with attribution_path.open(newline="", encoding="utf-8") as handle:
                attribution = {row["variant_id"]: row for row in csv.DictReader(handle)}

            self.assertEqual(
                set(attribution),
                {
                    "baseline",
                    "current_off",
                    "current_reversed",
                    "friction_off",
                    "contact_off",
                    "fixed_length",
                    "fixed_endpoints",
                    "frozen_geometry",
                },
            )
            self.assertEqual(attribution["fixed_endpoints"]["category"], "endpoint_motion")
            self.assertEqual(attribution["frozen_geometry"]["category"], "endpoint_motion_and_length")
            self.assertEqual(attribution["baseline"]["window_start_s"], "180")
            self.assertEqual(attribution["baseline"]["window_end_s"], "180.02")
            self.assertNotEqual(
                attribution["baseline"]["fairlead_tension_n"],
                attribution["current_off"]["fairlead_tension_n"],
            )
            self.assertNotEqual(
                attribution["current_off"]["fairlead_tension_n"],
                attribution["current_reversed"]["fairlead_tension_n"],
            )
            self.assertLess(
                abs(float(attribution["fixed_length"]["fairlead_delta_from_baseline_n"])),
                abs(float(attribution["current_off"]["fairlead_delta_from_baseline_n"])),
            )


if __name__ == "__main__":
    unittest.main()

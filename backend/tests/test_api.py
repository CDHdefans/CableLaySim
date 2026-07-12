import csv
import json
import math
import sys
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


class ApiTests(unittest.TestCase):
    def test_http_boundary_allows_and_dispatches_delete(self):
        from api.app import create_app, create_http_handler

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            created = app.handle("POST", "/api/realtime-sessions", _realtime_create_payload())
            session_id = json.loads(created.body.decode("utf-8"))["session_id"]
            server = ThreadingHTTPServer(("127.0.0.1", 0), create_http_handler(app))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                sample_url = f"{base}/api/realtime-sessions/{session_id}/samples"
                with urlopen(Request(sample_url, method="OPTIONS")) as response:
                    self.assertEqual(response.status, 204)
                    self.assertIn("DELETE", response.headers["Access-Control-Allow-Methods"])
                with urlopen(Request(f"{base}/api/realtime-sessions/{session_id}", method="DELETE")) as response:
                    self.assertEqual(response.status, 204)
                    self.assertIn("DELETE", response.headers["Access-Control-Allow-Methods"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2.0)

    def test_health_reports_ready_backend(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("GET", "/api/health")

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "cable-tension-backend")

    def test_cases_returns_named_case_inputs(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("GET", "/api/cases")

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        names = [case["name"] for case in payload["cases"]]
        self.assertIn("la_accel_200m", names)
        self.assertIn("power_current_speed_1p50", names)
        la_case = next(case for case in payload["cases"] if case["name"] == "la_accel_200m")
        power_case = next(case for case in payload["cases"] if case["name"] == "power_current_speed_1p50")
        hidden_power_case = next(case for case in payload["cases"] if case["name"] == "power_current_speed_0p50")
        self.assertEqual(la_case["group"], "LA")
        self.assertEqual(la_case["label"], "LA 信号缆｜水深 200 m")
        self.assertFalse(la_case["example"])
        self.assertEqual(la_case["inputs"]["cable"], "LA")
        self.assertEqual(la_case["inputs"]["solver_model"], "generic")
        self.assertEqual(la_case["inputs"]["water_depth_m"], 200.0)
        self.assertEqual(power_case["label"], "500kV电力缆｜水深100 m、流速1.50 m/s")
        self.assertEqual(power_case["suggested_output_dir"], "custom/500kv-standard-current-1p50")
        self.assertEqual(power_case["inputs"]["cable"], "500kV 电力缆")
        self.assertEqual(power_case["inputs"]["solver_model"], "power_500kv")
        self.assertFalse(hidden_power_case["example"])

    def test_run_case_writes_outputs_and_returns_artifact_paths(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-case",
                {"case_name": "ha_accel_200m", "points": 17},
            )
            payload = json.loads(response.body.decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["case_name"], "ha_accel_200m")
            self.assertGreater(payload["summary"]["top_tension_final_n"], 0.0)
            self.assertEqual(payload["artifacts"]["summary_csv"], "ha_accel_200m/summary.csv")
            self.assertTrue((Path(tmp) / payload["artifacts"]["profile_svg"]).exists())

            file_response = app.handle("GET", f"/api/files/{payload['artifacts']['profile_svg']}")

        self.assertEqual(file_response.status, 200)
        self.assertIn(b"<svg", file_response.body)
        self.assertEqual(file_response.headers["Content-Type"], "image/svg+xml; charset=utf-8")

    def test_theory_report_serves_html_and_relative_assets(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            report_root = output_root / "theory_formula_report"
            (report_root / "article_figures").mkdir(parents=True)
            (report_root / "theory_formula_report.html").write_text(
                '<!doctype html><meta charset="utf-8"><img src="article_figures/fig.png">',
                encoding="utf-8",
            )
            (report_root / "article_figures" / "fig.png").write_bytes(b"png")
            app = create_app(output_root=output_root)

            html_response = app.handle("GET", "/theory_formula_report.html")
            image_response = app.handle("GET", "/article_figures/fig.png")

        self.assertEqual(html_response.status, 200)
        self.assertEqual(html_response.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("article_figures/fig.png", html_response.body.decode("utf-8"))
        self.assertEqual(image_response.status, 200)
        self.assertEqual(image_response.body, b"png")

    def test_run_case_returns_plot_data_for_frontend_figures(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-case",
                {"case_name": "ha_accel_200m", "points": 11},
            )

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("plot_data", payload)
        profile = payload["plot_data"]["profile"]
        time_history = payload["plot_data"]["time_history"]["points"]

        self.assertEqual(len(profile), 11)
        self.assertEqual(
            set(profile[0]),
            {
                "index",
                "arc_m",
                "x_m",
                "y_m",
                "z_m",
                "theta_rad",
                "psi_rad",
                "tangent_x",
                "tangent_y",
                "tangent_z",
                "current_x_mps",
                "current_y_mps",
                "current_z_mps",
                "drag_x_n_per_m",
                "drag_y_n_per_m",
                "drag_z_n_per_m",
                "tension_n",
            },
        )
        self.assertGreater(profile[-1]["z_m"], profile[0]["z_m"])
        self.assertGreaterEqual(profile[0]["tension_n"], profile[-1]["tension_n"])
        self.assertGreaterEqual(len(time_history), 2)
        self.assertEqual(
            set(time_history[0]),
            {"time_s", "top_tension_n", "tdp_x_m", "tdp_y_m"},
        )
        self.assertEqual(time_history[0]["time_s"], 0.0)

    def test_run_time_history_returns_dynamic_plot_data_and_artifacts(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            cases_response = app.handle("GET", "/api/time-history-cases")
            run_response = app.handle(
                "POST",
                "/api/run-time-history",
                {"case_name": "plough_straight_baseline_6min", "points": 31},
            )
            payload = json.loads(run_response.body.decode("utf-8"))

            self.assertEqual(cases_response.status, 200)
            cases = json.loads(cases_response.body.decode("utf-8"))["cases"]
            self.assertEqual(
                [case["name"] for case in cases],
                [
                    "plough_straight_baseline_6min",
                    "plough_straight_low_speed_6min",
                    "plough_straight_high_speed_6min",
                    "plough_straight_low_tdp_tension_6min",
                    "plough_straight_high_tdp_tension_6min",
                    "plough_cross_current_0p50_90deg_6min",
                    "plough_cross_current_0p95_90deg_6min",
                    "plough_cross_current_0p95_60deg_6min",
                    "plough_cross_current_0p95_30deg_6min",
                    "plough_cross_current_0p95_0deg_6min",
                    "plough_decel_mild_6min",
                    "plough_decel_strong_6min",
                    "plough_decel_long_6min",
                    "plough_payout_matched_6min",
                    "plough_payout_fast_1p10_6min",
                    "plough_payout_fast_1p25_6min",
                    "plough_material_la_6min",
                    "plough_material_ha_6min",
                    "plough_material_power_500kv_6min",
                ],
            )
            visible_dynamic_cases = sorted(
                [case for case in cases if case["example"]],
                key=lambda case: case["display_order"],
            )
            self.assertEqual(len(visible_dynamic_cases), 19)
            self.assertEqual(
                sorted({case["group"] for case in visible_dynamic_cases}),
                ["信号缆与电力缆", "常规直线铺埋", "控速减速", "放缆偏快", "横流偏载"],
            )
            self.assertEqual(
                [case["label"] for case in visible_dynamic_cases[:3]],
                ["常规基准", "低速铺埋", "高速铺埋"],
            )
            for case in visible_dynamic_cases:
                self.assertEqual(case["inputs"]["length_boundary_source"], "known_plough_trajectory")
                self.assertEqual(case["inputs"]["total_duration_s"], 360.0)
                self.assertEqual(case["inputs"]["water_depth_m"], 80.0)
                self.assertEqual(case["inputs"]["element_count"], 24)
            known_plough_case = next(case for case in cases if case["name"] == "plough_straight_baseline_6min")
            self.assertEqual(known_plough_case["inputs"]["speed_change"], "steady")
            self.assertEqual(known_plough_case["inputs"]["current_direction_deg"], 90.0)
            self.assertAlmostEqual(known_plough_case["inputs"]["diameter_m"], 0.0264)
            self.assertAlmostEqual(known_plough_case["inputs"]["weight_air_n_per_m"], 16.09)
            self.assertAlmostEqual(known_plough_case["inputs"]["submerged_weight_n_per_m"], 10.59)
            self.assertAlmostEqual(known_plough_case["inputs"]["tangential_drag_coefficient"], 0.01)
            self.assertAlmostEqual(known_plough_case["inputs"]["normal_drag_coefficient"], 2.12)
            self.assertAlmostEqual(known_plough_case["inputs"]["axial_stiffness_n"], 1.0e9)
            self.assertEqual(known_plough_case["inputs"]["plough_initial_x_m"], -55.0)
            self.assertEqual(known_plough_case["inputs"]["plough_initial_y_m"], 0.0)
            self.assertEqual(known_plough_case["inputs"]["plough_speed_mps"], 0.75)
            by_name = {case["name"]: case for case in visible_dynamic_cases}
            self.assertEqual(by_name["plough_straight_low_tdp_tension_6min"]["inputs"]["touchdown_tension_n"], 100.0)
            self.assertEqual(by_name["plough_straight_high_tdp_tension_6min"]["inputs"]["touchdown_tension_n"], 400.0)
            self.assertEqual(by_name["plough_cross_current_0p95_60deg_6min"]["inputs"]["current_direction_deg"], 60.0)
            self.assertEqual(by_name["plough_cross_current_0p95_30deg_6min"]["inputs"]["current_direction_deg"], 30.0)
            self.assertEqual(by_name["plough_cross_current_0p95_0deg_6min"]["inputs"]["current_direction_deg"], 0.0)
            self.assertEqual(by_name["plough_decel_strong_6min"]["inputs"]["speed_change"], "decel")
            self.assertEqual(by_name["plough_decel_strong_6min"]["inputs"]["duration_s"], 90.0)
            self.assertEqual(by_name["plough_payout_fast_1p25_6min"]["inputs"]["payout_initial_speed_mps"], 1.0)
            self.assertEqual(by_name["plough_payout_fast_1p25_6min"]["inputs"]["plough_speed_mps"], 0.8)
            self.assertAlmostEqual(by_name["plough_material_ha_6min"]["inputs"]["diameter_m"], 0.0332)
            self.assertAlmostEqual(by_name["plough_material_ha_6min"]["inputs"]["submerged_weight_n_per_m"], 17.80)
            self.assertAlmostEqual(by_name["plough_material_power_500kv_6min"]["inputs"]["diameter_m"], 0.139)
            self.assertEqual(by_name["plough_material_la_6min"]["label"], "LA 信号缆")
            self.assertEqual(by_name["plough_material_ha_6min"]["label"], "HA 信号缆")
            self.assertEqual(by_name["plough_material_power_500kv_6min"]["label"], "500 kV 电力缆")
            self.assertAlmostEqual(
                by_name["plough_material_power_500kv_6min"]["inputs"]["submerged_weight_n_per_m"],
                32.0 * 9.8,
            )
            self.assertEqual(by_name["plough_material_power_500kv_6min"]["inputs"]["min_bending_radius_m"], 5.0)
            self.assertEqual(run_response.status, 200)
            self.assertEqual(payload["case_name"], "plough_straight_baseline_6min")
            self.assertEqual(payload["summary"]["speed_change"], "steady")
            self.assertEqual(payload["summary"]["duration_s"], 360.0)
            self.assertEqual(payload["summary"]["total_duration_s"], 360.0)
            self.assertEqual(payload["summary"]["payout_initial_speed_mps"], 0.88)
            self.assertEqual(payload["summary"]["payout_final_speed_mps"], 0.88)
            self.assertAlmostEqual(payload["summary"]["integration_time_step_max_s"], 0.05)
            self.assertGreater(payload["summary"]["spatial_step_min_m"], 0.0)
            self.assertGreaterEqual(payload["summary"]["xpbd_iterations_per_step"], 20)
            self.assertLessEqual(payload["summary"]["xpbd_iterations_per_step"], 100)
            self.assertEqual(
                payload["summary"]["xpbd_iterations_per_step"],
                payload["summary"]["xpbd_iterations_per_step_max"],
            )
            self.assertGreaterEqual(payload["summary"]["xpbd_iterations_per_step_min"], 1)
            self.assertEqual(payload["summary"]["xpbd_iteration_limit_per_solve"], 100)
            self.assertLessEqual(payload["summary"]["axial_constraint_residual_max_m"], 1.0e-10)
            self.assertEqual(payload["summary"]["length_boundary_source"], "known_plough_trajectory")
            self.assertGreater(payload["summary"]["initial_suspended_length_m"], 0.0)
            self.assertIn("geometric_length_deficit_max_m", payload["summary"])
            self.assertIn("geometric_length_deficit_final_m", payload["summary"])
            self.assertIn("plough_boundary_tension_final_n", payload["summary"])
            self.assertIn("plough_adjacent_segment_tension_final_n", payload["summary"])
            self.assertIn("plough_tension_status", payload["summary"])
            self.assertIn("known plough trajectory", payload["summary"]["evidence_level"])
            self.assertEqual(payload["plot_data"]["time_history"]["source"], "la_dynamic_xpbd_node_state")
            self.assertEqual(payload["plot_data"]["time_history"]["points"][0]["time_s"], 0.0)
            self.assertEqual(len(payload["plot_data"]["time_history"]["points"]), 31)
            self.assertIn("suspended_length_m", payload["plot_data"]["time_history"]["points"][0])
            self.assertIn("iterations", payload["plot_data"]["time_history"]["points"][0])
            self.assertIn("plough_boundary_tension_n", payload["plot_data"]["time_history"]["points"][0])
            self.assertIn("plough_adjacent_segment_tension_n", payload["plot_data"]["time_history"]["points"][0])
            self.assertIn("material_suspended_length_m", payload["plot_data"]["time_history"]["points"][0])
            self.assertIn("geometric_length_deficit_m", payload["plot_data"]["time_history"]["points"][0])
            self.assertEqual(payload["plot_data"]["frames"]["source"], "la_dynamic_xpbd_frames")
            self.assertEqual(len(payload["plot_data"]["frames"]["items"]), 31)
            first_frame = payload["plot_data"]["frames"]["items"][0]
            self.assertEqual(first_frame["time_s"], payload["plot_data"]["time_history"]["points"][0]["time_s"])
            self.assertEqual(len(first_frame["points"]), payload["summary"]["element_count"] + 1)
            self.assertEqual(len(first_frame["segment_tensions_n"]), payload["summary"]["element_count"])
            self.assertEqual(
                set(first_frame["points"][0]),
                {"index", "x_m", "y_m", "z_m", "tension_n"},
            )
            self.assertEqual(first_frame["points"][0]["z_m"], 0.0)
            self.assertAlmostEqual(first_frame["points"][-1]["z_m"], first_frame["plough_z_m"])
            self.assertGreater(payload["summary"]["initial_tension_n"], 0.0)
            self.assertEqual(
                payload["artifacts"]["time_history_csv"],
                "time_histories/plough_straight_baseline_6min/time_history.csv",
            )
            self.assertTrue((Path(tmp) / payload["artifacts"]["time_history_svg"]).exists())

    def test_named_time_history_rejects_removed_demo_case(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-time-history",
                {"case_name": "known_plough_boundary_demo", "points": 31},
            )

        self.assertEqual(response.status, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "unknown_time_history_case")

    def test_run_time_history_accepts_operator_dynamic_inputs(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-time-history",
                _known_plough_payload(
                    case_name="operator_dynamic",
                    output_dir="time_histories/known-plough-operator-check",
                    points=9,
                    current_speed_mps=1.25,
                    current_direction_deg=60.0,
                    water_depth_m=90.0,
                    element_count=8,
                    plough_initial_z_m=88.0,
                ),
            )
            payload = json.loads(response.body.decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["case_name"], "operator_dynamic")
            self.assertEqual(payload["summary"]["current_speed_mps"], 1.25)
            self.assertEqual(payload["summary"]["current_direction_deg"], 60.0)
            self.assertEqual(payload["summary"]["initial_speed_mps"], 0.8)
            self.assertEqual(payload["summary"]["final_speed_mps"], 1.0)
            self.assertEqual(payload["summary"]["payout_initial_speed_mps"], 1.05)
            self.assertEqual(payload["summary"]["payout_final_speed_mps"], 1.15)
            self.assertEqual(payload["summary"]["length_boundary_source"], "known_plough_trajectory")
            self.assertIn("known plough trajectory", payload["summary"]["evidence_level"])
            self.assertEqual(payload["summary"]["duration_s"], 10.0)
            self.assertEqual(payload["summary"]["total_duration_s"], 20.0)
            self.assertEqual(payload["summary"]["water_depth_m"], 90.0)
            self.assertEqual(payload["summary"]["element_count"], 8)
            self.assertEqual(payload["summary"]["touchdown_tension_n"], 200.0)
            self.assertEqual(payload["summary"]["diameter_m"], 0.0264)
            self.assertEqual(payload["summary"]["submerged_weight_n_per_m"], 10.59)
            self.assertEqual(payload["summary"]["normal_drag_coefficient"], 2.12)
            self.assertEqual(len(payload["plot_data"]["time_history"]["points"]), 9)
            self.assertEqual(len(payload["plot_data"]["frames"]["items"]), 9)
            self.assertEqual(len(payload["plot_data"]["frames"]["items"][0]["points"]), 9)
            self.assertEqual(len(payload["plot_data"]["frames"]["items"][0]["segment_tensions_n"]), 8)
            self.assertEqual(
                payload["artifacts"]["time_history_csv"],
                "time_histories/known-plough-operator-check/time_history.csv",
            )
            self.assertTrue((Path(tmp) / payload["artifacts"]["time_history_csv"]).exists())

    def test_known_plough_inputs_drive_boundary_positions_and_tension(self):
        from api.app import create_app

        base_payload = _known_plough_payload(output_dir="time_histories/known-plough-input-check-a")
        changed_payload = {
            **base_payload,
            "output_dir": "time_histories/known-plough-input-check-b",
            "current_speed_mps": 1.1,
            "final_speed_mps": 1.4,
            "plough_speed_mps": 1.05,
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            first_response = app.handle("POST", "/api/run-time-history", base_payload)
            second_response = app.handle("POST", "/api/run-time-history", changed_payload)

        self.assertEqual(first_response.status, 200)
        self.assertEqual(second_response.status, 200)
        first = json.loads(first_response.body.decode("utf-8"))
        second = json.loads(second_response.body.decode("utf-8"))
        self.assertEqual(first["case_name"], second["case_name"])
        self.assertNotAlmostEqual(
            first["plot_data"]["frames"]["items"][-1]["vessel_x_m"],
            second["plot_data"]["frames"]["items"][-1]["vessel_x_m"],
        )
        self.assertNotAlmostEqual(
            first["plot_data"]["frames"]["items"][-1]["plough_x_m"],
            second["plot_data"]["frames"]["items"][-1]["plough_x_m"],
        )
        self.assertNotAlmostEqual(
            first["summary"]["plough_inlet_tension_final_n"],
            second["summary"]["plough_inlet_tension_final_n"],
        )

    def test_known_plough_payout_and_current_inputs_change_outputs(self):
        from api.app import create_app

        base_payload = _known_plough_payload(output_dir="time_histories/known-plough-payout-check-a")
        faster_payout = {
            **base_payload,
            "output_dir": "time_histories/known-plough-payout-check-b",
            "payout_initial_speed_mps": 1.4,
            "payout_final_speed_mps": 1.7,
            "current_speed_mps": 1.2,
            "current_direction_deg": 45.0,
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            base_response = app.handle("POST", "/api/run-time-history", base_payload)
            payout_response = app.handle("POST", "/api/run-time-history", faster_payout)

        self.assertEqual(base_response.status, 200)
        self.assertEqual(payout_response.status, 200)
        base = json.loads(base_response.body.decode("utf-8"))
        changed = json.loads(payout_response.body.decode("utf-8"))

        self.assertNotAlmostEqual(
            base["plot_data"]["time_history"]["points"][-1]["suspended_length_m"],
            changed["plot_data"]["time_history"]["points"][-1]["suspended_length_m"],
        )
        self.assertNotAlmostEqual(
            base["summary"]["plough_inlet_tension_final_n"],
            changed["summary"]["plough_inlet_tension_final_n"],
        )

    def test_known_plough_exit_material_speed_changes_material_length_and_tension(self):
        from api.app import create_app

        inferred_payload = _known_plough_payload(output_dir="time_histories/known-plough-exit-inferred")
        measured_payload = {
            **inferred_payload,
            "output_dir": "time_histories/known-plough-exit-measured",
            "plough_exit_speed_mps": 0.2,
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            inferred_response = app.handle("POST", "/api/run-time-history", inferred_payload)
            measured_response = app.handle("POST", "/api/run-time-history", measured_payload)
            inferred_summary_path = Path(tmp) / "time_histories/known-plough-exit-inferred/time_summary.csv"
            measured_summary_path = Path(tmp) / "time_histories/known-plough-exit-measured/time_summary.csv"
            with inferred_summary_path.open(newline="", encoding="utf-8") as handle:
                inferred_summary_row = next(csv.DictReader(handle))
            with measured_summary_path.open(newline="", encoding="utf-8") as handle:
                measured_summary_row = next(csv.DictReader(handle))

        self.assertEqual(inferred_response.status, 200)
        self.assertEqual(measured_response.status, 200)
        inferred = json.loads(inferred_response.body.decode("utf-8"))
        measured = json.loads(measured_response.body.decode("utf-8"))

        self.assertEqual(inferred["summary"]["plough_exit_speed_source"], "no_slip_inferred")
        self.assertEqual(measured["summary"]["plough_exit_speed_source"], "measured")
        self.assertAlmostEqual(measured["summary"]["plough_exit_speed_mps"], 0.2)
        self.assertEqual(inferred_summary_row["plough_exit_speed_source"], "no_slip_inferred")
        self.assertEqual(measured_summary_row["plough_exit_speed_mps"], "0.200000")
        self.assertEqual(measured_summary_row["plough_exit_speed_source"], "measured")
        self.assertNotAlmostEqual(
            inferred["plot_data"]["time_history"]["points"][-1]["material_suspended_length_m"],
            measured["plot_data"]["time_history"]["points"][-1]["material_suspended_length_m"],
        )
        self.assertNotAlmostEqual(
            inferred["summary"]["plough_inlet_tension_final_n"],
            measured["summary"]["plough_inlet_tension_final_n"],
        )

    def test_known_plough_rejects_negative_exit_material_speed(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-time-history",
                _known_plough_payload(plough_exit_speed_mps=-0.1),
            )

        self.assertEqual(response.status, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "invalid_input")
        self.assertEqual(payload["details"]["fields"]["plough_exit_speed_mps"], "must be greater than or equal to 0")

    def test_known_plough_rejects_nonlongitudinal_or_sampled_fallback_without_exit_speed(self):
        from api.app import create_app

        transverse_payload = _known_plough_payload(
            plough_motion_segments=[
                {"duration_s": 20.0, "start_speed_mps": 0.75, "end_speed_mps": 0.75, "heading_deg": 90.0}
            ]
        )
        sampled_payload = _known_plough_payload(
            plough_initial_x_m=None,
            plough_initial_y_m=None,
            plough_initial_z_m=None,
            plough_speed_mps=None,
            plough_heading_deg=None,
            plough_motion_samples=[
                {"time_s": 0.0, "x_m": -55.0, "y_m": 0.0, "z_m": 78.0},
                {"time_s": 20.0, "x_m": -40.0, "y_m": 4.0, "z_m": 78.0},
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            transverse_response = app.handle("POST", "/api/run-time-history", transverse_payload)
            sampled_response = app.handle("POST", "/api/run-time-history", sampled_payload)

        for response in (transverse_response, sampled_response):
            self.assertEqual(response.status, 400)
            payload = json.loads(response.body.decode("utf-8"))
            self.assertEqual(payload["error"], "invalid_input")
            self.assertIn("plough_exit_speed_mps", payload["details"]["fields"])

    def test_known_plough_segmented_motion_inputs_drive_xy_boundaries(self):
        from api.app import create_app

        segmented_payload = _known_plough_payload(
            output_dir="time_histories/known-plough-segmented-motion",
            points=5,
            total_duration_s=20.0,
            duration_s=10.0,
            plough_exit_speed_mps=0.8,
            vessel_motion_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.8, "end_speed_mps": 1.2, "heading_deg": 0.0},
                {"duration_s": 10.0, "start_speed_mps": 1.2, "end_speed_mps": 1.2, "heading_deg": 90.0},
            ],
            plough_motion_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.6, "end_speed_mps": 0.8, "heading_deg": 0.0},
                {"duration_s": 10.0, "start_speed_mps": 0.8, "end_speed_mps": 0.8, "heading_deg": 90.0},
            ],
            payout_speed_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.9, "end_speed_mps": 1.1},
                {"duration_s": 10.0, "start_speed_mps": 1.1, "end_speed_mps": 1.1},
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", segmented_payload)

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        final_frame = payload["plot_data"]["frames"]["items"][-1]

        self.assertAlmostEqual(final_frame["vessel_x_m"], 10.0, delta=0.75)
        self.assertAlmostEqual(final_frame["vessel_y_m"], 12.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_x_m"], -48.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_y_m"], 8.0, delta=0.75)
        self.assertEqual(payload["summary"]["vessel_motion_segments"][1]["heading_deg"], 90.0)
        self.assertEqual(payload["summary"]["plough_motion_segments"][1]["end_speed_mps"], 0.8)
        self.assertEqual(payload["summary"]["payout_speed_segments"][1]["start_speed_mps"], 1.1)

    def test_known_plough_total_duration_truncates_without_compressing_motion_segment(self):
        from api.app import create_app

        payload = _known_plough_payload(
            output_dir="time_histories/known-plough-truncated-segment",
            points=3,
            total_duration_s=5.0,
            duration_s=5.0,
            plough_exit_speed_mps=0.7,
            vessel_motion_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.8, "end_speed_mps": 1.2, "heading_deg": 0.0},
            ],
            plough_motion_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.6, "end_speed_mps": 0.8, "heading_deg": 0.0},
            ],
            payout_speed_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.9, "end_speed_mps": 1.1},
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 200)
        result = json.loads(response.body.decode("utf-8"))
        final_frame = result["plot_data"]["frames"]["items"][-1]
        self.assertAlmostEqual(final_frame["vessel_x_m"], 4.5, delta=0.2)
        self.assertAlmostEqual(final_frame["plough_x_m"], -51.75, delta=0.2)
        self.assertEqual(result["summary"]["vessel_motion_segments"][0]["duration_s"], 10.0)

    def test_known_plough_accepts_measured_xy_motion_segment_velocities(self):
        from api.app import create_app

        vector_payload = _known_plough_payload(
            output_dir="time_histories/known-plough-vector-motion",
            points=3,
            total_duration_s=10.0,
            duration_s=10.0,
            plough_exit_speed_mps=0.5,
            vessel_motion_segments=[
                {
                    "duration_s": 10.0,
                    "start_speed_mps": 99.0,
                    "end_speed_mps": 99.0,
                    "heading_deg": 180.0,
                    "start_velocity_x_mps": 1.0,
                    "start_velocity_y_mps": 2.0,
                    "end_velocity_x_mps": 1.0,
                    "end_velocity_y_mps": 2.0,
                }
            ],
            plough_motion_segments=[
                {
                    "duration_s": 10.0,
                    "start_speed_mps": 99.0,
                    "end_speed_mps": 99.0,
                    "heading_deg": 180.0,
                    "start_velocity_x_mps": 0.5,
                    "start_velocity_y_mps": 1.0,
                    "end_velocity_x_mps": 0.5,
                    "end_velocity_y_mps": 1.0,
                }
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", vector_payload)

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        final_frame = payload["plot_data"]["frames"]["items"][-1]

        self.assertAlmostEqual(final_frame["vessel_x_m"], 10.0, delta=0.75)
        self.assertAlmostEqual(final_frame["vessel_y_m"], 20.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_x_m"], -50.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_y_m"], 10.0, delta=0.75)
        segment = payload["summary"]["vessel_motion_segments"][0]
        self.assertAlmostEqual(segment["start_speed_mps"], 5.0 ** 0.5)
        self.assertAlmostEqual(segment["end_speed_mps"], 5.0 ** 0.5)
        self.assertAlmostEqual(segment["heading_deg"], 63.43494882292201)
        self.assertEqual(segment["start_velocity_x_mps"], 1.0)
        self.assertEqual(segment["end_velocity_y_mps"], 2.0)

    def test_known_plough_accepts_measured_xy_motion_segments_without_heading_fallback(self):
        from api.app import create_app

        vector_payload = _known_plough_payload(
            output_dir="time_histories/known-plough-vector-only-motion",
            points=3,
            total_duration_s=10.0,
            duration_s=10.0,
            plough_exit_speed_mps=0.55,
            vessel_motion_segments=[
                {
                    "duration_s": 10.0,
                    "start_velocity_x_mps": 1.0,
                    "start_velocity_y_mps": 2.0,
                    "end_velocity_x_mps": 1.0,
                    "end_velocity_y_mps": 2.0,
                }
            ],
            plough_motion_segments=[
                {
                    "duration_s": 10.0,
                    "start_velocity_x_mps": 0.5,
                    "start_velocity_y_mps": 1.0,
                    "end_velocity_x_mps": 0.5,
                    "end_velocity_y_mps": 1.0,
                }
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", vector_payload)

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        final_frame = payload["plot_data"]["frames"]["items"][-1]

        self.assertAlmostEqual(final_frame["vessel_x_m"], 10.0, delta=0.75)
        self.assertAlmostEqual(final_frame["vessel_y_m"], 20.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_x_m"], -50.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_y_m"], 10.0, delta=0.75)
        segment = payload["summary"]["vessel_motion_segments"][0]
        self.assertAlmostEqual(segment["start_speed_mps"], 5.0 ** 0.5)
        self.assertAlmostEqual(segment["heading_deg"], 63.43494882292201)
        self.assertEqual(payload["summary"]["plough_exit_speed_source"], "measured")

    def test_known_plough_accepts_measured_endpoint_motion_samples_as_boundary(self):
        from api.app import create_app

        sample_payload = _known_plough_payload(
            output_dir="time_histories/known-plough-sampled-motion",
            points=3,
            total_duration_s=10.0,
            duration_s=10.0,
            plough_initial_x_m=None,
            plough_initial_y_m=None,
            plough_initial_z_m=None,
            plough_speed_mps=None,
            plough_heading_deg=None,
            plough_exit_speed_mps=0.55,
            vessel_motion_segments=[
                {
                    "duration_s": 10.0,
                    "start_velocity_x_mps": 100.0,
                    "start_velocity_y_mps": 100.0,
                    "end_velocity_x_mps": 100.0,
                    "end_velocity_y_mps": 100.0,
                }
            ],
            vessel_motion_samples=[
                {"time_s": 0.0, "x_m": 0.0, "y_m": 0.0, "velocity_x_mps": 1.2, "velocity_y_mps": 0.4},
                {"time_s": 10.0, "x_m": 12.0, "y_m": 4.0, "velocity_x_mps": 1.2, "velocity_y_mps": 0.4},
            ],
            plough_motion_samples=[
                {"time_s": 0.0, "x_m": -55.0, "y_m": 0.0, "z_m": 78.0},
                {"time_s": 10.0, "x_m": -45.0, "y_m": 6.0, "z_m": 78.0},
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", sample_payload)

        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        final_frame = payload["plot_data"]["frames"]["items"][-1]

        self.assertAlmostEqual(final_frame["vessel_x_m"], 12.0, delta=0.75)
        self.assertAlmostEqual(final_frame["vessel_y_m"], 4.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_x_m"], -45.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_y_m"], 6.0, delta=0.75)
        self.assertAlmostEqual(final_frame["plough_z_m"], 78.0, delta=1.0e-9)
        self.assertEqual(payload["summary"]["vessel_motion_samples"][1]["x_m"], 12.0)
        self.assertEqual(payload["summary"]["plough_motion_samples"][0]["z_m"], 78.0)
        self.assertEqual(payload["summary"]["plough_exit_speed_source"], "measured")
        self.assertIn("plough_inlet_tension_final_n", payload["summary"])
        self.assertIn("minimum_bend_radius_status", payload["summary"])

    def test_operator_payload_accepts_empty_optional_dynamic_arrays(self):
        from api.app import create_app

        payload = _known_plough_payload(
            output_dir="time_histories/known-plough-empty-optional-arrays",
            points=3,
            total_duration_s=1.0,
            duration_s=1.0,
            vessel_motion_segments=[],
            plough_motion_segments=[],
            vessel_motion_samples=[],
            plough_motion_samples=[],
            payout_speed_segments=[],
        )

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 200)

    def test_motion_samples_reject_invalid_optional_numeric_fields(self):
        from api.app import create_app

        for field in ("z_m", "velocity_x_mps", "velocity_y_mps", "velocity_z_mps"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                sample = {"time_s": 0.0, "x_m": 0.0, "y_m": 0.0, field: "not-a-number"}
                payload = _known_plough_payload(
                    output_dir=f"time_histories/invalid-motion-sample-{field}",
                    points=3,
                    total_duration_s=1.0,
                    duration_s=1.0,
                    plough_exit_speed_mps=0.75,
                    vessel_motion_samples=[sample],
                )
                app = create_app(output_root=Path(tmp))
                response = app.handle("POST", "/api/run-time-history", payload)

                self.assertEqual(response.status, 400)
                result = json.loads(response.body.decode("utf-8"))
                self.assertEqual(result["error"], "invalid_input")
                self.assertIn(
                    f"vessel_motion_samples[0].{field}",
                    result["details"]["fields"],
                )

    def test_known_plough_segmented_payout_changes_dynamic_outputs(self):
        from api.app import create_app

        base_payload = _known_plough_payload(
            output_dir="time_histories/known-plough-segmented-payout-a",
            payout_speed_segments=[
                {"duration_s": 10.0, "start_speed_mps": 0.9, "end_speed_mps": 1.0},
                {"duration_s": 10.0, "start_speed_mps": 1.0, "end_speed_mps": 1.0},
            ],
        )
        faster_payout = {
            **base_payload,
            "output_dir": "time_histories/known-plough-segmented-payout-b",
            "payout_speed_segments": [
                {"duration_s": 10.0, "start_speed_mps": 1.2, "end_speed_mps": 1.4},
                {"duration_s": 10.0, "start_speed_mps": 1.4, "end_speed_mps": 1.4},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            base_response = app.handle("POST", "/api/run-time-history", base_payload)
            changed_response = app.handle("POST", "/api/run-time-history", faster_payout)

        self.assertEqual(base_response.status, 200)
        self.assertEqual(changed_response.status, 200)
        base = json.loads(base_response.body.decode("utf-8"))
        changed = json.loads(changed_response.body.decode("utf-8"))

        self.assertEqual(changed["summary"]["payout_speed_segments"][1]["end_speed_mps"], 1.4)
        self.assertNotAlmostEqual(
            base["plot_data"]["time_history"]["points"][-1]["suspended_length_m"],
            changed["plot_data"]["time_history"]["points"][-1]["suspended_length_m"],
        )
        self.assertNotAlmostEqual(
            base["summary"]["plough_inlet_tension_final_n"],
            changed["summary"]["plough_inlet_tension_final_n"],
        )

    def test_known_plough_rejects_malformed_signed_coordinates_as_structured_error(self):
        from api.app import create_app

        payload = _known_plough_payload(vessel_initial_x_m="not-a-number")

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 400)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("vessel_initial_x_m", result["details"]["fields"])

    def test_known_plough_material_inputs_change_outputs(self):
        from api.app import create_app

        base_payload = _known_plough_payload(output_dir="time_histories/known-plough-material-check-a")
        heavier_cable = {
            **base_payload,
            "output_dir": "time_histories/known-plough-material-check-b",
            "diameter_m": 0.0528,
            "weight_air_n_per_m": 32.18,
            "submerged_weight_n_per_m": 21.18,
            "normal_drag_coefficient": 3.0,
            "axial_stiffness_n": 5.0e8,
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            base_response = app.handle("POST", "/api/run-time-history", base_payload)
            changed_response = app.handle("POST", "/api/run-time-history", heavier_cable)

        self.assertEqual(base_response.status, 200)
        self.assertEqual(changed_response.status, 200)
        base = json.loads(base_response.body.decode("utf-8"))
        changed = json.loads(changed_response.body.decode("utf-8"))

        self.assertEqual(changed["summary"]["diameter_m"], 0.0528)
        self.assertEqual(changed["summary"]["submerged_weight_n_per_m"], 21.18)
        self.assertNotAlmostEqual(
            base["summary"]["plough_inlet_tension_final_n"],
            changed["summary"]["plough_inlet_tension_final_n"],
        )

    def test_run_time_history_accepts_known_plough_boundary_inputs(self):
        from api.app import create_app

        payload = _known_plough_payload()

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 200)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["summary"]["length_boundary_source"], "known_plough_trajectory")
        self.assertEqual(result["summary"]["initial_suspended_length_m"], payload["initial_suspended_length_m"])
        self.assertEqual(result["summary"]["plough_speed_mps"], 0.75)
        self.assertGreater(result["summary"]["plough_inlet_tension_final_n"], 0.0)
        self.assertGreater(result["summary"]["minimum_bend_radius_min_m"], 0.0)
        self.assertEqual(result["summary"]["minimum_bend_radius_excluded_tail_nodes"], 2)
        self.assertLessEqual(
            result["summary"]["minimum_bend_radius_raw_m"],
            result["summary"]["minimum_bend_radius_min_m"],
        )
        first_point = result["plot_data"]["time_history"]["points"][0]
        self.assertIn("plough_inlet_tension_n", first_point)
        self.assertIn("plough_entry_angle_deg", first_point)
        self.assertIn("minimum_bend_radius_raw_m", first_point)
        self.assertIn("minimum_bend_radius_excluded_tail_nodes", first_point)
        self.assertIn("tdp_arc_length_m", first_point)
        self.assertIn("free_span_material_length_m", first_point)
        self.assertIn("seabed_contact_length_m", first_point)
        self.assertIn("seabed_normal_reaction_n", first_point)
        self.assertAlmostEqual(
            first_point["free_span_material_length_m"] + first_point["seabed_contact_length_m"],
            first_point["material_suspended_length_m"],
        )
        first_frame = result["plot_data"]["frames"]["items"][0]
        last_frame = result["plot_data"]["frames"]["items"][-1]
        self.assertEqual(first_frame["boundary"], "known_plough_trajectory")
        self.assertEqual(len(first_frame["segment_tensions_n"]), payload["element_count"])
        self.assertIn("minimum_bend_radius_left_segment_m", first_frame)
        self.assertIn("minimum_bend_radius_right_segment_m", first_frame)
        self.assertIn("minimum_bend_radius_node_depth_m", first_frame)
        self.assertIn("minimum_bend_radius_near_seabed", first_frame)
        self.assertIn("minimum_bend_radius_raw_m", first_frame)
        self.assertIn("minimum_bend_radius_excluded_tail_nodes", first_frame)
        self.assertAlmostEqual(first_frame["plough_x_m"], -55.0)
        self.assertAlmostEqual(first_frame["plough_y_m"], 0.0)
        self.assertAlmostEqual(last_frame["plough_x_m"], -40.0)
        self.assertAlmostEqual(last_frame["plough_y_m"], 0.0)
        self.assertAlmostEqual(last_frame["points"][-1]["x_m"], last_frame["plough_x_m"])

    def test_run_time_history_accepts_dynamic_minimum_bend_radius_limit(self):
        from api.app import create_app

        payload = _known_plough_payload(min_bending_radius_m=8.0)

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 200)
        result = json.loads(response.body.decode("utf-8"))
        summary = result["summary"]
        self.assertEqual(summary["minimum_bend_radius_limit_m"], 8.0)
        self.assertAlmostEqual(
            summary["minimum_bend_radius_margin_m"],
            summary["minimum_bend_radius_min_m"] - 8.0,
        )
        self.assertIn(summary["minimum_bend_radius_status"], {"ok", "below_limit"})

    def test_realtime_session_lifecycle_returns_latest_frame_without_artifacts(self):
        from api.app import create_app

        create_payload = _realtime_create_payload()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = create_app(output_root=root)
            created = app.handle("POST", "/api/realtime-sessions", create_payload)
            self.assertEqual(created.status, 201)
            created_payload = json.loads(created.body.decode("utf-8"))
            session_id = created_payload["session_id"]
            self.assertEqual(created_payload["sequence"], 0)
            self.assertEqual(created_payload["time_s"], 0.0)
            self.assertGreater(len(created_payload["frame"]["points"]), 2)

            advanced = app.handle(
                "POST",
                f"/api/realtime-sessions/{session_id}/samples",
                _realtime_packet_payload(1, 1.0),
            )
            self.assertEqual(advanced.status, 200)
            advanced_payload = json.loads(advanced.body.decode("utf-8"))
            self.assertEqual(advanced_payload["sequence"], 1)
            self.assertEqual(advanced_payload["time_s"], 1.0)
            self.assertGreater(advanced_payload["compute_wall_s"], 0.0)
            self.assertIn("top_tension_n", advanced_payload["tensions"])
            self.assertIn("plough_inlet_tension_n", advanced_payload["tensions"])

            latest = app.handle("GET", f"/api/realtime-sessions/{session_id}")
            self.assertEqual(latest.status, 200)
            self.assertEqual(json.loads(latest.body.decode("utf-8"))["sequence"], 1)
            self.assertEqual(list(root.rglob("*.csv")), [])
            self.assertEqual(list(root.rglob("*.svg")), [])

            deleted = app.handle("DELETE", f"/api/realtime-sessions/{session_id}")
            self.assertEqual(deleted.status, 204)
            missing = app.handle("GET", f"/api/realtime-sessions/{session_id}")
            self.assertEqual(missing.status, 404)

    def test_realtime_session_reports_sequence_conflict_without_advancing(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            created = app.handle("POST", "/api/realtime-sessions", _realtime_create_payload())
            session_id = json.loads(created.body.decode("utf-8"))["session_id"]
            rejected = app.handle(
                "POST",
                f"/api/realtime-sessions/{session_id}/samples",
                _realtime_packet_payload(2, 1.0),
            )
            latest = app.handle("GET", f"/api/realtime-sessions/{session_id}")

        self.assertEqual(rejected.status, 409)
        error = json.loads(rejected.body.decode("utf-8"))
        self.assertEqual(error["error"], "sequence_conflict")
        self.assertEqual(json.loads(latest.body.decode("utf-8"))["sequence"], 0)

    def test_run_time_history_rejects_mismatched_speed_change_direction(self):
        from api.app import create_app

        payload = {
            "case_name": "operator_dynamic",
            "points": 9,
            "current_speed_mps": 1.0,
            "current_direction_deg": 90.0,
            "speed_change": "accel",
            "initial_speed_mps": 1.5,
            "final_speed_mps": 0.5,
            "duration_s": 30.0,
            "total_duration_s": 120.0,
            "water_depth_m": 100.0,
            "element_count": 12,
            "touchdown_tension_n": 0.0,
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 400)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("final_speed_mps", result["details"]["fields"])

    def test_run_time_history_rejects_zero_speed_change_duration(self):
        from api.app import create_app

        payload = {
            "case_name": "operator_dynamic",
            "points": 9,
            "current_speed_mps": 1.0,
            "current_direction_deg": 90.0,
            "speed_change": "accel",
            "initial_speed_mps": 0.5,
            "final_speed_mps": 1.5,
            "duration_s": 0.0,
            "total_duration_s": 120.0,
            "water_depth_m": 100.0,
            "element_count": 12,
            "touchdown_tension_n": 0.0,
        }

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-time-history", payload)

        self.assertEqual(response.status, 400)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("duration_s", result["details"]["fields"])

    def test_api_rejects_fractional_point_counts(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            profile_response = app.handle("POST", "/api/run-custom-case", _custom_payload(points=3.9))
            dynamic_response = app.handle(
                "POST",
                "/api/run-time-history",
                {
                    "case_name": "la_dynamic_accel_current_1p50",
                    "points": 3.9,
                },
            )

        self.assertEqual(profile_response.status, 400)
        self.assertEqual(dynamic_response.status, 400)

    def test_run_custom_case_builds_case_from_payload(self):
        from api.app import create_app

        payload = _custom_payload(cable="CUSTOM", solver_model="generic")

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle("POST", "/api/run-custom-case", payload)
            result = json.loads(response.body.decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(result["case_name"], "custom_demo")
            self.assertGreater(result["summary"]["top_tension_final_n"], 0.0)
            self.assertEqual(result["artifacts"]["summary_csv"], "custom/custom_demo/summary.csv")
            self.assertTrue((Path(tmp) / result["artifacts"]["profile_svg"]).exists())

    def test_run_custom_case_solver_model_decouples_cable_label(self):
        from api.app import create_app

        summary_fields = (
            "top_tension_initial_n",
            "top_tension_min_n",
            "top_tension_final_n",
            "suspended_length_m",
            "layback_m",
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            reference_response = app.handle(
                "POST",
                "/api/run-custom-case",
                _custom_payload(
                    cable="POWER_500KV",
                    solver_model="power_500kv",
                    output_dir="custom/reference_power",
                ),
            )
            renamed_response = app.handle(
                "POST",
                "/api/run-custom-case",
                _custom_payload(
                    cable="Operator Cable A",
                    solver_model="power_500kv",
                    output_dir="custom/renamed_power",
                ),
            )

        self.assertEqual(reference_response.status, 200)
        self.assertEqual(renamed_response.status, 200)
        reference = json.loads(reference_response.body.decode("utf-8"))
        renamed = json.loads(renamed_response.body.decode("utf-8"))

        for field in summary_fields:
            self.assertAlmostEqual(reference["summary"][field], renamed["summary"][field])

    def test_run_custom_case_rejects_unknown_solver_model(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-custom-case",
                _custom_payload(cable="CUSTOM", solver_model="paper_branch"),
            )

        self.assertEqual(response.status, 400)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("solver_model", result["details"]["fields"])

    def test_run_custom_case_rejects_cable_too_short_for_water_depth(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-custom-case",
                _custom_payload(total_length_m=50.0, water_depth_m=100.0),
            )

        self.assertEqual(response.status, 400)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("solver", result["details"]["fields"])

    def test_solver_model_fallback_accepts_500kv_display_label(self):
        from api.app import _parse_solver_model

        self.assertEqual(_parse_solver_model(None, "500kV 电力缆"), "power_500kv")

    def test_run_custom_case_rejects_invalid_numeric_input(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-custom-case",
                _custom_payload(case_name="bad_custom", cable="CUSTOM", diameter_m=-0.05),
            )

        self.assertEqual(response.status, 400)
        result = json.loads(response.body.decode("utf-8"))
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("diameter_m", result["details"]["fields"])

    def test_run_case_reports_unknown_case_as_structured_error(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            response = app.handle(
                "POST",
                "/api/run-case",
                {"case_name": "missing_case", "points": 17},
            )

        self.assertEqual(response.status, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "unknown_case")
        self.assertIn("missing_case", payload["message"])

    def test_reproduce_generates_metadata_and_serves_figure(self):
        from api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(output_root=Path(tmp))
            reproduce_response = app.handle("POST", "/api/reproduce", {"points": 21})
            metadata_response = app.handle("GET", "/api/reproduction")
            metadata = json.loads(metadata_response.body.decode("utf-8"))

            self.assertEqual(reproduce_response.status, 200)
            self.assertEqual(metadata_response.status, 200)
            self.assertTrue(metadata["available"])
            self.assertIn("paper_reproduction/tables/table_4_1_dynamic_la.csv", metadata["tables"])
            self.assertIn("paper_reproduction/figures/fig_4_1_la_acceleration.svg", metadata["figures"])

            file_response = app.handle(
                "GET",
                "/api/files/paper_reproduction/figures/fig_4_1_la_acceleration.svg",
            )

        self.assertEqual(file_response.status, 200)
        self.assertIn(b"<svg", file_response.body)

def _custom_payload(**overrides):
    payload = {
        "case_name": "custom_demo",
        "points": 19,
        "cable": "CUSTOM",
        "solver_model": "generic",
        "diameter_m": 0.139,
        "weight_air_n_per_m": 470.4,
        "submerged_weight_n_per_m": 313.6,
        "hydrodynamic_constant": 0.0,
        "tangential_drag_coefficient": 0.0,
        "normal_drag_coefficient": 1.0,
        "total_length_m": 160.0,
        "axial_stiffness_n": 1.2e9,
        "max_water_depth_m": 100.0,
        "max_allowable_tension_n": 87500.0,
        "min_bending_radius_m": 5.0,
        "initial_speed_mps": 0.5,
        "final_speed_mps": 0.5,
        "duration_s": 0.0,
        "water_depth_m": 100.0,
        "touchdown_tension_n": 1500.0,
        "current_u_mps": 0.0,
        "current_v_mps": 0.0,
        "vessel_speed_mps": 0.5,
        "payout_speed_mps": 0.5,
        "current_surface_mps": 1.5,
        "current_bottom_mps": 0.5,
        "current_direction_deg": 90.0,
    }
    payload.update(overrides)
    return payload


def _known_plough_payload(**overrides):
    payload = {
        "case_name": "known_plough_operator",
        "points": 5,
        "diameter_m": 0.0264,
        "weight_air_n_per_m": 16.09,
        "submerged_weight_n_per_m": 10.59,
        "tangential_drag_coefficient": 0.01,
        "normal_drag_coefficient": 2.12,
        "axial_stiffness_n": 1.0e9,
        "current_speed_mps": 0.4,
        "current_direction_deg": 90.0,
        "speed_change": "accel",
        "initial_speed_mps": 0.8,
        "final_speed_mps": 1.0,
        "payout_initial_speed_mps": 1.05,
        "payout_final_speed_mps": 1.15,
        "length_boundary_source": "known_plough_trajectory",
        "duration_s": 10.0,
        "total_duration_s": 20.0,
        "water_depth_m": 80.0,
        "element_count": 10,
        "touchdown_tension_n": 200.0,
        "vessel_initial_x_m": 0.0,
        "vessel_initial_y_m": 0.0,
        "vessel_heading_deg": 0.0,
        "plough_initial_x_m": -55.0,
        "plough_initial_y_m": 0.0,
        "plough_initial_z_m": 78.0,
        "plough_speed_mps": 0.75,
        "plough_heading_deg": 0.0,
    }
    payload.update(overrides)
    if payload.get("initial_suspended_length_m") is None:
        vessel_samples = payload.get("vessel_motion_samples") or ()
        plough_samples = payload.get("plough_motion_samples") or ()
        first_vessel = vessel_samples[0] if vessel_samples else {}
        first_plough = plough_samples[0] if plough_samples else {}
        try:
            vessel = (
                float(payload["vessel_initial_x_m"] if payload["vessel_initial_x_m"] is not None else first_vessel["x_m"]),
                float(payload["vessel_initial_y_m"] if payload["vessel_initial_y_m"] is not None else first_vessel["y_m"]),
                0.0,
            )
            plough = (
                float(payload["plough_initial_x_m"] if payload["plough_initial_x_m"] is not None else first_plough["x_m"]),
                float(payload["plough_initial_y_m"] if payload["plough_initial_y_m"] is not None else first_plough["y_m"]),
                float(payload["plough_initial_z_m"] if payload["plough_initial_z_m"] is not None else first_plough["z_m"]),
            )
        except (KeyError, TypeError, ValueError):
            payload["initial_suspended_length_m"] = 100.0
        else:
            payload["initial_suspended_length_m"] = 1.03 * math.dist(vessel, plough)
    return payload


def _realtime_packet_payload(sequence: int, time_s: float) -> dict[str, object]:
    return {
        "sequence": sequence,
        "time_s": time_s,
        "observed_at_unix_s": time_s,
        "quality": "valid",
        "vessel": {
            "x_m": 0.8 * time_s,
            "y_m": 0.0,
            "z_m": 0.0,
            "velocity_x_mps": 0.8,
            "velocity_y_mps": 0.0,
            "velocity_z_mps": 0.0,
        },
        "plough": {
            "x_m": -55.0 + 0.8 * time_s,
            "y_m": 0.0,
            "z_m": 80.0,
            "velocity_x_mps": 0.8,
            "velocity_y_mps": 0.0,
            "velocity_z_mps": 0.0,
        },
        "payout_speed_mps": 0.8,
        "plough_exit_speed_mps": 0.8,
        "current_velocity_x_mps": 0.0,
        "current_velocity_y_mps": 0.35,
    }


def _realtime_create_payload() -> dict[str, object]:
    payload = _known_plough_payload(
        case_name="realtime_known_plough",
        element_count=24,
        speed_change="steady",
        initial_speed_mps=0.8,
        final_speed_mps=0.8,
        payout_initial_speed_mps=0.8,
        payout_final_speed_mps=0.8,
        plough_speed_mps=0.8,
        plough_exit_speed_mps=0.8,
        duration_s=3600.0,
        total_duration_s=3600.0,
    )
    payload.pop("points", None)
    payload["max_sensor_gap_s"] = 1.1
    payload["max_data_age_s"] = 1.0e12
    payload["initial_packet"] = _realtime_packet_payload(0, 0.0)
    return payload


if __name__ == "__main__":
    unittest.main()

"""Standard-library HTTP API for the cable tension backend."""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from cable_tension.cases import get_case, list_cases  # noqa: E402
from cable_tension.dynamic import (  # noqa: E402
    CONSTRUCTION_TIME_HISTORY_CASES,
    DynamicCaseInput,
    MotionSample,
    MotionSegment,
    SpeedSegment,
    allows_no_slip_inferred_plough_exit,
    get_time_history_case,
    list_time_history_cases,
)
from cable_tension.dynamic_laying import solve_dynamic_laying_time_history  # noqa: E402
from cable_tension.io import write_result, write_time_history  # noqa: E402
from cable_tension.parameters import CableParameters, OperationCase  # noqa: E402
from cable_tension.paper import reproduce_paper  # noqa: E402
from cable_tension.realtime import (  # noqa: E402
    RealtimeSensorPacket,
    RealtimeSessionError,
    RealtimeSessionRegistry,
    SynchronizedEndpointSample,
)
from cable_tension.solver import solve_case  # noqa: E402

try:  # pragma: no cover - supports both package import and direct script execution.
    from .schemas import (
        ApiResponse,
        case_payload,
        error_response,
        json_response,
        run_case_payload,
        realtime_frame_payload,
        run_time_history_payload,
        time_history_case_payload,
    )
except ImportError:  # pragma: no cover
    from schemas import (
        ApiResponse,
        case_payload,
        error_response,
        json_response,
        run_case_payload,
        realtime_frame_payload,
        run_time_history_payload,
        time_history_case_payload,
    )


class CableApiServer:
    """Testable API router used by the real HTTP handler."""

    def __init__(self, output_root: Path | None = None) -> None:
        self.output_root = (output_root or BACKEND_ROOT / "output").resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.realtime_sessions = RealtimeSessionRegistry()

    def handle(self, method: str, raw_path: str, payload: dict[str, Any] | None = None) -> ApiResponse:
        """Route a request and return a concrete response object."""

        method = method.upper()
        path = urlsplit(raw_path).path
        if method == "OPTIONS":
            return ApiResponse(status=204, body=b"", headers={"Content-Type": "text/plain"})
        if method == "GET" and path == "/api/health":
            return self._health()
        if method == "GET" and path == "/api/cases":
            return self._cases()
        if method == "GET" and path == "/api/time-history-cases":
            return self._time_history_cases()
        if method == "POST" and path == "/api/run-case":
            return self._run_case(payload or {})
        if method == "POST" and path == "/api/run-custom-case":
            return self._run_custom_case(payload or {})
        if method == "POST" and path == "/api/run-time-history":
            return self._run_time_history(payload or {})
        if method == "POST" and path == "/api/realtime-sessions":
            return self._create_realtime_session(payload or {})
        if path.startswith("/api/realtime-sessions/"):
            return self._handle_realtime_session(method, path, payload or {})
        if method == "GET" and path == "/api/reproduction":
            return self._reproduction()
        if method == "POST" and path == "/api/reproduce":
            return self._reproduce(payload or {})
        if method == "GET" and path == "/theory_formula_report.html":
            return self._theory_report_file("theory_formula_report.html")
        if method == "GET" and _is_theory_report_asset(path):
            return self._theory_report_file(path.lstrip("/"))
        if method == "GET" and path.startswith("/api/files/"):
            return self._file(path.removeprefix("/api/files/"))
        return error_response("not_found", f"No route for {method} {path}", status=404)

    def _health(self) -> ApiResponse:
        return json_response(
            {
                "status": "ok",
                "service": "cable-tension-backend",
                "output_root": self.output_root.as_posix(),
            }
        )

    def _cases(self) -> ApiResponse:
        return json_response({"cases": [case_payload(get_case(name)) for name in list_cases()]})

    def _time_history_cases(self) -> ApiResponse:
        return json_response(
            {
                "cases": [
                    time_history_case_payload(get_time_history_case(name))
                    for name in CONSTRUCTION_TIME_HISTORY_CASES
                ]
            }
        )

    def _run_case(self, payload: dict[str, Any]) -> ApiResponse:
        case_name = str(payload.get("case_name", "")).strip()
        if not case_name:
            return error_response("invalid_request", "`case_name` is required.", status=400)
        points = _parse_points(payload.get("points", 201))
        if points is None:
            return error_response("invalid_points", "`points` must be an integer between 2 and 1001.", status=400)
        try:
            case = get_case(case_name)
        except KeyError:
            return error_response("unknown_case", f"Unknown case: {case_name}", status=404)

        output_dir = self._safe_output_dir(payload.get("output_dir"), default=case.name)
        if output_dir is None:
            return error_response(
                "invalid_output_dir",
                "`output_dir` must stay inside the backend output root.",
                status=400,
            )

        result = solve_case(case, points=points)
        written = write_result(result, output_dir)
        return json_response(
            run_case_payload(
                result,
                {
                    "summary_csv": written.summary_csv,
                    "profile_csv": written.profile_csv,
                    "profile_svg": written.profile_svg,
                },
                self.output_root,
                duration_s=case.duration_s,
            )
        )

    def _run_time_history(self, payload: dict[str, Any]) -> ApiResponse:
        case_name = str(payload.get("case_name", "")).strip()
        if not case_name:
            return error_response("invalid_request", "`case_name` is required.", status=400)
        points = _parse_points(payload.get("points", 361), min_value=3)
        if points is None:
            return error_response("invalid_points", "`points` must be an integer between 3 and 1001.", status=400)

        is_operator_input = _has_operator_dynamic_inputs(payload)
        if is_operator_input:
            parsed_case = _dynamic_case_from_payload(payload)
            if isinstance(parsed_case, ApiResponse):
                return parsed_case
            dynamic_case = parsed_case
        else:
            if case_name not in CONSTRUCTION_TIME_HISTORY_CASES:
                return error_response("unknown_time_history_case", f"Unknown time-history case: {case_name}", status=404)
            dynamic_case = get_time_history_case(case_name)

        output_dir = self._safe_output_dir(
            payload.get("output_dir"),
            default=f"time_histories/{_safe_slug(dynamic_case.case_name)}",
        )
        if output_dir is None:
            return error_response(
                "invalid_output_dir",
                "`output_dir` must stay inside the backend output root.",
                status=400,
            )

        try:
            result = solve_dynamic_laying_time_history(dynamic_case, points=points)
        except ValueError as exc:
            return error_response("invalid_input", str(exc), status=400)

        written = write_time_history(result, output_dir)
        return json_response(
            run_time_history_payload(
                result,
                {
                    "time_summary_csv": written.summary_csv,
                    "time_history_csv": written.history_csv,
                    "time_history_svg": written.history_svg,
                },
                self.output_root,
            )
        )

    def _create_realtime_session(self, payload: dict[str, Any]) -> ApiResponse:
        parsed_case = _dynamic_case_from_payload(payload)
        if isinstance(parsed_case, ApiResponse):
            return parsed_case
        packet = _parse_realtime_packet(payload.get("initial_packet"))
        if isinstance(packet, ApiResponse):
            return packet
        max_sensor_gap_s = _parse_float(payload.get("max_sensor_gap_s", 1.5))
        max_data_age_s = _parse_float(payload.get("max_data_age_s", 1.0))
        if max_sensor_gap_s is None or max_sensor_gap_s <= 0.0:
            return error_response(
                "invalid_input",
                "`max_sensor_gap_s` must be a positive finite number.",
                status=400,
            )
        if max_data_age_s is None or max_data_age_s <= 0.0:
            return error_response(
                "invalid_input",
                "`max_data_age_s` must be a positive finite number.",
                status=400,
            )
        try:
            session = self.realtime_sessions.create(
                base_case=parsed_case,
                initial_packet=packet,
                max_sensor_gap_s=max_sensor_gap_s,
                max_data_age_s=max_data_age_s,
            )
        except RealtimeSessionError as exc:
            return _realtime_error_response(exc)
        except (RuntimeError, ValueError) as exc:
            return error_response("invalid_input", str(exc), status=400)
        return json_response(realtime_frame_payload(session.latest), status=201)

    def _handle_realtime_session(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> ApiResponse:
        suffix = path.removeprefix("/api/realtime-sessions/")
        parts = [part for part in suffix.split("/") if part]
        if not parts or len(parts) > 2:
            return error_response("not_found", f"No route for {method} {path}", status=404)
        session_id = parts[0]
        session = self.realtime_sessions.get(session_id)
        if session is None:
            return error_response("unknown_session", "Realtime session was not found.", status=404)
        if method == "GET" and len(parts) == 1:
            return json_response(realtime_frame_payload(session.latest))
        if method == "DELETE" and len(parts) == 1:
            self.realtime_sessions.delete(session_id)
            return ApiResponse(status=204, body=b"", headers={"Content-Type": "text/plain"})
        if method == "POST" and parts[1:] == ["samples"]:
            packet = _parse_realtime_packet(payload)
            if isinstance(packet, ApiResponse):
                return packet
            try:
                result = session.advance(packet)
            except RealtimeSessionError as exc:
                return _realtime_error_response(exc)
            except (RuntimeError, ValueError) as exc:
                return error_response("realtime_step_failed", str(exc), status=422)
            return json_response(realtime_frame_payload(result))
        return error_response("not_found", f"No route for {method} {path}", status=404)

    def _run_custom_case(self, payload: dict[str, Any]) -> ApiResponse:
        parsed = _custom_case_from_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        case, points = parsed

        output_dir = self._safe_output_dir(
            payload.get("output_dir"),
            default=f"custom/{_safe_slug(case.name)}",
        )
        if output_dir is None:
            return error_response(
                "invalid_output_dir",
                "`output_dir` must stay inside the backend output root.",
                status=400,
            )

        try:
            result = solve_case(case, points=points)
        except ValueError as exc:
            return error_response(
                "invalid_input",
                "Custom case input is invalid.",
                status=400,
                details={"fields": {"solver": str(exc)}},
            )
        written = write_result(result, output_dir)
        return json_response(
            run_case_payload(
                result,
                {
                    "summary_csv": written.summary_csv,
                    "profile_csv": written.profile_csv,
                    "profile_svg": written.profile_svg,
                },
                self.output_root,
                duration_s=case.duration_s,
            )
        )

    def _reproduce(self, payload: dict[str, Any]) -> ApiResponse:
        points = _parse_points(payload.get("points", 201))
        if points is None:
            return error_response("invalid_points", "`points` must be an integer between 2 and 1001.", status=400)
        result = reproduce_paper(self.output_root / "paper_reproduction", points=points)
        metadata = self._reproduction_payload()
        metadata["case_count"] = result.case_count
        return json_response(metadata)

    def _reproduction(self) -> ApiResponse:
        return json_response(self._reproduction_payload())

    def _theory_report_file(self, relative_url_path: str) -> ApiResponse:
        return self._file(f"theory_formula_report/{relative_url_path}")

    def _file(self, relative_url_path: str) -> ApiResponse:
        relative_path = unquote(relative_url_path).replace("\\", "/")
        target = (self.output_root / relative_path).resolve()
        try:
            # 文件下载只允许访问 output_root 内部，避免通过 ../ 读取本机其他文件。
            target.relative_to(self.output_root)
        except ValueError:
            return error_response("invalid_file_path", "File path must stay inside output root.", status=400)
        if not target.exists() or not target.is_file():
            return error_response("file_not_found", f"File not found: {relative_path}", status=404)
        content_type = _content_type(target)
        return ApiResponse(
            status=200,
            body=target.read_bytes(),
            headers={"Content-Type": content_type},
        )

    def _reproduction_payload(self) -> dict[str, Any]:
        root = self.output_root / "paper_reproduction"
        return {
            "available": root.exists(),
            "root": "paper_reproduction",
            "inputs": _relative_files(root / "inputs", self.output_root, "*.csv"),
            "tables": _relative_files(root / "tables", self.output_root, "*.csv"),
            "figures": _relative_files(root / "figures", self.output_root, "*.svg"),
            "cases": _relative_dirs(root / "cases"),
            "time_histories": _relative_dirs(root / "time_histories"),
        }

    def _safe_output_dir(self, value: Any, *, default: str) -> Path | None:
        raw = default if value in (None, "") else str(value)
        candidate = Path(raw)
        if candidate.is_absolute():
            return None
        resolved = (self.output_root / candidate).resolve()
        try:
            resolved.relative_to(self.output_root)
        except ValueError:
            return None
        return resolved


def create_app(output_root: Path | None = None) -> CableApiServer:
    """Create the testable API router."""

    return CableApiServer(output_root=output_root)


def run_dev_server(host: str = "127.0.0.1", port: int = 8765, output_root: Path | None = None) -> None:
    """Run the local development HTTP server."""

    app = create_app(output_root=output_root)

    server = ThreadingHTTPServer((host, port), create_http_handler(app))
    print(f"cable tension API: http://{host}:{port}")
    server.serve_forever()


def create_http_handler(app: CableApiServer) -> type[BaseHTTPRequestHandler]:
    """Create the concrete HTTP boundary used by the development server."""

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(app.handle("OPTIONS", self.path))

        def do_GET(self) -> None:  # noqa: N802
            self._send(app.handle("GET", self.path))

        def do_POST(self) -> None:  # noqa: N802
            payload = self._read_json_body()
            if payload is None:
                self._send(error_response("invalid_json", "Request body must be valid JSON.", status=400))
                return
            self._send(app.handle("POST", self.path, payload))

        def do_DELETE(self) -> None:  # noqa: N802
            self._send(app.handle("DELETE", self.path))

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write("[cable-api] " + format % args + "\n")

        def _read_json_body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            try:
                body = self.rfile.read(length).decode("utf-8")
                parsed = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return parsed if isinstance(parsed, dict) else None

        def _send(self, response: ApiResponse) -> None:
            self.send_response(response.status)
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Content-Length": str(len(response.body)),
                **response.headers,
            }
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if response.body:
                self.wfile.write(response.body)

    return Handler


_MAX_POINTS = 1001
_MAX_DYNAMIC_ELEMENT_COUNT = 256


def _parse_points(value: Any, *, min_value: int = 2, max_value: int = _MAX_POINTS) -> int | None:
    points = _parse_int(value)
    if points is None:
        return None
    return points if min_value <= points <= max_value else None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value)
    return None


_REQUIRED_CUSTOM_FLOATS = (
    "diameter_m",
    "weight_air_n_per_m",
    "submerged_weight_n_per_m",
    "hydrodynamic_constant",
    "tangential_drag_coefficient",
    "normal_drag_coefficient",
    "total_length_m",
    "axial_stiffness_n",
    "initial_speed_mps",
    "final_speed_mps",
    "duration_s",
    "water_depth_m",
    "touchdown_tension_n",
    "current_u_mps",
    "current_v_mps",
)
_OPTIONAL_CUSTOM_FLOATS = (
    "max_water_depth_m",
    "max_allowable_tension_n",
    "min_bending_radius_m",
    "vessel_speed_mps",
    "payout_speed_mps",
    "current_surface_mps",
    "current_bottom_mps",
    "current_direction_deg",
)
_POSITIVE_CUSTOM_FLOATS = {
    "diameter_m",
    "weight_air_n_per_m",
    "submerged_weight_n_per_m",
    "total_length_m",
    "axial_stiffness_n",
    "water_depth_m",
}
_NON_NEGATIVE_CUSTOM_FLOATS = {
    "hydrodynamic_constant",
    "tangential_drag_coefficient",
    "normal_drag_coefficient",
    "duration_s",
    "touchdown_tension_n",
    "current_surface_mps",
    "current_bottom_mps",
}
_OPTIONAL_POSITIVE_CUSTOM_FLOATS = {
    "max_water_depth_m",
    "max_allowable_tension_n",
    "min_bending_radius_m",
}
_CUSTOM_SOLVER_MODELS = {"generic", "power_500kv"}
_DYNAMIC_INPUT_FIELDS = {
    "diameter_m",
    "weight_air_n_per_m",
    "submerged_weight_n_per_m",
    "tangential_drag_coefficient",
    "normal_drag_coefficient",
    "axial_stiffness_n",
    "current_speed_mps",
    "current_direction_deg",
    "speed_change",
    "initial_speed_mps",
    "final_speed_mps",
    "payout_initial_speed_mps",
    "payout_final_speed_mps",
    "length_boundary_source",
    "duration_s",
    "total_duration_s",
    "water_depth_m",
    "element_count",
    "touchdown_tension_n",
    "vessel_initial_x_m",
    "vessel_initial_y_m",
    "vessel_heading_deg",
    "plough_initial_x_m",
    "plough_initial_y_m",
    "plough_initial_z_m",
    "plough_speed_mps",
    "plough_exit_speed_mps",
    "plough_heading_deg",
    "initial_suspended_length_m",
    "min_bending_radius_m",
    "vessel_motion_segments",
    "plough_motion_segments",
    "vessel_motion_samples",
    "plough_motion_samples",
    "payout_speed_segments",
}


def _has_operator_dynamic_inputs(payload: dict[str, Any]) -> bool:
    return any(field in payload for field in _DYNAMIC_INPUT_FIELDS)


def _dynamic_case_from_payload(payload: dict[str, Any]) -> DynamicCaseInput | ApiResponse:
    errors: dict[str, str] = {}

    case_name = str(payload.get("case_name", "")).strip()
    if not case_name:
        errors["case_name"] = "is required"

    speed_change = str(payload.get("speed_change", "")).strip().lower()
    if speed_change not in {"steady", "accel", "decel"}:
        errors["speed_change"] = "must be steady, accel, or decel"
    length_boundary_source = str(payload.get("length_boundary_source", "known_plough_trajectory")).strip()
    if length_boundary_source != "known_plough_trajectory":
        errors["length_boundary_source"] = "must be known_plough_trajectory"

    float_fields = (
        "diameter_m",
        "weight_air_n_per_m",
        "submerged_weight_n_per_m",
        "tangential_drag_coefficient",
        "normal_drag_coefficient",
        "axial_stiffness_n",
        "current_speed_mps",
        "current_direction_deg",
        "initial_speed_mps",
        "final_speed_mps",
        "duration_s",
        "total_duration_s",
        "water_depth_m",
        "touchdown_tension_n",
    )
    values: dict[str, float] = {}
    for field in float_fields:
        value = _parse_float(payload.get(field))
        if value is None:
            errors[field] = "must be a finite number"
            continue
        values[field] = value

    optional_float_fields = (
        "payout_initial_speed_mps",
        "payout_final_speed_mps",
        "vessel_initial_x_m",
        "vessel_initial_y_m",
        "vessel_heading_deg",
        "plough_initial_x_m",
        "plough_initial_y_m",
        "plough_initial_z_m",
        "plough_speed_mps",
        "plough_exit_speed_mps",
        "plough_heading_deg",
        "initial_suspended_length_m",
        "min_bending_radius_m",
    )
    optional_values: dict[str, float | None] = {}
    for field in optional_float_fields:
        raw = payload.get(field)
        if raw in (None, ""):
            optional_values[field] = None
            continue
        value = _parse_float(raw)
        if value is None:
            errors[field] = "must be a finite number"
            continue
        optional_values[field] = value

    vessel_motion_segments = _parse_motion_segments(
        payload.get("vessel_motion_segments"),
        field="vessel_motion_segments",
        errors=errors,
    )
    plough_motion_segments = _parse_motion_segments(
        payload.get("plough_motion_segments"),
        field="plough_motion_segments",
        errors=errors,
    )
    vessel_motion_samples = _parse_motion_samples(
        payload.get("vessel_motion_samples"),
        field="vessel_motion_samples",
        errors=errors,
    )
    plough_motion_samples = _parse_motion_samples(
        payload.get("plough_motion_samples"),
        field="plough_motion_samples",
        errors=errors,
    )
    payout_speed_segments = _parse_speed_segments(
        payload.get("payout_speed_segments"),
        field="payout_speed_segments",
        errors=errors,
    )

    if vessel_motion_samples:
        first_vessel_sample = vessel_motion_samples[0]
        if optional_values.get("vessel_initial_x_m") is None:
            optional_values["vessel_initial_x_m"] = first_vessel_sample.x_m
        if optional_values.get("vessel_initial_y_m") is None:
            optional_values["vessel_initial_y_m"] = first_vessel_sample.y_m
    if plough_motion_samples:
        first_plough_sample = plough_motion_samples[0]
        if optional_values.get("plough_initial_x_m") is None:
            optional_values["plough_initial_x_m"] = first_plough_sample.x_m
        if optional_values.get("plough_initial_y_m") is None:
            optional_values["plough_initial_y_m"] = first_plough_sample.y_m
        if optional_values.get("plough_initial_z_m") is None and first_plough_sample.z_m is not None:
            optional_values["plough_initial_z_m"] = first_plough_sample.z_m

    element_count = _parse_points(payload.get("element_count"), max_value=_MAX_DYNAMIC_ELEMENT_COUNT)
    if element_count is None:
        errors["element_count"] = "must be an integer between 2 and 256"

    for field in ("current_speed_mps", "initial_speed_mps", "final_speed_mps", "duration_s", "touchdown_tension_n"):
        if field in values and values[field] < 0.0:
            errors[field] = "must be greater than or equal to 0"
    for field in ("diameter_m", "weight_air_n_per_m", "submerged_weight_n_per_m", "axial_stiffness_n"):
        if field in values and values[field] <= 0.0:
            errors[field] = "must be greater than 0"
    for field in ("tangential_drag_coefficient", "normal_drag_coefficient"):
        if field in values and values[field] < 0.0:
            errors[field] = "must be greater than or equal to 0"
    signed_position_fields = {"vessel_initial_x_m", "vessel_initial_y_m", "plough_initial_x_m", "plough_initial_y_m"}
    for field in optional_float_fields:
        value = optional_values.get(field)
        if field in signed_position_fields:
            continue
        if value is not None and value < 0.0:
            errors[field] = "must be greater than or equal to 0"
    bend_radius = optional_values.get("min_bending_radius_m")
    if bend_radius is not None and bend_radius <= 0.0:
        errors["min_bending_radius_m"] = "must be greater than 0"
    initial_suspended_length = optional_values.get("initial_suspended_length_m")
    if initial_suspended_length is not None and initial_suspended_length <= 0.0:
        errors["initial_suspended_length_m"] = "must be greater than 0"
    for field in ("total_duration_s", "water_depth_m"):
        if field in values and values[field] <= 0.0:
            errors[field] = "must be greater than 0"
    if "current_direction_deg" in values and not 0.0 <= values["current_direction_deg"] <= 360.0:
        errors["current_direction_deg"] = "must be between 0 and 360"
    for field in ("vessel_heading_deg", "plough_heading_deg"):
        value = optional_values.get(field)
        if value is not None and not 0.0 <= value <= 360.0:
            errors[field] = "must be between 0 and 360"
    if length_boundary_source == "known_plough_trajectory":
        for field in (
            "plough_initial_x_m",
            "plough_initial_y_m",
            "plough_initial_z_m",
        ):
            if optional_values.get(field) is None:
                errors[field] = "is required for known_plough_trajectory"
        if not plough_motion_segments and not plough_motion_samples:
            for field in ("plough_speed_mps", "plough_heading_deg"):
                if optional_values.get(field) is None:
                    errors[field] = (
                        "is required for known_plough_trajectory when neither "
                        "plough_motion_segments nor plough_motion_samples is provided"
                    )
        if optional_values.get("initial_suspended_length_m") is None:
            errors["initial_suspended_length_m"] = "is required for known_plough_trajectory"
        if (
            optional_values.get("plough_exit_speed_mps") is None
            and not allows_no_slip_inferred_plough_exit(
                plough_motion_segments=plough_motion_segments,
                plough_motion_samples=plough_motion_samples,
                plough_heading_deg=optional_values.get("plough_heading_deg"),
            )
        ):
            errors["plough_exit_speed_mps"] = (
                "is required unless plough motion is a verified straight +X no-slip fallback"
            )
        plough_z = optional_values.get("plough_initial_z_m")
        if (
            plough_z is not None
            and "water_depth_m" in values
            and (plough_z < 0.0 or plough_z > values["water_depth_m"])
        ):
            errors["plough_initial_z_m"] = "must be between 0 and water_depth_m"
    if (
        "duration_s" in values
        and "total_duration_s" in values
        and values["duration_s"] > values["total_duration_s"]
    ):
        errors["duration_s"] = "must be less than or equal to total_duration_s"
    if "duration_s" in values and values["duration_s"] <= 0.0:
        errors["duration_s"] = "must be greater than 0 for dynamic speed-change cases"
    if "initial_speed_mps" in values and "final_speed_mps" in values:
        if speed_change == "accel" and values["final_speed_mps"] <= values["initial_speed_mps"]:
            errors["final_speed_mps"] = "must be greater than initial_speed_mps when speed_change is accel"
        if speed_change == "decel" and values["final_speed_mps"] >= values["initial_speed_mps"]:
            errors["final_speed_mps"] = "must be less than initial_speed_mps when speed_change is decel"
        if speed_change == "steady" and not math.isclose(values["final_speed_mps"], values["initial_speed_mps"]):
            errors["final_speed_mps"] = "must equal initial_speed_mps when speed_change is steady"

    if errors:
        return error_response(
            "invalid_input",
            "Dynamic time-history input is invalid.",
            status=400,
            details={"fields": errors},
        )

    return DynamicCaseInput(
        case_name=case_name,
        diameter_m=values["diameter_m"],
        weight_air_n_per_m=values["weight_air_n_per_m"],
        submerged_weight_n_per_m=values["submerged_weight_n_per_m"],
        tangential_drag_coefficient=values["tangential_drag_coefficient"],
        normal_drag_coefficient=values["normal_drag_coefficient"],
        axial_stiffness_n=values["axial_stiffness_n"],
        current_speed_mps=values["current_speed_mps"],
        current_direction_deg=values["current_direction_deg"],
        speed_change=speed_change,
        initial_speed_mps=values["initial_speed_mps"],
        final_speed_mps=values["final_speed_mps"],
        duration_s=values["duration_s"],
        total_duration_s=values["total_duration_s"],
        water_depth_m=values["water_depth_m"],
        element_count=element_count or 32,
        touchdown_tension_n=values["touchdown_tension_n"],
        payout_initial_speed_mps=optional_values["payout_initial_speed_mps"],
        payout_final_speed_mps=optional_values["payout_final_speed_mps"],
        length_boundary_source=length_boundary_source,
        vessel_initial_x_m=optional_values["vessel_initial_x_m"] or 0.0,
        vessel_initial_y_m=optional_values["vessel_initial_y_m"] or 0.0,
        vessel_heading_deg=optional_values["vessel_heading_deg"] or 0.0,
        plough_initial_x_m=optional_values["plough_initial_x_m"],
        plough_initial_y_m=optional_values["plough_initial_y_m"],
        plough_initial_z_m=optional_values["plough_initial_z_m"],
        plough_speed_mps=optional_values["plough_speed_mps"],
        plough_exit_speed_mps=optional_values["plough_exit_speed_mps"],
        plough_heading_deg=optional_values["plough_heading_deg"],
        initial_suspended_length_m=optional_values["initial_suspended_length_m"],
        min_bending_radius_m=optional_values["min_bending_radius_m"],
        vessel_motion_segments=vessel_motion_segments,
        plough_motion_segments=plough_motion_segments,
        vessel_motion_samples=vessel_motion_samples,
        plough_motion_samples=plough_motion_samples,
        payout_speed_segments=payout_speed_segments,
    )


def _custom_case_from_payload(payload: dict[str, Any]) -> tuple[OperationCase, int] | ApiResponse:
    errors: dict[str, str] = {}

    case_name = str(payload.get("case_name", "")).strip()
    if not case_name:
        errors["case_name"] = "is required"

    cable_name = str(payload.get("cable") or payload.get("cable_name") or "").strip()
    if not cable_name:
        errors["cable"] = "is required"

    # solver_model 明确决定求解分支；cable 只作为工程标识，不再隐含选择算法。
    solver_model = _parse_solver_model(payload.get("solver_model"), cable_name)
    if solver_model is None:
        errors["solver_model"] = "must be one of: generic, power_500kv"

    points = _parse_points(payload.get("points", 201))
    if points is None:
        errors["points"] = "must be an integer between 2 and 1001"

    values: dict[str, float] = {}
    for field in _REQUIRED_CUSTOM_FLOATS:
        value = _parse_float(payload.get(field))
        if value is None:
            errors[field] = "must be a finite number"
            continue
        values[field] = value

    optional_values: dict[str, float | None] = {}
    for field in _OPTIONAL_CUSTOM_FLOATS:
        raw = payload.get(field)
        if raw in (None, ""):
            optional_values[field] = None
            continue
        value = _parse_float(raw)
        if value is None:
            errors[field] = "must be a finite number"
            continue
        optional_values[field] = value

    for field in _POSITIVE_CUSTOM_FLOATS:
        if field in values and values[field] <= 0.0:
            errors[field] = "must be greater than 0"

    for field in _NON_NEGATIVE_CUSTOM_FLOATS:
        value = values.get(field, optional_values.get(field))
        if value is not None and value < 0.0:
            errors[field] = "must be greater than or equal to 0"

    for field in _OPTIONAL_POSITIVE_CUSTOM_FLOATS:
        value = optional_values.get(field)
        if value is not None and value <= 0.0:
            errors[field] = "must be greater than 0"

    direction = optional_values.get("current_direction_deg")
    if direction is not None and not 0.0 <= direction <= 360.0:
        errors["current_direction_deg"] = "must be between 0 and 360"

    if errors:
        return error_response(
            "invalid_input",
            "Custom case input is invalid.",
            status=400,
            details={"fields": errors},
        )

    cable = CableParameters(
        name=cable_name,
        diameter_m=values["diameter_m"],
        weight_air_n_per_m=values["weight_air_n_per_m"],
        submerged_weight_n_per_m=values["submerged_weight_n_per_m"],
        hydrodynamic_constant=values["hydrodynamic_constant"],
        tangential_drag_coefficient=values["tangential_drag_coefficient"],
        normal_drag_coefficient=values["normal_drag_coefficient"],
        total_length_m=values["total_length_m"],
        axial_stiffness_n=values["axial_stiffness_n"],
        max_water_depth_m=optional_values["max_water_depth_m"],
        max_allowable_tension_n=optional_values["max_allowable_tension_n"],
        min_bending_radius_m=optional_values["min_bending_radius_m"],
    )
    case = OperationCase(
        name=case_name,
        cable=cable,
        initial_speed_mps=values["initial_speed_mps"],
        final_speed_mps=values["final_speed_mps"],
        duration_s=values["duration_s"],
        water_depth_m=values["water_depth_m"],
        solver_model=solver_model,
        touchdown_tension_n=values["touchdown_tension_n"],
        current_u_mps=values["current_u_mps"],
        current_v_mps=values["current_v_mps"],
        vessel_speed_mps=optional_values["vessel_speed_mps"],
        payout_speed_mps=optional_values["payout_speed_mps"],
        current_surface_mps=optional_values["current_surface_mps"],
        current_bottom_mps=optional_values["current_bottom_mps"],
        current_direction_deg=optional_values["current_direction_deg"],
    )
    return case, points or 201


def _parse_realtime_packet(value: Any) -> RealtimeSensorPacket | ApiResponse:
    if not isinstance(value, dict):
        return error_response(
            "invalid_input",
            "Realtime sensor packet must be an object.",
            status=400,
        )
    errors: dict[str, str] = {}
    sequence = _parse_int(value.get("sequence"))
    if sequence is None or sequence < 0:
        errors["sequence"] = "must be a non-negative integer"
    numeric_names = (
        "time_s",
        "observed_at_unix_s",
        "payout_speed_mps",
        "plough_exit_speed_mps",
        "current_velocity_x_mps",
        "current_velocity_y_mps",
    )
    numeric: dict[str, float] = {}
    for name in numeric_names:
        parsed = _parse_float(value.get(name))
        if parsed is None:
            errors[name] = "must be a finite number"
        else:
            numeric[name] = parsed
    for name in ("time_s", "payout_speed_mps", "plough_exit_speed_mps"):
        if name in numeric and numeric[name] < 0.0:
            errors[name] = "must be greater than or equal to 0"
    quality = str(value.get("quality", "")).strip()
    if not quality:
        errors["quality"] = "is required"
    vessel = _parse_synchronized_endpoint(value.get("vessel"), field="vessel", errors=errors)
    plough = _parse_synchronized_endpoint(value.get("plough"), field="plough", errors=errors)
    if errors:
        return error_response(
            "invalid_input",
            "Realtime sensor packet is invalid.",
            status=400,
            details={"fields": errors},
        )
    assert sequence is not None and vessel is not None and plough is not None
    return RealtimeSensorPacket(
        sequence=sequence,
        time_s=numeric["time_s"],
        observed_at_unix_s=numeric["observed_at_unix_s"],
        quality=quality,
        vessel=vessel,
        plough=plough,
        payout_speed_mps=numeric["payout_speed_mps"],
        plough_exit_speed_mps=numeric["plough_exit_speed_mps"],
        current_velocity_x_mps=numeric["current_velocity_x_mps"],
        current_velocity_y_mps=numeric["current_velocity_y_mps"],
    )


def _parse_synchronized_endpoint(
    value: Any,
    *,
    field: str,
    errors: dict[str, str],
) -> SynchronizedEndpointSample | None:
    if not isinstance(value, dict):
        errors[field] = "must be an object"
        return None
    names = (
        "x_m",
        "y_m",
        "z_m",
        "velocity_x_mps",
        "velocity_y_mps",
        "velocity_z_mps",
    )
    parsed: dict[str, float] = {}
    for name in names:
        number = _parse_float(value.get(name))
        if number is None:
            errors[f"{field}.{name}"] = "must be a finite number"
        else:
            parsed[name] = number
    if len(parsed) != len(names):
        return None
    return SynchronizedEndpointSample(**parsed)


def _realtime_error_response(exc: RealtimeSessionError) -> ApiResponse:
    status = {
        "sequence_conflict": 409,
        "non_monotonic_time": 409,
        "session_busy": 409,
        "sensor_gap": 422,
        "stale_sample": 422,
        "invalid_quality": 422,
        "invalid_packet": 400,
    }.get(exc.code, 400)
    return error_response(exc.code, str(exc), status=status)


def _parse_solver_model(value: Any, cable_name: str) -> str | None:
    if value in (None, ""):
        normalized_cable = cable_name.strip().upper().replace(" ", "")
        return "power_500kv" if normalized_cable in {"POWER_500KV", "500KV电缆", "500KV电力缆"} else "generic"
    parsed = str(value).strip().lower()
    return parsed if parsed in _CUSTOM_SOLVER_MODELS else None


def _parse_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_motion_segments(
    value: Any,
    *,
    field: str,
    errors: dict[str, str],
) -> tuple[MotionSegment, ...]:
    if value in (None, ""):
        return ()
    if value == []:
        return ()
    if not isinstance(value, list):
        errors[field] = "must be a non-empty array"
        return ()
    segments: list[MotionSegment] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors[f"{field}[{index}]"] = "must be an object"
            continue
        duration = _parse_float(item.get("duration_s"))
        start_speed = _parse_float(item.get("start_speed_mps"))
        end_speed = _parse_float(item.get("end_speed_mps"))
        heading = _parse_float(item.get("heading_deg"))
        start_velocity_x = _parse_float(item.get("start_velocity_x_mps"))
        start_velocity_y = _parse_float(item.get("start_velocity_y_mps"))
        end_velocity_x = _parse_float(item.get("end_velocity_x_mps"))
        end_velocity_y = _parse_float(item.get("end_velocity_y_mps"))
        vector_values = (start_velocity_x, start_velocity_y, end_velocity_x, end_velocity_y)
        has_any_vector_value = any(value is not None for value in vector_values)
        has_all_vector_values = all(value is not None for value in vector_values)
        if has_all_vector_values:
            assert start_velocity_x is not None
            assert start_velocity_y is not None
            assert end_velocity_x is not None
            assert end_velocity_y is not None
            derived_start_speed = math.hypot(start_velocity_x, start_velocity_y)
            derived_end_speed = math.hypot(end_velocity_x, end_velocity_y)
            start_speed = derived_start_speed
            end_speed = derived_end_speed
            heading_source = (
                (start_velocity_x, start_velocity_y)
                if derived_start_speed > 1.0e-12
                else (end_velocity_x, end_velocity_y)
            )
            heading = math.degrees(math.atan2(heading_source[1], heading_source[0])) % 360.0
        if duration is None or duration <= 0.0:
            errors[f"{field}[{index}].duration_s"] = "must be greater than 0"
        if start_speed is None or start_speed < 0.0:
            errors[f"{field}[{index}].start_speed_mps"] = "must be greater than or equal to 0"
        if end_speed is None or end_speed < 0.0:
            errors[f"{field}[{index}].end_speed_mps"] = "must be greater than or equal to 0"
        if heading is None or not 0.0 <= heading <= 360.0:
            errors[f"{field}[{index}].heading_deg"] = "must be between 0 and 360"
        if has_any_vector_value and not has_all_vector_values:
            errors[f"{field}[{index}].velocity_components"] = "must provide start/end x/y velocity components together"
        if duration is None or start_speed is None or end_speed is None or heading is None:
            continue
        if (
            duration > 0.0
            and start_speed >= 0.0
            and end_speed >= 0.0
            and 0.0 <= heading <= 360.0
            and (not has_any_vector_value or has_all_vector_values)
        ):
            segments.append(
                MotionSegment(
                    duration_s=duration,
                    start_speed_mps=start_speed,
                    end_speed_mps=end_speed,
                    heading_deg=heading,
                    start_velocity_x_mps=start_velocity_x,
                    start_velocity_y_mps=start_velocity_y,
                    end_velocity_x_mps=end_velocity_x,
                    end_velocity_y_mps=end_velocity_y,
                )
            )
    return tuple(segments)


def _parse_motion_samples(
    value: Any,
    *,
    field: str,
    errors: dict[str, str],
) -> tuple[MotionSample, ...]:
    if value in (None, ""):
        return ()
    if value == []:
        return ()
    if not isinstance(value, list):
        errors[field] = "must be a non-empty array"
        return ()
    samples: list[MotionSample] = []
    previous_time: float | None = None
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors[f"{field}[{index}]"] = "must be an object"
            continue
        time_s = _parse_float(item.get("time_s"))
        x_m = _parse_float(item.get("x_m"))
        y_m = _parse_float(item.get("y_m"))
        optional_raw = {
            "z_m": item.get("z_m"),
            "velocity_x_mps": item.get("velocity_x_mps"),
            "velocity_y_mps": item.get("velocity_y_mps"),
            "velocity_z_mps": item.get("velocity_z_mps"),
        }
        optional_values: dict[str, float | None] = {}
        invalid_optional = False
        for name, raw in optional_raw.items():
            if raw in (None, ""):
                optional_values[name] = None
                continue
            parsed = _parse_float(raw)
            optional_values[name] = parsed
            if parsed is None:
                errors[f"{field}[{index}].{name}"] = "must be a finite number"
                invalid_optional = True
        z_m = optional_values["z_m"]
        velocity_x = optional_values["velocity_x_mps"]
        velocity_y = optional_values["velocity_y_mps"]
        velocity_z = optional_values["velocity_z_mps"]
        if time_s is None or time_s < 0.0:
            errors[f"{field}[{index}].time_s"] = "must be greater than or equal to 0"
        elif previous_time is not None and time_s <= previous_time:
            errors[f"{field}[{index}].time_s"] = "must be strictly increasing"
        elif index == 0 and not math.isclose(time_s, 0.0, abs_tol=1.0e-9):
            errors[f"{field}[{index}].time_s"] = "must start at 0"
        if x_m is None:
            errors[f"{field}[{index}].x_m"] = "must be a finite number"
        if y_m is None:
            errors[f"{field}[{index}].y_m"] = "must be a finite number"
        has_any_velocity = any(value is not None for value in (velocity_x, velocity_y, velocity_z))
        has_xy_velocity = velocity_x is not None and velocity_y is not None
        if has_any_velocity and not has_xy_velocity:
            errors[f"{field}[{index}].velocity_components"] = "must provide x/y velocity components together"
        if (
            time_s is None
            or x_m is None
            or y_m is None
            or invalid_optional
            or (has_any_velocity and not has_xy_velocity)
        ):
            continue
        previous_time = time_s
        samples.append(
            MotionSample(
                time_s=time_s,
                x_m=x_m,
                y_m=y_m,
                z_m=z_m,
                velocity_x_mps=velocity_x,
                velocity_y_mps=velocity_y,
                velocity_z_mps=velocity_z,
            )
        )
    return tuple(samples)


def _parse_speed_segments(
    value: Any,
    *,
    field: str,
    errors: dict[str, str],
) -> tuple[SpeedSegment, ...]:
    if value in (None, ""):
        return ()
    if value == []:
        return ()
    if not isinstance(value, list):
        errors[field] = "must be a non-empty array"
        return ()
    segments: list[SpeedSegment] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors[f"{field}[{index}]"] = "must be an object"
            continue
        duration = _parse_float(item.get("duration_s"))
        start_speed = _parse_float(item.get("start_speed_mps"))
        end_speed = _parse_float(item.get("end_speed_mps"))
        if duration is None or duration <= 0.0:
            errors[f"{field}[{index}].duration_s"] = "must be greater than 0"
        if start_speed is None or start_speed < 0.0:
            errors[f"{field}[{index}].start_speed_mps"] = "must be greater than or equal to 0"
        if end_speed is None or end_speed < 0.0:
            errors[f"{field}[{index}].end_speed_mps"] = "must be greater than or equal to 0"
        if duration is None or start_speed is None or end_speed is None:
            continue
        if duration > 0.0 and start_speed >= 0.0 and end_speed >= 0.0:
            segments.append(
                SpeedSegment(
                    duration_s=duration,
                    start_speed_mps=start_speed,
                    end_speed_mps=end_speed,
                )
            )
    return tuple(segments)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-")
    return slug[:80] or "custom_case"


def _relative_files(root: Path, output_root: Path, pattern: str) -> list[str]:
    if not root.exists():
        return []
    return [
        path.resolve().relative_to(output_root.resolve()).as_posix()
        for path in sorted(root.glob(pattern))
        if path.is_file()
    ]


def _relative_dirs(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [path.name for path in sorted(root.iterdir()) if path.is_dir()]


def _content_type(path: Path) -> str:
    if path.suffix.lower() == ".html":
        return "text/html; charset=utf-8"
    if path.suffix.lower() == ".svg":
        return "image/svg+xml; charset=utf-8"
    if path.suffix.lower() == ".csv":
        return "text/csv; charset=utf-8"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _is_theory_report_asset(path: str) -> bool:
    relative = path.lstrip("/")
    return relative.startswith(
        (
            "article_figures/",
            "paper_style_figures/",
            "figures/",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the cable tension backend API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-root", type=Path, default=BACKEND_ROOT / "output")
    args = parser.parse_args()
    run_dev_server(host=args.host, port=args.port, output_root=args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

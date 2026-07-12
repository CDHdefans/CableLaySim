"""Stateful synchronized-sensor execution for the known-plough solver."""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Callable

from .dynamic import CurrentSample, MotionSample, ScalarSample
from .dynamic_laying import (
    KnownPloughSample,
    advance_known_plough_runtime,
    initialize_known_plough_runtime,
    sample_known_plough_runtime,
)


@dataclass(frozen=True)
class SynchronizedEndpointSample:
    """One already transformed endpoint position and velocity sample."""

    x_m: float
    y_m: float
    z_m: float
    velocity_x_mps: float
    velocity_y_mps: float
    velocity_z_mps: float


@dataclass(frozen=True)
class RealtimeSensorPacket:
    """One common-time packet consumed atomically by a realtime session."""

    sequence: int
    time_s: float
    observed_at_unix_s: float
    quality: str
    vessel: SynchronizedEndpointSample
    plough: SynchronizedEndpointSample
    payout_speed_mps: float
    plough_exit_speed_mps: float
    current_velocity_x_mps: float
    current_velocity_y_mps: float


@dataclass(frozen=True)
class RealtimeFrameResult:
    """Latest frame and timing evidence returned by a realtime session."""

    session_id: str
    sequence: int
    time_s: float
    compute_wall_s: float
    realtime_factor: float | None
    input_age_s: float
    input_status: str
    point: object
    frame: object
    integration_time_step_min_s: float | None
    integration_time_step_max_s: float | None
    axial_constraint_residual_max_m: float | None


class RealtimeSessionError(ValueError):
    """Structured session error that leaves the accepted state unchanged."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RealtimeSimulationSession:
    """Own and serially advance one persistent known-plough simulation."""

    def __init__(
        self,
        *,
        session_id: str,
        base_case,
        initial_packet: RealtimeSensorPacket,
        max_sensor_gap_s: float = 1.5,
        max_data_age_s: float = 1.0,
        clock: Callable[[], float] = time.time,
        frame_buffer_size: int = 120,
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if max_sensor_gap_s <= 0.0 or max_data_age_s <= 0.0:
            raise ValueError("sensor gap and data age limits must be positive")
        if frame_buffer_size <= 0:
            raise ValueError("frame_buffer_size must be positive")
        self.session_id = session_id
        self.base_case = base_case
        self.max_sensor_gap_s = float(max_sensor_gap_s)
        self.max_data_age_s = float(max_data_age_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._frames: deque[RealtimeFrameResult] = deque(maxlen=frame_buffer_size)

        self._validate_initial_packet(initial_packet)
        initial_case = self._case_for_packets(initial_packet, initial_packet)
        self._runtime = initialize_known_plough_runtime(initial_case)
        self._runtime.dt_max_s = min(self._runtime.dt_max_s, 0.01)
        self._packet = initial_packet
        sample = sample_known_plough_runtime(self._runtime, initial_case)
        age = max(0.0, self._clock() - initial_packet.observed_at_unix_s)
        self._latest = self._result(
            packet=initial_packet,
            sample=sample,
            compute_wall_s=0.0,
            input_age_s=age,
            previous_time_s=None,
        )
        self._frames.append(self._latest)

    @property
    def current_sequence(self) -> int:
        return self._packet.sequence

    @property
    def current_time_s(self) -> float:
        return self._runtime.time_s

    @property
    def latest(self) -> RealtimeFrameResult:
        return self._latest

    @property
    def frames(self) -> tuple[RealtimeFrameResult, ...]:
        return tuple(self._frames)

    def advance(self, packet: RealtimeSensorPacket) -> RealtimeFrameResult:
        if not self._lock.acquire(blocking=False):
            raise RealtimeSessionError("session_busy", "the session is already advancing")
        try:
            input_age = self._validate_next_packet(packet)
            previous_packet = self._packet
            step_case = self._case_for_packets(previous_packet, packet)
            runtime_before = deepcopy(self._runtime)
            started = perf_counter()
            try:
                advance_known_plough_runtime(
                    self._runtime,
                    step_case,
                    target_time_s=packet.time_s,
                )
                sample = sample_known_plough_runtime(self._runtime, step_case)
            except Exception:
                self._runtime = runtime_before
                raise
            compute_wall = perf_counter() - started
            result = self._result(
                packet=packet,
                sample=sample,
                compute_wall_s=compute_wall,
                input_age_s=input_age,
                previous_time_s=previous_packet.time_s,
            )
            self._packet = packet
            self._latest = result
            self._frames.append(result)
            return result
        finally:
            self._lock.release()

    def _validate_initial_packet(self, packet: RealtimeSensorPacket) -> None:
        self._validate_packet_values(packet)
        if packet.sequence != 0:
            raise RealtimeSessionError("sequence_conflict", "initial sequence must be 0")
        if not math.isclose(packet.time_s, 0.0, abs_tol=1.0e-9):
            raise RealtimeSessionError("non_monotonic_time", "initial time_s must be 0")
        self._validate_quality_and_age(packet)

    def _validate_next_packet(self, packet: RealtimeSensorPacket) -> float:
        self._validate_packet_values(packet)
        if packet.sequence != self._packet.sequence + 1:
            raise RealtimeSessionError("sequence_conflict", "sequence must increment by one")
        if packet.time_s <= self._packet.time_s + 1.0e-12:
            raise RealtimeSessionError("non_monotonic_time", "time_s must strictly increase")
        if packet.time_s - self._packet.time_s > self.max_sensor_gap_s + 1.0e-12:
            raise RealtimeSessionError("sensor_gap", "sensor time gap exceeds the session limit")
        return self._validate_quality_and_age(packet)

    def _validate_quality_and_age(self, packet: RealtimeSensorPacket) -> float:
        if packet.quality != "valid":
            raise RealtimeSessionError("invalid_quality", "sensor packet quality must be valid")
        age = self._clock() - packet.observed_at_unix_s
        if abs(age) > self.max_data_age_s + 1.0e-12:
            raise RealtimeSessionError("stale_sample", "sensor packet age exceeds the session limit")
        return max(0.0, age)

    @staticmethod
    def _validate_packet_values(packet: RealtimeSensorPacket) -> None:
        numeric_values = (
            packet.time_s,
            packet.observed_at_unix_s,
            packet.vessel.x_m,
            packet.vessel.y_m,
            packet.vessel.z_m,
            packet.vessel.velocity_x_mps,
            packet.vessel.velocity_y_mps,
            packet.vessel.velocity_z_mps,
            packet.plough.x_m,
            packet.plough.y_m,
            packet.plough.z_m,
            packet.plough.velocity_x_mps,
            packet.plough.velocity_y_mps,
            packet.plough.velocity_z_mps,
            packet.payout_speed_mps,
            packet.plough_exit_speed_mps,
            packet.current_velocity_x_mps,
            packet.current_velocity_y_mps,
        )
        if packet.sequence < 0 or any(not math.isfinite(float(value)) for value in numeric_values):
            raise RealtimeSessionError("invalid_packet", "sensor packet values must be finite")
        if packet.payout_speed_mps < 0.0 or packet.plough_exit_speed_mps < 0.0:
            raise RealtimeSessionError("invalid_packet", "material speeds must be non-negative")

    def _case_for_packets(self, start: RealtimeSensorPacket, end: RealtimeSensorPacket):
        from .dynamic import CurrentSample, MotionSample, ScalarSample

        vessel_samples = tuple(
            self._motion_sample(packet.time_s, packet.vessel)
            for packet in self._distinct_packets(start, end)
        )
        plough_samples = tuple(
            self._motion_sample(packet.time_s, packet.plough)
            for packet in self._distinct_packets(start, end)
        )
        payout_samples = tuple(
            ScalarSample(packet.time_s, packet.payout_speed_mps)
            for packet in self._distinct_packets(start, end)
        )
        plough_exit_samples = tuple(
            ScalarSample(packet.time_s, packet.plough_exit_speed_mps)
            for packet in self._distinct_packets(start, end)
        )
        current_samples = tuple(
            CurrentSample(
                packet.time_s,
                packet.current_velocity_x_mps,
                packet.current_velocity_y_mps,
            )
            for packet in self._distinct_packets(start, end)
        )
        current_speed = math.hypot(end.current_velocity_x_mps, end.current_velocity_y_mps)
        current_direction = (
            math.degrees(math.atan2(end.current_velocity_y_mps, end.current_velocity_x_mps)) % 360.0
            if current_speed > 1.0e-12
            else self.base_case.current_direction_deg
        )
        return replace(
            self.base_case,
            current_speed_mps=current_speed,
            current_direction_deg=current_direction,
            payout_initial_speed_mps=start.payout_speed_mps,
            payout_final_speed_mps=end.payout_speed_mps,
            plough_exit_speed_mps=end.plough_exit_speed_mps,
            vessel_motion_segments=(),
            plough_motion_segments=(),
            payout_speed_segments=(),
            vessel_motion_samples=vessel_samples,
            plough_motion_samples=plough_samples,
            payout_speed_samples=payout_samples,
            plough_exit_speed_samples=plough_exit_samples,
            current_samples=current_samples,
        )

    @staticmethod
    def _distinct_packets(start: RealtimeSensorPacket, end: RealtimeSensorPacket):
        return (start,) if math.isclose(start.time_s, end.time_s, abs_tol=1.0e-12) else (start, end)

    @staticmethod
    def _motion_sample(time_s: float, endpoint: SynchronizedEndpointSample) -> MotionSample:
        return MotionSample(
            time_s=time_s,
            x_m=endpoint.x_m,
            y_m=endpoint.y_m,
            z_m=endpoint.z_m,
            velocity_x_mps=endpoint.velocity_x_mps,
            velocity_y_mps=endpoint.velocity_y_mps,
            velocity_z_mps=endpoint.velocity_z_mps,
        )

    def _result(
        self,
        *,
        packet: RealtimeSensorPacket,
        sample: KnownPloughSample,
        compute_wall_s: float,
        input_age_s: float,
        previous_time_s: float | None,
    ) -> RealtimeFrameResult:
        physical_step = None if previous_time_s is None else packet.time_s - previous_time_s
        realtime_factor = (
            None
            if physical_step is None or compute_wall_s <= 0.0
            else physical_step / compute_wall_s
        )
        return RealtimeFrameResult(
            session_id=self.session_id,
            sequence=packet.sequence,
            time_s=packet.time_s,
            compute_wall_s=compute_wall_s,
            realtime_factor=realtime_factor,
            input_age_s=input_age_s,
            input_status="valid",
            point=sample.point,
            frame=sample.frame,
            integration_time_step_min_s=self._runtime.integration_time_step_min_s,
            integration_time_step_max_s=self._runtime.integration_time_step_max_s,
            axial_constraint_residual_max_m=self._runtime.axial_constraint_residual_max_m,
        )


class RealtimeSessionRegistry:
    """Thread-safe owner for active in-memory realtime sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, RealtimeSimulationSession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        base_case,
        initial_packet: RealtimeSensorPacket,
        max_sensor_gap_s: float,
        max_data_age_s: float,
    ) -> RealtimeSimulationSession:
        session_id = uuid.uuid4().hex
        session = RealtimeSimulationSession(
            session_id=session_id,
            base_case=base_case,
            initial_packet=initial_packet,
            max_sensor_gap_s=max_sensor_gap_s,
            max_data_age_s=max_data_age_s,
        )
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> RealtimeSimulationSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

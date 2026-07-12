"""Experimental lumped-mass dynamic line model for LA time histories.

This module is a first practical step toward newer global dynamic line theory:
the cable is represented by nodes and segments, external loads are integrated
in time, and segment length constraints keep the suspended line coherent. It is
kept separate from ``dynamic.py`` so the existing thesis-reproduction diagnostic
path is not silently replaced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .cases import get_cable
from .dynamic import (
    DynamicCaseInput,
    TimeHistoryFrame,
    TimeHistoryFramePoint,
    TimeHistoryPoint,
    TimeHistoryResult,
    _GRAVITY_MPS2,
    _MIN_SPEED_MPS,
    _SEAWATER_DENSITY_KG_M3,
    _dynamic_mass_per_meter,
    _relative_current_components,
    _sample_times,
    _straight_line_state,
    _validate_dynamic_case,
    _vessel_speed,
)


_Vector = tuple[float, float, float]

_CONSTRAINT_ITERATIONS = 5
_VELOCITY_DAMPING = 0.985
_MAX_TIME_STEP_S = 0.02
_MIN_TIME_STEP_S = 0.005
_SEABED_FRICTION_COEFFICIENT = 0.6


@dataclass(frozen=True)
class _LumpedState:
    positions: list[_Vector]
    velocities: list[_Vector]
    rest_length_m: float


def solve_lumped_mass_time_history(case: DynamicCaseInput, *, points: int = 361) -> TimeHistoryResult:
    """Solve a LA time history with an experimental lumped-mass dynamic line."""

    if points < 3:
        raise ValueError("points must be at least 3")
    _validate_dynamic_case(case)
    sample_times = _sample_times(case, points)
    samples = _integrate_lumped_line(case, sample_times)
    tensions = [point.top_tension_n for point, _frame in samples]
    history = [point for point, _frame in samples]
    frames = [frame for _point, frame in samples]

    return TimeHistoryResult(
        case_name=case.case_name,
        diameter_m=case.diameter_m,
        weight_air_n_per_m=case.weight_air_n_per_m,
        submerged_weight_n_per_m=case.submerged_weight_n_per_m,
        tangential_drag_coefficient=case.tangential_drag_coefficient,
        normal_drag_coefficient=case.normal_drag_coefficient,
        axial_stiffness_n=case.axial_stiffness_n,
        current_speed_mps=case.current_speed_mps,
        current_direction_deg=case.current_direction_deg,
        speed_change=case.speed_change,
        initial_speed_mps=case.initial_speed_mps,
        final_speed_mps=case.final_speed_mps,
        duration_s=case.duration_s,
        total_duration_s=case.total_duration_s,
        water_depth_m=case.water_depth_m,
        element_count=case.element_count,
        touchdown_tension_n=case.touchdown_tension_n,
        payout_initial_speed_mps=(
            case.initial_speed_mps
            if case.payout_initial_speed_mps is None
            else case.payout_initial_speed_mps
        ),
        payout_final_speed_mps=(
            case.final_speed_mps
            if case.payout_final_speed_mps is None
            else case.payout_final_speed_mps
        ),
        length_boundary_source=case.length_boundary_source,
        initial_suspended_length_m=case.initial_suspended_length_m,
        evidence_level="experimental lumped-mass dynamic line; no paper target fitting",
        initial_tension_n=history[0].top_tension_n,
        extreme_tension_n=min(tensions) if case.speed_change == "accel" else max(tensions),
        steady_tension_n=history[-1].top_tension_n,
        history=history,
        frames=frames,
    )


def _integrate_lumped_line(
    case: DynamicCaseInput,
    sample_times: list[float],
) -> list[tuple[TimeHistoryPoint, TimeHistoryFrame]]:
    if not sample_times:
        return []

    state = _initial_state(case)
    outputs: list[tuple[TimeHistoryPoint, TimeHistoryFrame]] = []
    current_time = 0.0
    next_sample = 0
    integration_steps = 0
    dt_max = _time_step_s(case)

    while next_sample < len(sample_times):
        target_time = sample_times[next_sample]
        while current_time + 1.0e-9 < target_time:
            dt = min(dt_max, target_time - current_time)
            state = _advance_state(case, state, current_time, dt)
            current_time += dt
            integration_steps += 1

        outputs.append(_sample_state(case, state, target_time, integration_steps))
        next_sample += 1

    return outputs


def _initial_state(case: DynamicCaseInput) -> _LumpedState:
    steady = _straight_line_state(case, case.initial_speed_mps)
    element_count = case.element_count
    positions: list[_Vector] = []
    for index in range(element_count + 1):
        fraction = index / element_count
        positions.append(
            (
                steady.tdp_x_m * fraction,
                steady.tdp_y_m * fraction,
                case.water_depth_m * fraction,
            )
        )
    velocities = [(0.0, 0.0, 0.0) for _ in positions]
    rest_length = max(steady.suspended_length_m / element_count, case.water_depth_m / element_count)
    return _LumpedState(positions=positions, velocities=velocities, rest_length_m=rest_length)


def _advance_state(
    case: DynamicCaseInput,
    state: _LumpedState,
    time_s: float,
    dt: float,
) -> _LumpedState:
    cable = get_cable("LA")
    mass_per_node = _node_mass(case, state.rest_length_m)
    vessel_speed = _vessel_speed(case, time_s)
    accelerations = [
        _node_acceleration(
            case,
            cable,
            state.positions[index],
            state.velocities[index],
            vessel_speed,
            mass_per_node,
            state.rest_length_m,
        )
        for index in range(len(state.positions))
    ]

    predicted_positions = list(state.positions)
    predicted_velocities = list(state.velocities)
    for index in range(1, len(predicted_positions)):
        velocity = _mul(_add(predicted_velocities[index], _mul(accelerations[index], dt)), _VELOCITY_DAMPING)
        predicted_velocities[index] = velocity
        predicted_positions[index] = _add(predicted_positions[index], _mul(velocity, dt))

    predicted_positions[0] = (0.0, 0.0, 0.0)
    predicted_velocities[0] = (0.0, 0.0, 0.0)
    predicted_positions = _apply_length_constraints(predicted_positions, state.rest_length_m)
    predicted_positions = [_clamp_water_column(case, position) for position in predicted_positions]
    predicted_positions[-1] = (
        predicted_positions[-1][0],
        predicted_positions[-1][1],
        case.water_depth_m,
    )

    corrected_velocities = [
        _mul(_sub(new, old), 1.0 / max(dt, _MIN_SPEED_MPS))
        for new, old in zip(predicted_positions, state.positions)
    ]
    corrected_velocities[0] = (0.0, 0.0, 0.0)
    corrected_velocities[-1] = (
        corrected_velocities[-1][0],
        corrected_velocities[-1][1],
        0.0,
    )
    return _LumpedState(
        positions=predicted_positions,
        velocities=corrected_velocities,
        rest_length_m=state.rest_length_m,
    )


def _node_acceleration(
    case: DynamicCaseInput,
    cable,
    position: _Vector,
    velocity: _Vector,
    vessel_speed_mps: float,
    mass_per_node: float,
    tributary_length_m: float,
) -> _Vector:
    current_x, current_y = _relative_current_components(case, vessel_speed_mps)
    relative_current = (current_x - velocity[0], current_y - velocity[1], -velocity[2])
    speed = _norm(relative_current)
    if speed <= _MIN_SPEED_MPS:
        drag = (0.0, 0.0, 0.0)
    else:
        drag_scale = (
            0.5
            * _SEAWATER_DENSITY_KG_M3
            * cable.normal_drag_coefficient
            * cable.diameter_m
            * tributary_length_m
            * speed
        )
        drag = _mul(relative_current, drag_scale)
    weight = (0.0, 0.0, cable.submerged_weight_n_per_m * tributary_length_m)
    friction = _seabed_friction(case, cable, position, velocity, tributary_length_m)
    return _mul(_add(_add(weight, drag), friction), 1.0 / mass_per_node)


def _seabed_friction(
    case: DynamicCaseInput,
    cable,
    position: _Vector,
    velocity: _Vector,
    tributary_length_m: float,
) -> _Vector:
    if position[2] < case.water_depth_m * 0.98:
        return (0.0, 0.0, 0.0)
    horizontal_speed = math.hypot(velocity[0], velocity[1])
    if horizontal_speed <= _MIN_SPEED_MPS:
        return (0.0, 0.0, 0.0)
    normal_force = cable.submerged_weight_n_per_m * tributary_length_m
    friction = _SEABED_FRICTION_COEFFICIENT * normal_force
    return (
        -friction * velocity[0] / horizontal_speed,
        -friction * velocity[1] / horizontal_speed,
        0.0,
    )


def _apply_length_constraints(positions: list[_Vector], rest_length_m: float) -> list[_Vector]:
    constrained = list(positions)
    for _ in range(_CONSTRAINT_ITERATIONS):
        constrained[0] = (0.0, 0.0, 0.0)
        for index in range(len(constrained) - 1):
            left = constrained[index]
            right = constrained[index + 1]
            delta = _sub(right, left)
            length = _norm(delta)
            if length <= _MIN_SPEED_MPS:
                continue
            correction = _mul(delta, (length - rest_length_m) / length)
            if index == 0:
                constrained[index + 1] = _sub(right, correction)
            else:
                constrained[index] = _add(left, _mul(correction, 0.5))
                constrained[index + 1] = _sub(right, _mul(correction, 0.5))
    constrained[0] = (0.0, 0.0, 0.0)
    return constrained


def _sample_state(
    case: DynamicCaseInput,
    state: _LumpedState,
    time_s: float,
    integration_steps: int,
) -> tuple[TimeHistoryPoint, TimeHistoryFrame]:
    tensions = _shape_tensions(case, state, time_s)
    tdp = state.positions[-1]
    suspended_length = sum(
        _norm(_sub(right, left))
        for left, right in zip(state.positions, state.positions[1:])
    )
    history = TimeHistoryPoint(
        time_s=float(time_s),
        top_tension_n=float(tensions[0]),
        tdp_x_m=float(tdp[0]),
        tdp_y_m=float(tdp[1]),
        suspended_length_m=float(suspended_length),
        iterations=integration_steps,
    )
    frame = TimeHistoryFrame(
        time_s=float(time_s),
        points=[
            TimeHistoryFramePoint(
                index=index,
                x_m=float(position[0]),
                y_m=float(position[1]),
                z_m=float(position[2]),
                tension_n=float(tensions[index]),
            )
            for index, position in enumerate(state.positions)
        ],
    )
    return history, frame


def _shape_tensions(case: DynamicCaseInput, state: _LumpedState, time_s: float) -> list[float]:
    cable = get_cable("LA")
    vessel_speed = _vessel_speed(case, time_s)
    bottom_to_top = [case.touchdown_tension_n]
    running = case.touchdown_tension_n
    segment_lengths = [
        max(_norm(_sub(right, left)), _MIN_SPEED_MPS)
        for left, right in zip(state.positions, state.positions[1:])
    ]
    for index in reversed(range(len(segment_lengths))):
        left = state.positions[index]
        right = state.positions[index + 1]
        tangent = _mul(_sub(right, left), 1.0 / segment_lengths[index])
        current_x, current_y = _relative_current_components(case, vessel_speed)
        average_velocity = _mul(_add(state.velocities[index], state.velocities[index + 1]), 0.5)
        relative = (current_x - average_velocity[0], current_y - average_velocity[1], -average_velocity[2])
        along_tangent = _dot(relative, tangent)
        tangential_drag = (
            -0.5
            * math.pi
            * _SEAWATER_DENSITY_KG_M3
            * cable.tangential_drag_coefficient
            * cable.diameter_m
            * along_tangent
            * abs(along_tangent)
        )
        vertical_weight = cable.submerged_weight_n_per_m * segment_lengths[index] * max(tangent[2], 0.0)
        running += vertical_weight - tangential_drag * segment_lengths[index]
        bottom_to_top.append(max(running, 0.0))
    return list(reversed(bottom_to_top))


def _node_mass(case: DynamicCaseInput, rest_length_m: float) -> float:
    cable = get_cable("LA")
    mass = _dynamic_mass_per_meter(cable) * rest_length_m
    return max(mass, cable.weight_air_n_per_m / _GRAVITY_MPS2)


def _time_step_s(case: DynamicCaseInput) -> float:
    return max(_MIN_TIME_STEP_S, min(_MAX_TIME_STEP_S, case.total_duration_s / 6000.0))


def _clamp_water_column(case: DynamicCaseInput, position: _Vector) -> _Vector:
    return (
        position[0],
        position[1],
        min(max(position[2], 0.0), case.water_depth_m),
    )


def _add(a: _Vector, b: _Vector) -> _Vector:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: _Vector, b: _Vector) -> _Vector:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: _Vector, scalar: float) -> _Vector:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a: _Vector, b: _Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: _Vector) -> float:
    return math.sqrt(_dot(a, a))

"""Steady and quasi-static submarine cable tension solver.

This module deliberately treats validation targets as diagnostics, not as
values to fit. The 500 kV path now uses a 3D vector integration from the
touchdown point to the vessel elevation. Distributed loads come only from
submerged weight and Morison normal drag based on the input current profile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .kinematics import axial_strain
from .parameters import OperationCase


_SEAWATER_DENSITY_KG_M3 = 1025.0
_PROFILE_INTEGRATION_STEPS = 2000
_MIN_VECTOR_NORM = 1.0e-12

_Record = tuple[
    float,
    tuple[float, float, float],
    tuple[float, float, float],
    float,
]


@dataclass(frozen=True)
class ProfilePoint:
    """One point on a vessel-to-touchdown cable profile."""

    index: int
    arc_m: float
    x_m: float
    y_m: float
    z_m: float
    theta_rad: float
    psi_rad: float
    tangent_x: float
    tangent_y: float
    tangent_z: float
    current_x_mps: float
    current_y_mps: float
    current_z_mps: float
    drag_x_n_per_m: float
    drag_y_n_per_m: float
    drag_z_n_per_m: float
    tension_n: float


@dataclass(frozen=True)
class SolverResult:
    """Scalar result and sampled profile for one laying case."""

    case_name: str
    profile: list[ProfilePoint]
    top_tension_initial_n: float
    top_tension_min_n: float
    top_tension_final_n: float
    suspended_length_m: float
    layback_m: float


@dataclass(frozen=True)
class _IntegratedProfile:
    profile: list[ProfilePoint]
    top_tension_n: float
    suspended_length_m: float


def solve_case(case: OperationCase, *, points: int = 201) -> SolverResult:
    """Solve one laying case with the same 3D integration path.

    Cases without horizontal current or touchdown pretension naturally reduce
    to a vertical 3D equilibrium. They are not forced to paper table values.
    """

    if points < 2:
        raise ValueError("points must be at least 2")
    if case.water_depth_m <= 0.0:
        raise ValueError("water_depth_m must be positive")

    integrated = _integrate_3d_profile_from_touchdown(case, points=points)
    top_tension = integrated.top_tension_n

    return SolverResult(
        case_name=case.name,
        profile=integrated.profile,
        top_tension_initial_n=top_tension,
        top_tension_min_n=top_tension,
        top_tension_final_n=top_tension,
        suspended_length_m=integrated.suspended_length_m,
        layback_m=math.hypot(integrated.profile[-1].x_m, integrated.profile[-1].y_m),
    )


def _integrate_3d_profile_from_touchdown(case: OperationCase, *, points: int) -> _IntegratedProfile:
    """Integrate the suspended cable from TDP toward the vessel.

    Coordinate convention:
    - z is positive downward.
    - x is transverse current offset.
    - y is the laying direction.

    The touchdown pretension acts along the laying direction toward the
    vessel. At each arc-length step, equilibrium of the bottom-to-current
    segment gives ``T_next = T - q ds``, where ``q`` is the external load per
    meter from weight and current drag.
    """

    if case.cable.total_length_m <= 0.0:
        raise ValueError("cable total_length_m must be positive")
    if case.touchdown_tension_n < 0.0:
        raise ValueError("touchdown_tension_n must be non-negative")

    step_m = case.cable.total_length_m / _PROFILE_INTEGRATION_STEPS
    position = (0.0, 0.0, case.water_depth_m)
    tension = (0.0, -case.touchdown_tension_n, 0.0)
    tangent_fallback = (0.0, -1.0, 0.0) if case.touchdown_tension_n > 0.0 else (0.0, 0.0, -1.0)
    axial_tension = case.touchdown_tension_n
    records: list[_Record] = [(0.0, position, tension, axial_tension)]

    arc = 0.0
    for _ in range(_PROFILE_INTEGRATION_STEPS):
        tangent = _unit(tension, fallback=tangent_fallback)
        load = _distributed_load(case, tangent, position[2])
        axial_load = _axial_load_per_meter(case, tangent, position[2])
        strain = axial_strain(axial_tension, case.cable.axial_stiffness_n)
        segment_m = step_m * (1.0 + strain)
        next_tension = _sub(tension, _mul(load, segment_m))
        next_axial_tension = max(0.0, axial_tension + axial_load * segment_m)
        next_position = _add(position, _mul(tangent, segment_m))
        next_arc = arc + segment_m

        if next_position[2] <= 0.0:
            fraction = position[2] / max(position[2] - next_position[2], _MIN_VECTOR_NORM)
            surface_position = _add(position, _mul(_sub(next_position, position), fraction))
            surface_tension = _add(tension, _mul(_sub(next_tension, tension), fraction))
            surface_axial_tension = axial_tension + (next_axial_tension - axial_tension) * fraction
            surface_arc = arc + segment_m * fraction
            records.append((surface_arc, surface_position, surface_tension, surface_axial_tension))
            break

        records.append((next_arc, next_position, next_tension, next_axial_tension))
        arc = next_arc
        position = next_position
        tension = next_tension
        axial_tension = next_axial_tension
    else:
        raise ValueError("cable total_length_m is too short to reach the water surface")

    top_arc, top_position, _top_tension, top_axial_tension = records[-1]
    profile = _sample_integrated_profile(case, records, top_position, points)
    return _IntegratedProfile(
        profile=profile,
        top_tension_n=top_axial_tension,
        suspended_length_m=top_arc,
    )


def _distributed_load(
    case: OperationCase,
    tangent: tuple[float, float, float],
    depth_m: float,
) -> tuple[float, float, float]:
    """Return physical external load per meter in global x/y/z coordinates."""

    current = _current_vector_at_depth(case, depth_m)
    along = _dot(current, tangent)
    normal_current = _sub(current, _mul(tangent, along))
    normal_speed = _norm(normal_current)
    if normal_speed <= _MIN_VECTOR_NORM:
        drag = (0.0, 0.0, 0.0)
    else:
        drag_scale = (
            0.5
            * _SEAWATER_DENSITY_KG_M3
            * case.cable.normal_drag_coefficient
            * case.cable.diameter_m
            * normal_speed
        )
        drag = _mul(normal_current, drag_scale)
    return (drag[0], drag[1], case.cable.submerged_weight_n_per_m)


def _axial_load_per_meter(
    case: OperationCase,
    tangent: tuple[float, float, float],
    depth_m: float,
) -> float:
    """Return the load contribution that changes scalar axial tension."""

    current = _current_vector_at_depth(case, depth_m)
    relative_t = _dot(current, tangent) - (case.payout_speed_mps or 0.0)
    tangential_drag = (
        -0.5
        * math.pi
        * _SEAWATER_DENSITY_KG_M3
        * case.cable.tangential_drag_coefficient
        * case.cable.diameter_m
        * relative_t
        * abs(relative_t)
    )
    return -case.cable.submerged_weight_n_per_m * tangent[2] - tangential_drag


def _current_vector_at_depth(case: OperationCase, depth_m: float) -> tuple[float, float, float]:
    """Return the current vector from either profile or explicit components."""

    if case.current_surface_mps is not None and case.current_bottom_mps is not None:
        fraction = max(0.0, min(1.0, depth_m / case.water_depth_m))
        speed = case.current_surface_mps + (case.current_bottom_mps - case.current_surface_mps) * fraction
        direction = math.radians(case.current_direction_deg or 0.0)
        vessel_speed = case.vessel_speed_mps or 0.0
        return (speed * math.cos(direction) + vessel_speed, speed * math.sin(direction), 0.0)
    return (case.current_u_mps + (case.vessel_speed_mps or 0.0), case.current_v_mps, 0.0)


def _sample_integrated_profile(
    case: OperationCase,
    records: list[_Record],
    top_position: tuple[float, float, float],
    points: int,
) -> list[ProfilePoint]:
    """Sample bottom-to-top records as a vessel-to-TDP profile."""

    total_arc = records[-1][0]
    profile: list[ProfilePoint] = []
    for index in range(points):
        u = index / (points - 1)
        bottom_arc = total_arc * (1.0 - u)
        position, tension, axial_tension = _interpolate_record(records, bottom_arc)
        profile_tangent = _unit(_mul(tension, -1.0), fallback=(0.0, 0.0, 1.0))
        horizontal = math.hypot(profile_tangent[0], profile_tangent[1])
        theta = math.atan2(profile_tangent[2], horizontal if horizontal else _MIN_VECTOR_NORM)
        psi = math.atan2(profile_tangent[1], profile_tangent[0])
        current = _current_vector_at_depth(case, position[2])
        load = _distributed_load(case, profile_tangent, position[2])
        drag = (load[0], load[1], 0.0)

        relative = _sub(position, top_position)
        profile.append(
            ProfilePoint(
                index=index,
                arc_m=total_arc * u,
                x_m=relative[0],
                y_m=relative[1],
                z_m=max(0.0, relative[2]),
                theta_rad=theta,
                psi_rad=psi,
                tangent_x=profile_tangent[0],
                tangent_y=profile_tangent[1],
                tangent_z=profile_tangent[2],
                current_x_mps=current[0],
                current_y_mps=current[1],
                current_z_mps=current[2],
                drag_x_n_per_m=drag[0],
                drag_y_n_per_m=drag[1],
                drag_z_n_per_m=drag[2],
                tension_n=axial_tension,
            )
        )
    return profile


def _interpolate_record(
    records: list[_Record],
    target_arc: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float], float]:
    """Interpolate an integration record by bottom-origin arc length."""

    if target_arc <= records[0][0]:
        return records[0][1], records[0][2], records[0][3]
    if target_arc >= records[-1][0]:
        return records[-1][1], records[-1][2], records[-1][3]
    for left, right in zip(records, records[1:]):
        left_arc, left_position, left_tension, left_axial_tension = left
        right_arc, right_position, right_tension, right_axial_tension = right
        if left_arc <= target_arc <= right_arc:
            fraction = (target_arc - left_arc) / max(right_arc - left_arc, _MIN_VECTOR_NORM)
            return (
                _add(left_position, _mul(_sub(right_position, left_position), fraction)),
                _add(left_tension, _mul(_sub(right_tension, left_tension), fraction)),
                left_axial_tension + (right_axial_tension - left_axial_tension) * fraction,
            )
    return records[-1][1], records[-1][2], records[-1][3]


def _add(a, b) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, scalar: float) -> tuple[float, float, float]:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a, *, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = _norm(a)
    if magnitude <= _MIN_VECTOR_NORM:
        return fallback
    return _mul(a, 1.0 / magnitude)

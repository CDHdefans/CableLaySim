"""Unified current and Morison hydrodynamic loads."""

from __future__ import annotations

import math

from .geometry import Vector3


_MIN_NORM = 1.0e-12


def current_at(
    *,
    depth_m: float,
    water_depth_m: float,
    current_surface_mps: float | None = None,
    current_bottom_mps: float | None = None,
    current_direction_deg: float | None = None,
    current_u_mps: float = 0.0,
    current_v_mps: float = 0.0,
    vessel_speed_mps: float = 0.0,
) -> Vector3:
    """Return operation-frame current velocity at depth.

    When surface/bottom speeds are supplied, the current profile is linearly
    interpolated with depth and decomposed by direction angle. Otherwise the
    explicit ``u/v`` components are used. Direction angles use the engineering
    convention 0 deg = +X and 90 deg = +Y. ``vessel_speed_mps`` is a legacy
    apparent-water offset for vessel-fixed cases; known-plough runs pass zero
    so the returned value remains an operation-frame water velocity.
    """

    if water_depth_m <= 0.0:
        raise ValueError("water_depth_m must be positive")
    if current_surface_mps is not None and current_bottom_mps is not None:
        fraction = max(0.0, min(1.0, depth_m / water_depth_m))
        speed = current_surface_mps + (current_bottom_mps - current_surface_mps) * fraction
        direction = math.radians(current_direction_deg or 0.0)
        return (speed * math.cos(direction) + vessel_speed_mps, speed * math.sin(direction), 0.0)
    return (current_u_mps + vessel_speed_mps, current_v_mps, 0.0)


def morison_drag(
    *,
    seawater_density: float,
    diameter_m: float,
    segment_length_m: float,
    tangent: Vector3,
    relative_velocity: Vector3,
    tangential_coefficient: float,
    normal_coefficient: float,
) -> Vector3:
    """Return total Morison drag on one segment in global coordinates.

    ``relative_velocity`` is cable velocity relative to water. The returned
    force opposes that relative motion and separates tangential and normal
    components before recombining them in global coordinates.
    """

    if seawater_density <= 0.0:
        raise ValueError("seawater_density must be positive")
    if diameter_m <= 0.0:
        raise ValueError("diameter_m must be positive")
    if segment_length_m < 0.0:
        raise ValueError("segment_length_m must be non-negative")
    unit_tangent = _unit(tangent)
    relative_t_scalar = _dot(relative_velocity, unit_tangent)
    relative_t = _mul(unit_tangent, relative_t_scalar)
    relative_n = _sub(relative_velocity, relative_t)
    normal_speed = _norm(relative_n)
    tangential_force = _mul(
        unit_tangent,
        -0.5
        * math.pi
        * seawater_density
        * tangential_coefficient
        * diameter_m
        * segment_length_m
        * relative_t_scalar
        * abs(relative_t_scalar),
    )
    normal_force = (
        (0.0, 0.0, 0.0)
        if normal_speed <= _MIN_NORM
        else _mul(
            relative_n,
            -0.5
            * seawater_density
            * normal_coefficient
            * diameter_m
            * segment_length_m
            * normal_speed,
        )
    )
    return _add(tangential_force, normal_force)


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vector3, scalar: float) -> Vector3:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vector3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vector3) -> Vector3:
    magnitude = _norm(a)
    if magnitude <= _MIN_NORM:
        raise ValueError("tangent length must be positive")
    return _mul(a, 1.0 / magnitude)

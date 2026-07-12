"""Seabed contact constraints for node-based laying dynamics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .geometry import Vector3, interpolate_tdp


_MIN_SPEED = 1.0e-12
SEABED_CONTACT_TOLERANCE_M = 1.0e-3


@dataclass(frozen=True)
class ProjectionResult:
    """Node position and velocity after seabed projection."""

    point: Vector3
    velocity: Vector3
    in_contact: bool


@dataclass(frozen=True)
class TdpContact:
    """First cable node or segment point in seabed contact."""

    node_index: int
    segment_index: int
    point: Vector3
    fraction: float


@dataclass(frozen=True)
class SegmentContactProfile:
    """Material-arc reconstruction of a flat-seabed contact interval."""

    has_contact: bool
    segment_contact_fractions: tuple[float, ...]
    tdp_segment_index: int
    tdp_segment_fraction: float
    tdp_point: Vector3
    tdp_arc_length_m: float
    suspended_length_m: float
    contact_length_m: float
    normal_resultant_n: float


def project_to_seabed(
    *,
    point: Vector3,
    velocity: Vector3,
    seabed_depth_m: float,
) -> ProjectionResult:
    """Project a node that penetrates the seabed back onto ``z = H``."""

    if seabed_depth_m < 0.0:
        raise ValueError("seabed_depth_m must be non-negative")
    if point[2] >= seabed_depth_m:
        return ProjectionResult(
            point=(point[0], point[1], seabed_depth_m),
            velocity=(velocity[0], velocity[1], min(velocity[2], 0.0)),
            in_contact=True,
        )
    return ProjectionResult(point=point, velocity=velocity, in_contact=False)


def detect_tdp(*, nodes: Iterable[Vector3], seabed_depth_m: float) -> TdpContact:
    """Return the first point where the cable reaches seabed contact."""

    node_list = tuple(nodes)
    if len(node_list) < 2:
        raise ValueError("at least two nodes are required")
    interpolated = interpolate_tdp(node_list, seabed_depth_m=seabed_depth_m)
    node_index = min(
        range(len(node_list)),
        key=lambda index: abs(node_list[index][0] - interpolated.point[0])
        + abs(node_list[index][1] - interpolated.point[1])
        + abs(node_list[index][2] - interpolated.point[2]),
    )
    for index, node in enumerate(node_list):
        if node[2] >= seabed_depth_m:
            node_index = index
            break
    return TdpContact(
        node_index=node_index,
        segment_index=interpolated.segment_index,
        point=interpolated.point,
        fraction=interpolated.fraction,
    )


def build_segment_contact_profile(
    *,
    nodes: Iterable[Vector3],
    rest_lengths_m: Iterable[float],
    contact_flags: Iterable[bool],
    contact_normal_reactions_n: Iterable[float],
    seabed_depth_m: float,
) -> SegmentContactProfile:
    """Reconstruct the first flat-seabed contact transition on material arc.

    A penetrating transition uses the exact segment-plane intersection. Once
    hard projection has placed the first active node exactly on the plane, its
    lumped reaction represents a nodal control volume; the unresolved contact
    boundary is therefore placed at the adjacent segment midpoint.
    """

    node_list = tuple(nodes)
    rest_lengths = tuple(float(value) for value in rest_lengths_m)
    flags = tuple(bool(value) for value in contact_flags)
    reactions = tuple(float(value) for value in contact_normal_reactions_n)
    if len(node_list) < 2:
        raise ValueError("at least two nodes are required")
    if len(rest_lengths) != len(node_list) - 1:
        raise ValueError("rest_lengths_m must have one entry per segment")
    if len(flags) != len(node_list) or len(reactions) != len(node_list):
        raise ValueError("contact fields must have one entry per node")
    if seabed_depth_m < 0.0 or not math.isfinite(seabed_depth_m):
        raise ValueError("seabed_depth_m must be finite and non-negative")
    if any(length <= 0.0 or not math.isfinite(length) for length in rest_lengths):
        raise ValueError("rest_lengths_m must be finite and positive")
    if any(not math.isfinite(reaction) for reaction in reactions):
        raise ValueError("contact_normal_reactions_n must be finite")

    total_length = sum(rest_lengths)
    active = tuple(flag or reaction > 0.0 for flag, reaction in zip(flags, reactions))
    normal_resultant = sum(max(0.0, reaction) for reaction in reactions)
    first_active = next((index for index, value in enumerate(active) if value), None)
    if first_active is None:
        return SegmentContactProfile(
            has_contact=False,
            segment_contact_fractions=tuple(0.0 for _ in rest_lengths),
            tdp_segment_index=len(rest_lengths) - 1,
            tdp_segment_fraction=1.0,
            tdp_point=node_list[-1],
            tdp_arc_length_m=total_length,
            suspended_length_m=total_length,
            contact_length_m=0.0,
            normal_resultant_n=normal_resultant,
        )

    transition_segment = max(0, min(first_active - 1, len(rest_lengths) - 1))
    if first_active == 0:
        transition_fraction = 0.0
    else:
        start_gap = node_list[transition_segment][2] - seabed_depth_m
        end_gap = node_list[transition_segment + 1][2] - seabed_depth_m
        if start_gap < 0.0 < end_gap:
            transition_fraction = -start_gap / (end_gap - start_gap)
        else:
            transition_fraction = 0.5
    transition_fraction = max(0.0, min(1.0, transition_fraction))

    fractions = [0.0 for _ in rest_lengths]
    fractions[transition_segment] = 1.0 - transition_fraction
    for segment_index in range(transition_segment + 1, len(rest_lengths)):
        left_on_bed = node_list[segment_index][2] >= seabed_depth_m - SEABED_CONTACT_TOLERANCE_M
        right_on_bed = node_list[segment_index + 1][2] >= seabed_depth_m - SEABED_CONTACT_TOLERANCE_M
        left_supported = active[segment_index] or left_on_bed
        right_supported = active[segment_index + 1] or right_on_bed
        if left_supported and right_supported and (active[segment_index] or active[segment_index + 1]):
            fractions[segment_index] = 1.0
            continue
        break

    contact_length = sum(length * fraction for length, fraction in zip(rest_lengths, fractions))
    tdp_arc_length = sum(rest_lengths[:transition_segment]) + (
        transition_fraction * rest_lengths[transition_segment]
    )
    start = node_list[transition_segment]
    end = node_list[transition_segment + 1]
    tdp_point = (
        start[0] + transition_fraction * (end[0] - start[0]),
        start[1] + transition_fraction * (end[1] - start[1]),
        seabed_depth_m,
    )
    return SegmentContactProfile(
        has_contact=True,
        segment_contact_fractions=tuple(fractions),
        tdp_segment_index=transition_segment,
        tdp_segment_fraction=transition_fraction,
        tdp_point=tdp_point,
        tdp_arc_length_m=tdp_arc_length,
        suspended_length_m=max(0.0, total_length - contact_length),
        contact_length_m=contact_length,
        normal_resultant_n=normal_resultant,
    )


def seabed_friction(
    *,
    normal_force_n: float,
    tangential_velocity: Vector3,
    friction_coefficient: float,
) -> Vector3:
    """Return Coulomb friction opposing horizontal contact motion."""

    if normal_force_n <= 0.0 or friction_coefficient <= 0.0:
        return (0.0, 0.0, 0.0)
    horizontal = (tangential_velocity[0], tangential_velocity[1], 0.0)
    speed = math.hypot(horizontal[0], horizontal[1])
    if speed <= _MIN_SPEED:
        return (0.0, 0.0, 0.0)
    scale = -friction_coefficient * normal_force_n / speed
    return (horizontal[0] * scale, horizontal[1] * scale, 0.0)

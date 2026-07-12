"""Node-based cable geometry helpers.

The dynamic laying model uses node coordinates as the primary state. Angles
are derived outputs for comparison with paper notation and plotting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


Vector3 = tuple[float, float, float]

_MIN_LENGTH_M = 1.0e-12


@dataclass(frozen=True)
class SegmentVector:
    """Geometry for one segment between two cable nodes."""

    index: int
    start: Vector3
    end: Vector3
    delta: Vector3
    length_m: float
    tangent: Vector3


@dataclass(frozen=True)
class SegmentAngle:
    """Paper-style angles derived from a node segment."""

    index: int
    theta_rad: float
    psi_rad: float
    length_m: float


@dataclass(frozen=True)
class TdpIntersection:
    """Touchdown point interpolated from the first seabed crossing."""

    segment_index: int
    point: Vector3
    fraction: float


def segment_vectors(nodes: Iterable[Vector3]) -> list[SegmentVector]:
    """Return segment deltas, lengths and tangents for node coordinates."""

    node_list = tuple(nodes)
    if len(node_list) < 2:
        raise ValueError("at least two nodes are required")
    segments: list[SegmentVector] = []
    for index, (start, end) in enumerate(zip(node_list, node_list[1:])):
        delta = _sub(end, start)
        length = _norm(delta)
        if length <= _MIN_LENGTH_M:
            raise ValueError("segment length must be positive")
        tangent = _mul(delta, 1.0 / length)
        segments.append(
            SegmentVector(
                index=index,
                start=start,
                end=end,
                delta=delta,
                length_m=length,
                tangent=tangent,
            )
        )
    return segments


def segment_angles(nodes: Iterable[Vector3]) -> list[SegmentAngle]:
    """Return inclination and azimuth derived from node geometry."""

    angles: list[SegmentAngle] = []
    for segment in segment_vectors(nodes):
        tz = max(-1.0, min(1.0, segment.tangent[2]))
        theta = math.asin(tz)
        psi = math.atan2(segment.tangent[1], segment.tangent[0])
        angles.append(
            SegmentAngle(
                index=segment.index,
                theta_rad=theta,
                psi_rad=psi,
                length_m=segment.length_m,
            )
        )
    return angles


def interpolate_tdp(nodes: Iterable[Vector3], *, seabed_depth_m: float) -> TdpIntersection:
    """Interpolate the first point where the cable reaches the seabed.

    The project convention is ``z=0`` at the water surface and positive
    ``z`` downward, so seabed contact is ``z >= seabed_depth_m``.
    """

    node_list = tuple(nodes)
    if len(node_list) < 2:
        raise ValueError("at least two nodes are required")
    if seabed_depth_m < 0.0:
        raise ValueError("seabed_depth_m must be non-negative")
    if node_list[0][2] >= seabed_depth_m:
        return TdpIntersection(segment_index=0, point=node_list[0], fraction=0.0)
    for index, (start, end) in enumerate(zip(node_list, node_list[1:])):
        if end[2] >= seabed_depth_m:
            dz = end[2] - start[2]
            fraction = 1.0 if abs(dz) <= _MIN_LENGTH_M else (seabed_depth_m - start[2]) / dz
            fraction = max(0.0, min(1.0, fraction))
            point = _add(start, _mul(_sub(end, start), fraction))
            return TdpIntersection(segment_index=index, point=point, fraction=fraction)
    return TdpIntersection(segment_index=len(node_list) - 2, point=node_list[-1], fraction=1.0)


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

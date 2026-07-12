"""Node-coordinate dynamic laying model scaffold.

This module is the new engineering-oriented dynamic path. It treats node
coordinates and velocities as the primary unknowns, while the existing
angle-based reproduction remains available through ``legacy_dynamic.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .axial_constraints import axial_constraint_residual_m, solve_global_axial_constraint_step
from .contact import SEABED_CONTACT_TOLERANCE_M, build_segment_contact_profile, seabed_friction
from .geometry import Vector3, segment_vectors
from .hydrodynamics import current_at, morison_drag
from .parameters import OperationCase


_SEAWATER_DENSITY_KG_M3 = 1025.0
_GRAVITY_MPS2 = 9.8
_MIN_MASS = 1.0e-12
_MIN_LENGTH = 1.0e-12
_SEABED_CONTACT_TOLERANCE_M = SEABED_CONTACT_TOLERANCE_M
_SEABED_FRICTION_COEFFICIENT = 0.6
_MAX_NODE_CFL_FRACTION = 0.25
_MIN_INTERNAL_TIME_STEP_S = 1.0e-4
_TANGENT_CONTINUITY_RELAXATION = 0.45
_TANGENT_CONTINUITY_DOT_LIMIT = 0.25
_SEGMENT_SPACING_FLOOR_FRACTION = 0.25
_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES = 2
_KNOWN_PLOUGH_XPBD_MIN_ITERATIONS = 1
_KNOWN_PLOUGH_XPBD_ITERATIONS = 100
_KNOWN_PLOUGH_AXIAL_RESIDUAL_TOLERANCE_M = 1.0e-10
_REMESH_PROJECTION_MAX_ITERATIONS = 6000
_REMESH_PROJECTION_REL_TOLERANCE = 1.0e-12


@dataclass(frozen=True)
class DynamicLayingState:
    """State for a node-based laying simulation."""

    time_s: float
    positions: tuple[Vector3, ...]
    velocities: tuple[Vector3, ...]
    rest_lengths_m: tuple[float, ...]
    paid_length_m: float
    laid_length_m: float
    contact_flags: tuple[bool, ...]
    length_lambdas_n_s2: tuple[float, ...] = ()
    contact_lambdas_n_s2: tuple[float, ...] = ()
    segment_tensions_n: tuple[float, ...] = ()
    length_constraint_reactions_n: tuple[float, ...] = ()
    contact_normal_reactions_n: tuple[float, ...] = ()
    payout_buffer_m: float = 0.0
    laydown_buffer_m: float = 0.0
    laid_segment_lengths_m: tuple[float, ...] = ()
    material_suspended_length_m: float = 0.0
    geometric_length_deficit_m: float = 0.0
    axial_solve_iterations: int = 0
    axial_constraint_residual_m: float = 0.0

    @property
    def suspended_length_m(self) -> float:
        """Suspended length follows the payout continuity state."""

        return max(0.0, self.paid_length_m - self.laid_length_m)


@dataclass(frozen=True)
class DynamicLayingResult:
    """Time-marching result for the node-coordinate laying path."""

    states: list[DynamicLayingState]
    evidence_level: str


@dataclass(frozen=True)
class _BendRadiusDiagnostic:
    radius_m: float
    node_index: int | None = None
    left_segment_m: float | None = None
    right_segment_m: float | None = None
    turn_angle_deg: float | None = None
    node_depth_m: float | None = None
    near_seabed: bool | None = None


@dataclass
class KnownPloughRuntime:
    """Persistent state and diagnostics for incremental known-plough solves."""

    state: DynamicLayingState
    cable: object
    time_s: float
    dt_max_s: float
    steps: int
    integration_time_step_min_s: float | None
    integration_time_step_max_s: float | None
    axial_iterations_min: int | None
    axial_iterations_max: int | None
    axial_constraint_residual_max_m: float | None
    bend_radius_diagnostic: _BendRadiusDiagnostic
    bend_radius_min_m: float
    bend_radius_time_s: float | None
    raw_bend_radius_diagnostic: _BendRadiusDiagnostic
    raw_bend_radius_min_m: float
    raw_bend_radius_time_s: float | None


@dataclass(frozen=True)
class KnownPloughSample:
    """One output sample generated from a persistent known-plough state."""

    point: object
    frame: object


def _optional_min(current, value):
    return value if current is None else min(current, value)


def _optional_max(current, value):
    return value if current is None else max(current, value)


def initialize_from_static(
    static_result,
    *,
    paid_length_m: float | None = None,
    laid_length_m: float = 0.0,
) -> DynamicLayingState:
    """Build a node state from an existing quasi-static profile result."""

    positions = tuple((point.x_m, point.y_m, point.z_m) for point in static_result.profile)
    lengths = tuple(segment.length_m for segment in segment_vectors(positions))
    paid = sum(lengths) + laid_length_m if paid_length_m is None else paid_length_m
    return DynamicLayingState(
        time_s=0.0,
        positions=positions,
        velocities=tuple((0.0, 0.0, 0.0) for _ in positions),
        rest_lengths_m=lengths,
        paid_length_m=paid,
        laid_length_m=laid_length_m,
        contact_flags=tuple(False for _ in positions),
    )


def compute_forces(
    case: OperationCase,
    state: DynamicLayingState,
    *,
    seabed_depth_m: float | None = None,
    payout_speed_mps: float | None = None,
    plough_exit_speed_mps: float | None = None,
    seabed_friction_coefficient: float = _SEABED_FRICTION_COEFFICIENT,
    include_axial_tension: bool = True,
) -> tuple[Vector3, ...]:
    """Compute nodal forces from axial tension, weight, drag and contact."""

    _validate_state(state)
    payout_speed = (
        payout_speed_mps
        if payout_speed_mps is not None
        else case.payout_speed_mps
        if case.payout_speed_mps is not None
        else 0.0
    )
    forces = [(0.0, 0.0, 0.0) for _ in state.positions]
    segments = segment_vectors(state.positions)
    segment_material_speeds = _segment_material_flow_speeds(
        state.rest_lengths_m,
        fairlead_speed_mps=payout_speed,
        plough_speed_mps=plough_exit_speed_mps,
    )
    for segment, rest_length, material_speed in zip(
        segments,
        state.rest_lengths_m,
        segment_material_speeds,
    ):
        left = segment.index
        right = left + 1
        if include_axial_tension:
            axial_tension = _segment_tension(case, segment.length_m, rest_length)
            axial_force = _mul(segment.tangent, axial_tension)
            forces[left] = _add(forces[left], axial_force)
            forces[right] = _sub(forces[right], axial_force)

        midpoint_depth = 0.5 * (segment.start[2] + segment.end[2])
        midpoint_velocity = _mul(_add(state.velocities[left], state.velocities[right]), 0.5)
        material_velocity = _segment_material_velocity(
            node_velocity=midpoint_velocity,
            tangent=segment.tangent,
            payout_speed_mps=material_speed,
        )
        water_velocity = current_at(
            depth_m=midpoint_depth,
            water_depth_m=case.water_depth_m,
            current_surface_mps=case.current_surface_mps,
            current_bottom_mps=case.current_bottom_mps,
            current_direction_deg=case.current_direction_deg,
            current_u_mps=case.current_u_mps,
            current_v_mps=case.current_v_mps,
            vessel_speed_mps=case.vessel_speed_mps or 0.0,
        )
        relative_velocity = _sub(material_velocity, water_velocity)
        drag = morison_drag(
            seawater_density=_SEAWATER_DENSITY_KG_M3,
            diameter_m=case.cable.diameter_m,
            segment_length_m=segment.length_m,
            tangent=segment.tangent,
            relative_velocity=relative_velocity,
            tangential_coefficient=case.cable.tangential_drag_coefficient,
            normal_coefficient=case.cable.normal_drag_coefficient,
        )
        weight = (0.0, 0.0, case.cable.submerged_weight_n_per_m * rest_length)
        segment_force = _add(drag, weight)
        half = _mul(segment_force, 0.5)
        forces[left] = _add(forces[left], half)
        forces[right] = _add(forces[right], half)
    if seabed_depth_m is not None:
        node_material_speeds = _node_material_flow_speeds(
            state.rest_lengths_m,
            fairlead_speed_mps=payout_speed,
            plough_speed_mps=plough_exit_speed_mps,
        )
        for index, (force, position, contact) in enumerate(zip(forces, state.positions, state.contact_flags)):
            if contact or position[2] >= seabed_depth_m:
                normal_reaction = max(force[2], 0.0)
                material_velocity = _add(
                    state.velocities[index],
                    _mul(_node_tangent(segments, index), node_material_speeds[index]),
                )
                friction = seabed_friction(
                    normal_force_n=normal_reaction,
                    tangential_velocity=material_velocity,
                    friction_coefficient=seabed_friction_coefficient,
                )
                forces[index] = _add((force[0], force[1], min(force[2], 0.0)), friction)
    return tuple(forces)


def step_dynamic(
    case: OperationCase,
    state: DynamicLayingState,
    *,
    dt_s: float,
    payout_speed_mps: float | None = None,
    seabed_depth_m: float | None = None,
    length_projection_iterations: int = 1,
    xpbd_iterations: int | None = None,
    target_segment_length_m: float | None = None,
    seabed_friction_coefficient: float = _SEABED_FRICTION_COEFFICIENT,
    remove_laid_segments: bool = True,
    enforce_chain_lengths: bool = False,
    top_tangent_boundary: Vector3 | None = None,
) -> DynamicLayingState:
    """Advance the node-coordinate dynamic state with XPBD constraints."""

    if dt_s <= 0.0:
        raise ValueError("dt_s must be positive")
    _validate_state(state)
    seabed = case.water_depth_m if seabed_depth_m is None else seabed_depth_m
    payout_speed = (
        payout_speed_mps
        if payout_speed_mps is not None
        else case.payout_speed_mps
        if case.payout_speed_mps is not None
        else case.final_speed_mps
    )
    paid_length = state.paid_length_m + payout_speed * dt_s
    target_segment = _target_segment_length(state.rest_lengths_m, target_segment_length_m)
    remeshed = _insert_payout_nodes(
        state,
        payout_increment_m=max(payout_speed, 0.0) * dt_s,
        target_segment_length_m=target_segment,
    )
    previous_positions = remeshed.positions
    forces = compute_forces(
        case,
        remeshed,
        seabed_depth_m=None,
        payout_speed_mps=payout_speed,
        include_axial_tension=False,
    )
    masses = _node_masses(case, remeshed)
    inverse_masses = tuple(0.0 if index == 0 else 1.0 / max(mass, _MIN_MASS) for index, mass in enumerate(masses))
    predicted_velocities = tuple(
        _add(velocity, _mul(force, dt_s / max(mass, _MIN_MASS)))
        for velocity, force, mass in zip(remeshed.velocities, forces, masses)
    )
    predicted_velocities = ((0.0, 0.0, 0.0),) + predicted_velocities[1:]
    predicted_velocities = _limit_node_velocities(predicted_velocities, remeshed.rest_lengths_m, dt_s)
    predicted_positions = tuple(
        _add(position, _mul(velocity, dt_s))
        for position, velocity in zip(remeshed.positions, predicted_velocities)
    )
    predicted_positions = ((0.0, 0.0, 0.0),) + predicted_positions[1:]
    iterations = xpbd_iterations if xpbd_iterations is not None else max(4, length_projection_iterations)
    constrained_positions, length_lambdas, contact_lambdas = _solve_xpbd_constraints(
        case,
        positions=predicted_positions,
        rest_lengths_m=remeshed.rest_lengths_m,
        contact_flags=remeshed.contact_flags,
        inverse_masses=inverse_masses,
        seabed_depth_m=seabed,
        dt_s=dt_s,
        iterations=iterations,
    )
    contact_normal_reactions = tuple(
        _contact_normal_reaction_from_constraint_or_load(
            index=index,
            lambda_value=lambda_value,
            dt_s=dt_s,
            contact=index < len(remeshed.contact_flags) and remeshed.contact_flags[index],
            force=forces[index],
        )
        for index, lambda_value in enumerate(contact_lambdas)
    )
    segment_tensions = tuple(max(0.0, lambda_value / (dt_s * dt_s)) for lambda_value in length_lambdas)
    contact_flags = tuple(
        index > 0
        and (
            remeshed.contact_flags[index]
            or position[2] >= seabed - _SEABED_CONTACT_TOLERANCE_M
            or contact_normal_reactions[index] > 0.0
        )
        for index, position in enumerate(constrained_positions)
    )
    constrained_velocities = [
        _mul(_sub(position, previous), 1.0 / dt_s)
        for previous, position in zip(previous_positions, constrained_positions)
    ]
    constrained_velocities[0] = (0.0, 0.0, 0.0)
    constrained_velocities = list(_limit_node_velocities(tuple(constrained_velocities), remeshed.rest_lengths_m, dt_s))
    friction_positions, friction_velocities = _apply_contact_friction(
        positions=constrained_positions,
        previous_positions=previous_positions,
        velocities=tuple(constrained_velocities),
        contact_flags=contact_flags,
        contact_normal_reactions_n=contact_normal_reactions,
        masses=masses,
        payout_speed_mps=payout_speed,
        dt_s=dt_s,
        friction_coefficient=seabed_friction_coefficient,
    )
    if enforce_chain_lengths:
        friction_positions, friction_velocities = _enforce_chain_lengths_from_top(
            positions=friction_positions,
            previous_positions=previous_positions,
            rest_lengths_m=remeshed.rest_lengths_m,
            dt_s=dt_s,
            iterations=2,
            contact_flags=contact_flags,
            seabed_depth_m=seabed,
            top_tangent_boundary=top_tangent_boundary,
        )
        contact_flags = _contact_flags_from_positions(friction_positions, seabed)
    segment_tensions = _step_dynamic_segment_tensions(
        case,
        positions=friction_positions,
        velocities=friction_velocities,
        rest_lengths_m=remeshed.rest_lengths_m,
        payout_speed_mps=payout_speed,
    )
    laid_length = state.laid_length_m
    laid_segments = remeshed.laid_segment_lengths_m
    laydown_buffer = _stable_tail_contact_length(remeshed.rest_lengths_m, contact_flags)
    rest_lengths_m = remeshed.rest_lengths_m
    positions = friction_positions
    velocities = friction_velocities
    if remove_laid_segments:
        (
            positions,
            velocities,
            rest_lengths_m,
            contact_flags,
            length_lambdas,
            contact_lambdas,
            segment_tensions,
            contact_normal_reactions,
            laid_length,
            laydown_buffer,
            laid_segments,
        ) = _remove_stable_laid_bottom_segment(
            positions=positions,
            velocities=velocities,
            rest_lengths_m=rest_lengths_m,
            contact_flags=contact_flags,
            length_lambdas_n_s2=length_lambdas,
            contact_lambdas_n_s2=contact_lambdas,
            segment_tensions_n=segment_tensions,
            contact_normal_reactions_n=contact_normal_reactions,
            laid_length_m=laid_length,
            laydown_buffer_m=laydown_buffer,
            laid_segment_lengths_m=laid_segments,
            paid_length_m=paid_length,
        )
    return DynamicLayingState(
        time_s=state.time_s + dt_s,
        positions=positions,
        velocities=velocities,
        rest_lengths_m=rest_lengths_m,
        paid_length_m=paid_length,
        laid_length_m=laid_length,
        contact_flags=tuple(contact_flags),
        length_lambdas_n_s2=length_lambdas,
        contact_lambdas_n_s2=contact_lambdas,
        segment_tensions_n=segment_tensions,
        contact_normal_reactions_n=contact_normal_reactions,
        payout_buffer_m=remeshed.payout_buffer_m,
        laydown_buffer_m=laydown_buffer,
        laid_segment_lengths_m=laid_segments,
    )


def _contact_normal_reaction_from_constraint_or_load(
    *,
    index: int,
    lambda_value: float,
    dt_s: float,
    contact: bool,
    force: Vector3,
) -> float:
    constraint_reaction = lambda_value / (dt_s * dt_s)
    if index == 0 or not contact:
        return max(0.0, constraint_reaction)
    return max(0.0, constraint_reaction, force[2])


def _target_segment_length(
    rest_lengths_m: tuple[float, ...],
    requested_length_m: float | None,
) -> float:
    if requested_length_m is not None:
        if requested_length_m <= 0.0:
            raise ValueError("target_segment_length_m must be positive")
        return requested_length_m
    positive_lengths = sorted(length for length in rest_lengths_m if length > _MIN_LENGTH)
    if not positive_lengths:
        return 1.0
    return positive_lengths[len(positive_lengths) // 2]


def _insert_payout_nodes(
    state: DynamicLayingState,
    *,
    payout_increment_m: float,
    target_segment_length_m: float,
) -> DynamicLayingState:
    positions = list(state.positions)
    velocities = list(state.velocities)
    rest_lengths = list(state.rest_lengths_m)
    contact_flags = list(state.contact_flags)
    length_lambdas = _padded_values(state.length_lambdas_n_s2, len(rest_lengths))
    segment_tensions = _padded_values(state.segment_tensions_n, len(rest_lengths))
    length_reactions = _padded_values(state.length_constraint_reactions_n, len(rest_lengths))
    contact_lambdas = _padded_values(state.contact_lambdas_n_s2, len(positions))
    contact_reactions = _padded_values(state.contact_normal_reactions_n, len(positions))
    payout_increment = max(0.0, state.payout_buffer_m + payout_increment_m)
    should_split_top = payout_increment > _MIN_LENGTH
    if payout_increment > _MIN_LENGTH:
        rest_lengths[0] += payout_increment
    split_count = 0
    while should_split_top and rest_lengths and rest_lengths[0] > 1.5 * target_segment_length_m:
        if split_count > 10000:
            raise RuntimeError("payout remesh inserted too many nodes in one step")
        material_fraction = target_segment_length_m / rest_lengths[0]
        new_position = _add(
            positions[0],
            _mul(_sub(positions[1], positions[0]), material_fraction),
        )
        new_velocity = _add(
            velocities[0],
            _mul(_sub(velocities[1], velocities[0]), material_fraction),
        )
        remaining_length = rest_lengths[0] - target_segment_length_m
        top_lambda = length_lambdas[0] if length_lambdas else 0.0
        top_tension = segment_tensions[0] if segment_tensions else 0.0
        top_reaction = length_reactions[0] if length_reactions else 0.0
        positions = [positions[0], new_position] + positions[1:]
        velocities = [velocities[0], new_velocity] + velocities[1:]
        rest_lengths = [target_segment_length_m, remaining_length] + rest_lengths[1:]
        contact_flags = [False, False] + contact_flags[1:]
        length_lambdas = [top_lambda, top_lambda] + length_lambdas[1:]
        segment_tensions = [top_tension, top_tension] + segment_tensions[1:]
        length_reactions = [top_reaction, top_reaction] + length_reactions[1:]
        contact_lambdas = [contact_lambdas[0] if contact_lambdas else 0.0, 0.0] + contact_lambdas[1:]
        contact_reactions = [contact_reactions[0] if contact_reactions else 0.0, 0.0] + contact_reactions[1:]
        split_count += 1
    return DynamicLayingState(
        time_s=state.time_s,
        positions=tuple(positions),
        velocities=tuple(velocities),
        rest_lengths_m=tuple(rest_lengths),
        paid_length_m=state.paid_length_m,
        laid_length_m=state.laid_length_m,
        contact_flags=tuple(contact_flags),
        length_lambdas_n_s2=tuple(length_lambdas),
        contact_lambdas_n_s2=tuple(contact_lambdas),
        segment_tensions_n=tuple(segment_tensions),
        length_constraint_reactions_n=tuple(length_reactions),
        contact_normal_reactions_n=tuple(contact_reactions),
        payout_buffer_m=0.0,
        laydown_buffer_m=state.laydown_buffer_m,
        laid_segment_lengths_m=state.laid_segment_lengths_m,
        material_suspended_length_m=state.material_suspended_length_m,
        geometric_length_deficit_m=state.geometric_length_deficit_m,
    )


def _limit_node_velocities(
    velocities: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    dt_s: float,
) -> tuple[Vector3, ...]:
    limited: list[Vector3] = []
    for index, velocity in enumerate(velocities):
        if index == 0:
            limited.append((0.0, 0.0, 0.0))
            continue
        speed = _norm(velocity)
        if speed <= _MIN_LENGTH or not math.isfinite(speed):
            limited.append((0.0, 0.0, 0.0))
            continue
        local_length = _local_segment_length(index, rest_lengths_m)
        max_speed = _MAX_NODE_CFL_FRACTION * local_length / max(dt_s, _MIN_LENGTH)
        if speed <= max_speed:
            limited.append(velocity)
            continue
        limited.append(_mul(velocity, max_speed / speed))
    return tuple(limited)


def _local_segment_length(index: int, rest_lengths_m: tuple[float, ...]) -> float:
    adjacent: list[float] = []
    if index > 0 and index - 1 < len(rest_lengths_m):
        adjacent.append(rest_lengths_m[index - 1])
    if index < len(rest_lengths_m):
        adjacent.append(rest_lengths_m[index])
    positive = [length for length in adjacent if length > _MIN_LENGTH]
    if not positive:
        return 1.0
    return min(positive)


def _solve_xpbd_constraints(
    case: OperationCase,
    *,
    positions: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    contact_flags: tuple[bool, ...],
    inverse_masses: tuple[float, ...],
    seabed_depth_m: float,
    dt_s: float,
    iterations: int,
) -> tuple[tuple[Vector3, ...], tuple[float, ...], tuple[float, ...]]:
    solved = list(positions)
    solved[0] = (0.0, 0.0, 0.0)
    length_lambdas = [0.0 for _ in rest_lengths_m]
    contact_lambdas = [0.0 for _ in solved]
    dt2 = dt_s * dt_s
    axial_stiffness = max(case.cable.axial_stiffness_n, _MIN_MASS)
    for _ in range(max(1, iterations)):
        for index, rest_length in enumerate(rest_lengths_m):
            start = solved[index]
            end = solved[index + 1]
            delta = _sub(end, start)
            length = _norm(delta)
            if length <= _MIN_LENGTH:
                continue
            constraint = length - rest_length
            if constraint <= 0.0:
                length_lambdas[index] = 0.0
                continue
            wi = inverse_masses[index]
            wj = inverse_masses[index + 1]
            compliance = rest_length / (axial_stiffness * dt2)
            denominator = wi + wj + compliance
            if denominator <= _MIN_MASS:
                continue
            delta_lambda = (constraint - compliance * length_lambdas[index]) / denominator
            next_lambda = max(0.0, length_lambdas[index] + delta_lambda)
            applied_lambda = next_lambda - length_lambdas[index]
            direction = _mul(delta, 1.0 / length)
            solved[index] = _add(start, _mul(direction, wi * applied_lambda))
            solved[index + 1] = _sub(end, _mul(direction, wj * applied_lambda))
            length_lambdas[index] = next_lambda
        solved[0] = (0.0, 0.0, 0.0)
        for index in range(1, len(solved)):
            persisted_contact = index < len(contact_flags) and contact_flags[index]
            penetration = solved[index][2] - seabed_depth_m
            if not persisted_contact and penetration <= 0.0:
                continue
            wi = inverse_masses[index]
            if wi <= _MIN_MASS:
                continue
            if penetration > 0.0:
                delta_lambda = penetration / wi
                contact_lambdas[index] += delta_lambda
            solved[index] = (solved[index][0], solved[index][1], seabed_depth_m)
        solved[0] = (0.0, 0.0, 0.0)
    return tuple(solved), tuple(length_lambdas), tuple(contact_lambdas)


def _padded_values(values: tuple[float, ...], count: int) -> list[float]:
    padded = list(values[:count])
    if len(padded) < count:
        padded.extend(0.0 for _ in range(count - len(padded)))
    return padded


def _apply_contact_friction(
    *,
    positions: tuple[Vector3, ...],
    previous_positions: tuple[Vector3, ...],
    velocities: tuple[Vector3, ...],
    contact_flags: tuple[bool, ...],
    contact_normal_reactions_n: tuple[float, ...],
    masses: tuple[float, ...],
    payout_speed_mps: float,
    rest_lengths_m: tuple[float, ...] = (),
    plough_exit_speed_mps: float | None = None,
    dt_s: float,
    friction_coefficient: float,
    update_positions: bool = True,
) -> tuple[tuple[Vector3, ...], tuple[Vector3, ...]]:
    if friction_coefficient <= 0.0:
        return positions, velocities
    next_positions = list(positions)
    next_velocities = list(velocities)
    try:
        segments = segment_vectors(positions)
    except ValueError:
        segments = []
    if rest_lengths_m and len(rest_lengths_m) != len(positions) - 1:
        raise ValueError("rest_lengths_m must have one entry per segment")
    node_material_speeds = (
        _node_material_flow_speeds(
            rest_lengths_m,
            fairlead_speed_mps=payout_speed_mps,
            plough_speed_mps=plough_exit_speed_mps,
        )
        if rest_lengths_m
        else tuple(payout_speed_mps for _ in positions)
    )
    for index, contact in enumerate(contact_flags):
        if index == 0 or not contact:
            continue
        normal_reaction = contact_normal_reactions_n[index] if index < len(contact_normal_reactions_n) else 0.0
        if normal_reaction <= 0.0:
            continue
        tangent = _node_tangent(segments, index)
        material_velocity = _add(next_velocities[index], _mul(tangent, node_material_speeds[index]))
        horizontal_speed = math.hypot(material_velocity[0], material_velocity[1])
        if horizontal_speed <= _MIN_LENGTH:
            continue
        max_delta_v = friction_coefficient * normal_reaction * dt_s / max(masses[index], _MIN_MASS)
        delta_v = min(horizontal_speed, max_delta_v)
        correction = (-material_velocity[0] / horizontal_speed * delta_v, -material_velocity[1] / horizontal_speed * delta_v, 0.0)
        velocity = next_velocities[index]
        next_velocity = (velocity[0] + correction[0], velocity[1] + correction[1], min(velocity[2], 0.0))
        next_velocities[index] = next_velocity
        if not update_positions:
            continue
        previous = previous_positions[index]
        position = next_positions[index]
        next_positions[index] = (
            previous[0] + next_velocity[0] * dt_s,
            previous[1] + next_velocity[1] * dt_s,
            position[2],
        )
    next_velocities[0] = (0.0, 0.0, 0.0)
    next_positions[0] = (0.0, 0.0, 0.0)
    return tuple(next_positions), tuple(next_velocities)


def _enforce_chain_lengths_from_top(
    *,
    positions: tuple[Vector3, ...],
    previous_positions: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    dt_s: float,
    iterations: int,
    contact_flags: tuple[bool, ...] = (),
    seabed_depth_m: float | None = None,
    top_tangent_boundary: Vector3 | None = None,
) -> tuple[tuple[Vector3, ...], tuple[Vector3, ...]]:
    corrected = list(positions)
    top_direction = _safe_unit(top_tangent_boundary) if top_tangent_boundary is not None else None
    for _ in range(max(1, iterations)):
        corrected[0] = (0.0, 0.0, 0.0)
        previous_direction: Vector3 | None = top_direction
        for index, rest_length in enumerate(rest_lengths_m):
            start = corrected[index]
            end = corrected[index + 1]
            delta = _sub(end, start)
            length = _norm(delta)
            if index == 0 and top_direction is not None:
                direction = top_direction
            elif length <= _MIN_LENGTH:
                direction = (0.0, 0.0, 1.0)
            else:
                direction = _mul(delta, 1.0 / length)
            if (
                index > 0
                and previous_direction is not None
                and _dot(direction, previous_direction) < _TANGENT_CONTINUITY_DOT_LIMIT
            ):
                direction = _safe_unit(
                    _add(
                        _mul(direction, 1.0 - _TANGENT_CONTINUITY_RELAXATION),
                        _mul(previous_direction, _TANGENT_CONTINUITY_RELAXATION),
                    )
                )
            next_position = _add(start, _mul(direction, rest_length))
            if next_position[2] + 1.0e-9 < start[2]:
                horizontal = _horizontal_unit(_sub(next_position, start), fallback=(direction[0], direction[1]))
                next_position = (
                    start[0] + horizontal[0] * rest_length,
                    start[1] + horizontal[1] * rest_length,
                    start[2],
                )
            if next_position[2] < 0.0:
                horizontal = _horizontal_unit(_sub(next_position, start), fallback=(1.0, 0.0))
                vertical_gap = max(start[2], 0.0)
                horizontal_length = math.sqrt(max(rest_length * rest_length - vertical_gap * vertical_gap, 0.0))
                next_position = (
                    start[0] + horizontal[0] * horizontal_length,
                    start[1] + horizontal[1] * horizontal_length,
                    0.0,
                )
            corrected[index + 1] = next_position
            accepted_delta = _sub(next_position, start)
            previous_direction = _safe_unit(accepted_delta)
    if seabed_depth_m is not None and contact_flags:
        corrected = _pin_contact_tail_to_seabed(
            positions=tuple(corrected),
            rest_lengths_m=rest_lengths_m,
            contact_flags=contact_flags,
            seabed_depth_m=seabed_depth_m,
        )
    corrected = _enforce_monotonic_depths(corrected, rest_lengths_m)
    velocities = tuple(
        (0.0, 0.0, 0.0) if index == 0 else _mul(_sub(position, previous), 1.0 / dt_s)
        for index, (previous, position) in enumerate(zip(previous_positions, corrected))
    )
    return tuple(corrected), velocities


def _enforce_monotonic_depths(
    positions: list[Vector3],
    rest_lengths_m: tuple[float, ...],
) -> list[Vector3]:
    corrected = list(positions)
    for index, rest_length in enumerate(rest_lengths_m):
        start = corrected[index]
        end = corrected[index + 1]
        if end[2] + 1.0e-9 >= start[2]:
            continue
        horizontal = _horizontal_unit(_sub(end, start), fallback=(1.0, 0.0))
        corrected[index + 1] = (
            start[0] + horizontal[0] * rest_length,
            start[1] + horizontal[1] * rest_length,
            start[2],
        )
    return corrected


def _pin_contact_tail_to_seabed(
    *,
    positions: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    contact_flags: tuple[bool, ...],
    seabed_depth_m: float,
) -> list[Vector3]:
    corrected = list(positions)
    contact_index = _first_reachable_contact_index(corrected, rest_lengths_m, contact_flags, seabed_depth_m)
    if contact_index is None:
        return _pin_tail_end_to_seabed(
            positions=tuple(corrected),
            rest_lengths_m=rest_lengths_m,
            seabed_depth_m=seabed_depth_m,
        )

    previous_horizontal = _horizontal_unit(_sub(corrected[contact_index], corrected[contact_index - 1]), fallback=(1.0, 0.0))
    start = corrected[contact_index - 1]
    rest_length = rest_lengths_m[contact_index - 1]
    vertical_gap = max(0.0, seabed_depth_m - start[2])
    horizontal_length = math.sqrt(max(rest_length * rest_length - vertical_gap * vertical_gap, 0.0))
    corrected[contact_index] = (
        start[0] + previous_horizontal[0] * horizontal_length,
        start[1] + previous_horizontal[1] * horizontal_length,
        seabed_depth_m,
    )

    for index in range(contact_index + 1, len(corrected)):
        segment_delta = _sub(corrected[index], corrected[index - 1])
        previous_horizontal = _horizontal_unit(segment_delta, fallback=previous_horizontal)
        rest_length = rest_lengths_m[index - 1]
        start = corrected[index - 1]
        corrected[index] = (
            start[0] + previous_horizontal[0] * rest_length,
            start[1] + previous_horizontal[1] * rest_length,
            seabed_depth_m,
        )
    return corrected


def _pin_tail_end_to_seabed(
    *,
    positions: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    seabed_depth_m: float,
) -> list[Vector3]:
    corrected = list(positions)
    start_index = _latest_tail_start_that_can_reach_seabed(corrected, rest_lengths_m, seabed_depth_m)
    if start_index is None:
        return corrected
    remaining_length = sum(rest_lengths_m[start_index:])
    start = corrected[start_index]
    vertical_gap = max(0.0, seabed_depth_m - start[2])
    horizontal_length = math.sqrt(max(remaining_length * remaining_length - vertical_gap * vertical_gap, 0.0))
    horizontal = _horizontal_unit(_sub(corrected[-1], start), fallback=(1.0, 0.0))
    direction = (
        horizontal[0] * horizontal_length / max(remaining_length, _MIN_LENGTH),
        horizontal[1] * horizontal_length / max(remaining_length, _MIN_LENGTH),
        vertical_gap / max(remaining_length, _MIN_LENGTH),
    )
    for index in range(start_index, len(rest_lengths_m)):
        corrected[index + 1] = _add(corrected[index], _mul(direction, rest_lengths_m[index]))
    corrected[-1] = (corrected[-1][0], corrected[-1][1], seabed_depth_m)
    return corrected


def _latest_tail_start_that_can_reach_seabed(
    positions: list[Vector3],
    rest_lengths_m: tuple[float, ...],
    seabed_depth_m: float,
) -> int | None:
    remaining_length = 0.0
    for start_index in range(len(rest_lengths_m) - 1, -1, -1):
        remaining_length += rest_lengths_m[start_index]
        vertical_gap = seabed_depth_m - positions[start_index][2]
        if vertical_gap <= remaining_length + _SEABED_CONTACT_TOLERANCE_M:
            return start_index
    return None


def _first_reachable_contact_index(
    positions: list[Vector3],
    rest_lengths_m: tuple[float, ...],
    contact_flags: tuple[bool, ...],
    seabed_depth_m: float,
) -> int | None:
    contact_started = False
    for index in range(1, len(positions)):
        contact_started = contact_started or (
            index < len(contact_flags) and contact_flags[index]
        ) or positions[index][2] >= seabed_depth_m - _SEABED_CONTACT_TOLERANCE_M
        if not contact_started:
            continue
        vertical_gap = seabed_depth_m - positions[index - 1][2]
        if vertical_gap <= rest_lengths_m[index - 1] + _SEABED_CONTACT_TOLERANCE_M:
            return index
    for index in range(1, len(positions)):
        vertical_gap = seabed_depth_m - positions[index - 1][2]
        if vertical_gap <= rest_lengths_m[index - 1] + _SEABED_CONTACT_TOLERANCE_M:
            return index
    return None


def _horizontal_unit(delta: Vector3, *, fallback: tuple[float, float]) -> tuple[float, float]:
    horizontal = math.hypot(delta[0], delta[1])
    if horizontal <= _MIN_LENGTH:
        fallback_length = math.hypot(fallback[0], fallback[1])
        if fallback_length <= _MIN_LENGTH:
            return (1.0, 0.0)
        return (fallback[0] / fallback_length, fallback[1] / fallback_length)
    return (delta[0] / horizontal, delta[1] / horizontal)


def _safe_unit(vector: Vector3 | None) -> Vector3:
    if vector is None:
        return (0.0, 0.0, 1.0)
    magnitude = _norm(vector)
    if magnitude <= _MIN_LENGTH or not math.isfinite(magnitude):
        return (0.0, 0.0, 1.0)
    return _mul(vector, 1.0 / magnitude)


def _contact_flags_from_positions(
    positions: tuple[Vector3, ...],
    seabed_depth_m: float,
) -> tuple[bool, ...]:
    return tuple(
        index > 0 and position[2] >= seabed_depth_m - _SEABED_CONTACT_TOLERANCE_M
        for index, position in enumerate(positions)
    )


def _remove_stable_laid_bottom_segment(
    *,
    positions: tuple[Vector3, ...],
    velocities: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    contact_flags: tuple[bool, ...],
    length_lambdas_n_s2: tuple[float, ...],
    contact_lambdas_n_s2: tuple[float, ...],
    segment_tensions_n: tuple[float, ...],
    contact_normal_reactions_n: tuple[float, ...],
    laid_length_m: float,
    laydown_buffer_m: float,
    laid_segment_lengths_m: tuple[float, ...],
    paid_length_m: float,
) -> tuple[
    tuple[Vector3, ...],
    tuple[Vector3, ...],
    tuple[float, ...],
    tuple[bool, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    float,
    float,
    tuple[float, ...],
]:
    if len(positions) <= 2 or len(rest_lengths_m) == 0:
        return (
            positions,
            velocities,
            rest_lengths_m,
            contact_flags,
            length_lambdas_n_s2,
            contact_lambdas_n_s2,
            segment_tensions_n,
            contact_normal_reactions_n,
            laid_length_m,
            laydown_buffer_m,
            laid_segment_lengths_m,
        )
    positions_list = list(positions)
    velocities_list = list(velocities)
    rest_lengths = list(rest_lengths_m)
    contact_flags_list = list(contact_flags)
    length_lambdas = list(length_lambdas_n_s2)
    contact_lambdas = list(contact_lambdas_n_s2)
    segment_tensions = list(segment_tensions_n)
    contact_reactions = list(contact_normal_reactions_n)
    laid_segments = list(laid_segment_lengths_m)
    laid_length = laid_length_m
    laydown_buffer = laydown_buffer_m
    changed = False

    while len(positions_list) > 2 and len(rest_lengths) > 0:
        if not (contact_flags_list[-1] and contact_flags_list[-2]):
            break
        removed_length = rest_lengths[-1]
        if laydown_buffer + _MIN_LENGTH < removed_length:
            break
        positions_list.pop()
        velocities_list.pop()
        rest_lengths.pop()
        contact_flags_list.pop()
        if length_lambdas:
            length_lambdas.pop()
        if contact_lambdas:
            contact_lambdas.pop()
        if segment_tensions:
            segment_tensions.pop()
        if contact_reactions:
            contact_reactions.pop()
        laid_length = min(paid_length_m, laid_length + removed_length)
        laid_segments.append(removed_length)
        laydown_buffer = max(0.0, laydown_buffer - removed_length)
        changed = True

    if not changed:
        return (
            positions,
            velocities,
            rest_lengths_m,
            contact_flags,
            length_lambdas_n_s2,
            contact_lambdas_n_s2,
            segment_tensions_n,
            contact_normal_reactions_n,
            laid_length_m,
            laydown_buffer,
            laid_segment_lengths_m,
        )
    return (
        tuple(positions_list),
        tuple(velocities_list),
        tuple(rest_lengths),
        tuple(contact_flags_list),
        tuple(length_lambdas),
        tuple(contact_lambdas),
        tuple(segment_tensions),
        tuple(contact_reactions),
        laid_length,
        laydown_buffer,
        tuple(laid_segments),
    )


def _stable_tail_contact_length(
    rest_lengths_m: tuple[float, ...],
    contact_flags: tuple[bool, ...],
) -> float:
    stable_length = 0.0
    for segment_index in range(len(rest_lengths_m) - 1, -1, -1):
        if not (
            segment_index < len(contact_flags)
            and segment_index + 1 < len(contact_flags)
            and contact_flags[segment_index]
            and contact_flags[segment_index + 1]
        ):
            break
        stable_length += rest_lengths_m[segment_index]
    return stable_length


def solve_dynamic_laying(
    case: OperationCase,
    *,
    total_time_s: float,
    dt_s: float,
    nodes: int = 33,
) -> DynamicLayingResult:
    """Run the first node-coordinate dynamic laying path from static geometry."""

    if total_time_s < 0.0:
        raise ValueError("total_time_s must be non-negative")
    if nodes < 2:
        raise ValueError("nodes must be at least 2")
    from .solver import solve_case

    state = initialize_from_static(solve_case(case, points=nodes))
    states = [state]
    while states[-1].time_s + 1.0e-12 < total_time_s:
        step = min(dt_s, total_time_s - states[-1].time_s)
        states.append(step_dynamic(case, states[-1], dt_s=step))
    return DynamicLayingResult(
        states=states,
        evidence_level="node-coordinate dynamic laying scaffold; not fitted to paper tables",
    )


def solve_dynamic_laying_time_history(dynamic_case, *, points: int = 361):
    """Solve an LA time history with the node-coordinate dynamic model.

    The return type intentionally matches ``dynamic.TimeHistoryResult`` so the
    paper comparison and HTML report can use the same output path while the
    underlying model changes from angle-state diagnostics to node dynamics.
    """

    if points < 3:
        raise ValueError("points must be at least 3")
    from .dynamic import (
        TimeHistoryFrame,
        TimeHistoryFramePoint,
        TimeHistoryPoint,
        TimeHistoryResult,
        _sample_times,
        _validate_dynamic_case,
        cable_parameters_from_dynamic_case,
    )
    from .parameters import OperationCase

    _validate_dynamic_case(
        dynamic_case,
        allowed_length_boundary_sources={
            "straight_line_sensitivity",
            "xpbd_node_dynamics_contact_remesh",
            "known_plough_trajectory",
        },
    )
    if dynamic_case.length_boundary_source == "known_plough_trajectory":
        return _solve_known_plough_time_history(dynamic_case, points=points)
    cable = cable_parameters_from_dynamic_case(dynamic_case)
    sample_times = _sample_times(dynamic_case, points)
    state = _initial_laying_state(dynamic_case)
    target_segment_length = _time_history_target_segment_length(state)
    samples: list[tuple[float, DynamicLayingState, int]] = []
    current_time = 0.0
    steps = 0
    next_sample = 0
    dt_max = min(0.1, max(dynamic_case.total_duration_s / 3600.0, 0.02))
    used_dts: list[float] = []

    while next_sample < len(sample_times):
        target_time = sample_times[next_sample]
        while current_time + 1.0e-9 < target_time:
            dt = min(_time_history_step_limit_s(dynamic_case, state, base_step_s=dt_max), target_time - current_time)
            case_at_time = _operation_case_at_time(dynamic_case, cable, current_time)
            state = step_dynamic(
                case_at_time,
                state,
                dt_s=dt,
                payout_speed_mps=_payout_speed(dynamic_case, current_time),
                seabed_depth_m=dynamic_case.water_depth_m,
                xpbd_iterations=8,
                target_segment_length_m=target_segment_length,
                enforce_chain_lengths=True,
                top_tangent_boundary=_straight_line_tangent(
                    dynamic_case,
                    _shape_response_speed(dynamic_case, current_time + dt),
                ),
            )
            current_time += dt
            used_dts.append(dt)
            steps += 1
        samples.append((target_time, state, max(steps * len(state.positions), len(state.positions))))
        next_sample += 1

    history: list[TimeHistoryPoint] = []
    frames: list[TimeHistoryFrame] = []
    for time_s, sample_state, iterations in samples:
        case_at_time = _operation_case_at_time(dynamic_case, cable, time_s)
        top_tension = _top_tension_from_dynamic_state(dynamic_case, case_at_time, sample_state, time_s)
        point_tensions = _point_tensions_from_dynamic_state(dynamic_case, case_at_time, sample_state, time_s)
        segment_tensions = _dynamic_segment_tensions(dynamic_case, case_at_time, sample_state, time_s)
        contact_profile = _state_contact_profile(sample_state, dynamic_case.water_depth_m)
        tdp = _state_tdp(sample_state, dynamic_case.water_depth_m)
        history.append(
            TimeHistoryPoint(
                time_s=float(time_s),
                top_tension_n=float(top_tension),
                tdp_x_m=float(tdp[0]),
                tdp_y_m=float(tdp[1]),
                suspended_length_m=float(sample_state.suspended_length_m),
                iterations=iterations,
                tdp_arc_length_m=float(contact_profile.tdp_arc_length_m),
                free_span_material_length_m=float(contact_profile.suspended_length_m),
                seabed_contact_length_m=float(contact_profile.contact_length_m),
                seabed_normal_reaction_n=float(contact_profile.normal_resultant_n),
            )
        )
        frames.append(
            TimeHistoryFrame(
                time_s=float(time_s),
                points=[
                    TimeHistoryFramePoint(
                        index=index,
                        x_m=float(position[0]),
                        y_m=float(position[1]),
                        z_m=float(position[2]),
                        tension_n=float(point_tensions[index]),
                    )
                    for index, position in enumerate(sample_state.positions)
                ],
                segment_tensions_n=tuple(float(tension) for tension in segment_tensions),
            )
        )

    tensions = [point.top_tension_n for point in history]
    return TimeHistoryResult(
        case_name=dynamic_case.case_name,
        diameter_m=dynamic_case.diameter_m,
        weight_air_n_per_m=dynamic_case.weight_air_n_per_m,
        submerged_weight_n_per_m=dynamic_case.submerged_weight_n_per_m,
        tangential_drag_coefficient=dynamic_case.tangential_drag_coefficient,
        normal_drag_coefficient=dynamic_case.normal_drag_coefficient,
        axial_stiffness_n=dynamic_case.axial_stiffness_n,
        current_speed_mps=dynamic_case.current_speed_mps,
        current_direction_deg=dynamic_case.current_direction_deg,
        speed_change=dynamic_case.speed_change,
        initial_speed_mps=dynamic_case.initial_speed_mps,
        final_speed_mps=dynamic_case.final_speed_mps,
        duration_s=dynamic_case.duration_s,
        total_duration_s=dynamic_case.total_duration_s,
        water_depth_m=dynamic_case.water_depth_m,
        element_count=dynamic_case.element_count,
        touchdown_tension_n=dynamic_case.touchdown_tension_n,
        payout_initial_speed_mps=_initial_payout_speed(dynamic_case),
        payout_final_speed_mps=_final_payout_speed(dynamic_case),
        length_boundary_source="xpbd_node_dynamics_contact_remesh",
        initial_suspended_length_m=dynamic_case.initial_suspended_length_m,
        evidence_level=(
            "node-coordinate XPBD dynamic laying with payout insertion, contact/friction, "
            "bottom remeshing, and XPBD/load-recursive segment tension diagnostics; "
            "tail contact laydown transfer, top tangent, and monotone depth constraints "
            "keep frame arc, TDP migration, and suspended shape consistent; "
            "top tension is exported from the state tension field"
        ),
        initial_tension_n=history[0].top_tension_n,
        extreme_tension_n=min(tensions) if dynamic_case.speed_change == "accel" else max(tensions),
        steady_tension_n=history[-1].top_tension_n,
        history=history,
        frames=frames,
        integration_time_step_max_s=max(used_dts) if used_dts else None,
        integration_time_step_min_s=min(used_dts) if used_dts else None,
        spatial_step_mean_m=_mean_positive_length(state.rest_lengths_m),
        spatial_step_min_m=_min_positive_length(state.rest_lengths_m),
        xpbd_iterations_per_step=8,
        vessel_motion_segments=dynamic_case.vessel_motion_segments,
        plough_motion_segments=dynamic_case.plough_motion_segments,
        vessel_motion_samples=dynamic_case.vessel_motion_samples,
        plough_motion_samples=dynamic_case.plough_motion_samples,
        payout_speed_segments=dynamic_case.payout_speed_segments,
    )


def initialize_known_plough_runtime(dynamic_case) -> KnownPloughRuntime:
    """Create one persistent known-plough runtime without advancing time."""

    from .dynamic import _validate_dynamic_case, cable_parameters_from_dynamic_case

    _validate_dynamic_case(
        dynamic_case,
        allowed_length_boundary_sources={"known_plough_trajectory"},
    )
    cable = cable_parameters_from_dynamic_case(dynamic_case)
    state = _initial_known_plough_state(dynamic_case, cable)
    bend_radius = _minimum_bend_radius_diagnostic(
        state.positions,
        exclude_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
    )
    raw_bend_radius = _minimum_bend_radius_diagnostic(state.positions)
    return KnownPloughRuntime(
        state=state,
        cable=cable,
        time_s=0.0,
        dt_max_s=min(0.05, max(dynamic_case.total_duration_s / 7200.0, 0.01)),
        steps=0,
        integration_time_step_min_s=None,
        integration_time_step_max_s=None,
        axial_iterations_min=None,
        axial_iterations_max=None,
        axial_constraint_residual_max_m=None,
        bend_radius_diagnostic=bend_radius,
        bend_radius_min_m=bend_radius.radius_m,
        bend_radius_time_s=0.0 if bend_radius.node_index is not None else None,
        raw_bend_radius_diagnostic=raw_bend_radius,
        raw_bend_radius_min_m=raw_bend_radius.radius_m,
        raw_bend_radius_time_s=0.0 if raw_bend_radius.node_index is not None else None,
    )


def advance_known_plough_runtime(
    runtime: KnownPloughRuntime,
    dynamic_case,
    *,
    target_time_s: float,
) -> KnownPloughRuntime:
    """Advance a persistent known-plough state to one later physical time."""

    if target_time_s < runtime.time_s - 1.0e-9:
        raise ValueError("target_time_s must not precede the runtime time")
    while runtime.time_s + 1.0e-9 < target_time_s:
        step_start_time = runtime.time_s
        dt = min(
            _time_history_step_limit_s(dynamic_case, runtime.state, base_step_s=runtime.dt_max_s),
            target_time_s - step_start_time,
        )
        case_at_time = _operation_case_at_time(
            dynamic_case,
            runtime.cable,
            step_start_time,
            vessel_fixed_current=False,
        )
        runtime.state = _step_known_plough_dynamic(
            dynamic_case,
            case_at_time,
            runtime.state,
            time_s=step_start_time,
            dt_s=dt,
        )
        runtime.time_s = step_start_time + dt
        runtime.integration_time_step_min_s = _optional_min(runtime.integration_time_step_min_s, dt)
        runtime.integration_time_step_max_s = _optional_max(runtime.integration_time_step_max_s, dt)
        runtime.axial_iterations_min = _optional_min(
            runtime.axial_iterations_min,
            runtime.state.axial_solve_iterations,
        )
        runtime.axial_iterations_max = _optional_max(
            runtime.axial_iterations_max,
            runtime.state.axial_solve_iterations,
        )
        runtime.axial_constraint_residual_max_m = _optional_max(
            runtime.axial_constraint_residual_max_m,
            runtime.state.axial_constraint_residual_m,
        )
        runtime.steps += 1

        bend_radius = _minimum_bend_radius_diagnostic(
            runtime.state.positions,
            exclude_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
        )
        if bend_radius.radius_m < runtime.bend_radius_min_m:
            runtime.bend_radius_diagnostic = bend_radius
            runtime.bend_radius_min_m = bend_radius.radius_m
            runtime.bend_radius_time_s = runtime.time_s
        raw_bend_radius = _minimum_bend_radius_diagnostic(runtime.state.positions)
        if raw_bend_radius.radius_m < runtime.raw_bend_radius_min_m:
            runtime.raw_bend_radius_diagnostic = raw_bend_radius
            runtime.raw_bend_radius_min_m = raw_bend_radius.radius_m
            runtime.raw_bend_radius_time_s = runtime.time_s
    return runtime


def sample_known_plough_runtime(runtime: KnownPloughRuntime, dynamic_case) -> KnownPloughSample:
    """Build one latest-frame output without changing the runtime state."""

    from .dynamic import TimeHistoryFrame, TimeHistoryFramePoint, TimeHistoryPoint

    time_s = runtime.time_s
    state = runtime.state
    case_at_time = _operation_case_at_time(
        dynamic_case,
        runtime.cable,
        time_s,
        vessel_fixed_current=False,
    )
    segment_tensions = _known_plough_output_segment_tensions(dynamic_case, case_at_time, state, time_s)
    point_tensions = _point_tensions_from_segment_tensions(dynamic_case, state, segment_tensions)
    length_constraint_reactions = _length_constraint_reactions_from_dynamic_state(state)
    top_tension = point_tensions[0] if point_tensions else 0.0
    plough_adjacent_tension = (
        length_constraint_reactions[-1]
        if length_constraint_reactions
        else segment_tensions[-1]
        if segment_tensions
        else top_tension
    )
    tdp_inlet_tension = _plough_inlet_tension_from_dynamic_state(
        dynamic_case,
        case_at_time,
        state,
        time_s,
        endpoint_segment_tensions=length_constraint_reactions or segment_tensions,
    )
    vessel = _vessel_position(dynamic_case, time_s)
    plough = _plough_position(dynamic_case, time_s)
    contact_profile = _state_contact_profile(state, dynamic_case.water_depth_m)
    tdp = _known_plough_tdp(state, dynamic_case.water_depth_m)
    bend_radius = _minimum_bend_radius_diagnostic(
        state.positions,
        exclude_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
    )
    raw_bend_radius = _minimum_bend_radius_diagnostic(state.positions)
    entry_angle = _plough_entry_angle_deg(state.positions)
    iterations = max(runtime.steps * len(state.positions), len(state.positions))

    point = TimeHistoryPoint(
        time_s=float(time_s),
        top_tension_n=float(top_tension),
        tdp_x_m=float(tdp[0]),
        tdp_y_m=float(tdp[1]),
        suspended_length_m=float(state.suspended_length_m),
        iterations=iterations,
        plough_x_m=float(plough[0]),
        plough_y_m=float(plough[1]),
        plough_z_m=float(plough[2]),
        plough_inlet_tension_n=float(tdp_inlet_tension),
        plough_boundary_tension_n=float(plough_adjacent_tension),
        plough_adjacent_segment_tension_n=float(plough_adjacent_tension),
        plough_entry_angle_deg=float(entry_angle),
        minimum_bend_radius_m=float(bend_radius.radius_m),
        minimum_bend_radius_node_index=bend_radius.node_index,
        minimum_bend_radius_left_segment_m=bend_radius.left_segment_m,
        minimum_bend_radius_right_segment_m=bend_radius.right_segment_m,
        minimum_bend_radius_turn_angle_deg=bend_radius.turn_angle_deg,
        minimum_bend_radius_node_depth_m=bend_radius.node_depth_m,
        minimum_bend_radius_near_seabed=bend_radius.near_seabed,
        minimum_bend_radius_excluded_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
        minimum_bend_radius_raw_m=float(raw_bend_radius.radius_m),
        minimum_bend_radius_raw_node_index=raw_bend_radius.node_index,
        minimum_bend_radius_raw_left_segment_m=raw_bend_radius.left_segment_m,
        minimum_bend_radius_raw_right_segment_m=raw_bend_radius.right_segment_m,
        minimum_bend_radius_raw_turn_angle_deg=raw_bend_radius.turn_angle_deg,
        minimum_bend_radius_raw_node_depth_m=raw_bend_radius.node_depth_m,
        minimum_bend_radius_raw_near_seabed=raw_bend_radius.near_seabed,
        material_suspended_length_m=float(
            state.material_suspended_length_m
            if state.material_suspended_length_m > _MIN_LENGTH
            else state.suspended_length_m
        ),
        geometric_length_deficit_m=float(state.geometric_length_deficit_m),
        tdp_arc_length_m=float(contact_profile.tdp_arc_length_m),
        free_span_material_length_m=float(contact_profile.suspended_length_m),
        seabed_contact_length_m=float(contact_profile.contact_length_m),
        seabed_normal_reaction_n=float(contact_profile.normal_resultant_n),
    )
    frame = TimeHistoryFrame(
        time_s=float(time_s),
        points=[
            TimeHistoryFramePoint(
                index=index,
                x_m=float(position[0]),
                y_m=float(position[1]),
                z_m=float(position[2]),
                tension_n=float(point_tensions[index]),
            )
            for index, position in enumerate(state.positions)
        ],
        segment_tensions_n=tuple(float(tension) for tension in segment_tensions),
        boundary="known_plough_trajectory",
        vessel_x_m=float(vessel[0]),
        vessel_y_m=float(vessel[1]),
        vessel_z_m=float(vessel[2]),
        plough_x_m=float(plough[0]),
        plough_y_m=float(plough[1]),
        plough_z_m=float(plough[2]),
        minimum_bend_radius_m=float(bend_radius.radius_m),
        minimum_bend_radius_node_index=bend_radius.node_index,
        minimum_bend_radius_left_segment_m=bend_radius.left_segment_m,
        minimum_bend_radius_right_segment_m=bend_radius.right_segment_m,
        minimum_bend_radius_turn_angle_deg=bend_radius.turn_angle_deg,
        minimum_bend_radius_node_depth_m=bend_radius.node_depth_m,
        minimum_bend_radius_near_seabed=bend_radius.near_seabed,
        minimum_bend_radius_excluded_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
        minimum_bend_radius_raw_m=float(raw_bend_radius.radius_m),
        minimum_bend_radius_raw_node_index=raw_bend_radius.node_index,
        minimum_bend_radius_raw_left_segment_m=raw_bend_radius.left_segment_m,
        minimum_bend_radius_raw_right_segment_m=raw_bend_radius.right_segment_m,
        minimum_bend_radius_raw_turn_angle_deg=raw_bend_radius.turn_angle_deg,
        minimum_bend_radius_raw_node_depth_m=raw_bend_radius.node_depth_m,
        minimum_bend_radius_raw_near_seabed=raw_bend_radius.near_seabed,
    )
    return KnownPloughSample(point=point, frame=frame)


def _solve_known_plough_time_history(dynamic_case, *, points: int = 361):
    """Solve the suspended span between prescribed vessel and plough endpoints."""

    from .dynamic import (
        TimeHistoryFrame,
        TimeHistoryFramePoint,
        TimeHistoryPoint,
        TimeHistoryResult,
        _sample_times,
        _validate_dynamic_case,
        cable_parameters_from_dynamic_case,
    )

    _validate_dynamic_case(
        dynamic_case,
        allowed_length_boundary_sources={"known_plough_trajectory"},
    )
    cable = cable_parameters_from_dynamic_case(dynamic_case)
    sample_times = _sample_times(dynamic_case, points)
    state = _initial_known_plough_state(dynamic_case, cable)
    samples: list[tuple[float, DynamicLayingState, int]] = []
    current_time = 0.0
    steps = 0
    next_sample = 0
    dt_max = min(0.05, max(dynamic_case.total_duration_s / 7200.0, 0.01))
    used_dts: list[float] = []
    axial_iteration_counts: list[int] = []
    axial_constraint_residuals: list[float] = []
    bend_radius_diagnostic = _minimum_bend_radius_diagnostic(
        state.positions,
        exclude_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
    )
    bend_radius_min = bend_radius_diagnostic.radius_m
    bend_radius_time_s = 0.0 if bend_radius_diagnostic.node_index is not None else None
    raw_bend_radius_diagnostic = _minimum_bend_radius_diagnostic(state.positions)
    raw_bend_radius_min = raw_bend_radius_diagnostic.radius_m
    raw_bend_radius_time_s = 0.0 if raw_bend_radius_diagnostic.node_index is not None else None

    while next_sample < len(sample_times) and sample_times[next_sample] <= 1.0e-9:
        samples.append((sample_times[next_sample], state, len(state.positions)))
        next_sample += 1

    while current_time + 1.0e-9 < dynamic_case.total_duration_s:
        step_start_time = current_time
        step_start_state = state
        dt = min(
            _time_history_step_limit_s(dynamic_case, state, base_step_s=dt_max),
            dynamic_case.total_duration_s - current_time,
        )
        case_at_time = _operation_case_at_time(
            dynamic_case,
            cable,
            step_start_time,
            vessel_fixed_current=False,
        )
        state = _step_known_plough_dynamic(
            dynamic_case,
            case_at_time,
            state,
            time_s=step_start_time,
            dt_s=dt,
        )
        current_time = step_start_time + dt
        used_dts.append(dt)
        axial_iteration_counts.append(state.axial_solve_iterations)
        axial_constraint_residuals.append(state.axial_constraint_residual_m)
        steps += 1
        candidate_bend_radius = _minimum_bend_radius_diagnostic(
            state.positions,
            exclude_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
        )
        if candidate_bend_radius.radius_m < bend_radius_min:
            bend_radius_diagnostic = candidate_bend_radius
            bend_radius_min = candidate_bend_radius.radius_m
            bend_radius_time_s = current_time
        raw_candidate_bend_radius = _minimum_bend_radius_diagnostic(state.positions)
        if raw_candidate_bend_radius.radius_m < raw_bend_radius_min:
            raw_bend_radius_diagnostic = raw_candidate_bend_radius
            raw_bend_radius_min = raw_candidate_bend_radius.radius_m
            raw_bend_radius_time_s = current_time

        while next_sample < len(sample_times) and sample_times[next_sample] <= current_time + 1.0e-9:
            target_time = sample_times[next_sample]
            if abs(target_time - current_time) <= 1.0e-9:
                sample_state = state
            elif target_time <= step_start_time + 1.0e-9:
                sample_state = step_start_state
            else:
                sample_dt = target_time - step_start_time
                sample_case = _operation_case_at_time(
                    dynamic_case,
                    cable,
                    step_start_time,
                    vessel_fixed_current=False,
                )
                sample_state = _step_known_plough_dynamic(
                    dynamic_case,
                    sample_case,
                    step_start_state,
                    time_s=step_start_time,
                    dt_s=sample_dt,
                )
            samples.append(
                (
                    target_time,
                    sample_state,
                    max(steps * len(sample_state.positions), len(sample_state.positions)),
                )
            )
            next_sample += 1

    history: list[TimeHistoryPoint] = []
    frames: list[TimeHistoryFrame] = []
    for time_s, sample_state, iterations in samples:
        case_at_time = _operation_case_at_time(
            dynamic_case,
            cable,
            time_s,
            vessel_fixed_current=False,
        )
        segment_tensions = _known_plough_output_segment_tensions(dynamic_case, case_at_time, sample_state, time_s)
        point_tensions = _point_tensions_from_segment_tensions(dynamic_case, sample_state, segment_tensions)
        length_constraint_reactions = _length_constraint_reactions_from_dynamic_state(sample_state)
        top_tension = point_tensions[0] if point_tensions else 0.0
        plough_adjacent_tension = (
            length_constraint_reactions[-1]
            if length_constraint_reactions
            else segment_tensions[-1]
            if segment_tensions
            else top_tension
        )
        tdp_inlet_tension = _plough_inlet_tension_from_dynamic_state(
            dynamic_case,
            case_at_time,
            sample_state,
            time_s,
            endpoint_segment_tensions=length_constraint_reactions or segment_tensions,
        )
        plough_boundary_tension = plough_adjacent_tension
        vessel = _vessel_position(dynamic_case, time_s)
        plough = _plough_position(dynamic_case, time_s)
        contact_profile = _state_contact_profile(sample_state, dynamic_case.water_depth_m)
        tdp = _known_plough_tdp(sample_state, dynamic_case.water_depth_m)
        sample_bend_radius = _minimum_bend_radius_diagnostic(
            sample_state.positions,
            exclude_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
        )
        raw_sample_bend_radius = _minimum_bend_radius_diagnostic(sample_state.positions)
        minimum_bend_radius = sample_bend_radius.radius_m
        entry_angle = _plough_entry_angle_deg(sample_state.positions)
        history.append(
            TimeHistoryPoint(
                time_s=float(time_s),
                top_tension_n=float(top_tension),
                tdp_x_m=float(tdp[0]),
                tdp_y_m=float(tdp[1]),
                suspended_length_m=float(sample_state.suspended_length_m),
                iterations=iterations,
                plough_x_m=float(plough[0]),
                plough_y_m=float(plough[1]),
                plough_z_m=float(plough[2]),
                plough_inlet_tension_n=float(tdp_inlet_tension),
                plough_boundary_tension_n=float(plough_boundary_tension),
                plough_adjacent_segment_tension_n=float(plough_adjacent_tension),
                plough_entry_angle_deg=float(entry_angle),
                minimum_bend_radius_m=float(minimum_bend_radius),
                minimum_bend_radius_node_index=sample_bend_radius.node_index,
                minimum_bend_radius_left_segment_m=sample_bend_radius.left_segment_m,
                minimum_bend_radius_right_segment_m=sample_bend_radius.right_segment_m,
                minimum_bend_radius_turn_angle_deg=sample_bend_radius.turn_angle_deg,
                minimum_bend_radius_node_depth_m=sample_bend_radius.node_depth_m,
                minimum_bend_radius_near_seabed=sample_bend_radius.near_seabed,
                minimum_bend_radius_excluded_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
                minimum_bend_radius_raw_m=float(raw_sample_bend_radius.radius_m),
                minimum_bend_radius_raw_node_index=raw_sample_bend_radius.node_index,
                minimum_bend_radius_raw_left_segment_m=raw_sample_bend_radius.left_segment_m,
                minimum_bend_radius_raw_right_segment_m=raw_sample_bend_radius.right_segment_m,
                minimum_bend_radius_raw_turn_angle_deg=raw_sample_bend_radius.turn_angle_deg,
                minimum_bend_radius_raw_node_depth_m=raw_sample_bend_radius.node_depth_m,
                minimum_bend_radius_raw_near_seabed=raw_sample_bend_radius.near_seabed,
                material_suspended_length_m=float(
                    sample_state.material_suspended_length_m
                    if sample_state.material_suspended_length_m > _MIN_LENGTH
                    else sample_state.suspended_length_m
                ),
                geometric_length_deficit_m=float(sample_state.geometric_length_deficit_m),
                tdp_arc_length_m=float(contact_profile.tdp_arc_length_m),
                free_span_material_length_m=float(contact_profile.suspended_length_m),
                seabed_contact_length_m=float(contact_profile.contact_length_m),
                seabed_normal_reaction_n=float(contact_profile.normal_resultant_n),
            )
        )
        frames.append(
            TimeHistoryFrame(
                time_s=float(time_s),
                points=[
                    TimeHistoryFramePoint(
                        index=index,
                        x_m=float(position[0]),
                        y_m=float(position[1]),
                        z_m=float(position[2]),
                        tension_n=float(point_tensions[index]),
                    )
                    for index, position in enumerate(sample_state.positions)
                ],
                segment_tensions_n=tuple(float(tension) for tension in segment_tensions),
                boundary="known_plough_trajectory",
                vessel_x_m=float(vessel[0]),
                vessel_y_m=float(vessel[1]),
                vessel_z_m=float(vessel[2]),
                plough_x_m=float(plough[0]),
                plough_y_m=float(plough[1]),
                plough_z_m=float(plough[2]),
                minimum_bend_radius_m=float(minimum_bend_radius),
                minimum_bend_radius_node_index=sample_bend_radius.node_index,
                minimum_bend_radius_left_segment_m=sample_bend_radius.left_segment_m,
                minimum_bend_radius_right_segment_m=sample_bend_radius.right_segment_m,
                minimum_bend_radius_turn_angle_deg=sample_bend_radius.turn_angle_deg,
                minimum_bend_radius_node_depth_m=sample_bend_radius.node_depth_m,
                minimum_bend_radius_near_seabed=sample_bend_radius.near_seabed,
                minimum_bend_radius_excluded_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
                minimum_bend_radius_raw_m=float(raw_sample_bend_radius.radius_m),
                minimum_bend_radius_raw_node_index=raw_sample_bend_radius.node_index,
                minimum_bend_radius_raw_left_segment_m=raw_sample_bend_radius.left_segment_m,
                minimum_bend_radius_raw_right_segment_m=raw_sample_bend_radius.right_segment_m,
                minimum_bend_radius_raw_turn_angle_deg=raw_sample_bend_radius.turn_angle_deg,
                minimum_bend_radius_raw_node_depth_m=raw_sample_bend_radius.node_depth_m,
                minimum_bend_radius_raw_near_seabed=raw_sample_bend_radius.near_seabed,
            )
        )

    top_tensions = [point.top_tension_n for point in history]
    plough_tensions = [
        point.plough_inlet_tension_n
        for point in history
        if point.plough_inlet_tension_n is not None
    ]
    final_plough_boundary_tension = history[-1].plough_boundary_tension_n
    final_plough_adjacent_tension = history[-1].plough_adjacent_segment_tension_n
    final_plough_exit_speed, plough_exit_speed_source = _plough_exit_material_speed(
        dynamic_case,
        _plough_velocity(dynamic_case, sample_times[-1]),
        time_s=sample_times[-1],
    )
    length_deficits = [
        point.geometric_length_deficit_m
        for point in history
        if point.geometric_length_deficit_m is not None
    ]
    bend_radius_limit = cable.min_bending_radius_m
    bend_radius_margin = (
        None
        if not math.isfinite(bend_radius_min) or bend_radius_limit is None
        else bend_radius_min - bend_radius_limit
    )
    return TimeHistoryResult(
        case_name=dynamic_case.case_name,
        diameter_m=dynamic_case.diameter_m,
        weight_air_n_per_m=dynamic_case.weight_air_n_per_m,
        submerged_weight_n_per_m=dynamic_case.submerged_weight_n_per_m,
        tangential_drag_coefficient=dynamic_case.tangential_drag_coefficient,
        normal_drag_coefficient=dynamic_case.normal_drag_coefficient,
        axial_stiffness_n=dynamic_case.axial_stiffness_n,
        current_speed_mps=dynamic_case.current_speed_mps,
        current_direction_deg=dynamic_case.current_direction_deg,
        speed_change=dynamic_case.speed_change,
        initial_speed_mps=dynamic_case.initial_speed_mps,
        final_speed_mps=dynamic_case.final_speed_mps,
        duration_s=dynamic_case.duration_s,
        total_duration_s=dynamic_case.total_duration_s,
        water_depth_m=dynamic_case.water_depth_m,
        element_count=dynamic_case.element_count,
        touchdown_tension_n=dynamic_case.touchdown_tension_n,
        payout_initial_speed_mps=_initial_payout_speed(dynamic_case),
        payout_final_speed_mps=_final_payout_speed(dynamic_case),
        length_boundary_source="known_plough_trajectory",
        initial_suspended_length_m=dynamic_case.initial_suspended_length_m,
        evidence_level=(
            "known plough trajectory endpoint model: vessel top node and plough inlet node "
            "are prescribed kinematic boundaries; the suspended span uses node-coordinate "
            "forces, fixed-end catenary initial reaction seeding, XPBD length "
            "constraints, Morison drag, post-contact seabed-friction velocity "
            "correction driven by XPBD contact reactions, endpoint material-flow "
            "rest-length updates for payout and plough-exit material flow, geometric length-deficit "
            "diagnostics, and XPBD "
            "length-constraint reactions for reported "
            "free-span, contact-tail, fairlead, and plough-boundary tensions; "
            "plough_inlet_tension reports the TDP/contact-transition segment reaction, "
            "while plough_boundary_tension and plough_adjacent_segment_tension report "
            "the endpoint-adjacent constraint reaction at the prescribed plough inlet; "
            "tdp_x/y is the contact transition when contact exists and the plough-inlet "
            "endpoint when no seabed contact exists; plough-soil dynamics are not solved"
        ),
        initial_tension_n=history[0].top_tension_n,
        extreme_tension_n=min(top_tensions) if dynamic_case.speed_change == "accel" else max(top_tensions),
        steady_tension_n=history[-1].top_tension_n,
        history=history,
        frames=frames,
        plough_speed_mps=dynamic_case.plough_speed_mps,
        plough_exit_speed_mps=final_plough_exit_speed,
        plough_exit_speed_source=plough_exit_speed_source,
        plough_inlet_tension_final_n=plough_tensions[-1] if plough_tensions else None,
        plough_boundary_tension_final_n=final_plough_boundary_tension,
        plough_adjacent_segment_tension_final_n=final_plough_adjacent_tension,
        plough_tension_status=_plough_tension_status(
            boundary_tension_n=final_plough_boundary_tension,
            adjacent_segment_tension_n=final_plough_adjacent_tension,
        ),
        minimum_bend_radius_min_m=bend_radius_min if math.isfinite(bend_radius_min) else None,
        minimum_bend_radius_limit_m=bend_radius_limit,
        minimum_bend_radius_margin_m=bend_radius_margin,
        minimum_bend_radius_status=_minimum_bend_radius_status(
            minimum_radius_m=bend_radius_min if math.isfinite(bend_radius_min) else None,
            limit_m=bend_radius_limit,
        ),
        minimum_bend_radius_time_s=bend_radius_time_s,
        minimum_bend_radius_node_index=bend_radius_diagnostic.node_index,
        minimum_bend_radius_left_segment_m=bend_radius_diagnostic.left_segment_m,
        minimum_bend_radius_right_segment_m=bend_radius_diagnostic.right_segment_m,
        minimum_bend_radius_turn_angle_deg=bend_radius_diagnostic.turn_angle_deg,
        minimum_bend_radius_node_depth_m=bend_radius_diagnostic.node_depth_m,
        minimum_bend_radius_near_seabed=bend_radius_diagnostic.near_seabed,
        minimum_bend_radius_excluded_tail_nodes=_KNOWN_PLOUGH_RMIN_EXCLUDED_TAIL_NODES,
        minimum_bend_radius_raw_m=raw_bend_radius_min if math.isfinite(raw_bend_radius_min) else None,
        minimum_bend_radius_raw_time_s=raw_bend_radius_time_s,
        minimum_bend_radius_raw_node_index=raw_bend_radius_diagnostic.node_index,
        minimum_bend_radius_raw_left_segment_m=raw_bend_radius_diagnostic.left_segment_m,
        minimum_bend_radius_raw_right_segment_m=raw_bend_radius_diagnostic.right_segment_m,
        minimum_bend_radius_raw_turn_angle_deg=raw_bend_radius_diagnostic.turn_angle_deg,
        minimum_bend_radius_raw_node_depth_m=raw_bend_radius_diagnostic.node_depth_m,
        minimum_bend_radius_raw_near_seabed=raw_bend_radius_diagnostic.near_seabed,
        integration_time_step_max_s=max(used_dts) if used_dts else None,
        integration_time_step_min_s=min(used_dts) if used_dts else None,
        spatial_step_mean_m=_mean_positive_length(state.rest_lengths_m),
        spatial_step_min_m=_min_positive_length(state.rest_lengths_m),
        xpbd_iterations_per_step=max(axial_iteration_counts) if axial_iteration_counts else None,
        xpbd_iterations_per_step_min=min(axial_iteration_counts) if axial_iteration_counts else None,
        xpbd_iterations_per_step_max=max(axial_iteration_counts) if axial_iteration_counts else None,
        xpbd_iteration_limit_per_solve=_KNOWN_PLOUGH_XPBD_ITERATIONS,
        axial_constraint_residual_max_m=(
            max(axial_constraint_residuals) if axial_constraint_residuals else None
        ),
        geometric_length_deficit_max_m=max(length_deficits) if length_deficits else None,
        geometric_length_deficit_final_m=history[-1].geometric_length_deficit_m,
        vessel_motion_segments=dynamic_case.vessel_motion_segments,
        plough_motion_segments=dynamic_case.plough_motion_segments,
        vessel_motion_samples=dynamic_case.vessel_motion_samples,
        plough_motion_samples=dynamic_case.plough_motion_samples,
        payout_speed_segments=dynamic_case.payout_speed_segments,
    )


def _initial_known_plough_state(dynamic_case, cable=None) -> DynamicLayingState:
    if cable is None:
        from .dynamic import cable_parameters_from_dynamic_case

        cable = cable_parameters_from_dynamic_case(dynamic_case)
    vessel = _vessel_position(dynamic_case, 0.0)
    plough = _plough_position(dynamic_case, 0.0)
    vessel_velocity = _vessel_velocity(dynamic_case, 0.0)
    plough_velocity = _plough_velocity(dynamic_case, 0.0)
    element_count = dynamic_case.element_count
    direct_distance = max(_norm(_sub(plough, vessel)), _MIN_LENGTH)
    if dynamic_case.initial_suspended_length_m is None:
        raise ValueError("initial_suspended_length_m is required for known_plough_trajectory")
    active_length = float(dynamic_case.initial_suspended_length_m)
    if active_length + 1.0e-9 < direct_distance:
        raise ValueError("initial_suspended_length_m must be no less than the initial endpoint distance")
    static_initial_profile = _initial_endpoint_catenary_profile(
        vessel,
        plough,
        element_count=element_count,
        suspended_length_m=active_length,
        submerged_weight_n_per_m=cable.submerged_weight_n_per_m,
        water_depth_m=dynamic_case.water_depth_m,
    )
    contact_flags: tuple[bool, ...]
    if static_initial_profile is not None:
        positions, segment_tensions = static_initial_profile
        contact_flags = tuple(False for _ in positions)
    else:
        contact_initial_profile = _initial_endpoint_catenary_with_laid_tail_profile(
            vessel,
            plough,
            element_count=element_count,
            active_length_m=active_length,
            submerged_weight_n_per_m=cable.submerged_weight_n_per_m,
            water_depth_m=dynamic_case.water_depth_m,
        )
        if contact_initial_profile is not None:
            positions, segment_tensions, contact_flags = contact_initial_profile
        else:
            positions = _initial_endpoint_curve(
                vessel,
                plough,
                element_count=element_count,
                water_depth_m=dynamic_case.water_depth_m,
            )
            segment_tensions = ()
            contact_flags = tuple(False for _ in positions)
    rest_length = active_length / element_count
    velocities = tuple(
        _add(vessel_velocity, _mul(_sub(plough_velocity, vessel_velocity), index / element_count))
        for index in range(element_count + 1)
    )
    case_at_time = _operation_case_at_time(
        dynamic_case,
        cable,
        0.0,
        vessel_fixed_current=False,
    )
    rest_lengths = tuple(rest_length for _ in range(element_count))
    if not segment_tensions:
        segment_tensions = _step_dynamic_segment_tensions(
            case_at_time,
            positions=positions,
            velocities=velocities,
            rest_lengths_m=rest_lengths,
            payout_speed_mps=_payout_speed(dynamic_case, 0.0),
            terminal_tension_n=0.0,
        )
    return DynamicLayingState(
        time_s=0.0,
        positions=positions,
        velocities=velocities,
        rest_lengths_m=rest_lengths,
        paid_length_m=active_length,
        laid_length_m=0.0,
        contact_flags=contact_flags,
        segment_tensions_n=segment_tensions,
        material_suspended_length_m=active_length,
    )


def _initial_endpoint_catenary_tensions(
    vessel: Vector3,
    plough: Vector3,
    *,
    element_count: int,
    suspended_length_m: float,
    submerged_weight_n_per_m: float,
    water_depth_m: float,
) -> tuple[float, ...] | None:
    profile = _initial_endpoint_catenary_profile(
        vessel,
        plough,
        element_count=element_count,
        suspended_length_m=suspended_length_m,
        submerged_weight_n_per_m=submerged_weight_n_per_m,
        water_depth_m=water_depth_m,
    )
    if profile is None:
        return None
    return profile[1]


def _initial_endpoint_catenary_profile(
    vessel: Vector3,
    plough: Vector3,
    *,
    element_count: int,
    suspended_length_m: float,
    submerged_weight_n_per_m: float,
    water_depth_m: float,
) -> tuple[tuple[Vector3, ...], tuple[float, ...]] | None:
    if element_count <= 0:
        return None
    if suspended_length_m <= 0.0 or submerged_weight_n_per_m <= 0.0:
        return None
    horizontal_vector = (plough[0] - vessel[0], plough[1] - vessel[1])
    horizontal_span_m = math.hypot(horizontal_vector[0], horizontal_vector[1])
    vertical_drop_m = plough[2] - vessel[2]
    straight_span_m = math.hypot(horizontal_span_m, vertical_drop_m)
    if horizontal_span_m <= 1.0e-9 or suspended_length_m <= straight_span_m * (1.0 + 1.0e-12):
        return None
    if abs(vertical_drop_m) >= suspended_length_m:
        return None
    reduced_length_m = math.sqrt(max(suspended_length_m * suspended_length_m - vertical_drop_m * vertical_drop_m, 0.0))
    if reduced_length_m <= horizontal_span_m:
        return None
    try:
        parameter_m = _solve_initial_catenary_parameter(
            horizontal_span_m=horizontal_span_m,
            reduced_length_m=reduced_length_m,
        )
    except ValueError:
        return None
    half_dimensionless_span = horizontal_span_m / (2.0 * parameter_m)
    mean_dimensionless_height = math.atanh(vertical_drop_m / suspended_length_m)
    plough_argument = mean_dimensionless_height - half_dimensionless_span
    vessel_argument = mean_dimensionless_height + half_dimensionless_span
    horizontal_tension_n = submerged_weight_n_per_m * parameter_m
    vessel_sinh = math.sinh(vessel_argument)
    max_depth = max(vessel[2], plough[2], water_depth_m)
    horizontal_unit = (horizontal_vector[0] / horizontal_span_m, horizontal_vector[1] / horizontal_span_m)
    positions: list[Vector3] = []
    for index in range(element_count + 1):
        fraction = index / element_count
        argument = math.asinh(vessel_sinh - fraction * suspended_length_m / parameter_m)
        horizontal_distance = parameter_m * (vessel_argument - argument)
        depth = vessel[2] + parameter_m * (math.cosh(vessel_argument) - math.cosh(argument))
        if depth > max_depth + 1.0e-6:
            return None
        positions.append(
            (
                vessel[0] + horizontal_unit[0] * horizontal_distance,
                vessel[1] + horizontal_unit[1] * horizontal_distance,
                depth,
            )
        )
    positions[0] = vessel
    positions[-1] = plough
    if element_count == 1:
        tensions = (horizontal_tension_n * math.cosh(vessel_argument),)
    else:
        tensions = tuple(
            horizontal_tension_n
            * math.cosh(
                vessel_argument
                + (plough_argument - vessel_argument) * index / (element_count - 1)
            )
            for index in range(element_count)
        )
    return tuple(positions), tuple(max(0.0, tension) for tension in tensions)


def _initial_endpoint_catenary_with_laid_tail_profile(
    vessel: Vector3,
    plough: Vector3,
    *,
    element_count: int,
    active_length_m: float,
    submerged_weight_n_per_m: float,
    water_depth_m: float,
) -> tuple[tuple[Vector3, ...], tuple[float, ...], tuple[bool, ...]] | None:
    """Build a zero-slope TDP catenary followed by a flat laid tail."""

    if element_count <= 0 or active_length_m <= 0.0 or submerged_weight_n_per_m <= 0.0:
        return None
    if abs(plough[2] - water_depth_m) > 1.0e-6 or vessel[2] >= water_depth_m:
        return None
    horizontal_vector = (plough[0] - vessel[0], plough[1] - vessel[1])
    route_span_m = math.hypot(horizontal_vector[0], horizontal_vector[1])
    vertical_drop_m = water_depth_m - vessel[2]
    if route_span_m <= _MIN_LENGTH or vertical_drop_m <= _MIN_LENGTH:
        return None
    excess_ratio = (active_length_m - route_span_m) / vertical_drop_m
    if not 0.0 < excess_ratio < 1.0:
        return None

    touchdown_argument = _solve_touchdown_catenary_argument(excess_ratio)
    parameter_m = vertical_drop_m / (math.cosh(touchdown_argument) - 1.0)
    suspended_horizontal_m = parameter_m * touchdown_argument
    suspended_arc_m = parameter_m * math.sinh(touchdown_argument)
    laid_tail_m = route_span_m - suspended_horizontal_m
    if laid_tail_m <= 1.0e-9:
        return None
    if abs((suspended_arc_m + laid_tail_m) - active_length_m) > 1.0e-7:
        return None

    route_unit = (horizontal_vector[0] / route_span_m, horizontal_vector[1] / route_span_m)
    positions: list[Vector3] = []
    contact_flags: list[bool] = []
    for node_index in range(element_count + 1):
        station_m = active_length_m * node_index / element_count
        if station_m <= suspended_arc_m:
            remaining_arc_m = max(0.0, suspended_arc_m - station_m)
            argument = math.asinh(remaining_arc_m / parameter_m)
            route_distance_m = suspended_horizontal_m - parameter_m * argument
            depth_m = water_depth_m - parameter_m * (math.cosh(argument) - 1.0)
        else:
            route_distance_m = suspended_horizontal_m + (station_m - suspended_arc_m)
            depth_m = water_depth_m
        positions.append(
            (
                vessel[0] + route_unit[0] * route_distance_m,
                vessel[1] + route_unit[1] * route_distance_m,
                min(water_depth_m, max(vessel[2], depth_m)),
            )
        )
        contact_flags.append(
            0 < node_index < element_count and station_m >= suspended_arc_m - 1.0e-9
        )
    positions[0] = vessel
    positions[-1] = plough

    horizontal_tension_n = submerged_weight_n_per_m * parameter_m
    tensions: list[float] = []
    segment_length_m = active_length_m / element_count
    for segment_index in range(element_count):
        center_station_m = (segment_index + 0.5) * segment_length_m
        if center_station_m < suspended_arc_m:
            remaining_arc_m = suspended_arc_m - center_station_m
            argument = math.asinh(remaining_arc_m / parameter_m)
            tensions.append(horizontal_tension_n * math.cosh(argument))
        else:
            tensions.append(horizontal_tension_n)
    return tuple(positions), tuple(tensions), tuple(contact_flags)


def _solve_touchdown_catenary_argument(excess_ratio: float) -> float:
    """Solve (sinh(u)-u)/(cosh(u)-1) for the contact-catenary argument."""

    if not 0.0 < excess_ratio < 1.0:
        raise ValueError("excess_ratio must lie strictly between zero and one")

    def ratio(argument: float) -> float:
        return (math.sinh(argument) - argument) / (math.cosh(argument) - 1.0)

    low = 1.0e-8
    high = 1.0
    while ratio(high) < excess_ratio:
        high *= 2.0
        if high > 64.0:
            raise ValueError("failed to bracket touchdown catenary argument")
    for _ in range(120):
        mid = 0.5 * (low + high)
        if ratio(mid) < excess_ratio:
            low = mid
        else:
            high = mid
    return high


def _solve_initial_catenary_parameter(*, horizontal_span_m: float, reduced_length_m: float) -> float:
    def span_for(parameter_m: float) -> float:
        argument = horizontal_span_m / (2.0 * parameter_m)
        if argument > 700.0:
            return math.inf
        return 2.0 * parameter_m * math.sinh(argument)

    low = max(horizontal_span_m, 1.0e-9) / 1400.0
    high = max(horizontal_span_m, reduced_length_m, 1.0)
    while span_for(high) > reduced_length_m:
        high *= 2.0
        if high > 1.0e18:
            raise ValueError("failed to bracket initial catenary parameter")
    for _ in range(120):
        mid = 0.5 * (low + high)
        if span_for(mid) > reduced_length_m:
            low = mid
        else:
            high = mid
    return high


def _initial_endpoint_curve(
    vessel: Vector3,
    plough: Vector3,
    *,
    element_count: int,
    water_depth_m: float,
) -> tuple[Vector3, ...]:
    direct = _sub(plough, vessel)
    horizontal_span = math.hypot(direct[0], direct[1])
    sag = min(max(0.03 * max(horizontal_span, water_depth_m), 0.5), max(0.0, water_depth_m - max(vessel[2], plough[2])))
    points: list[Vector3] = []
    for index in range(element_count + 1):
        fraction = index / element_count
        baseline = _add(vessel, _mul(direct, fraction))
        sag_z = sag * 4.0 * fraction * (1.0 - fraction)
        points.append((baseline[0], baseline[1], min(water_depth_m, baseline[2] + sag_z)))
    points[0] = vessel
    points[-1] = plough
    return tuple(points)


def _step_known_plough_dynamic(
    dynamic_case,
    case: OperationCase,
    state: DynamicLayingState,
    *,
    time_s: float,
    dt_s: float,
    seabed_friction_coefficient: float = _SEABED_FRICTION_COEFFICIENT,
) -> DynamicLayingState:
    if dt_s <= 0.0:
        raise ValueError("dt_s must be positive")
    _validate_state(state)
    next_time = time_s + dt_s
    vessel = _vessel_position(dynamic_case, next_time)
    plough = _plough_position(dynamic_case, next_time)
    vessel_velocity = _vessel_velocity(dynamic_case, next_time)
    plough_velocity = _plough_velocity(dynamic_case, next_time)
    payout_speed = _payout_speed(dynamic_case, time_s)
    plough_transfer_speed, _ = _plough_exit_material_speed(
        dynamic_case,
        plough_velocity,
        time_s=time_s,
    )
    previous_material_length = _state_material_suspended_length(state)
    material_active_length = max(
        _MIN_LENGTH,
        previous_material_length + (payout_speed - plough_transfer_speed) * dt_s,
    )
    material_state = _advance_known_plough_material_flow(
        state,
        payout_increment_m=payout_speed * dt_s,
        laydown_increment_m=plough_transfer_speed * dt_s,
        target_segment_length_m=_known_plough_target_segment_length(dynamic_case, state),
        seabed_depth_m=dynamic_case.water_depth_m,
    )
    material_active_length = sum(material_state.rest_lengths_m)
    geometric_length_deficit = max(0.0, _norm(_sub(plough, vessel)) - material_active_length)
    paid_length = state.paid_length_m + payout_speed * dt_s
    laid_length = max(0.0, paid_length - material_active_length)
    rest_lengths = material_state.rest_lengths_m
    anchored_state = DynamicLayingState(
        time_s=material_state.time_s,
        positions=material_state.positions,
        velocities=material_state.velocities,
        rest_lengths_m=rest_lengths,
        paid_length_m=material_state.paid_length_m,
        laid_length_m=material_state.laid_length_m,
        contact_flags=material_state.contact_flags,
        length_lambdas_n_s2=material_state.length_lambdas_n_s2,
        contact_lambdas_n_s2=material_state.contact_lambdas_n_s2,
        segment_tensions_n=material_state.segment_tensions_n,
        length_constraint_reactions_n=material_state.length_constraint_reactions_n,
        contact_normal_reactions_n=material_state.contact_normal_reactions_n,
        material_suspended_length_m=material_active_length,
        geometric_length_deficit_m=geometric_length_deficit,
    )
    forces = list(compute_forces(
        case,
        anchored_state,
        seabed_depth_m=None,
        payout_speed_mps=payout_speed,
        plough_exit_speed_mps=plough_transfer_speed,
        include_axial_tension=False,
    ))
    masses = _node_masses(case, anchored_state)
    inverse_masses = tuple(
        0.0 if index in (0, len(anchored_state.positions) - 1) else 1.0 / max(mass, _MIN_MASS)
        for index, mass in enumerate(masses)
    )
    predicted_velocities = [
        _add(velocity, _mul(force, dt_s / max(mass, _MIN_MASS)))
        for velocity, force, mass in zip(anchored_state.velocities, forces, masses)
    ]
    predicted_velocities[0] = vessel_velocity
    predicted_velocities[-1] = plough_velocity
    predicted_velocities = list(_limit_endpoint_span_velocities(tuple(predicted_velocities), rest_lengths, dt_s))
    predicted_positions = [
        _add(position, _mul(velocity, dt_s))
        for position, velocity in zip(anchored_state.positions, predicted_velocities)
    ]
    predicted_positions[0] = vessel
    predicted_positions[-1] = plough
    (
        constrained_positions,
        length_lambdas,
        contact_lambdas,
        axial_solve_iterations,
        axial_constraint_residual,
    ) = _solve_xpbd_endpoint_constraints(
        case,
        positions=tuple(predicted_positions),
        rest_lengths_m=rest_lengths,
        inverse_masses=inverse_masses,
        seabed_depth_m=dynamic_case.water_depth_m,
        dt_s=dt_s,
        iterations=_KNOWN_PLOUGH_XPBD_ITERATIONS,
        minimum_iterations=_KNOWN_PLOUGH_XPBD_MIN_ITERATIONS,
        top_position=vessel,
        bottom_position=plough,
        initial_constraint_reactions_n=(),
    )
    constrained_velocities = [
        _mul(_sub(position, previous), 1.0 / dt_s)
        for previous, position in zip(anchored_state.positions, constrained_positions)
    ]
    constrained_velocities[0] = vessel_velocity
    constrained_velocities[-1] = plough_velocity
    contact_flags = tuple(
        False if index in (0, len(constrained_positions) - 1) else position[2] >= dynamic_case.water_depth_m - _SEABED_CONTACT_TOLERANCE_M
        for index, position in enumerate(constrained_positions)
    )
    contact_normal_reactions = tuple(
        max(0.0, lambda_value / (dt_s * dt_s))
        for lambda_value in contact_lambdas
    )
    pre_merge_rest_lengths = rest_lengths
    (
        constrained_positions,
        constrained_velocities,
        rest_lengths,
        contact_flags,
        length_lambdas,
        contact_lambdas,
        contact_normal_reactions,
    ) = _merge_known_plough_tail_contact_cluster(
        positions=constrained_positions,
        velocities=tuple(constrained_velocities),
        rest_lengths_m=rest_lengths,
        contact_flags=contact_flags,
        length_lambdas_n_s2=length_lambdas,
        contact_lambdas_n_s2=contact_lambdas,
        contact_normal_reactions_n=contact_normal_reactions,
        seabed_depth_m=dynamic_case.water_depth_m,
        minimum_tail_length_m=max(
            _MIN_LENGTH,
            max(
                _max_node_speed(tuple(constrained_velocities)),
                abs(payout_speed),
                abs(plough_transfer_speed),
            )
            * dt_s
            / _MAX_NODE_CFL_FRACTION,
        ),
    )
    merged_positions = constrained_positions
    if len(rest_lengths) != len(pre_merge_rest_lengths):
        merged_velocities = tuple(constrained_velocities)
        merged_state = DynamicLayingState(
            time_s=state.time_s,
            positions=merged_positions,
            velocities=merged_velocities,
            rest_lengths_m=rest_lengths,
            paid_length_m=paid_length,
            laid_length_m=laid_length,
            contact_flags=contact_flags,
            material_suspended_length_m=material_active_length,
            geometric_length_deficit_m=geometric_length_deficit,
        )
        merged_inverse_masses = tuple(
            0.0 if index in (0, len(merged_positions) - 1) else 1.0 / max(mass, _MIN_MASS)
            for index, mass in enumerate(_node_masses(case, merged_state))
        )
        (
            constrained_positions,
            length_lambdas,
            contact_lambdas,
            merge_axial_iterations,
            axial_constraint_residual,
        ) = _solve_xpbd_endpoint_constraints(
            case,
            positions=merged_positions,
            rest_lengths_m=rest_lengths,
            inverse_masses=merged_inverse_masses,
            seabed_depth_m=dynamic_case.water_depth_m,
            dt_s=dt_s,
            iterations=_KNOWN_PLOUGH_XPBD_ITERATIONS,
            minimum_iterations=_KNOWN_PLOUGH_XPBD_MIN_ITERATIONS,
            top_position=vessel,
            bottom_position=plough,
            initial_constraint_reactions_n=_segment_tensions_from_length_constraints(
                length_lambdas,
                dt_s=dt_s,
                expected_count=len(rest_lengths),
            ),
        )
        axial_solve_iterations += merge_axial_iterations
        constrained_velocities = [
            _add(velocity, _mul(_sub(position, previous), 1.0 / dt_s))
            for velocity, previous, position in zip(merged_velocities, merged_positions, constrained_positions)
        ]
        constrained_velocities[0] = vessel_velocity
        constrained_velocities[-1] = plough_velocity
        contact_flags = tuple(
            False if index in (0, len(constrained_positions) - 1) else position[2] >= dynamic_case.water_depth_m - _SEABED_CONTACT_TOLERANCE_M
            for index, position in enumerate(constrained_positions)
        )
        contact_normal_reactions = tuple(
            max(0.0, lambda_value / (dt_s * dt_s))
            for lambda_value in contact_lambdas
        )
    friction_state = DynamicLayingState(
        time_s=state.time_s,
        positions=constrained_positions,
        velocities=tuple(constrained_velocities),
        rest_lengths_m=rest_lengths,
        paid_length_m=paid_length,
        laid_length_m=laid_length,
        contact_flags=contact_flags,
        material_suspended_length_m=material_active_length,
        geometric_length_deficit_m=geometric_length_deficit,
        axial_solve_iterations=axial_solve_iterations,
        axial_constraint_residual_m=axial_constraint_residual,
    )
    _, constrained_velocities = _apply_contact_friction(
        positions=constrained_positions,
        previous_positions=merged_positions,
        velocities=tuple(constrained_velocities),
        contact_flags=contact_flags,
        contact_normal_reactions_n=contact_normal_reactions,
        masses=_node_masses(case, friction_state),
        payout_speed_mps=payout_speed,
        rest_lengths_m=rest_lengths,
        plough_exit_speed_mps=plough_transfer_speed,
        dt_s=dt_s,
        friction_coefficient=seabed_friction_coefficient,
        update_positions=False,
    )
    constrained_velocities = tuple(constrained_velocities)
    constrained_velocities = (
        vessel_velocity,
        *constrained_velocities[1:-1],
        plough_velocity,
    )
    length_constraint_reactions = _segment_tensions_from_length_constraints(
        length_lambdas,
        dt_s=dt_s,
        expected_count=len(rest_lengths),
    )
    load_recursive_tensions = _step_dynamic_segment_tensions(
        case,
        positions=constrained_positions,
        velocities=constrained_velocities,
        rest_lengths_m=rest_lengths,
        payout_speed_mps=payout_speed,
        plough_exit_speed_mps=plough_transfer_speed,
        terminal_tension_n=0.0,
    )
    segment_tensions = length_constraint_reactions or load_recursive_tensions
    return DynamicLayingState(
        time_s=state.time_s + dt_s,
        positions=constrained_positions,
        velocities=constrained_velocities,
        rest_lengths_m=rest_lengths,
        paid_length_m=paid_length,
        laid_length_m=laid_length,
        contact_flags=contact_flags,
        length_lambdas_n_s2=length_lambdas,
        contact_lambdas_n_s2=contact_lambdas,
        segment_tensions_n=segment_tensions,
        length_constraint_reactions_n=length_constraint_reactions,
        contact_normal_reactions_n=contact_normal_reactions,
        material_suspended_length_m=material_active_length,
        geometric_length_deficit_m=geometric_length_deficit,
        axial_solve_iterations=axial_solve_iterations,
        axial_constraint_residual_m=axial_constraint_residual,
    )


def _merge_known_plough_tail_contact_cluster(
    *,
    positions: tuple[Vector3, ...],
    velocities: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    contact_flags: tuple[bool, ...],
    length_lambdas_n_s2: tuple[float, ...],
    contact_lambdas_n_s2: tuple[float, ...],
    contact_normal_reactions_n: tuple[float, ...],
    seabed_depth_m: float,
    minimum_tail_length_m: float = _MIN_LENGTH,
) -> tuple[
    tuple[Vector3, ...],
    tuple[Vector3, ...],
    tuple[float, ...],
    tuple[bool, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
]:
    """Merge folded contact remnants immediately before the prescribed plough."""

    if len(positions) <= 3:
        return (
            positions,
            velocities,
            rest_lengths_m,
            contact_flags,
            length_lambdas_n_s2,
            contact_lambdas_n_s2,
            contact_normal_reactions_n,
        )
    positions_list = list(positions)
    velocities_list = list(velocities)
    rest_lengths = list(rest_lengths_m)
    contact_flags_list = list(contact_flags)
    length_lambdas = _padded_values(length_lambdas_n_s2, len(rest_lengths))
    contact_lambdas = _padded_values(contact_lambdas_n_s2, len(positions_list))
    contact_reactions = _padded_values(contact_normal_reactions_n, len(positions_list))

    while len(positions_list) > 3 and len(rest_lengths) >= 2:
        reference_length = _median_positive_length(tuple(rest_lengths))
        if reference_length is None:
            break
        tolerance = max(_SEABED_CONTACT_TOLERANCE_M, 0.005 * reference_length)
        tail = positions_list[-1]
        near_tail = positions_list[-2]
        before_tail = positions_list[-3]
        if tail[2] < seabed_depth_m - tolerance or near_tail[2] < seabed_depth_m - tolerance:
            break
        first = _sub(near_tail, before_tail)
        second = _sub(tail, near_tail)
        first_length = _norm(first)
        second_length = _norm(second)
        folded = (
            first_length > _MIN_LENGTH
            and second_length > _MIN_LENGTH
            and _dot(first, second) < 0.0
        )
        subgrid_tail = min(first_length, second_length) <= max(
            _MIN_LENGTH,
            minimum_tail_length_m,
        )
        if not (folded or subgrid_tail):
            break
        remeshed = _remesh_known_plough_tail_window(
            positions=positions_list,
            velocities=velocities_list,
            rest_lengths_m=rest_lengths,
            contact_flags=contact_flags_list,
            length_lambdas_n_s2=length_lambdas,
            segment_tensions_n=[0.0 for _ in rest_lengths],
            length_constraint_reactions_n=[0.0 for _ in rest_lengths],
            contact_lambdas_n_s2=contact_lambdas,
            contact_normal_reactions_n=contact_reactions,
            seabed_depth_m=seabed_depth_m,
        )
        if remeshed is None:
            if not folded:
                break
            left_rest_length = rest_lengths[-2]
            right_rest_length = rest_lengths[-1]
            merged_rest_length = left_rest_length + right_rest_length
            merged_lambda = (
                length_lambdas[-2] * left_rest_length
                + length_lambdas[-1] * right_rest_length
            ) / max(merged_rest_length, _MIN_LENGTH)
            rest_lengths[-2:] = [merged_rest_length]
            length_lambdas[-2:] = [merged_lambda]
            positions_list.pop(-2)
            velocities_list.pop(-2)
            contact_flags_list.pop(-2)
            contact_lambdas.pop(-2)
            contact_reactions.pop(-2)
            continue
        (
            positions_list,
            velocities_list,
            rest_lengths,
            contact_flags_list,
            length_lambdas,
            _,
            _,
            contact_lambdas,
            contact_reactions,
        ) = remeshed

    return (
        tuple(positions_list),
        tuple(velocities_list),
        tuple(rest_lengths),
        tuple(contact_flags_list),
        tuple(length_lambdas),
        tuple(contact_lambdas),
        tuple(contact_reactions),
    )


def _solve_xpbd_endpoint_constraints(
    case: OperationCase,
    *,
    positions: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    inverse_masses: tuple[float, ...],
    seabed_depth_m: float,
    dt_s: float,
    iterations: int,
    minimum_iterations: int | None = None,
    top_position: Vector3,
    bottom_position: Vector3,
    initial_constraint_reactions_n: tuple[float, ...] = (),
) -> tuple[tuple[Vector3, ...], tuple[float, ...], tuple[float, ...], int, float]:
    solved = list(positions)
    solved[0] = top_position
    solved[-1] = bottom_position
    if initial_constraint_reactions_n and len(initial_constraint_reactions_n) != len(rest_lengths_m):
        raise ValueError("initial_constraint_reactions_n must have one entry per segment")
    length_lambdas = [
        max(0.0, reaction) * dt_s * dt_s
        for reaction in (
            initial_constraint_reactions_n
            if initial_constraint_reactions_n
            else (0.0 for _ in rest_lengths_m)
        )
    ]
    contact_lambdas = [0.0 for _ in solved]
    axial_stiffness = max(case.cable.axial_stiffness_n, _MIN_MASS)
    bend_projection_radius_m = _feasible_bend_projection_radius_m(
        requested_radius_m=case.cable.min_bending_radius_m,
        rest_lengths_m=rest_lengths_m,
        top_position=top_position,
        bottom_position=bottom_position,
    )
    maximum_iterations = max(1, iterations)
    convergence_check_start = (
        maximum_iterations
        if minimum_iterations is None
        else min(maximum_iterations, max(1, minimum_iterations))
    )
    axial_residual_m = math.inf
    for iteration_index in range(maximum_iterations):
        axial_step = solve_global_axial_constraint_step(
            positions=solved,
            rest_lengths_m=rest_lengths_m,
            inverse_masses_per_kg=inverse_masses,
            axial_stiffness_n=axial_stiffness,
            dt_s=dt_s,
            lambdas_n_s2=length_lambdas,
        )
        solved = list(axial_step.positions)
        length_lambdas = list(axial_step.lambdas_n_s2)
        solved[0] = top_position
        solved[-1] = bottom_position
        _apply_minimum_bend_radius_constraints(
            solved,
            inverse_masses=inverse_masses,
            minimum_radius_m=bend_projection_radius_m,
        )
        solved[0] = top_position
        solved[-1] = bottom_position
        for index in range(1, len(solved) - 1):
            penetration = solved[index][2] - seabed_depth_m
            if penetration <= 0.0:
                continue
            wi = inverse_masses[index]
            if wi <= _MIN_MASS:
                continue
            contact_lambdas[index] += penetration / wi
            solved[index] = (solved[index][0], solved[index][1], seabed_depth_m)
        _apply_segment_spacing_floor_constraints(
            solved,
            rest_lengths_m=rest_lengths_m,
            inverse_masses=inverse_masses,
        )
        solved[0] = top_position
        solved[-1] = bottom_position
        if iteration_index + 1 >= convergence_check_start:
            axial_residual_m = axial_constraint_residual_m(
                positions=solved,
                rest_lengths_m=rest_lengths_m,
                lambdas_n_s2=length_lambdas,
                axial_stiffness_n=axial_stiffness,
                dt_s=dt_s,
            )
            if axial_residual_m <= _KNOWN_PLOUGH_AXIAL_RESIDUAL_TOLERANCE_M:
                break
    if axial_residual_m > _KNOWN_PLOUGH_AXIAL_RESIDUAL_TOLERANCE_M:
        raise RuntimeError(
            "global axial constraints did not converge: "
            f"residual {axial_residual_m:.6g} m exceeds "
            f"{_KNOWN_PLOUGH_AXIAL_RESIDUAL_TOLERANCE_M:.6g} m"
        )
    return (
        tuple(solved),
        tuple(length_lambdas),
        tuple(contact_lambdas),
        iteration_index + 1,
        axial_residual_m,
    )


def _feasible_bend_projection_radius_m(
    *,
    requested_radius_m: float | None,
    rest_lengths_m: tuple[float, ...],
    top_position: Vector3,
    bottom_position: Vector3,
) -> float | None:
    """Return the requested radius only when a constant-curvature span can satisfy it."""

    if requested_radius_m is None:
        return None
    if not math.isfinite(requested_radius_m):
        raise ValueError("requested minimum bend radius must be finite")
    if requested_radius_m <= _MIN_LENGTH:
        return None
    arc_length_m = sum(rest_lengths_m)
    chord_length_m = math.dist(top_position, bottom_position)
    if arc_length_m <= chord_length_m + _MIN_LENGTH:
        return requested_radius_m
    chord_ratio = max(0.0, min(1.0, chord_length_m / arc_length_m))
    lower_angle = 0.0
    upper_angle = math.pi
    for _ in range(80):
        half_angle = 0.5 * (lower_angle + upper_angle)
        ratio = math.sin(half_angle) / half_angle
        if ratio > chord_ratio:
            lower_angle = half_angle
        else:
            upper_angle = half_angle
    equivalent_arc_radius_m = arc_length_m / (lower_angle + upper_angle)
    if requested_radius_m > equivalent_arc_radius_m * (1.0 + 1.0e-12):
        return None
    return requested_radius_m


def _apply_minimum_bend_radius_constraints(
    positions: list[Vector3],
    *,
    inverse_masses: tuple[float, ...],
    minimum_radius_m: float | None,
) -> None:
    """Reduce local kinks when an engineering minimum bend radius is configured."""

    if minimum_radius_m is None or minimum_radius_m <= _MIN_LENGTH or len(positions) < 3:
        return
    for index in range(1, len(positions) - 1):
        wi = inverse_masses[index]
        if wi <= _MIN_MASS:
            continue
        previous = positions[index - 1]
        current = positions[index]
        next_point = positions[index + 1]
        first = _sub(current, previous)
        second = _sub(next_point, current)
        first_length = _norm(first)
        second_length = _norm(second)
        if first_length <= _MIN_LENGTH or second_length <= _MIN_LENGTH:
            continue
        dot = max(-1.0, min(1.0, _dot(first, second) / (first_length * second_length)))
        turn = math.acos(dot)
        max_turn = 0.5 * (first_length + second_length) / minimum_radius_m
        if turn <= max_turn:
            continue
        chord = _sub(next_point, previous)
        chord_length2 = max(_dot(chord, chord), _MIN_LENGTH)
        fraction = max(0.0, min(1.0, _dot(_sub(current, previous), chord) / chord_length2))
        foot = _add(previous, _mul(chord, fraction))
        relaxation = min(0.65, max(0.05, (turn - max_turn) / max(turn, _MIN_LENGTH)))
        positions[index] = _add(current, _mul(_sub(foot, current), relaxation))


def _apply_segment_spacing_floor_constraints(
    positions: list[Vector3],
    *,
    rest_lengths_m: tuple[float, ...],
    inverse_masses: tuple[float, ...],
) -> None:
    """Keep relaxed/slack nodes from collapsing into sub-grid contact clusters."""

    for index, rest_length in enumerate(rest_lengths_m):
        floor_length = _SEGMENT_SPACING_FLOOR_FRACTION * rest_length
        if floor_length <= _MIN_LENGTH:
            continue
        start = positions[index]
        end = positions[index + 1]
        delta = _sub(end, start)
        length = _norm(delta)
        if length >= floor_length:
            continue
        direction = _spacing_floor_direction(positions, index, delta)
        correction = floor_length - length
        wi = inverse_masses[index]
        wj = inverse_masses[index + 1]
        total_weight = wi + wj
        if total_weight <= _MIN_MASS:
            continue
        if wi > _MIN_MASS:
            positions[index] = _sub(start, _mul(direction, correction * wi / total_weight))
        if wj > _MIN_MASS:
            positions[index + 1] = _add(end, _mul(direction, correction * wj / total_weight))


def _spacing_floor_direction(
    positions: list[Vector3],
    index: int,
    delta: Vector3,
) -> Vector3:
    length = _norm(delta)
    if length > _MIN_LENGTH:
        return _mul(delta, 1.0 / length)
    if index > 0:
        previous = _sub(positions[index], positions[index - 1])
        previous_length = _norm(previous)
        if previous_length > _MIN_LENGTH:
            return _mul(previous, 1.0 / previous_length)
    if index + 2 < len(positions):
        next_delta = _sub(positions[index + 2], positions[index + 1])
        next_length = _norm(next_delta)
        if next_length > _MIN_LENGTH:
            return _mul(next_delta, 1.0 / next_length)
    return (1.0, 0.0, 0.0)


def _minimum_bend_radius_status(
    *,
    minimum_radius_m: float | None,
    limit_m: float | None,
) -> str:
    if limit_m is None:
        return "not_configured"
    if minimum_radius_m is None or not math.isfinite(minimum_radius_m):
        return "not_available"
    if minimum_radius_m + 1.0e-6 < limit_m:
        return "below_limit"
    return "ok"


def _plough_tension_status(
    *,
    boundary_tension_n: float | None,
    adjacent_segment_tension_n: float | None,
) -> str:
    """Classify whether the plough boundary tension is carried by the span."""

    if boundary_tension_n is None or adjacent_segment_tension_n is None:
        return "not_available"
    boundary = max(0.0, boundary_tension_n)
    adjacent = max(0.0, adjacent_segment_tension_n)
    if boundary <= 1.0e-9:
        return "free_or_unset"
    if adjacent <= max(1.0e-6, 0.01 * boundary):
        return "slack_or_unclosed"
    if adjacent < 0.5 * boundary:
        return "low_adjacent_tension"
    return "carried"


def _scaled_rest_lengths(rest_lengths_m: tuple[float, ...], total_length_m: float) -> tuple[float, ...]:
    if not rest_lengths_m:
        return ()
    current_total = sum(rest_lengths_m)
    if current_total <= _MIN_LENGTH:
        return tuple(total_length_m / len(rest_lengths_m) for _ in rest_lengths_m)
    scale = total_length_m / current_total
    return tuple(max(_MIN_LENGTH, length * scale) for length in rest_lengths_m)


def _state_material_suspended_length(state: DynamicLayingState) -> float:
    material_length = state.material_suspended_length_m
    if material_length > _MIN_LENGTH and math.isfinite(material_length):
        return material_length
    return state.suspended_length_m


def _known_plough_target_segment_length(dynamic_case, state: DynamicLayingState) -> float:
    material_length = _state_material_suspended_length(state)
    count_based = material_length / max(int(getattr(dynamic_case, "element_count", 1)), 1)
    local_median = _target_segment_length(state.rest_lengths_m, None)
    return max(count_based, 0.5 * local_median, 0.25)


def _plough_exit_material_speed(
    dynamic_case,
    plough_velocity: Vector3,
    *,
    time_s: float | None = None,
) -> tuple[float, str]:
    """Return the lower material boundary speed and its declared source.

    A plough-exit encoder measurement is the lower material-flow boundary. When
    it is unavailable, the route-longitudinal plough speed is used only as the
    explicit straight-route, no-slip inference required by the input contract.
    """

    samples = getattr(dynamic_case, "plough_exit_speed_samples", ())
    if samples:
        if time_s is None:
            time_s = samples[-1].time_s
        return _sampled_scalar_value(samples, time_s), "measured"
    measured_speed = getattr(dynamic_case, "plough_exit_speed_mps", None)
    if measured_speed is not None:
        return measured_speed, "measured"
    from .dynamic import allows_no_slip_inferred_plough_exit

    if not allows_no_slip_inferred_plough_exit(
        plough_motion_segments=dynamic_case.plough_motion_segments,
        plough_motion_samples=dynamic_case.plough_motion_samples,
        plough_heading_deg=dynamic_case.plough_heading_deg,
    ):
        raise ValueError("plough_exit_speed_mps is required for non-longitudinal or sampled plough motion")
    return _plough_laydown_transfer_speed(plough_velocity), "no_slip_inferred"


def _plough_laydown_transfer_speed(plough_velocity: Vector3) -> float:
    """Infer lower material outflow from a straight, no-slip route assumption.

    The operation-track frame uses +X as the laying route tangent. Transverse
    plough motion changes the 3D boundary, but it does not by itself consume
    cable length into the laid route. Callers must expose this as an inference.
    """

    return max(0.0, plough_velocity[0])


def _advance_known_plough_material_flow(
    state: DynamicLayingState,
    *,
    payout_increment_m: float,
    laydown_increment_m: float,
    target_segment_length_m: float,
    seabed_depth_m: float | None = None,
) -> DynamicLayingState:
    payout_increment = max(0.0, payout_increment_m)
    laydown_increment = max(0.0, laydown_increment_m)
    net_increment = payout_increment - laydown_increment
    if abs(net_increment) <= _MIN_LENGTH:
        return state
    if net_increment > 0.0:
        return _insert_payout_nodes(
            state,
            payout_increment_m=net_increment,
            target_segment_length_m=target_segment_length_m,
        )
    withdrawal_increment = -net_increment
    return _withdraw_known_plough_tail_length(
        state,
        laydown_increment_m=withdrawal_increment,
        minimum_segment_length_m=max(
            _MIN_LENGTH,
            withdrawal_increment / _MAX_NODE_CFL_FRACTION,
        ),
        seabed_depth_m=seabed_depth_m,
    )


def _withdraw_known_plough_tail_length(
    state: DynamicLayingState,
    *,
    laydown_increment_m: float,
    minimum_segment_length_m: float,
    seabed_depth_m: float | None = None,
) -> DynamicLayingState:
    if laydown_increment_m <= _MIN_LENGTH or not state.rest_lengths_m:
        return state
    positions = list(state.positions)
    velocities = list(state.velocities)
    rest_lengths = list(state.rest_lengths_m)
    contact_flags = list(state.contact_flags)
    length_lambdas = _padded_values(state.length_lambdas_n_s2, len(rest_lengths))
    segment_tensions = _padded_values(state.segment_tensions_n, len(rest_lengths))
    length_reactions = _padded_values(state.length_constraint_reactions_n, len(rest_lengths))
    contact_lambdas = _padded_values(state.contact_lambdas_n_s2, len(positions))
    contact_reactions = _padded_values(state.contact_normal_reactions_n, len(positions))
    remaining = laydown_increment_m
    min_length = max(_MIN_LENGTH, minimum_segment_length_m)
    while remaining > _MIN_LENGTH and rest_lengths:
        if len(rest_lengths) == 1:
            withdrawn = min(remaining, max(0.0, rest_lengths[-1] - _MIN_LENGTH))
            rest_lengths[-1] -= withdrawn
            remaining -= withdrawn
            break
        length_to_remesh = max(0.0, rest_lengths[-1] - min_length)
        if remaining + _MIN_LENGTH < length_to_remesh:
            rest_lengths[-1] -= remaining
            remaining = 0.0
            break
        rest_lengths[-1] -= length_to_remesh
        remaining = max(0.0, remaining - length_to_remesh)
        remeshed = _remesh_known_plough_tail_window(
            positions=positions,
            velocities=velocities,
            rest_lengths_m=rest_lengths,
            contact_flags=contact_flags,
            length_lambdas_n_s2=length_lambdas,
            segment_tensions_n=segment_tensions,
            length_constraint_reactions_n=length_reactions,
            contact_lambdas_n_s2=contact_lambdas,
            contact_normal_reactions_n=contact_reactions,
            seabed_depth_m=seabed_depth_m,
        )
        if remeshed is None:
            raise RuntimeError(
                "known-plough tail remesh projection failed; refusing to advance a sub-grid segment"
            )
        (
            positions,
            velocities,
            rest_lengths,
            contact_flags,
            length_lambdas,
            segment_tensions,
            length_reactions,
            contact_lambdas,
            contact_reactions,
        ) = remeshed
        if remaining <= _MIN_LENGTH:
            break
    return DynamicLayingState(
        time_s=state.time_s,
        positions=tuple(positions),
        velocities=tuple(velocities),
        rest_lengths_m=tuple(rest_lengths),
        paid_length_m=state.paid_length_m,
        laid_length_m=state.laid_length_m,
        contact_flags=tuple(contact_flags),
        length_lambdas_n_s2=tuple(length_lambdas[: len(rest_lengths)]),
        contact_lambdas_n_s2=tuple(contact_lambdas[: len(positions)]),
        segment_tensions_n=tuple(segment_tensions[: len(rest_lengths)]),
        length_constraint_reactions_n=tuple(length_reactions[: len(rest_lengths)]),
        contact_normal_reactions_n=tuple(contact_reactions[: len(positions)]),
        payout_buffer_m=state.payout_buffer_m,
        laydown_buffer_m=state.laydown_buffer_m,
        laid_segment_lengths_m=state.laid_segment_lengths_m,
        material_suspended_length_m=state.material_suspended_length_m,
        geometric_length_deficit_m=state.geometric_length_deficit_m,
    )


def _remesh_known_plough_tail_window(
    *,
    positions: list[Vector3],
    velocities: list[Vector3],
    rest_lengths_m: list[float],
    contact_flags: list[bool],
    length_lambdas_n_s2: list[float],
    segment_tensions_n: list[float],
    length_constraint_reactions_n: list[float],
    contact_lambdas_n_s2: list[float],
    contact_normal_reactions_n: list[float],
    seabed_depth_m: float | None = None,
) -> tuple[
    list[Vector3],
    list[Vector3],
    list[float],
    list[bool],
    list[float],
    list[float],
    list[float],
    list[float],
    list[float],
] | None:
    """Remove one tail node without discarding local curve length or state."""

    window_segment_count = min(6, len(rest_lengths_m))
    if window_segment_count < 3:
        return None
    start_segment = len(rest_lengths_m) - window_segment_count
    old_rest_lengths = rest_lengths_m[start_segment:]
    if any(length <= _MIN_LENGTH for length in old_rest_lengths):
        return None
    old_positions = positions[start_segment:]
    old_velocities = velocities[start_segment:]
    old_contact_lambdas = contact_lambdas_n_s2[start_segment:]
    old_contact_reactions = contact_normal_reactions_n[start_segment:]
    old_coordinates = _cumulative_coordinates(old_rest_lengths)
    new_segment_count = window_segment_count - 1
    new_rest_length = old_coordinates[-1] / new_segment_count
    new_rest_lengths = [new_rest_length for _ in range(new_segment_count)]
    new_coordinates = [new_rest_length * index for index in range(new_segment_count + 1)]

    old_deformed_lengths = [
        _norm(_sub(right, left))
        for left, right in zip(old_positions, old_positions[1:])
    ]
    old_stretches = [
        deformed_length / rest_length
        for deformed_length, rest_length in zip(old_deformed_lengths, old_rest_lengths)
    ]
    target_deformed_lengths = [
        _material_interval_average(
            old_stretches,
            old_coordinates,
            new_coordinates[index],
            new_coordinates[index + 1],
        )
        * new_rest_length
        for index in range(new_segment_count)
    ]
    sampled_positions = [
        _sample_material_vector(old_positions, old_coordinates, coordinate)
        for coordinate in new_coordinates
    ]
    projected_positions = _project_open_chain_segment_lengths(
        sampled_positions,
        target_deformed_lengths,
    )
    if projected_positions is None:
        return None
    if seabed_depth_m is not None:
        seabed_projected_positions = _project_open_chain_segment_lengths_with_seabed(
            projected_positions,
            target_deformed_lengths,
            seabed_depth_m=seabed_depth_m,
        )
        if seabed_projected_positions is None:
            return None
        projected_positions = seabed_projected_positions

    sampled_velocities = [
        _sample_material_vector(old_velocities, old_coordinates, coordinate)
        for coordinate in new_coordinates
    ]
    sampled_contact_lambdas = [
        _sample_material_scalar(old_contact_lambdas, old_coordinates, coordinate)
        for coordinate in new_coordinates
    ]
    sampled_contact_reactions = [
        _sample_material_scalar(old_contact_reactions, old_coordinates, coordinate)
        for coordinate in new_coordinates
    ]
    sampled_contact_flags = [
        _sample_material_contact_flag(
            contact_flags[start_segment:],
            old_coordinates,
            coordinate,
        )
        for coordinate in new_coordinates
    ]

    def remap_segment_field(values: list[float]) -> list[float]:
        old_values = values[start_segment:]
        return [
            _material_interval_average(
                old_values,
                old_coordinates,
                new_coordinates[index],
                new_coordinates[index + 1],
            )
            for index in range(new_segment_count)
        ]

    return (
        positions[:start_segment] + projected_positions,
        velocities[:start_segment] + sampled_velocities,
        rest_lengths_m[:start_segment] + new_rest_lengths,
        contact_flags[:start_segment] + sampled_contact_flags,
        length_lambdas_n_s2[:start_segment] + remap_segment_field(length_lambdas_n_s2),
        segment_tensions_n[:start_segment] + remap_segment_field(segment_tensions_n),
        length_constraint_reactions_n[:start_segment] + remap_segment_field(length_constraint_reactions_n),
        contact_lambdas_n_s2[:start_segment] + sampled_contact_lambdas,
        contact_normal_reactions_n[:start_segment] + sampled_contact_reactions,
    )


def _cumulative_coordinates(lengths: list[float]) -> list[float]:
    coordinates = [0.0]
    for length in lengths:
        coordinates.append(coordinates[-1] + length)
    return coordinates


def _material_interval_average(
    values: list[float],
    coordinates: list[float],
    start: float,
    end: float,
) -> float:
    interval = end - start
    if interval <= _MIN_LENGTH:
        return 0.0
    integral = 0.0
    for index, value in enumerate(values):
        overlap = max(
            0.0,
            min(end, coordinates[index + 1]) - max(start, coordinates[index]),
        )
        integral += value * overlap
    return integral / interval


def _material_sample_interval(coordinates: list[float], coordinate: float) -> tuple[int, float]:
    if coordinate <= coordinates[0]:
        return 0, 0.0
    if coordinate >= coordinates[-1]:
        return len(coordinates) - 2, 1.0
    for index in range(len(coordinates) - 1):
        if coordinate <= coordinates[index + 1]:
            span = coordinates[index + 1] - coordinates[index]
            fraction = (coordinate - coordinates[index]) / max(span, _MIN_LENGTH)
            return index, fraction
    return len(coordinates) - 2, 1.0


def _sample_material_vector(
    values: list[Vector3],
    coordinates: list[float],
    coordinate: float,
) -> Vector3:
    index, fraction = _material_sample_interval(coordinates, coordinate)
    return _add(values[index], _mul(_sub(values[index + 1], values[index]), fraction))


def _sample_material_scalar(
    values: list[float],
    coordinates: list[float],
    coordinate: float,
) -> float:
    index, fraction = _material_sample_interval(coordinates, coordinate)
    return values[index] + fraction * (values[index + 1] - values[index])


def _sample_material_contact_flag(
    values: list[bool],
    coordinates: list[float],
    coordinate: float,
) -> bool:
    index, fraction = _material_sample_interval(coordinates, coordinate)
    if fraction <= _MIN_LENGTH:
        return values[index]
    if 1.0 - fraction <= _MIN_LENGTH:
        return values[index + 1]
    return values[index] and values[index + 1]


def _project_open_chain_segment_lengths(
    positions: list[Vector3],
    target_lengths: list[float],
) -> list[Vector3] | None:
    if len(positions) != len(target_lengths) + 1 or len(positions) < 3:
        return None
    total_length = sum(target_lengths)
    endpoint_distance = _norm(_sub(positions[-1], positions[0]))
    longest = max(target_lengths, default=0.0)
    minimum_endpoint_distance = max(0.0, 2.0 * longest - total_length)
    tolerance = 1.0e-11 * max(1.0, total_length)
    if endpoint_distance > total_length + tolerance or endpoint_distance + tolerance < minimum_endpoint_distance:
        return None
    if endpoint_distance <= _MIN_LENGTH:
        return None

    start = positions[0]
    chord_direction = _mul(_sub(positions[-1], start), 1.0 / endpoint_distance)
    transverse_offsets = []
    for position in positions:
        relative = _sub(position, start)
        axial_coordinate = _dot(relative, chord_direction)
        transverse_offsets.append(_sub(relative, _mul(chord_direction, axial_coordinate)))
    transverse_offsets[0] = (0.0, 0.0, 0.0)
    transverse_offsets[-1] = (0.0, 0.0, 0.0)
    transverse_steps = [
        _sub(right, left)
        for left, right in zip(transverse_offsets, transverse_offsets[1:])
    ]
    transverse_step_lengths = [_norm(step) for step in transverse_steps]

    if max(transverse_step_lengths, default=0.0) <= _MIN_LENGTH and total_length > endpoint_distance + tolerance:
        normal = _stable_transverse_direction(chord_direction)
        transverse_offsets = [
            _mul(normal, math.sin(math.pi * index / len(target_lengths)))
            for index in range(len(positions))
        ]
        transverse_offsets[0] = (0.0, 0.0, 0.0)
        transverse_offsets[-1] = (0.0, 0.0, 0.0)
        transverse_steps = [
            _sub(right, left)
            for left, right in zip(transverse_offsets, transverse_offsets[1:])
        ]
        transverse_step_lengths = [_norm(step) for step in transverse_steps]

    def axial_reach(scale: float) -> float:
        return sum(
            math.sqrt(max(0.0, target * target - (scale * transverse) ** 2))
            for target, transverse in zip(target_lengths, transverse_step_lengths)
        )

    positive_limits = [
        target / transverse
        for target, transverse in zip(target_lengths, transverse_step_lengths)
        if transverse > _MIN_LENGTH
    ]
    if not positive_limits:
        if abs(total_length - endpoint_distance) > tolerance:
            return None
        transverse_scale = 0.0
    else:
        lower = 0.0
        upper = min(positive_limits) * (1.0 - 1.0e-12)
        if axial_reach(upper) > endpoint_distance + tolerance:
            return None
        for _ in range(160):
            middle = 0.5 * (lower + upper)
            if axial_reach(middle) > endpoint_distance:
                lower = middle
            else:
                upper = middle
        transverse_scale = upper

    axial_increments = [
        math.sqrt(max(0.0, target * target - (transverse_scale * transverse) ** 2))
        for target, transverse in zip(target_lengths, transverse_step_lengths)
    ]
    axial_scale = endpoint_distance / max(sum(axial_increments), _MIN_LENGTH)
    projected = [start]
    axial_coordinate = 0.0
    for index in range(1, len(positions) - 1):
        axial_coordinate += axial_increments[index - 1] * axial_scale
        projected.append(
            _add(
                _add(start, _mul(chord_direction, axial_coordinate)),
                _mul(transverse_offsets[index], transverse_scale),
            )
        )
    projected.append(positions[-1])
    errors = [
        abs(_norm(_sub(right, left)) - target)
        for left, right, target in zip(projected, projected[1:], target_lengths)
    ]
    if errors and max(errors) > 1.0e-8 * max(1.0, total_length):
        return None
    return projected


def _project_open_chain_segment_lengths_with_seabed(
    positions: list[Vector3],
    target_lengths: list[float],
    *,
    seabed_depth_m: float,
) -> list[Vector3] | None:
    """Enforce remeshed segment lengths without allowing seabed penetration."""

    if len(positions) != len(target_lengths) + 1 or len(positions) < 3:
        return None
    if positions[0][2] > seabed_depth_m or positions[-1][2] > seabed_depth_m:
        return None
    tolerance = _REMESH_PROJECTION_REL_TOLERANCE * max(1.0, sum(target_lengths))
    seabed_chain = _project_tail_chain_onto_seabed(
        positions,
        target_lengths,
        seabed_depth_m=seabed_depth_m,
    )
    if seabed_chain is not None:
        return seabed_chain
    endpoint_delta = _sub(positions[-1], positions[0])
    endpoint_distance = _norm(endpoint_delta)
    if endpoint_distance > _MIN_LENGTH:
        chord_direction = _mul(endpoint_delta, 1.0 / endpoint_distance)
        reflected: list[Vector3] = []
        for position in positions:
            relative = _sub(position, positions[0])
            chord_point = _add(
                positions[0],
                _mul(chord_direction, _dot(relative, chord_direction)),
            )
            reflected.append(_sub(_mul(chord_point, 2.0), position))
        reflection_error = max(
            abs(math.dist(left, right) - target)
            for left, right, target in zip(reflected, reflected[1:], target_lengths)
        )
        if (
            reflection_error <= tolerance
            and max(position[2] for position in reflected) <= seabed_depth_m
        ):
            return reflected
    solved = [list(position) for position in positions]
    fixed_start = tuple(positions[0])
    fixed_end = tuple(positions[-1])
    for position in solved[1:-1]:
        position[2] = min(position[2], seabed_depth_m)
    for _ in range(_REMESH_PROJECTION_MAX_ITERATIONS):
        for segment_indices in (
            range(len(target_lengths)),
            range(len(target_lengths) - 1, -1, -1),
        ):
            for index in segment_indices:
                left = solved[index]
                right = solved[index + 1]
                delta = [right[axis] - left[axis] for axis in range(3)]
                length = math.sqrt(sum(component * component for component in delta))
                if length <= _MIN_LENGTH:
                    continue
                error = length - target_lengths[index]
                left_weight = 0.0 if index == 0 else 1.0
                right_weight = 0.0 if index + 1 == len(solved) - 1 else 1.0
                weight_sum = left_weight + right_weight
                if weight_sum <= 0.0:
                    continue
                for axis in range(3):
                    correction = error * delta[axis] / length
                    left[axis] += left_weight * correction / weight_sum
                    right[axis] -= right_weight * correction / weight_sum
                if index > 0:
                    left[2] = min(left[2], seabed_depth_m)
                if index + 1 < len(solved) - 1:
                    right[2] = min(right[2], seabed_depth_m)
        solved[0] = list(fixed_start)
        solved[-1] = list(fixed_end)
        maximum_error = max(
            abs(math.dist(left, right) - target)
            for left, right, target in zip(solved, solved[1:], target_lengths)
        )
        if maximum_error <= tolerance:
            return [tuple(position) for position in solved]
    return None


def _project_tail_chain_onto_seabed(
    positions: list[Vector3],
    target_lengths: list[float],
    *,
    seabed_depth_m: float,
) -> list[Vector3] | None:
    """Place the largest feasible suffix on the seabed."""

    if len(target_lengths) < 2:
        return None
    start = positions[0]
    end = positions[-1]
    if start[2] > seabed_depth_m + _SEABED_CONTACT_TOLERANCE_M:
        return None
    horizontal_delta = (end[0] - start[0], end[1] - start[1], 0.0)
    horizontal_distance = _norm(horizontal_delta)
    if horizontal_distance <= _MIN_LENGTH:
        route_direction = (1.0, 0.0, 0.0)
    else:
        route_direction = _mul(horizontal_delta, 1.0 / horizontal_distance)
    tolerance = _REMESH_PROJECTION_REL_TOLERANCE * max(1.0, sum(target_lengths))
    segment_count = len(target_lengths)
    for contact_segment_count in range(segment_count - 1, 0, -1):
        prefix_segment_count = segment_count - contact_segment_count
        contact_lengths = target_lengths[prefix_segment_count:]
        contact_length = sum(contact_lengths)
        first_contact = (
            end[0] - route_direction[0] * contact_length,
            end[1] - route_direction[1] * contact_length,
            seabed_depth_m,
        )
        prefix_lengths = target_lengths[:prefix_segment_count]
        prefix_distance = _norm(_sub(first_contact, start))
        prefix_total = sum(prefix_lengths)
        prefix_longest = max(prefix_lengths, default=0.0)
        prefix_minimum_distance = max(0.0, 2.0 * prefix_longest - prefix_total)
        if (
            prefix_distance > prefix_total + tolerance
            or prefix_distance + tolerance < prefix_minimum_distance
        ):
            continue
        if prefix_segment_count == 1:
            prefix = [start, first_contact]
        else:
            prefix_seed = positions[:prefix_segment_count] + [first_contact]
            prefix = _project_open_chain_segment_lengths(prefix_seed, prefix_lengths)
            if prefix is None:
                continue
        if max(position[2] for position in prefix) > seabed_depth_m:
            prefix_delta = _sub(prefix[-1], prefix[0])
            prefix_distance = _norm(prefix_delta)
            if prefix_distance <= _MIN_LENGTH:
                continue
            prefix_direction = _mul(prefix_delta, 1.0 / prefix_distance)
            reflected: list[Vector3] = []
            for position in prefix:
                relative = _sub(position, prefix[0])
                chord_point = _add(
                    prefix[0],
                    _mul(prefix_direction, _dot(relative, prefix_direction)),
                )
                reflected.append(_sub(_mul(chord_point, 2.0), position))
            prefix = reflected
        if max(position[2] for position in prefix) > seabed_depth_m + tolerance:
            continue
        contact_nodes = [first_contact]
        cursor = first_contact
        for length in contact_lengths:
            cursor = (
                cursor[0] + route_direction[0] * length,
                cursor[1] + route_direction[1] * length,
                seabed_depth_m,
            )
            contact_nodes.append(cursor)
        contact_nodes[-1] = end
        projected = prefix + contact_nodes[1:]
        maximum_error = max(
            abs(math.dist(left, right) - target)
            for left, right, target in zip(projected, projected[1:], target_lengths)
        )
        if maximum_error <= tolerance:
            return projected
    return None


def _stable_transverse_direction(direction: Vector3) -> Vector3:
    candidate = (0.0, 0.0, 1.0)
    if abs(_dot(direction, candidate)) > 0.9:
        candidate = (0.0, 1.0, 0.0)
    transverse = _sub(candidate, _mul(direction, _dot(direction, candidate)))
    return _safe_unit(transverse)


def _limit_endpoint_span_velocities(
    velocities: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    dt_s: float,
) -> tuple[Vector3, ...]:
    limited = list(velocities)
    for index in range(1, len(limited) - 1):
        speed = _norm(limited[index])
        if speed <= _MIN_LENGTH or not math.isfinite(speed):
            limited[index] = (0.0, 0.0, 0.0)
            continue
        local_length = _local_segment_length(index, rest_lengths_m)
        max_speed = _MAX_NODE_CFL_FRACTION * local_length / max(dt_s, _MIN_LENGTH)
        if speed > max_speed:
            limited[index] = _mul(limited[index], max_speed / speed)
    return tuple(limited)


def _vessel_position(dynamic_case, time_s: float) -> Vector3:
    if getattr(dynamic_case, "vessel_motion_samples", ()):
        return _sampled_motion_position(dynamic_case.vessel_motion_samples, time_s, default_z=0.0)
    if getattr(dynamic_case, "vessel_motion_segments", ()):
        offset = _motion_displacement(dynamic_case.vessel_motion_segments, time_s)
        return (
            dynamic_case.vessel_initial_x_m + offset[0],
            dynamic_case.vessel_initial_y_m + offset[1],
            0.0,
        )
    direction = _heading_unit(dynamic_case.vessel_heading_deg)
    distance = _vessel_distance(dynamic_case, time_s)
    return (
        dynamic_case.vessel_initial_x_m + direction[0] * distance,
        dynamic_case.vessel_initial_y_m + direction[1] * distance,
        0.0,
    )


def _plough_position(dynamic_case, time_s: float) -> Vector3:
    if getattr(dynamic_case, "plough_motion_samples", ()):
        default_z = dynamic_case.plough_initial_z_m if dynamic_case.plough_initial_z_m is not None else 0.0
        return _sampled_motion_position(dynamic_case.plough_motion_samples, time_s, default_z=default_z)
    if dynamic_case.plough_initial_x_m is None or dynamic_case.plough_initial_y_m is None or dynamic_case.plough_initial_z_m is None:
        raise ValueError("plough initial position is required")
    if getattr(dynamic_case, "plough_motion_segments", ()):
        offset = _motion_displacement(dynamic_case.plough_motion_segments, time_s)
        return (
            dynamic_case.plough_initial_x_m + offset[0],
            dynamic_case.plough_initial_y_m + offset[1],
            dynamic_case.plough_initial_z_m,
        )
    direction = _heading_unit(dynamic_case.plough_heading_deg or 0.0)
    distance = (dynamic_case.plough_speed_mps or 0.0) * time_s
    return (
        dynamic_case.plough_initial_x_m + direction[0] * distance,
        dynamic_case.plough_initial_y_m + direction[1] * distance,
        dynamic_case.plough_initial_z_m,
    )


def _vessel_velocity(dynamic_case, time_s: float) -> Vector3:
    if getattr(dynamic_case, "vessel_motion_samples", ()):
        return _sampled_motion_velocity(dynamic_case.vessel_motion_samples, time_s, default_z=0.0)
    if getattr(dynamic_case, "vessel_motion_segments", ()):
        return _motion_velocity(dynamic_case.vessel_motion_segments, time_s)
    direction = _heading_unit(dynamic_case.vessel_heading_deg)
    speed = _vessel_speed(dynamic_case, time_s)
    return (direction[0] * speed, direction[1] * speed, 0.0)


def _plough_velocity(dynamic_case, time_s: float) -> Vector3:
    if getattr(dynamic_case, "plough_motion_samples", ()):
        default_z = dynamic_case.plough_initial_z_m if dynamic_case.plough_initial_z_m is not None else 0.0
        return _sampled_motion_velocity(dynamic_case.plough_motion_samples, time_s, default_z=default_z)
    if getattr(dynamic_case, "plough_motion_segments", ()):
        return _motion_velocity(dynamic_case.plough_motion_segments, time_s)
    direction = _heading_unit(dynamic_case.plough_heading_deg or 0.0)
    speed = dynamic_case.plough_speed_mps or 0.0
    return (direction[0] * speed, direction[1] * speed, 0.0)


def _sampled_motion_position(samples, time_s: float, *, default_z: float) -> Vector3:
    if not samples:
        return (0.0, 0.0, default_z)
    if len(samples) == 1 or time_s <= samples[0].time_s:
        return _motion_sample_position(samples[0], default_z=default_z)
    for start, end in zip(samples, samples[1:]):
        if time_s <= end.time_s:
            duration = max(end.time_s - start.time_s, _MIN_LENGTH)
            fraction = max(0.0, min(1.0, (time_s - start.time_s) / duration))
            start_pos = _motion_sample_position(start, default_z=default_z)
            end_pos = _motion_sample_position(end, default_z=default_z)
            return (
                start_pos[0] + (end_pos[0] - start_pos[0]) * fraction,
                start_pos[1] + (end_pos[1] - start_pos[1]) * fraction,
                start_pos[2] + (end_pos[2] - start_pos[2]) * fraction,
            )
    last = samples[-1]
    last_pos = _motion_sample_position(last, default_z=default_z)
    last_velocity = _sampled_motion_velocity(samples, last.time_s, default_z=default_z)
    dt = max(0.0, time_s - last.time_s)
    return (
        last_pos[0] + last_velocity[0] * dt,
        last_pos[1] + last_velocity[1] * dt,
        last_pos[2] + last_velocity[2] * dt,
    )


def _sampled_motion_velocity(samples, time_s: float, *, default_z: float) -> Vector3:
    if not samples:
        return (0.0, 0.0, 0.0)
    if len(samples) == 1:
        return _motion_sample_velocity_or_default(samples[0])
    if time_s <= samples[0].time_s:
        return _sample_velocity_between(samples[0], samples[1], default_z=default_z)
    for start, end in zip(samples, samples[1:]):
        if time_s <= end.time_s:
            if _motion_sample_has_velocity(start) and _motion_sample_has_velocity(end):
                duration = max(end.time_s - start.time_s, _MIN_LENGTH)
                fraction = max(0.0, min(1.0, (time_s - start.time_s) / duration))
                start_velocity = _motion_sample_velocity_or_default(start)
                end_velocity = _motion_sample_velocity_or_default(end)
                return (
                    start_velocity[0] + (end_velocity[0] - start_velocity[0]) * fraction,
                    start_velocity[1] + (end_velocity[1] - start_velocity[1]) * fraction,
                    start_velocity[2] + (end_velocity[2] - start_velocity[2]) * fraction,
                )
            return _sample_velocity_between(start, end, default_z=default_z)
    last = samples[-1]
    if _motion_sample_has_velocity(last):
        return _motion_sample_velocity_or_default(last)
    return _sample_velocity_between(samples[-2], last, default_z=default_z)


def _sample_velocity_between(start, end, *, default_z: float) -> Vector3:
    duration = max(end.time_s - start.time_s, _MIN_LENGTH)
    start_pos = _motion_sample_position(start, default_z=default_z)
    end_pos = _motion_sample_position(end, default_z=default_z)
    return (
        (end_pos[0] - start_pos[0]) / duration,
        (end_pos[1] - start_pos[1]) / duration,
        (end_pos[2] - start_pos[2]) / duration,
    )


def _motion_sample_position(sample, *, default_z: float) -> Vector3:
    return (
        float(sample.x_m),
        float(sample.y_m),
        float(default_z if sample.z_m is None else sample.z_m),
    )


def _motion_sample_has_velocity(sample) -> bool:
    return sample.velocity_x_mps is not None and sample.velocity_y_mps is not None


def _motion_sample_velocity_or_default(sample) -> Vector3:
    if not _motion_sample_has_velocity(sample):
        return (0.0, 0.0, 0.0)
    return (
        float(sample.velocity_x_mps),
        float(sample.velocity_y_mps),
        float(0.0 if sample.velocity_z_mps is None else sample.velocity_z_mps),
    )


def _motion_displacement(segments, time_s: float) -> Vector3:
    remaining = max(0.0, time_s)
    x = 0.0
    y = 0.0
    last_segment = None
    for segment in segments:
        last_segment = segment
        duration = max(segment.duration_s, _MIN_LENGTH)
        elapsed = min(remaining, duration)
        if elapsed > 0.0:
            start_velocity, end_velocity = _segment_velocity_endpoints(segment)
            x += start_velocity[0] * elapsed
            x += 0.5 * (end_velocity[0] - start_velocity[0]) * elapsed * elapsed / duration
            y += start_velocity[1] * elapsed
            y += 0.5 * (end_velocity[1] - start_velocity[1]) * elapsed * elapsed / duration
        remaining -= elapsed
        if remaining <= _MIN_LENGTH:
            break
    if remaining > _MIN_LENGTH and last_segment is not None:
        _, end_velocity = _segment_velocity_endpoints(last_segment)
        x += end_velocity[0] * remaining
        y += end_velocity[1] * remaining
    return (x, y, 0.0)


def _motion_velocity(segments, time_s: float) -> Vector3:
    remaining = max(0.0, time_s)
    last_segment = None
    for segment in segments:
        last_segment = segment
        duration = max(segment.duration_s, _MIN_LENGTH)
        if remaining <= duration:
            fraction = max(0.0, min(1.0, remaining / duration))
            start_velocity, end_velocity = _segment_velocity_endpoints(segment)
            return (
                start_velocity[0] + (end_velocity[0] - start_velocity[0]) * fraction,
                start_velocity[1] + (end_velocity[1] - start_velocity[1]) * fraction,
                0.0,
            )
        remaining -= duration
    if last_segment is None:
        return (0.0, 0.0, 0.0)
    _, end_velocity = _segment_velocity_endpoints(last_segment)
    return (end_velocity[0], end_velocity[1], 0.0)


def _segment_velocity_endpoints(segment) -> tuple[Vector3, Vector3]:
    vector_fields = (
        getattr(segment, "start_velocity_x_mps", None),
        getattr(segment, "start_velocity_y_mps", None),
        getattr(segment, "end_velocity_x_mps", None),
        getattr(segment, "end_velocity_y_mps", None),
    )
    if all(value is not None for value in vector_fields):
        start_x, start_y, end_x, end_y = vector_fields
        return (
            (float(start_x), float(start_y), 0.0),
            (float(end_x), float(end_y), 0.0),
        )
    direction = _heading_unit(segment.heading_deg)
    return (
        (direction[0] * segment.start_speed_mps, direction[1] * segment.start_speed_mps, 0.0),
        (direction[0] * segment.end_speed_mps, direction[1] * segment.end_speed_mps, 0.0),
    )


def _heading_unit(degrees: float) -> Vector3:
    radians = math.radians(degrees)
    return (math.cos(radians), math.sin(radians), 0.0)


def _vessel_distance(dynamic_case, time_s: float) -> float:
    if time_s <= 0.0:
        return 0.0
    if time_s <= dynamic_case.duration_s:
        acceleration = (dynamic_case.final_speed_mps - dynamic_case.initial_speed_mps) / max(dynamic_case.duration_s, _MIN_LENGTH)
        return dynamic_case.initial_speed_mps * time_s + 0.5 * acceleration * time_s * time_s
    ramp_distance = 0.5 * (dynamic_case.initial_speed_mps + dynamic_case.final_speed_mps) * dynamic_case.duration_s
    return ramp_distance + dynamic_case.final_speed_mps * (time_s - dynamic_case.duration_s)


def _plough_entry_angle_deg(positions: tuple[Vector3, ...]) -> float:
    if len(positions) < 2:
        return 0.0
    tangent = _safe_unit(_sub(positions[-1], positions[-2]))
    horizontal = math.hypot(tangent[0], tangent[1])
    return math.degrees(math.atan2(abs(tangent[2]), max(horizontal, _MIN_LENGTH)))


def _minimum_bend_radius(positions: tuple[Vector3, ...], *, exclude_tail_nodes: int = 0) -> float:
    return _minimum_bend_radius_diagnostic(
        positions,
        exclude_tail_nodes=exclude_tail_nodes,
    ).radius_m


def _minimum_bend_radius_diagnostic(
    positions: tuple[Vector3, ...],
    *,
    exclude_tail_nodes: int = 0,
) -> _BendRadiusDiagnostic:
    if len(positions) < 3:
        return _BendRadiusDiagnostic(radius_m=math.inf)
    best = _BendRadiusDiagnostic(radius_m=math.inf)
    segment_lengths = [
        _norm(_sub(end, start))
        for start, end in zip(positions, positions[1:])
    ]
    positive_lengths = sorted(length for length in segment_lengths if length > _MIN_LENGTH)
    if not positive_lengths:
        return _BendRadiusDiagnostic(radius_m=1.0e12)
    reference_length = positive_lengths[len(positive_lengths) // 2]
    degenerate_cutoff = 0.10 * reference_length
    seabed_like_depth = max(position[2] for position in positions)
    seabed_cluster_tolerance = max(_SEABED_CONTACT_TOLERANCE_M, 0.005 * reference_length)
    last_included_node_index = len(positions) - 2 - max(0, exclude_tail_nodes)
    for node_index, (previous, current, next_point) in enumerate(zip(positions, positions[1:], positions[2:]), start=1):
        if node_index > last_included_node_index:
            continue
        first = _sub(current, previous)
        second = _sub(next_point, current)
        first_length = _norm(first)
        second_length = _norm(second)
        if first_length <= degenerate_cutoff or second_length <= degenerate_cutoff:
            continue
        if (
            min(previous[2], current[2], next_point[2]) >= seabed_like_depth - seabed_cluster_tolerance
            and min(first_length, second_length) <= 0.5 * reference_length
        ):
            continue
        dot = max(-1.0, min(1.0, _dot(first, second) / (first_length * second_length)))
        turn = math.acos(dot)
        if turn <= 1.0e-9:
            continue
        radius = 0.5 * (first_length + second_length) / turn
        if radius < best.radius_m:
            best = _BendRadiusDiagnostic(
                radius_m=radius,
                node_index=node_index,
                left_segment_m=first_length,
                right_segment_m=second_length,
                turn_angle_deg=math.degrees(turn),
                node_depth_m=current[2],
                near_seabed=current[2] >= seabed_like_depth - seabed_cluster_tolerance,
            )
    return best if math.isfinite(best.radius_m) else _BendRadiusDiagnostic(radius_m=1.0e12)


def _initial_laying_state(dynamic_case) -> DynamicLayingState:
    from .dynamic import _straight_line_state

    straight_state = _straight_line_state(dynamic_case, dynamic_case.initial_speed_mps)
    cable_tangent = _straight_line_tangent(dynamic_case, dynamic_case.initial_speed_mps)
    sin_theta = max(cable_tangent[2], 1.0e-12)
    suspended_length = dynamic_case.water_depth_m / sin_theta
    element_count = dynamic_case.element_count
    rest_length = suspended_length / element_count
    positions = tuple(
        _mul(cable_tangent, rest_length * index)
        for index in range(element_count + 1)
    )
    velocities = tuple((0.0, 0.0, 0.0) for _ in positions)
    contact_flags = tuple(position[2] >= dynamic_case.water_depth_m - 1.0e-9 for position in positions)
    return DynamicLayingState(
        time_s=0.0,
        positions=positions,
        velocities=velocities,
        rest_lengths_m=tuple(rest_length for _ in range(element_count)),
        paid_length_m=suspended_length,
        laid_length_m=0.0,
        contact_flags=contact_flags,
        segment_tensions_n=_initial_segment_tensions(
            top_tension_n=straight_state.top_tension_n,
            touchdown_tension_n=dynamic_case.touchdown_tension_n,
            element_count=element_count,
        ),
    )


def _initial_segment_tensions(
    *,
    top_tension_n: float,
    touchdown_tension_n: float,
    element_count: int,
) -> tuple[float, ...]:
    if element_count <= 0:
        return ()
    if element_count == 1:
        return (max(0.0, top_tension_n),)
    return tuple(
        max(
            0.0,
            top_tension_n + (touchdown_tension_n - top_tension_n) * index / (element_count - 1),
        )
        for index in range(element_count)
    )


def _time_history_target_segment_length(state: DynamicLayingState) -> float:
    positive = [length for length in state.rest_lengths_m if length > _MIN_LENGTH]
    if not positive:
        return 1.0
    return max(min(positive) * 0.5, 0.25)


def _time_history_step_limit_s(dynamic_case, state: DynamicLayingState, *, base_step_s: float) -> float:
    """Bound the integration step by a simple CFL condition."""

    cfl_lengths = state.rest_lengths_m
    if dynamic_case.length_boundary_source == "known_plough_trajectory" and len(cfl_lengths) > 1:
        # The final segment is a controlled material-outflow cell. Its lifetime
        # is handled by tail remeshing; including it here creates a shrinking
        # step/remesh-threshold feedback as the segment is consumed.
        cfl_lengths = cfl_lengths[:-1]
    positive_lengths = [length for length in cfl_lengths if length > _MIN_LENGTH]
    if not positive_lengths:
        return max(_MIN_INTERNAL_TIME_STEP_S, base_step_s)
    min_length = min(positive_lengths)
    speed_scale = max(
        abs(dynamic_case.initial_speed_mps),
        abs(dynamic_case.final_speed_mps),
        _max_motion_segment_speed(getattr(dynamic_case, "vessel_motion_segments", ())),
        _max_motion_segment_speed(getattr(dynamic_case, "plough_motion_segments", ())),
        abs(_initial_payout_speed(dynamic_case)),
        abs(_final_payout_speed(dynamic_case)),
        abs(dynamic_case.current_speed_mps),
        abs(dynamic_case.plough_speed_mps or 0.0),
        _max_node_speed(state.velocities),
        _MIN_LENGTH,
    )
    cfl_step = _MAX_NODE_CFL_FRACTION * min_length / speed_scale
    return max(_MIN_INTERNAL_TIME_STEP_S, min(base_step_s, cfl_step))


def _max_node_speed(velocities: tuple[Vector3, ...]) -> float:
    if not velocities:
        return 0.0
    return max(_norm(velocity) for velocity in velocities)


def _max_motion_segment_speed(segments) -> float:
    if not segments:
        return 0.0
    return max(max(abs(segment.start_speed_mps), abs(segment.end_speed_mps)) for segment in segments)


def _mean_positive_length(lengths: tuple[float, ...]) -> float | None:
    positive = [length for length in lengths if length > _MIN_LENGTH]
    if not positive:
        return None
    return sum(positive) / len(positive)


def _median_positive_length(lengths: tuple[float, ...]) -> float | None:
    positive = sorted(length for length in lengths if length > _MIN_LENGTH)
    if not positive:
        return None
    return positive[len(positive) // 2]


def _min_positive_length(lengths: tuple[float, ...]) -> float | None:
    positive = [length for length in lengths if length > _MIN_LENGTH]
    if not positive:
        return None
    return min(positive)


def _operation_case_at_time(
    dynamic_case,
    cable,
    time_s: float,
    *,
    vessel_fixed_current: bool = True,
) -> OperationCase:
    vessel_speed = _vessel_speed(dynamic_case, time_s)
    current_x, current_y = _current_velocity_components(dynamic_case, time_s)
    current_speed = math.hypot(current_x, current_y)
    current_direction = (
        math.degrees(math.atan2(current_y, current_x)) % 360.0
        if current_speed > _MIN_LENGTH
        else dynamic_case.current_direction_deg
    )
    return OperationCase(
        name=dynamic_case.case_name,
        cable=cable,
        initial_speed_mps=dynamic_case.initial_speed_mps,
        final_speed_mps=dynamic_case.final_speed_mps,
        duration_s=dynamic_case.duration_s,
        water_depth_m=dynamic_case.water_depth_m,
        solver_model="dynamic_laying",
        touchdown_tension_n=dynamic_case.touchdown_tension_n,
        current_surface_mps=current_speed,
        current_bottom_mps=current_speed,
        current_direction_deg=current_direction,
        vessel_speed_mps=vessel_speed if vessel_fixed_current else 0.0,
        payout_speed_mps=_payout_speed(dynamic_case, time_s),
    )


def _current_velocity_components(dynamic_case, time_s: float) -> tuple[float, float]:
    samples = getattr(dynamic_case, "current_samples", ())
    if samples:
        start, end, fraction = _sample_bracket(samples, time_s)
        return (
            float(start.velocity_x_mps + (end.velocity_x_mps - start.velocity_x_mps) * fraction),
            float(start.velocity_y_mps + (end.velocity_y_mps - start.velocity_y_mps) * fraction),
        )
    direction = math.radians(dynamic_case.current_direction_deg)
    return (
        float(dynamic_case.current_speed_mps * math.cos(direction)),
        float(dynamic_case.current_speed_mps * math.sin(direction)),
    )


def _sampled_scalar_value(samples, time_s: float) -> float:
    start, end, fraction = _sample_bracket(samples, time_s)
    return float(start.value + (end.value - start.value) * fraction)


def _sample_bracket(samples, time_s: float):
    if not samples:
        raise ValueError("at least one synchronized sample is required")
    if len(samples) == 1 or time_s <= samples[0].time_s:
        return samples[0], samples[0], 0.0
    for start, end in zip(samples, samples[1:]):
        if time_s <= end.time_s:
            duration = max(end.time_s - start.time_s, _MIN_LENGTH)
            fraction = max(0.0, min(1.0, (time_s - start.time_s) / duration))
            return start, end, fraction
    return samples[-1], samples[-1], 0.0


def _top_tension_from_dynamic_state(dynamic_case, case: OperationCase, state: DynamicLayingState, time_s: float) -> float:
    """Return top tension from the node-state tension field."""

    segment_tensions = _dynamic_segment_tensions(dynamic_case, case, state, time_s)
    if not segment_tensions:
        return 0.0
    return max(0.0, segment_tensions[0])


def _terminal_tension_seed(dynamic_case) -> float:
    if dynamic_case.length_boundary_source == "known_plough_trajectory":
        return 0.0
    return max(0.0, dynamic_case.touchdown_tension_n)


def _segment_tensions_from_length_constraints(
    length_lambdas_n_s2: tuple[float, ...],
    *,
    dt_s: float,
    expected_count: int,
) -> tuple[float, ...]:
    """Convert XPBD length multipliers to segment reaction magnitudes."""

    if dt_s <= 0.0 or len(length_lambdas_n_s2) != expected_count:
        return ()
    dt2 = dt_s * dt_s
    return tuple(max(0.0, lambda_value / dt2) for lambda_value in length_lambdas_n_s2)


def _point_tensions_from_dynamic_state(
    dynamic_case,
    case: OperationCase,
    state: DynamicLayingState,
    time_s: float,
) -> tuple[float, ...]:
    """Map segment tensions to frame nodes without a linear placeholder."""

    _validate_state(state)
    segment_tensions = _dynamic_segment_tensions(dynamic_case, case, state, time_s)
    return _point_tensions_from_segment_tensions(dynamic_case, state, segment_tensions)


def _point_tensions_from_segment_tensions(
    dynamic_case,
    state: DynamicLayingState,
    segment_tensions: tuple[float, ...],
) -> tuple[float, ...]:
    """Map an explicit segment-tension field to frame nodes."""

    _validate_state(state)
    if not segment_tensions:
        return tuple(0.0 for _ in state.positions)
    point_tensions: list[float] = []
    for index in range(len(state.positions)):
        adjacent: list[float] = []
        if index > 0 and index - 1 < len(segment_tensions):
            adjacent.append(segment_tensions[index - 1])
        if index < len(segment_tensions):
            adjacent.append(segment_tensions[index])
        if adjacent:
            point_tensions.append(max(0.0, sum(adjacent) / len(adjacent)))
        else:
            point_tensions.append(_terminal_tension_seed(dynamic_case))
    return tuple(point_tensions)


def _length_constraint_reactions_from_dynamic_state(state: DynamicLayingState) -> tuple[float, ...]:
    _validate_state(state)
    if state.length_constraint_reactions_n:
        return tuple(max(0.0, reaction) for reaction in state.length_constraint_reactions_n)
    return ()


def _dynamic_segment_tensions(
    dynamic_case,
    case: OperationCase,
    state: DynamicLayingState,
    time_s: float,
) -> tuple[float, ...]:
    """Return the best available per-segment tension from the dynamic solve."""

    _validate_state(state)
    if state.segment_tensions_n:
        return tuple(max(0.0, tension) for tension in state.segment_tensions_n)
    return _segment_tensions_from_state(case, state)


def _known_plough_output_segment_tensions(
    dynamic_case,
    case: OperationCase,
    state: DynamicLayingState,
    time_s: float,
) -> tuple[float, ...]:
    """Use XPBD line reactions for the segment distribution output."""

    _validate_state(state)
    natural_tensions = _dynamic_segment_tensions(dynamic_case, case, state, time_s)
    length_reactions = _length_constraint_reactions_from_dynamic_state(state)
    if len(length_reactions) != len(state.rest_lengths_m):
        return natural_tensions
    return length_reactions


def _plough_inlet_tension_from_dynamic_state(
    dynamic_case,
    case: OperationCase,
    state: DynamicLayingState,
    time_s: float,
    *,
    endpoint_segment_tensions: tuple[float, ...] = (),
) -> float:
    """Return the TDP/contact-transition tension from the active segment field."""

    _validate_state(state)
    segment_tensions = endpoint_segment_tensions or _dynamic_segment_tensions(dynamic_case, case, state, time_s)
    endpoint_adjacent = max(0.0, segment_tensions[-1]) if segment_tensions else 0.0
    contact_profile = build_segment_contact_profile(
        nodes=state.positions,
        rest_lengths_m=state.rest_lengths_m,
        contact_flags=state.contact_flags,
        contact_normal_reactions_n=_padded_values(state.contact_normal_reactions_n, len(state.positions)),
        seabed_depth_m=dynamic_case.water_depth_m,
    )
    if segment_tensions:
        return max(
            0.0,
            _segment_field_at_material_station(
                values=segment_tensions,
                rest_lengths_m=state.rest_lengths_m,
                material_station_m=contact_profile.tdp_arc_length_m,
            ),
        )
    return endpoint_adjacent


def _segment_field_at_material_station(
    *,
    values: tuple[float, ...],
    rest_lengths_m: tuple[float, ...],
    material_station_m: float,
) -> float:
    """Interpolate a segment-centred scalar on unstretched material arc."""

    if len(values) != len(rest_lengths_m):
        raise ValueError("values and rest_lengths_m must have the same length")
    if not values:
        return 0.0
    if any(length <= 0.0 for length in rest_lengths_m):
        raise ValueError("rest_lengths_m must be positive")
    centers: list[float] = []
    cursor = 0.0
    for length in rest_lengths_m:
        centers.append(cursor + 0.5 * length)
        cursor += length
    station = max(0.0, min(float(material_station_m), cursor))
    if station <= centers[0]:
        return float(values[0])
    if station >= centers[-1]:
        return float(values[-1])
    for index in range(len(centers) - 1):
        left_station = centers[index]
        right_station = centers[index + 1]
        if station > right_station:
            continue
        fraction = (station - left_station) / max(right_station - left_station, _MIN_LENGTH)
        return float(values[index] + fraction * (values[index + 1] - values[index]))
    return float(values[-1])


def _node_state_force_balance_tensions(
    dynamic_case,
    case: OperationCase,
    state: DynamicLayingState,
    time_s: float,
) -> tuple[float, ...]:
    """Compute segment tensions by tangential force balance on current nodes."""

    _validate_state(state)
    segment_tensions = [0.0 for _ in state.rest_lengths_m]
    running = _terminal_tension_seed(dynamic_case)
    payout_speed = case.payout_speed_mps if case.payout_speed_mps is not None else case.vessel_speed_mps or 0.0
    for segment in reversed(segment_vectors(state.positions)):
        midpoint_depth = 0.5 * (segment.start[2] + segment.end[2])
        water = current_at(
            depth_m=midpoint_depth,
            water_depth_m=case.water_depth_m,
            current_surface_mps=case.current_surface_mps,
            current_bottom_mps=case.current_bottom_mps,
            current_direction_deg=case.current_direction_deg,
            current_u_mps=case.current_u_mps,
            current_v_mps=case.current_v_mps,
            vessel_speed_mps=case.vessel_speed_mps or 0.0,
        )
        vertical = case.cable.submerged_weight_n_per_m * segment.length_m * max(segment.tangent[2], 0.0)
        tangential_drag = _tangential_drag_per_meter(
            case,
            water_velocity=water,
            tangent=segment.tangent,
            cable_speed_along_mps=payout_speed,
        )
        running += vertical - tangential_drag * segment.length_m
        segment_tensions[segment.index] = max(0.0, running)
    return tuple(segment_tensions)


def _step_dynamic_segment_tensions(
    case: OperationCase,
    *,
    positions: tuple[Vector3, ...],
    velocities: tuple[Vector3, ...],
    rest_lengths_m: tuple[float, ...],
    payout_speed_mps: float,
    plough_exit_speed_mps: float | None = None,
    terminal_tension_n: float | None = None,
) -> tuple[float, ...]:
    """Return load-recursive segment tension diagnostics after the dynamic step."""

    segments = segment_vectors(positions)
    if len(segments) != len(rest_lengths_m):
        raise ValueError("rest_lengths_m must have one entry per segment")
    segment_tensions = [0.0 for _ in rest_lengths_m]
    terminal_tension = case.touchdown_tension_n if terminal_tension_n is None else terminal_tension_n
    running = max(0.0, terminal_tension)
    material_speeds = _segment_material_flow_speeds(
        rest_lengths_m,
        fairlead_speed_mps=payout_speed_mps,
        plough_speed_mps=plough_exit_speed_mps,
    )
    for segment, rest_length, material_speed in reversed(
        list(zip(segments, rest_lengths_m, material_speeds))
    ):
        left = segment.index
        right = left + 1
        midpoint_depth = 0.5 * (segment.start[2] + segment.end[2])
        midpoint_velocity = _mul(_add(velocities[left], velocities[right]), 0.5)
        material_velocity = _segment_material_velocity(
            node_velocity=midpoint_velocity,
            tangent=segment.tangent,
            payout_speed_mps=material_speed,
        )
        water_velocity = current_at(
            depth_m=midpoint_depth,
            water_depth_m=case.water_depth_m,
            current_surface_mps=case.current_surface_mps,
            current_bottom_mps=case.current_bottom_mps,
            current_direction_deg=case.current_direction_deg,
            current_u_mps=case.current_u_mps,
            current_v_mps=case.current_v_mps,
            vessel_speed_mps=case.vessel_speed_mps or 0.0,
        )
        relative_velocity = _sub(material_velocity, water_velocity)
        drag = morison_drag(
            seawater_density=_SEAWATER_DENSITY_KG_M3,
            diameter_m=case.cable.diameter_m,
            segment_length_m=segment.length_m,
            tangent=segment.tangent,
            relative_velocity=relative_velocity,
            tangential_coefficient=case.cable.tangential_drag_coefficient,
            normal_coefficient=case.cable.normal_drag_coefficient,
        )
        weight = (0.0, 0.0, case.cable.submerged_weight_n_per_m * rest_length)
        tangential_dynamic_load = _dot(_add(weight, drag), segment.tangent)
        running = max(0.0, running + tangential_dynamic_load)
        segment_tensions[segment.index] = running
    return tuple(segment_tensions)


def _top_tension_from_node_state(dynamic_case, case: OperationCase, state: DynamicLayingState, time_s: float) -> float:
    return _top_tension_from_dynamic_state(dynamic_case, case, state, time_s)


def _tangential_drag_per_meter(
    case: OperationCase,
    *,
    water_velocity: Vector3,
    tangent: Vector3,
    cable_speed_along_mps: float,
) -> float:
    along_tangent = _dot(water_velocity, tangent)
    tangential_relative_speed = along_tangent - cable_speed_along_mps
    return (
        -0.5
        * math.pi
        * _SEAWATER_DENSITY_KG_M3
        * case.cable.tangential_drag_coefficient
        * case.cable.diameter_m
        * tangential_relative_speed
        * abs(tangential_relative_speed)
    )


def _state_tdp(state: DynamicLayingState, seabed_depth_m: float) -> Vector3:
    profile = _state_contact_profile(state, seabed_depth_m)
    if profile.has_contact:
        return profile.tdp_point
    from .contact import detect_tdp

    return detect_tdp(nodes=state.positions, seabed_depth_m=seabed_depth_m).point


def _state_contact_profile(state: DynamicLayingState, seabed_depth_m: float):
    return build_segment_contact_profile(
        nodes=state.positions,
        rest_lengths_m=state.rest_lengths_m,
        contact_flags=state.contact_flags,
        contact_normal_reactions_n=_padded_values(state.contact_normal_reactions_n, len(state.positions)),
        seabed_depth_m=seabed_depth_m,
    )


def _known_plough_tdp(state: DynamicLayingState, seabed_depth_m: float) -> Vector3:
    """Return the cable near-bottom transition for a prescribed plough endpoint."""

    return _state_contact_profile(state, seabed_depth_m).tdp_point


def _straight_line_tangent(dynamic_case, vessel_speed_mps: float) -> Vector3:
    from .cases import get_cable

    cable = get_cable("LA")
    current_x, current_y = _relative_current_components(dynamic_case, vessel_speed_mps)
    relative_speed = math.hypot(current_x, current_y)
    ratio = _hydrodynamic_constant(cable) / max(relative_speed, 1.0e-12)
    cos_theta = math.sqrt(1.0 + 0.25 * ratio**4) - 0.5 * ratio**2
    cos_theta = max(0.0, min(1.0, cos_theta))
    theta = math.acos(cos_theta)
    psi = math.atan2(current_y, current_x)
    return (
        math.cos(theta) * math.cos(psi),
        math.cos(theta) * math.sin(psi),
        math.sin(theta),
    )


def _relative_current_components(dynamic_case, vessel_speed_mps: float) -> tuple[float, float]:
    direction = math.radians(dynamic_case.current_direction_deg)
    return (
        dynamic_case.current_speed_mps * math.cos(direction) + vessel_speed_mps,
        dynamic_case.current_speed_mps * math.sin(direction),
    )


def _hydrodynamic_constant(cable) -> float:
    if cable.hydrodynamic_constant > 0.0:
        return cable.hydrodynamic_constant
    return math.sqrt(
        2.0
        * cable.submerged_weight_n_per_m
        / (_SEAWATER_DENSITY_KG_M3 * cable.normal_drag_coefficient * cable.diameter_m)
    )


def _vessel_speed(dynamic_case, time_s: float) -> float:
    if getattr(dynamic_case, "vessel_motion_segments", ()):
        velocity = _motion_velocity(dynamic_case.vessel_motion_segments, time_s)
        return math.hypot(velocity[0], velocity[1])
    if time_s >= dynamic_case.duration_s:
        return dynamic_case.final_speed_mps
    fraction = max(0.0, min(1.0, time_s / max(dynamic_case.duration_s, 1.0e-12)))
    return dynamic_case.initial_speed_mps + (dynamic_case.final_speed_mps - dynamic_case.initial_speed_mps) * fraction


def _shape_response_speed(dynamic_case, time_s: float) -> float:
    """Return the cable-shape speed after a first-order response to the ramp."""

    return _first_order_ramp_response(
        initial=dynamic_case.initial_speed_mps,
        final=dynamic_case.final_speed_mps,
        duration_s=dynamic_case.duration_s,
        time_s=time_s,
    )


def _first_order_ramp_response(
    *,
    initial: float,
    final: float,
    duration_s: float,
    time_s: float,
) -> float:
    if duration_s <= _MIN_LENGTH:
        return final
    if time_s <= 0.0:
        return initial
    tau = max(duration_s, _MIN_LENGTH)
    delta = final - initial
    if time_s <= duration_s:
        return initial + delta * (
            time_s / duration_s
            - tau / duration_s * (1.0 - math.exp(-time_s / tau))
        )
    end_value = initial + delta * (
        1.0
        - tau / duration_s * (1.0 - math.exp(-duration_s / tau))
    )
    return final + (end_value - final) * math.exp(-(time_s - duration_s) / tau)


def _vessel_acceleration(dynamic_case, time_s: float) -> float:
    if time_s <= 0.0 or time_s > dynamic_case.duration_s:
        return 0.0
    return (dynamic_case.final_speed_mps - dynamic_case.initial_speed_mps) / dynamic_case.duration_s


def _cable_response_acceleration(dynamic_case, time_s: float) -> float:
    """Return cable-body acceleration response after a finite speed ramp."""

    ramp_acceleration = (dynamic_case.final_speed_mps - dynamic_case.initial_speed_mps) / dynamic_case.duration_s
    if time_s <= 0.0:
        return 0.0
    if time_s <= dynamic_case.duration_s:
        return ramp_acceleration
    response_time = _cable_response_time_s(dynamic_case)
    return ramp_acceleration * math.exp(-(time_s - dynamic_case.duration_s) / response_time)


def _cable_response_time_s(dynamic_case) -> float:
    return max(dynamic_case.duration_s, _MIN_LENGTH)


def _payout_speed(dynamic_case, time_s: float) -> float:
    if getattr(dynamic_case, "payout_speed_samples", ()):
        return _sampled_scalar_value(dynamic_case.payout_speed_samples, time_s)
    if getattr(dynamic_case, "payout_speed_segments", ()):
        return _scalar_segment_speed(dynamic_case.payout_speed_segments, time_s)
    initial = _initial_payout_speed(dynamic_case)
    final = _final_payout_speed(dynamic_case)
    if time_s >= dynamic_case.duration_s:
        return final
    fraction = max(0.0, min(1.0, time_s / max(dynamic_case.duration_s, 1.0e-12)))
    return initial + (final - initial) * fraction


def _scalar_segment_speed(segments, time_s: float) -> float:
    remaining = max(0.0, time_s)
    last_segment = None
    for segment in segments:
        last_segment = segment
        duration = max(segment.duration_s, _MIN_LENGTH)
        if remaining <= duration:
            fraction = max(0.0, min(1.0, remaining / duration))
            return segment.start_speed_mps + (segment.end_speed_mps - segment.start_speed_mps) * fraction
        remaining -= duration
    return 0.0 if last_segment is None else last_segment.end_speed_mps


def _initial_payout_speed(dynamic_case) -> float:
    if getattr(dynamic_case, "payout_speed_samples", ()):
        return float(dynamic_case.payout_speed_samples[0].value)
    if getattr(dynamic_case, "payout_speed_segments", ()):
        return dynamic_case.payout_speed_segments[0].start_speed_mps
    return dynamic_case.initial_speed_mps if dynamic_case.payout_initial_speed_mps is None else dynamic_case.payout_initial_speed_mps


def _final_payout_speed(dynamic_case) -> float:
    if getattr(dynamic_case, "payout_speed_samples", ()):
        return float(dynamic_case.payout_speed_samples[-1].value)
    if getattr(dynamic_case, "payout_speed_segments", ()):
        return dynamic_case.payout_speed_segments[-1].end_speed_mps
    return dynamic_case.final_speed_mps if dynamic_case.payout_final_speed_mps is None else dynamic_case.payout_final_speed_mps


def _validate_state(state: DynamicLayingState) -> None:
    if len(state.positions) < 2:
        raise ValueError("at least two nodes are required")
    if len(state.velocities) != len(state.positions):
        raise ValueError("velocities must match positions")
    if len(state.rest_lengths_m) != len(state.positions) - 1:
        raise ValueError("rest_lengths_m must have one entry per segment")
    if len(state.contact_flags) != len(state.positions):
        raise ValueError("contact_flags must match positions")
    if state.length_lambdas_n_s2 and len(state.length_lambdas_n_s2) != len(state.rest_lengths_m):
        raise ValueError("length_lambdas_n_s2 must have one entry per segment")
    if state.segment_tensions_n and len(state.segment_tensions_n) != len(state.rest_lengths_m):
        raise ValueError("segment_tensions_n must have one entry per segment")
    if state.length_constraint_reactions_n and len(state.length_constraint_reactions_n) != len(state.rest_lengths_m):
        raise ValueError("length_constraint_reactions_n must have one entry per segment")
    if state.contact_lambdas_n_s2 and len(state.contact_lambdas_n_s2) != len(state.positions):
        raise ValueError("contact_lambdas_n_s2 must match positions")
    if state.contact_normal_reactions_n and len(state.contact_normal_reactions_n) != len(state.positions):
        raise ValueError("contact_normal_reactions_n must match positions")


def _point_tensions_from_state(dynamic_case, case: OperationCase, state: DynamicLayingState, time_s: float) -> tuple[float, ...]:
    """Return nodal tensions from dynamic segment tensions."""

    return _point_tensions_from_dynamic_state(dynamic_case, case, state, time_s)


def _segment_tensions_from_state(case: OperationCase, state: DynamicLayingState) -> tuple[float, ...]:
    """Return per-segment tension from stretch relative to rest length."""

    _validate_state(state)
    return tuple(
        _segment_tension(case, segment.length_m, rest_length)
        for segment, rest_length in zip(segment_vectors(state.positions), state.rest_lengths_m)
    )


def _segment_tension(case: OperationCase, length_m: float, rest_length_m: float) -> float:
    rest = max(rest_length_m, _MIN_LENGTH)
    strain = (length_m - rest) / rest
    return max(0.0, case.cable.axial_stiffness_n * strain)


def _node_masses(case: OperationCase, state: DynamicLayingState) -> tuple[float, ...]:
    mass_per_meter = _dynamic_mass_per_meter(case)
    return tuple(
        max(_node_tributary_length(index, state.rest_lengths_m) * mass_per_meter, _MIN_MASS)
        for index in range(len(state.positions))
    )


def _dynamic_mass_per_meter(case: OperationCase) -> float:
    structural_mass = case.cable.weight_air_n_per_m / _GRAVITY_MPS2
    added_mass = _SEAWATER_DENSITY_KG_M3 * math.pi * case.cable.diameter_m * case.cable.diameter_m / 4.0
    return structural_mass + added_mass


def _node_tributary_length(index: int, rest_lengths_m: tuple[float, ...]) -> float:
    length = 0.0
    if index > 0:
        length += 0.5 * rest_lengths_m[index - 1]
    if index < len(rest_lengths_m):
        length += 0.5 * rest_lengths_m[index]
    return length


def _node_tangent(segments, index: int) -> Vector3:
    if not segments:
        return (0.0, 0.0, 0.0)
    if index <= 0:
        return segments[0].tangent
    if index >= len(segments):
        return segments[-1].tangent
    averaged = _add(segments[index - 1].tangent, segments[index].tangent)
    magnitude = _norm(averaged)
    if magnitude <= _MIN_LENGTH:
        return segments[index].tangent
    return _mul(averaged, 1.0 / magnitude)


def _segment_material_velocity(
    *,
    node_velocity: Vector3,
    tangent: Vector3,
    payout_speed_mps: float,
) -> Vector3:
    """Return cable material velocity for Morison drag."""

    tangential_node_velocity = _mul(tangent, _dot(node_velocity, tangent))
    normal_node_velocity = _sub(node_velocity, tangential_node_velocity)
    return _add(normal_node_velocity, _mul(tangent, payout_speed_mps))


def _segment_material_flow_speeds(
    rest_lengths_m: tuple[float, ...],
    *,
    fairlead_speed_mps: float,
    plough_speed_mps: float | None,
) -> tuple[float, ...]:
    plough_speed = fairlead_speed_mps if plough_speed_mps is None else plough_speed_mps
    total_length = sum(rest_lengths_m)
    if total_length <= _MIN_LENGTH:
        return tuple(fairlead_speed_mps for _ in rest_lengths_m)
    coordinate = 0.0
    speeds = []
    for rest_length in rest_lengths_m:
        midpoint_fraction = (coordinate + 0.5 * rest_length) / total_length
        speeds.append(
            fairlead_speed_mps
            + midpoint_fraction * (plough_speed - fairlead_speed_mps)
        )
        coordinate += rest_length
    return tuple(speeds)


def _node_material_flow_speeds(
    rest_lengths_m: tuple[float, ...],
    *,
    fairlead_speed_mps: float,
    plough_speed_mps: float | None,
) -> tuple[float, ...]:
    plough_speed = fairlead_speed_mps if plough_speed_mps is None else plough_speed_mps
    total_length = sum(rest_lengths_m)
    if total_length <= _MIN_LENGTH:
        return tuple(fairlead_speed_mps for _ in range(len(rest_lengths_m) + 1))
    coordinate = 0.0
    speeds = [fairlead_speed_mps]
    for rest_length in rest_lengths_m:
        coordinate += rest_length
        fraction = min(1.0, max(0.0, coordinate / total_length))
        speeds.append(fairlead_speed_mps + fraction * (plough_speed - fairlead_speed_mps))
    return tuple(speeds)


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

"""铺缆张力算法的输入数据结构。

算法说明：
这里不做计算，只定义“算法需要哪些输入”。所有字段都使用 SI 单位。
数据类设置为不可变，便于核查时从一个命名工况追踪到求解器输入，再追踪到
CSV/SVG 输出。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CableParameters:
    """一种电缆的物理参数和设计参数。"""

    name: str
    diameter_m: float
    weight_air_n_per_m: float
    submerged_weight_n_per_m: float
    hydrodynamic_constant: float
    tangential_drag_coefficient: float
    normal_drag_coefficient: float
    total_length_m: float
    axial_stiffness_n: float = 1.0e9
    max_water_depth_m: float | None = None
    max_allowable_tension_n: float | None = None
    min_bending_radius_m: float | None = None


@dataclass(frozen=True)
class OperationCase:
    """一个铺缆工况所需的全部输入。"""

    name: str
    cable: CableParameters
    initial_speed_mps: float
    final_speed_mps: float
    duration_s: float
    water_depth_m: float
    solver_model: str = "generic"
    touchdown_tension_n: float = 0.0
    current_u_mps: float = 0.0
    current_v_mps: float = 0.0
    vessel_speed_mps: float | None = None
    payout_speed_mps: float | None = None
    current_surface_mps: float | None = None
    current_bottom_mps: float | None = None
    current_direction_deg: float | None = None

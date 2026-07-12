"""电缆水动力载荷计算。

算法说明：
本文件只处理局部坐标系下的 Morison 阻力分量。调用方负责把全局速度
投影到电缆局部 `t/n/b` 方向；本文件根据相对速度、直径、阻力系数和
海水密度返回作用在电缆上的阻力。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DragComponents:
    """局部 t/n/b 坐标中的 Morison 阻力分量。"""

    tangential: float
    normal: float
    binormal: float


def reynolds_number(
    speed: float,
    diameter: float,
    kinematic_viscosity: float,
) -> float:
    """计算雷诺数 Re = u d / nu。"""

    if diameter <= 0.0:
        raise ValueError("diameter must be positive")
    if kinematic_viscosity <= 0.0:
        raise ValueError("kinematic_viscosity must be positive")
    return abs(speed) * diameter / kinematic_viscosity


def tangential_drag_coefficient(reynolds: float) -> float:
    """计算经验切向阻力系数 Ct = 0.055 / Re^0.14。"""

    if reynolds <= 0.0:
        raise ValueError("reynolds must be positive")
    return 0.055 / (reynolds**0.14)


def morison_drag_components(
    *,
    seawater_density: float,
    diameter: float,
    strain: float,
    relative_t: float,
    relative_n: float,
    relative_b: float,
    tangential_coefficient: float,
    normal_coefficient: float,
) -> DragComponents:
    """计算单位未拉伸长度上的局部 Morison 阻力。

    算法说明：
    - `relative_t/n/b` 是流体相对电缆的速度分量。
    - 切向阻力与 `relative_t * abs(relative_t)` 成正比。
    - 法向和副法向阻力共用合横向速度 `sqrt(relative_n^2 + relative_b^2)`。
    - 返回的阻力方向始终反抗相对流动，所以公式前保留负号。
    """

    if seawater_density <= 0.0:
        raise ValueError("seawater_density must be positive")
    if diameter <= 0.0:
        raise ValueError("diameter must be positive")
    # 轴向应变会改变单位未拉伸长度对应的受流长度，用 stretch 修正。
    stretch = math.sqrt(1.0 + strain)
    normal_speed = math.hypot(relative_n, relative_b)

    tangential = (
        -0.5
        * math.pi
        * seawater_density
        * tangential_coefficient
        * diameter
        * stretch
        * relative_t
        * abs(relative_t)
    )
    normal = (
        -0.5
        * seawater_density
        * normal_coefficient
        * diameter
        * stretch
        * relative_n
        * normal_speed
    )
    binormal = (
        -0.5
        * seawater_density
        * normal_coefficient
        * diameter
        * stretch
        * relative_b
        * normal_speed
    )
    return DragComponents(tangential=tangential, normal=normal, binormal=binormal)

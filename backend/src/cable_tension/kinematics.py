"""电缆局部坐标和几何关系。

算法说明：
电缆任意一点的姿态由两个角度描述：`theta` 为竖向剖面倾角，`psi`
为水平面方位角。本文件把这两个角度转换为局部切向 t、法向 n、副法向 b
三个单位向量。动态方程和剖面输出都复用这套局部坐标系定义。
"""

from __future__ import annotations

import math

import numpy as np


def orientation_vectors(theta: float, psi: float) -> dict[str, np.ndarray]:
    """返回固定坐标系下的局部 t/n/b 单位向量。

    算法说明：
    - t 为电缆切向，后续坐标积分沿 t 方向累加。
    - n 在竖向剖面内，主要用于重力和法向载荷投影。
    - b 垂直于 t-n 平面，用于横向水动力和方位角运动。
    """

    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    cos_psi = math.cos(psi)
    sin_psi = math.sin(psi)

    tangent = np.array(
        [cos_theta * cos_psi, cos_theta * sin_psi, sin_theta],
        dtype=float,
    )
    normal = np.array(
        [-sin_theta * cos_psi, -sin_theta * sin_psi, cos_theta],
        dtype=float,
    )
    binormal = np.array([sin_psi, -cos_psi, 0.0], dtype=float)

    return {"t": tangent, "n": normal, "b": binormal}


def axial_strain(tension: float, axial_stiffness: float) -> float:
    """计算轴向应变 epsilon = T / EA。"""

    if axial_stiffness <= 0.0:
        raise ValueError("axial_stiffness must be positive")
    return tension / axial_stiffness


def stretched_step_components(
    ds: float,
    theta: float,
    psi: float,
    strain: float,
) -> tuple[float, float, float]:
    """计算一个未拉伸单元在全局坐标中的 dX、dY、dZ。

    算法说明：
    先把未拉伸长度 `ds` 乘以 `(1 + strain)`，再沿切向向量投影。
    这个函数用于核查“角度 -> 坐标”的几何链条。
    """

    basis = orientation_vectors(theta, psi)
    stretched = ds * (1.0 + strain)
    delta = stretched * basis["t"]
    return float(delta[0]), float(delta[1]), float(delta[2])

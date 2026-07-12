"""命名铺缆工况库。

算法说明：
本文件集中保存可直接运行的电缆参数和工况。外部核查时可以先看这里，
确认每个工况的水深、流速、流向、预张力和电缆参数，再进入求解器。
工况名称保持稳定，因为脚本、输出目录和文件清单都会引用这些名称。
"""

from __future__ import annotations

from .parameters import CableParameters, OperationCase


# 电缆参数组。所有值使用 SI 单位，输出 CSV 可直接做后处理。
_CABLES: dict[str, CableParameters] = {
    "LA": CableParameters(
        name="LA",
        diameter_m=0.0264,
        weight_air_n_per_m=16.09,
        submerged_weight_n_per_m=10.59,
        hydrodynamic_constant=0.6173,
        tangential_drag_coefficient=0.01,
        normal_drag_coefficient=2.12,
        total_length_m=350.0,
    ),
    "HA": CableParameters(
        name="HA",
        diameter_m=0.0332,
        weight_air_n_per_m=26.50,
        submerged_weight_n_per_m=17.80,
        hydrodynamic_constant=0.7974,
        tangential_drag_coefficient=0.01,
        normal_drag_coefficient=1.64,
        total_length_m=300.0,
    ),
    "POWER_500KV": CableParameters(
        name="POWER_500KV",
        diameter_m=0.139,
        weight_air_n_per_m=48.0 * 9.8,
        submerged_weight_n_per_m=32.0 * 9.8,
        hydrodynamic_constant=0.0,
        tangential_drag_coefficient=0.0,
        normal_drag_coefficient=1.0,
        total_length_m=160.0,
        max_water_depth_m=100.0,
        max_allowable_tension_n=87_500.0,
        min_bending_radius_m=5.0,
    ),
}


# LA/HA 工况：用于稳态剖面和动态时程入口。
_CASES: dict[str, OperationCase] = {
    "la_accel_200m": OperationCase(
        name="la_accel_200m",
        cable=_CABLES["LA"],
        initial_speed_mps=0.5,
        final_speed_mps=1.5,
        duration_s=30.0,
        water_depth_m=200.0,
    ),
    "la_decel_200m": OperationCase(
        name="la_decel_200m",
        cable=_CABLES["LA"],
        initial_speed_mps=1.5,
        final_speed_mps=0.5,
        duration_s=30.0,
        water_depth_m=200.0,
    ),
    "ha_accel_200m": OperationCase(
        name="ha_accel_200m",
        cable=_CABLES["HA"],
        initial_speed_mps=0.5,
        final_speed_mps=1.5,
        duration_s=30.0,
        water_depth_m=200.0,
    ),
    "ha_decel_200m": OperationCase(
        name="ha_decel_200m",
        cable=_CABLES["HA"],
        initial_speed_mps=1.5,
        final_speed_mps=0.5,
        duration_s=30.0,
        water_depth_m=200.0,
    ),
}


# 500 kV 电缆流速扫描：表层流速变化，底层流速保持 0.5 m/s。
for _surface in (0.50, 1.00, 1.50, 2.00):
    _CASES[f"power_current_speed_{_surface:.2f}".replace(".", "p")] = OperationCase(
        name=f"power_current_speed_{_surface:.2f}".replace(".", "p"),
        cable=_CABLES["POWER_500KV"],
        initial_speed_mps=0.5,
        final_speed_mps=0.5,
        duration_s=0.0,
        water_depth_m=100.0,
        solver_model="power_500kv",
        touchdown_tension_n=1500.0,
        vessel_speed_mps=0.5,
        payout_speed_mps=0.5,
        current_surface_mps=_surface,
        current_bottom_mps=0.5,
        current_direction_deg=90.0,
    )

# 500 kV 电缆流向扫描：表层/底层流速固定，改变相对船舶航向。
for _direction in (90, 60, 30, 0):
    _CASES[f"power_current_direction_{_direction}"] = OperationCase(
        name=f"power_current_direction_{_direction}",
        cable=_CABLES["POWER_500KV"],
        initial_speed_mps=0.5,
        final_speed_mps=0.5,
        duration_s=0.0,
        water_depth_m=100.0,
        solver_model="power_500kv",
        touchdown_tension_n=1500.0,
        vessel_speed_mps=0.5,
        payout_speed_mps=0.5,
        current_surface_mps=1.5,
        current_bottom_mps=0.5,
        current_direction_deg=float(_direction),
    )

# 500 kV 电缆触地点预张力扫描。
for _pretension in (2000, 3000, 4000, 5000):
    _CASES[f"power_pretension_{_pretension}"] = OperationCase(
        name=f"power_pretension_{_pretension}",
        cable=_CABLES["POWER_500KV"],
        initial_speed_mps=0.5,
        final_speed_mps=0.5,
        duration_s=0.0,
        water_depth_m=100.0,
        solver_model="power_500kv",
        touchdown_tension_n=float(_pretension),
        vessel_speed_mps=0.5,
        payout_speed_mps=0.5,
        current_surface_mps=1.5,
        current_bottom_mps=0.5,
        current_direction_deg=90.0,
    )


def list_cables() -> list[str]:
    """返回可用电缆参数组名称。"""

    return sorted(_CABLES)


def get_cable(name: str) -> CableParameters:
    """按名称读取一个电缆参数组。"""

    key = name.upper()
    if key not in _CABLES:
        raise KeyError(f"unknown cable: {name}")
    return _CABLES[key]


def list_cases() -> list[str]:
    """返回可运行工况名称。"""

    return sorted(_CASES)


def get_case(name: str) -> OperationCase:
    """按名称读取一个铺缆工况。"""

    key = name.lower()
    if key not in _CASES:
        raise KeyError(f"unknown case: {name}")
    return _CASES[key]

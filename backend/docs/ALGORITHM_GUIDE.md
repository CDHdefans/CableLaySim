# 核心算法阅读说明

这份说明按代码阅读顺序组织，方便核查人员从输入、物理量、单工况求解到批量输出逐层检查。

## 1. 输入层

`src/cable_tension/parameters.py` 定义两个不可变数据结构：

- `CableParameters`: 电缆直径、单位长度重量、阻力系数、轴向刚度、允许张力等参数。
- `OperationCase`: 一个工况的水深、船速、放缆速度、水流、预张力和速度变化信息。

`src/cable_tension/cases.py` 保存预设工况。LA/HA 工况用于基础剖面和时程诊断，`POWER_500KV` 工况用于第 4 章水流速度、流向和预张力参数扫描。

## 2. 坐标和载荷层

`src/cable_tension/kinematics.py` 提供局部 `t/n/b` 坐标系：

- `orientation_vectors(theta, psi)` 返回切向、法向、副法向单位向量。
- `axial_strain(tension, axial_stiffness)` 计算轴向应变。
- `stretched_step_components(...)` 将单元长度投影到全局坐标。

`src/cable_tension/loads.py` 提供 Morison 阻力分量：

- 切向阻力使用 `Ct`。
- 法向和副法向阻力共用 `Cn`，并使用横向合速度。
- 返回值均为作用在电缆上的局部坐标力分量。

## 3. 三维准静态求解

`src/cable_tension/solver.py` 是单工况主入口：

- `solve_case(case, points=201)` 负责参数检查、三维积分和结果组装。
- `_integrate_3d_profile_from_touchdown` 从 TDP 边界向船端积分三维位置和张力。
- 分布载荷来自水中重量和 Morison 法向阻力；不读取论文表格目标值。
- `profile.csv` 输出 signed `x/y/z`、`theta/psi`、切向向量、海流向量、阻力向量和张力。

计算路径不依赖工况名称中的文字分支判断，而是根据 `OperationCase` 中的物理输入决定流速、流向和预张力响应。

## 4. 时程诊断

`src/cable_tension/dynamic.py` 处理 LA 张力时程诊断。当前动态部分不能称为完整 3.5.5 实现；它没有按论文 3.5.5 逐式求解 `N_i`、`B_i` 并回代至收敛。

- `solve_time_history(case_name, points=361)` 生成命名预设兼容路径的时间采样点。
- `solve_time_history_input(case, points=361)` 接收工作台提交的完整动态输入，并校验速度变化方向、时长、水深和离散单元数。
- `_solve_finite_difference_angle_time_history` 生成 LA 多单元角运动动态时程。
- `_integrate_angle_motion` 对沿缆离散单元的倾角、方位角和角速度做时间迭代。
- `_angle_accelerations` 组合直线平衡残差、相邻单元二阶差分、悬挂段几何尺度下的运动加速度和阻尼。
- `_finite_difference_tensions` 按单元倾角/方位角、重量、切向阻力和局部切向加速度 `Act_i` 递推底端到顶端张力；`Act_i` 只保留船体加速度在单元切向的投影。
- `_dynamic_mass_per_meter` 用结构质量和圆柱排水附加质量计算动态惯性质量。
- `_straight_line_state` 按论文直线初始条件计算角度、悬挂长度和切向阻力张力。

当前时程已经从单自由度张力响应升级为多单元角运动诊断，但仍不把表 4-1 当硬贴目标，也不声明完整复现论文第 3.5.5 节。测试中的百分比误差上限只是诊断包络，用来防止结果数量级退化；若要继续缩小动态差异，需要完整 PDF 中的式 (3.71)-(3.75)、论文边界输入、时间采样口径、TDP 接触约束或实验数据。

## 5. 输出层

`src/cable_tension/io.py` 只负责稳定输出格式：

- `write_result` 写出稳态/剖面工况的 `summary.csv`、`profile.csv`、`profile.svg`。
- `write_time_history` 写出动态时程的 `time_summary.csv`、`time_history.csv`、`time_history.svg`。

`src/cable_tension/paper.py` 是批量编排入口，负责运行预设工况并生成输入表、结果表和 SVG 曲线。该文件不改变求解算法，只组织输出文件。

## 6. 建议核查顺序

1. 先看 `parameters.py` 和 `cases.py`，确认输入参数单位和工况定义。
2. 再看 `kinematics.py` 和 `loads.py`，确认坐标系和阻力符号。
3. 检查 `solver.py` 中的 `solve_case`、`_integrate_3d_profile_from_touchdown` 和 `_distributed_load`。
4. 检查 `dynamic.py` 中的 `_solve_finite_difference_angle_time_history`、`_integrate_angle_motion`、`_angle_accelerations`、`_finite_difference_tensions` 和 `_straight_line_state`。
5. 运行 `scripts/run_case.py` 或 `scripts/reproduce_paper.py`，对照 CSV/SVG 输出核查结果。

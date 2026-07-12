# 输入输出说明

## 单工况输入

列出可用工况：

```powershell
python scripts/run_case.py --list
```

运行命名工况：

```powershell
python scripts/run_case.py --case <case_name> --points 201
```

工况输入由 `src/cable_tension/parameters.py` 中的数据结构定义，预设值集中在 `src/cable_tension/cases.py`。

主要字段：

- `case_name`: 工况编号。
- `cable`: 电缆参数组。
- `diameter_m`: 等效直径。
- `weight_air_n_per_m`: 空气中单位长度重量。
- `submerged_weight_n_per_m`: 水中单位长度重量。
- `tangential_drag_coefficient`: 切向阻力系数。
- `normal_drag_coefficient`: 法向阻力系数。
- `total_length_m`: 参与剖面计算的电缆长度。
- `initial_speed_mps`, `final_speed_mps`, `duration_s`: 速度变化设置。
- `water_depth_m`: 水深。
- `touchdown_tension_n`: 触地点/TDP 张力估计输入。`known_plough_trajectory` 已知犁轨迹分支中该值只作为输入回显和对比标签，不作为犁端外加边界力。
- `vessel_speed_mps`, `payout_speed_mps`: 船速和放缆速度。
- `current_surface_mps`, `current_bottom_mps`, `current_direction_deg`: 表层流速、底层流速和流向。

## 单工况输出

`scripts/run_case.py` 写出：

- `summary.csv`: 一行标量结果。
- `profile.csv`: 剖面离散点。
- `profile.svg`: 剖面图。

`summary.csv` 字段：

- `case_name`
- `top_tension_initial_n`
- `top_tension_min_n`
- `top_tension_final_n`
- `suspended_length_m`
- `layback_m`

`profile.csv` 字段：

- `index`
- `arc_m`
- `x_m`
- `y_m`
- `z_m`
- `theta_rad`
- `psi_rad`
- `tangent_x`, `tangent_y`, `tangent_z`
- `current_x_mps`, `current_y_mps`, `current_z_mps`
- `drag_x_n_per_m`, `drag_y_n_per_m`, `drag_z_n_per_m`
- `tension_n`

## 动态时程输入

`scripts/reproduce_paper.py` 会生成 `inputs/time_history_cases.csv`。

前端工作台通过后端 API 读取参数例子，但运行时应提交当前表单里的完整动态输入。命名工况只作为兼容的预设入口，不能代替操作输入。

### 船载可测输入优先

动态铺缆入口的物理输入应优先来自船上或作业系统可测、可接入的量，再统一变换到项目内部路由坐标：

- 船端导缆点位置与速度：来自 GNSS/DP/INS、陀螺姿态和导缆点杆臂换算后的导缆点轨迹；平动边界优先使用导缆点对地速度矢量或位置差分速度。若现场系统给出船体坐标速度，应使用船舶纵荡速度 `u`、横荡速度 `v`、艏向/艉向姿态和导缆点杆臂换算到导缆点；不把船体艏向本身当作平动速度方向。
- 犁端入口位置与速度：来自 USBL/声学跟踪、脐带/拖体定位、深度或姿态系统换算后的犁入口轨迹；优先输入平面速度分量和深度。
- 放缆速度与放出长度：来自绞车、张紧器或计米轮编码器，作为标量材料通量输入。
- 海流速度：来自 ADCP、流速仪或外部环境模型；优先输入水体对地速度矢量。若只给速度大小和方向角，方向角表示水体速度矢量的去向。
- 材料与环境：缆径、单位重、刚度、阻力系数、水深、海床和接触参数应以工程参数表或现场设置为准。

输入解释必须区分三套坐标。船体坐标系 `{b}` 使用船舶运动专用口径：`x_b` 为艏向纵向，速度分量为纵荡 `u`；`y_b` 为右舷横向，速度分量为横荡 `v`；`z_b` 为垂向。导航坐标系 `{n}` 承接 GNSS/DP/INS 的 SOG、COG、艏向、经纬度或本地 ENU/NED 位置。求解器内部使用作业航迹坐标系 `{s}`：`x_s` 为作业纵向/铺缆前进方向，`y_s` 为作业横向，`z_s` 为向下深度。前端显示采用纵向速度 `u`、横向速度 `v`；API 字段名仍保留 `start_velocity_x_mps/start_velocity_y_mps`，表示已经从船体坐标或导航坐标换算到 `{s}` 后的导缆点/犁入口速度分量。船体艏向、SOG/COG、作业航迹方位和水流去向必须分开记录。

- `GET /api/time-history-cases`: 返回可运行的 LA 动态时程工况及输入字段。
- `POST /api/run-time-history`: 提交 `case_name`、`points` 和完整动态输入字段，运行 `dynamic.py::solve_time_history_input`，并写出 `time_summary.csv`、`time_history.csv`、`time_history.svg`。
- `POST /api/run-time-history`: 仅提交 `case_name` 和 `points` 时走命名预设兼容路径，运行 `dynamic.py::solve_time_history`。
- `POST /api/run-time-history` 的 JSON 同时返回 `plot_data.frames`，每帧包含三维节点 `x_m/y_m/z_m/tension_n` 和逐段张力数组 `segment_tensions_n`，供前端三维动画和张力颜色分布使用。
- `POST /api/realtime-sessions`: 用静态材料/几何配置和首个同步传感器包创建内存会话，返回首帧，不写 CSV/SVG。首包必须包含船端导缆点和犁入口的位置/速度、放缆速度、犁出口材料速度及水平海流速度矢量。
- `POST /api/realtime-sessions/{session_id}/samples`: 提交下一连续序号的同步包并从上一求解状态推进。当前工程更新周期为 5 s，相邻包之间仍按内部稳定步长积分，不能把 5 s 直接作为数值积分步长。
- `GET /api/realtime-sessions/{session_id}`: 读取最新帧但不推进；`DELETE` 释放会话。跳号、乱序、超龄、间隔过大、无效质量或并发推进会返回结构化错误，拒绝包不会改变已接受状态。

`length_boundary_source` 决定动态边界：

- `straight_line_sensitivity`: 旧 LA 角运动诊断入口，保留给历史表格和论文复现。
- `xpbd_node_dynamics_contact_remesh`: 节点坐标、XPBD 长度约束、接触和重网格的自由铺缆原型入口。
- `known_plough_trajectory`: 工程场景入口；船端位置由船速积分或实测样本给定，犁端位置由用户给定轨迹和速度推进，求解船端到犁端之间的悬垂段。船端放缆材料速度为 `q_f`，犁出口材料速度为 `q_p`，悬垂材料长度按 `dL_s/dt = q_f - q_p` 更新；端点运动速度不替代材料速度。首帧优先采用同端点、同主动长度的闭式悬链线静力几何与张力；后续放缆长度只从船端进入，铺底转移长度只从犁端退出，目标段长按材料悬垂长度和原始单元数控制，不再把新增长度全线比例缩放。预测阶段包含 Morison 阻力和重力/浮力；XPBD 接触约束形成当前步法向反力后，再按库仑摩擦施加接触节点速度修正。该入口不求解犁土相互作用，犁端轨迹视为已知边界。

请求输入字段：

- `case_name`: 本次计算名称；命名预设兼容路径中也是预设工况编号。
- `diameter_m`: 缆线等效外径，进入 Morison 阻力和附加质量。
- `weight_air_n_per_m`: 空气中单位重，进入节点结构质量。
- `submerged_weight_n_per_m`: 水中单位重，进入节点重力荷载。
- `tangential_drag_coefficient`: 切向阻力系数 `Ct`。
- `normal_drag_coefficient`: 法向阻力系数 `Cn`。
- `axial_stiffness_n`: 轴向刚度 `EA`，进入 XPBD 长度约束刚度。
- `current_speed_mps`: 水流速度。
- `current_direction_deg`: 全局水体速度矢量的去向；作业航迹坐标中 `0 deg = +X`（作业纵向/铺缆前进方向），`90 deg = +Y`（作业横向）。该角度进入 Morison 相对速度和成熟工具 current-profile 映射。
- `speed_change`: `accel` 表示加速，`decel` 表示减速。
- `initial_speed_mps`: 初始铺设速度。
- `final_speed_mps`: 最终铺设速度。
- `duration_s`: 速度变化历时；动态变速工况必须大于 0。
- `total_duration_s`: 总仿真时长。
- `water_depth_m`: 作业水深。
- `element_count`: 离散单元数。
- `touchdown_tension_n`: 触地点/TDP 名义张力输入。已知犁轨迹分支会回显该输入并用于工况标签，但不把该值作为犁端外加载荷；张力输出来自当前时刻离散缆段约束反力。
- `payout_initial_speed_mps`: 初始放缆速度；缺省时取 `initial_speed_mps`。
- `payout_final_speed_mps`: 最终放缆速度；缺省时取 `final_speed_mps`。
- `length_boundary_source`: 动态边界类型。
- `vessel_initial_x_m`, `vessel_initial_y_m`: 船端导缆点初始平面位置；`x` 为作业纵向，`y` 为作业横向。
- `vessel_heading_deg`: 船端速度方位 fallback，`0 deg = +X`，`90 deg = +Y`。该字段是缺少速度分量时的兼容输入，不等同于船体艏向、首向角或陀螺罗经读数；当分段运动提供完整 `start_velocity_x_mps/start_velocity_y_mps/end_velocity_x_mps/end_velocity_y_mps` 时，求解器优先使用实测速度矢量。
- `plough_initial_x_m`, `plough_initial_y_m`, `plough_initial_z_m`: 犁端初始位置；`known_plough_trajectory` 必填。
- `plough_speed_mps`: 犁端速度；`known_plough_trajectory` 必填。
- `plough_exit_speed_mps`: 可选犁出口材料速度 `q_p`，单位 m/s，来自犁端牵引或导缆轮编码器；必须大于或等于 0。填写时优先于犁入口运动速度并直接进入悬垂材料长度更新。缺省时仅允许无实测犁轨迹、全部犁运动命令严格沿作业航迹 `+X` 的直线施工，并采用无滑移、铺后立即静止于海床的工程假设；系统按 `+X` 速度分量推定。横向、曲线或任意实测轨迹缺少 `q_p` 时 API 会拒绝请求，要求实测编码器值；响应中的 `plough_exit_speed_source=no_slip_inferred` 不得称为实测。
- `plough_heading_deg`: 犁端速度方位 fallback，角度约定同船端；仅在未提供犁端速度分量时用于兼容输入。
- `initial_suspended_length_m`: 初始悬垂材料长度；`known_plough_trajectory` 必填，用作首帧闭式悬链线主动长度和 OrcaFlex/MoorDyn 同输入对比的初始长度口径。该值必须不小于船端导缆点到犁入口的初始端点直线距离；求解器不再用隐藏比例系数静默补长。
- `vessel_motion_segments`, `plough_motion_segments`: 可选分段运动命令。每段必须包含 `duration_s`。若现场测量或控制系统给出平面速度分量，则提供完整 `start_velocity_x_mps`、`start_velocity_y_mps`、`end_velocity_x_mps`、`end_velocity_y_mps`；API 和求解器直接使用这些实测速度矢量积分船端/犁端边界轨迹，并强制从矢量派生速度模长和 fallback 方向用于回显。即使请求同时携带冗余 `start_speed_mps`、`end_speed_mps` 或 `heading_deg`，完整速度分量也优先。若没有实测矢量，则每段用 `start_speed_mps`、`end_speed_mps`、`heading_deg` 表示速度模长和方向角 fallback。
- `vessel_motion_samples`, `plough_motion_samples`: 可选实测端点轨迹样本，是实时/准实时接入的优先入口。每个样本包含 `time_s`、`x_m`、`y_m`，可选 `z_m`、`velocity_x_mps`、`velocity_y_mps`、`velocity_z_mps`；`time_s` 必须从 `0` 开始且严格递增。船端样本表示导缆点在作业航迹坐标中的实测位置/速度；犁端样本表示犁入口 USBL/声学跟踪或融合定位后的实测位置/速度。求解器优先使用样本插值得到端点位置和速度；样本缺少速度时使用相邻位置差分估计速度。若同一请求同时给出 motion samples 和 motion segments，samples 优先，segments 只作为兼容回显或降级输入。犁端样本第一个点给出 `z_m` 时，可以作为 `plough_initial_z_m` 的来源。
- `payout_speed_segments`: 可选放缆分段速度命令。每段包含 `duration_s`、`start_speed_mps`、`end_speed_mps`，用于主动悬垂长度和材料速度边界。
- `min_bending_radius_m`: 工程最小弯曲半径限值；可选。填写后进入动态铺埋求解的弯曲半径约束，并用于输出裕度；缺失时只输出计算最小半径，不判定合格性。

结果输出字段：

- `time_summary.csv` 和 API `summary` 会回显 `diameter_m`、`weight_air_n_per_m`、`submerged_weight_n_per_m`、`tangential_drag_coefficient`、`normal_drag_coefficient`、`axial_stiffness_n`、`current_speed_mps`、`current_direction_deg`、`speed_change`、`initial_speed_mps`、`final_speed_mps`、`initial_suspended_length_m`、`duration_s`、`total_duration_s`、`water_depth_m`、`element_count`、`touchdown_tension_n`。
- `initial_tension_n`: 起始顶端张力。
- `extreme_tension_n`: 加速工况为最低张力，减速工况为最高张力。
- `steady_tension_n`: 稳态顶端张力。
- `plough_speed_mps`: 已知犁端轨迹入口的犁端速度。
- `plough_exit_speed_mps`: 末帧实际用于材料流更新的犁出口材料速度 `q_p`，单位 m/s。
- `plough_exit_speed_source`: `measured` 表示请求提供的编码器读数；`no_slip_inferred` 表示请求未提供 `q_p`，系统仅按直线、无滑移假设由犁沿作业航迹速度分量推定。
- `plough_inlet_tension_final_n`: 末帧 TDP/接触过渡前段张力；来自接触过渡前自由悬垂段的 XPBD 轴向约束反力。
- `plough_boundary_tension_final_n`: 末帧犁入口端点边界张力；来自犁入口相邻缆段的 XPBD 轴向约束反力，不再来自 `touchdown_tension_n`。
- `plough_adjacent_segment_tension_final_n`: 末帧犁端相邻段张力诊断；已知犁轨迹分支中保留最后一段 XPBD 长度约束反力，可能包含贴底尾段被犁端位置强制闭合的端点反力。
- `plough_tension_status`: 犁入口端点张力状态。`carried` 表示犁入口边界张力为正且端点相邻段承载；`free_or_unset` 表示边界张力接近零；`slack_or_unclosed` 和 `low_adjacent_tension` 保留给兼容诊断。
- `minimum_bend_radius_min_m`: 时程中的最小弯曲半径估计。
- `minimum_bend_radius_limit_m`: 输入的工程最小弯曲半径限值；未输入时为空。
- `minimum_bend_radius_margin_m`: `minimum_bend_radius_min_m - minimum_bend_radius_limit_m`；未输入限值时为空。
- `minimum_bend_radius_status`: `ok`、`below_limit`、`not_available` 或 `not_configured`。
- `geometric_length_deficit_max_m` / `geometric_length_deficit_final_m`: 几何长度缺口诊断。该值为两端距离超过当前材料悬垂长度时的差额；大于零表示输入的放缆/铺底/端点运动在当前材料长度下不可无拉伸闭合，应作为过张紧或输入不一致风险处理，而不是由求解器静默补缆。
- `time_history.csv` 对 `known_plough_trajectory` 额外输出 `plough_x_m`、`plough_y_m`、`plough_z_m`、`plough_inlet_tension_n`、`plough_boundary_tension_n`、`plough_adjacent_segment_tension_n`、`plough_entry_angle_deg`、`minimum_bend_radius_m`。
- `time_history.csv` 对 `known_plough_trajectory` 还输出 `material_suspended_length_m` 和 `geometric_length_deficit_m`，用于核查放缆材料流与几何闭合风险。
- `plot_data.frames.items[*]` 输出 `segment_tensions_n`，数组长度等于当前离散缆段数；对 `known_plough_trajectory` 该数组为整条可视离散缆段的 XPBD 长度约束反力分布，包括接触/贴底尾段的动态分布反力，用于前端缆线颜色和分布对比。`plough_inlet_tension_final_n` 表示 TDP/接触过渡前段张力；`plough_boundary_tension_final_n` 与 `plough_adjacent_segment_tension_final_n` 表示犁入口端点相邻段约束反力。对 `known_plough_trajectory` 还额外输出 `boundary`、`vessel_x_m/y_m/z_m`、`plough_x_m/y_m/z_m` 和 `minimum_bend_radius_m`，用于前端显示船端、犁端和悬垂段运动。
- `summary.vessel_motion_samples` 和 `summary.plough_motion_samples`: API 回显已解析的实测端点样本，供联调确认现场 GNSS/DP/INS/USBL 轨迹没有被静默丢弃。

## 成熟工具验证输出

`backend/scripts/validate_moordyn_moorpy.py` 生成的 MoorPy/MoorDyn 对比文件只属于 validation/diagnostic 层，不写回生产求解器，也不作为前端仿真真值。

`backend/scripts/validate_orcaflex.py` 生成的 OrcaFlex 接入文件同样只属于 validation/diagnostic 层。该脚本先探测本机 `OrcFxAPI`、DLL 版本和许可证状态，再写出项目到 OrcaFlex 的同输入映射和端点时程文件；只有当 `Model()` 能成功创建后，后续 OrcaFlex 数值运行才可作为精度对比入口。若安装目录中 GUI 使用的 `lib64` 与 Python API 目录中的运行时依赖不一致，脚本只在验证输出目录创建本地 Win64 运行时副本并覆盖 GUI 同源 `lib64` 文件，不修改 OrcaFlex 安装目录。许可证缺失时状态写为 `license_unavailable`，不得解释为项目算法或 OrcaFlex 物理结果。

主要验证输出：

- `*_validation_summary.csv`: 项目、MoorPy、MoorDyn 标量对比和运行状态。
- `*_diagnostic_gaps.csv`: 标量差异诊断。
- `*_frame_scope_audit.csv`: 同帧、同窗口和同初始化状态口径核查。
- `*_quasi_static_time_history.csv`: MoorPy 可用时的同帧准静态时程参照。
- `*_initial_state_static_audit.csv`: 项目 `t=0` 首帧静态初态审计表，汇总项目首帧、同帧 MoorPy 静力、闭式自由悬链线诊断和 MoorDyn endpoint-history 初始化张力；验收口径固定为 `separate_static_initial_state_audit`，不纳入 post-initial driven-history 收敛。
- `*_moordyn_input_mapping.csv`: 项目输入到 MoorDyn 输入的映射或 out-of-scope 标记。
- `*_moordyn_runtime_sensitivity.csv`: MoorDyn 同窗口运行时敏感性表，用于检查 current、摩擦、接触、阻尼和附加质量等验证模型输入的影响。
- `*_moordyn_dt_convergence.csv`: MoorDyn endpoint-history 不同时间步的末帧标量收敛表，数值参考取最小已完成 `endpoint_history_ok` 时间步。
- `*_moordyn_dt_history_convergence.csv`: MoorDyn 采样时程收敛表，比较 fairlead、犁侧节点和 line-max 标量历史，并包含排除首个共同样本的 `post_initial_*` 字段。
- `*_moordyn_dt_node_convergence.csv`: MoorDyn 同时刻同节点收敛表，比较节点张力、海床反力、位置和接触状态，并包含排除首个共同样本的 `post_initial_*` 字段。
- `*_moordyn_initialization_acceptance.csv`: MoorDyn `t=0` 初始化验收口径表，明确初始化样本属于单独 static/initial-state 审核，不纳入 driven endpoint-history 收敛验收；同时列出包含首样本和排除首样本后的关键差值。
- `*_moordyn_fairlead_attribution.csv`: MoorDyn 同窗口 fairlead 归因表，用于检查 current、摩擦、接触、端点运动和放缆长度变化的影响。
- `*_moordyn_endpoint_nodes.csv`: MoorDyn endpoint-history 的节点张力、节点位置和海床接触力历史。
- `*_distribution_comparison.csv`: 按归一化线长把 MoorDyn 节点与项目最终帧节点张力插值对齐的诊断表。
- `*_distribution_mouth_audit.csv`: 审核用逐点表，列出项目 `segment_tensions_n` 段张力、项目 TDP/接触过渡张力、项目犁入口端点相邻段反力、MoorDyn 节点张力、MoorDyn 海床力和 `comparison_mouth`/`direct_tension_comparison` 分类。该表用于区分直接分布比较、接触模型诊断和犁端口径差异，不得用于回填 MoorDyn 结果。
- `*_distribution_attribution.csv`: 基于 MoorDyn sensitivity 节点历史的张力分布归因汇总表。仅当 `window_end_s` 等于项目输出帧时间时汇总直接分布、自由跨、fairlead、接触和犁端口径差异；表内记录 `dynamic_history_window_s` 和 `initialization_scope`，用于区分窗口起点 MoorDyn 静态初始化诊断和完整历史接续。
- `*_orcaflex_probe.csv` / `*_orcaflex_probe.json`: OrcaFlex Python API、DLL、Python 版本、验证本地运行时覆盖和许可证状态探测结果。
- `*_orcaflex_input_mapping.csv`: 项目输入到 OrcaFlex 输入口径的映射、共享假设和 out-of-scope 标记；坐标固定为 `X=x`、`Y=y`、`Z=-z`。
- `*_orcaflex_endpoint_history.csv`: 船端导缆点和犁入口在 OrcaFlex z-up 坐标中的位置、速度、悬垂材料长度和长度变化率时程。
- `*_orcaflex_validation_report.md`: OrcaFlex 接入状态、输入映射文件和端点历史文件的文字审查摘要。

## 批量输出

运行：

```powershell
python scripts/reproduce_paper.py --points 201
```

默认写入：

```text
output/paper_reproduction/
```

目录内容：

- `inputs/cases.csv`: 全部稳态/剖面工况输入。
- `inputs/time_history_cases.csv`: LA 时程诊断工况输入。
- `tables/table_4_1_dynamic_la.csv`: LA 时程诊断张力结果。
- `tables/table_4_3_current_speed.csv`: 水流速度影响结果。
- `tables/table_4_4_current_direction.csv`: 水流方向影响结果。
- `tables/table_4_5_pretension.csv`: 预张力影响结果。
- `figures/*.svg`: 批量对比图。
- `time_histories/<case_name>/time_summary.csv`: 时程诊断标量结果。
- `time_histories/<case_name>/time_history.csv`: 时程诊断张力时程。
- `time_histories/<case_name>/time_history.svg`: 时程诊断张力时程图。
- `cases/<case_name>/summary.csv`: 单工况标量结果。
- `cases/<case_name>/profile.csv`: 单工况剖面明细。
- `cases/<case_name>/profile.svg`: 单工况剖面图。

## 接触与 TDP 输出口径

动态时程的 API 与 `time_history.csv` 同步输出以下字段：

- `tdp_arc_length_m`：从船端导缆点沿未伸长材料弧长量取的 TDP/犁入口截面位置，单位 m。
- `free_span_material_length_m`：TDP 截面之前的自由悬跨材料长度，单位 m。
- `seabed_contact_length_m`：TDP 截面之后连续贴底段的材料长度，单位 m。
- `seabed_normal_reaction_n`：当前连续贴底段的海床法向反力合力，单位 N。

存在海床接触时，TDP 位于自由悬跨段与连续贴底段之间；投影接触节点采用相邻单元半控制体重构亚单元转折位置。不存在海床接触时，不构造虚假的触地点，TDP/入口截面退化为活动缆末端的犁入口：点取犁入口、材料弧长取活动总长、张力取犁入口相邻段的轴向约束反力。任一时刻均满足
`free_span_material_length_m + seabed_contact_length_m = active_material_length_m`。

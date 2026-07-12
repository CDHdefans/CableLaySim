# CableLaySim 后端

后端由 Python 实现，包含缆线静态/动态求解、准实时会话、HTTP API、结果输出以及外部软件对比工具。核心运行路径只依赖 Python 标准库。

## 结构

```text
backend/
├─ api/                   HTTP 服务与请求/响应结构
├─ src/cable_tension/     求解器和物理模型
├─ scripts/               工况、基准测试和外部验证脚本
├─ docs/                  算法与输入输出说明
└─ tests/                 单元和集成测试
```

核心模块：

- `parameters.py`：缆材和环境参数。
- `geometry.py`、`kinematics.py`：几何、坐标与运动学。
- `hydrodynamics.py`、`loads.py`：相对流速与 Morison 载荷。
- `contact.py`：海床接触和摩擦。
- `axial_constraints.py`：全局轴向约束求解。
- `dynamic_laying.py`、`lumped_mass_dynamic.py`：铺缆时域推进。
- `realtime.py`：有状态准实时会话和同步数据包。
- `io.py`：CSV/SVG 输出。

## 启动 API

在仓库根目录执行：

```powershell
python backend/api/app.py --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

主要接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 服务状态 |
| GET | `/api/cases` | 静态/准静态命名工况 |
| GET | `/api/time-history-cases` | 动态时程模板 |
| POST | `/api/run-custom-case` | 自定义静态/准静态工况 |
| POST | `/api/run-time-history` | 离线动态时程 |
| POST | `/api/realtime-sessions` | 创建准实时会话 |
| POST | `/api/realtime-sessions/{id}/samples` | 提交下一帧同步传感器数据 |
| GET | `/api/realtime-sessions/{id}` | 查询会话状态 |
| DELETE | `/api/realtime-sessions/{id}` | 结束会话 |

完整字段和单位见 [docs/INPUT_OUTPUT.md](docs/INPUT_OUTPUT.md)。

## 命令行工况

```powershell
python backend/scripts/run_case.py --list
python backend/scripts/run_case.py --case power_current_speed_1p50 --points 201
```

默认结果写入 `backend/output/`，该目录不会提交到 Git。

## 准实时会话

准实时路径以固定周期接收同步后的船端、犁端、放缆和海流数据。每一帧从上一帧的节点位置、节点速度、活动悬垂长度和内部求解状态继续积分。5 s 是默认数据更新周期，不是内部数值时间步；每个周期内部仍按更小步长推进。

数据源应满足：

- 统一时间戳和 SI 单位。
- 船端数据已换算到导缆点，犁端数据已换算到犁入口。
- 所有位置、速度和海流使用同一右手坐标系。
- 输入间隔已知，乱序、重复和异常跳变应在接入层处理。

运行本地性能基准：

```powershell
python backend/scripts/benchmark_realtime_session.py
```

## 外部精度验证

仓库提供 OrcaFlex、MoorDyn 和 MoorPy 对比脚本，但不包含这些软件及其许可证。OrcaFlex 脚本仅在本机已安装并可导入 `OrcFxAPI` 时运行。

```powershell
python backend/scripts/validate_orcaflex.py --help
python backend/scripts/analyze_orcaflex_60s_validation.py --help
python backend/scripts/validate_moordyn_moorpy.py --help
```

对比时应对齐材料、外径、单位长度质量/水中重量、轴向刚度、阻力系数、海流、海床、端点轨迹、初始状态、输出时刻和张力定义。不得用经验修正系数把结果硬拟合到参考软件。

## 测试

在仓库根目录执行：

```powershell
python -m unittest discover -s backend/tests -v
```

## 模型边界

当前模型面向水中悬垂段和海床接触段的实时/准实时张力估计。犁被抽象为给定运动的入口边界；模型不描述犁内导缆槽摩擦、土体切削和犁体六自由度动力学。结果用于研究和软件对比，不应直接作为施工安全控制指令。

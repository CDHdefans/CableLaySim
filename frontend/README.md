# CableLaySim 前端

前端是 React、TypeScript、Vite 和 Three.js 构建的工程工作台，用于设置仿真参数、调用 Python API，并查看缆线三维运动与张力结果。

## 环境与启动

- Node.js 20 或更高版本
- npm 10 或更高版本

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

前端默认调用 `http://127.0.0.1:8765`。请先在仓库根目录启动后端：

```powershell
python backend/api/app.py --host 127.0.0.1 --port 8765
```

## 页面功能

- **参数设置**：材料、环境/施工、船端、放缆、犁端和数值参数。
- **离线时程**：总仿真时长控制停止时刻，运动阶段定义边界速度随时间的变化。
- **准实时模式**：创建后端会话，按 5 s 周期提交同步数据并从上一状态续算。
- **三维视图**：鼠标旋转、缩放和平移；显示船、缆、犁、海面、海床、来流方向和张力色标。
- **张力分析**：船端、TDP/接触过渡、犁入口时程与沿缆张力分布。
- **结果导出**：下载时程和分布数据。

## 参数语义

- `uX`：作业纵向速度分量，沿铺缆前进方向。
- `vY`：作业横向速度分量，正方向按界面坐标说明。
- 起始/末端速度：单个阶段两端的速度值，阶段内采用线性插值；不是 x/y 两个方向。
- 总仿真时长：求解停止条件。阶段超出总时长时按总时长截断；阶段不足时后续保持最后有效指令。
- 离散单元数：数值求解设置，不属于材料或环境参数。

## 代码结构

```text
frontend/src/
├─ App.tsx                       应用状态与页面编排
├─ SimulationParameterPanel.tsx  参数输入与工况模板
├─ SimulationResultView.tsx      离线结果页面
├─ RealtimeResultView.tsx        准实时结果页面
├─ DynamicFrameViewer.tsx        Three.js 三维视图
├─ ResultPlots.tsx               时程和沿缆分布图
├─ api.ts                        后端 API 客户端
├─ types.ts                      前后端数据类型
└─ styles.css                    界面样式
```

## 测试与构建

```powershell
cd frontend
npm test -- --run
npm run build
```

生产构建输出到 `frontend/dist/`，该目录不提交到 Git。

## 开发约束

- 前端字段必须与后端 schema 的单位和物理含义一致。
- 新增参数时应证明它真实进入求解路径，而不只是出现在表单中。
- 三维时间轴、张力曲线和统计值必须引用同一个输出帧。
- 不在浏览器端重新计算或修正后端张力结果。

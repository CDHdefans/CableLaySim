# 算法代码交付说明

本文档说明如何运行这份算法代码。对外交付时，以 `README.md`、`REPRODUCTION_FILE_MANIFEST.md`、`docs/ALGORITHM_GUIDE.md` 和 `docs/INPUT_OUTPUT.md` 为主要核查入口。

## 1. 解压后检查目录

应看到：

- `README.md`
- `REPRODUCTION_FILE_MANIFEST.md`
- `docs/`
- `src/cable_tension/`
- `scripts/`

交付包只包含源码、脚本和说明文件。运行后产生的 CSV/SVG 会写入本地 `output/` 目录。

## 2. 运行单个工况

列出所有工况：

```powershell
python scripts/run_case.py --list
```

运行一个例子：

```powershell
python scripts/run_case.py --case power_current_speed_1p50 --points 201
```

输出目录：

```text
output/power_current_speed_1p50/
```

其中：

- `summary.csv`: 顶端张力、悬垂长度、水平后拖量等标量结果。
- `profile.csv`: 每个离散点的坐标、角度和张力。
- `profile.svg`: 剖面图。

## 3. 批量生成结果

运行：

```powershell
python scripts/reproduce_paper.py --points 201
```

输出目录：

```text
output/paper_reproduction/
```

主要结果：

- `inputs/cases.csv`
- `inputs/time_history_cases.csv`
- `tables/table_4_1_dynamic_la.csv`
- `tables/table_4_3_current_speed.csv`
- `tables/table_4_4_current_direction.csv`
- `tables/table_4_5_pretension.csv`
- `figures/*.svg`

## 4. 算法边界说明

本代码输出当前算法计算值。500 kV 工况采用输入驱动的三维准静态路径；LA 时程工况采用多单元倾角/方位角有限差分、张力递推和局部切向加速度 `Act_i`，其中 `Act_i` 只保留船体加速度在单元切向的投影。若要进一步贴近论文完整动态曲线形态，需要补充论文边界条件、输入参数、时间采样口径或实验数据，而不是加入修正系数。

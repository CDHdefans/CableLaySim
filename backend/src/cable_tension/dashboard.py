"""Static HTML dashboard for paper reproduction comparisons."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TableSpec:
    title: str
    path: str
    variable_label: str
    variable_column: str
    value_columns: tuple[str, ...]
    evidence_level: str
    evidence_label: str
    evidence_note: str
    source_note: str


@dataclass(frozen=True)
class FigureSpec:
    title: str
    path: str
    evidence_level: str
    evidence_label: str
    evidence_note: str


_TABLES = (
    TableSpec(
        title="表 4-1 LA 动态顶端张力",
        path="tables/table_4_1_dynamic_la.csv",
        variable_label="工况",
        variable_column="case_name",
        value_columns=("initial_tension_n", "extreme_tension_n", "steady_tension_n"),
        evidence_level="l1",
        evidence_label="LA 多单元角运动输出",
        evidence_note="初值、峰/谷值和稳态值由多单元倾角/方位角有限差分、张力递推和局部切向加速度 Act 计算得到；Act 只保留船体加速度切向投影，论文基准只用于百分比误差诊断。",
        source_note="src/cable_tension/dynamic.py::_solve_finite_difference_angle_time_history",
    ),
    TableSpec(
        title="表 4-3 不同流速",
        path="tables/table_4_3_current_speed.csv",
        variable_label="表层流速 m/s",
        variable_column="current_surface_mps",
        value_columns=("top_tension_n", "tdp_x_m", "tdp_y_m"),
        evidence_level="l1",
        evidence_label="准静态算法输出",
        evidence_note="表格数值由 500kV 准静态求解路径计算，不再读取论文第 4 章目标值；论文基准只在测试集对比。",
        source_note="src/cable_tension/solver.py::_integrate_3d_profile_from_touchdown",
    ),
    TableSpec(
        title="表 4-4 不同流向",
        path="tables/table_4_4_current_direction.csv",
        variable_label="流向 deg",
        variable_column="current_direction_deg",
        value_columns=("top_tension_n", "tdp_x_m", "tdp_y_m"),
        evidence_level="l1",
        evidence_label="准静态算法输出",
        evidence_note="流向工况由海流方向、平均流速、海底张力和水深输入计算 TDP 与顶端张力。",
        source_note="src/cable_tension/solver.py::_integrate_3d_profile_from_touchdown",
    ),
    TableSpec(
        title="表 4-5 不同 TDP 预张力",
        path="tables/table_4_5_pretension.csv",
        variable_label="海底张力 N",
        variable_column="touchdown_tension_n",
        value_columns=("top_tension_n", "tdp_x_m", "tdp_y_m"),
        evidence_level="l1",
        evidence_label="准静态算法输出",
        evidence_note="预张力工况由 TDP 边界张力、水深、流向和 Morison 法向阻力共同驱动三维积分，论文基准只在测试集对比。",
        source_note="src/cable_tension/solver.py::_integrate_3d_profile_from_touchdown",
    ),
)

_FIGURES = (
    FigureSpec(
        title="图 4-1 LA 加速顶端张力",
        path="figures/fig_4_1_la_acceleration.svg",
        evidence_level="l1",
        evidence_label="LA 多单元角运动输出",
        evidence_note="时程由船速变化、多单元角运动、张力递推和局部切向加速度 Act 生成；Act 只保留船体加速度切向投影，论文表 4-1 只作为非阻断百分比诊断基准。",
    ),
    FigureSpec(
        title="图 4-2 LA 减速顶端张力",
        path="figures/fig_4_2_la_deceleration.svg",
        evidence_level="l1",
        evidence_label="LA 多单元角运动输出",
        evidence_note="时程由船速变化、多单元角运动、张力递推和局部切向加速度 Act 生成；Act 只保留船体加速度切向投影，论文表 4-1 只作为非阻断百分比诊断基准。",
    ),
    FigureSpec(
        title="图 4-11 流速影响",
        path="figures/fig_4_11_current_speed.svg",
        evidence_level="l1",
        evidence_label="准静态算法输出",
        evidence_note="TDP 与顶端张力来自准静态算法输出，空间曲线由算法端点生成。",
    ),
    FigureSpec(
        title="图 4-12 流向影响",
        path="figures/fig_4_12_current_direction.svg",
        evidence_level="l1",
        evidence_label="准静态算法输出",
        evidence_note="流向改变由算法输入驱动，图中展示求得的 TDP 端点和 profile。",
    ),
    FigureSpec(
        title="图 4-13 预张力影响",
        path="figures/fig_4_13_pretension.svg",
        evidence_level="l1",
        evidence_label="准静态算法输出",
        evidence_note="预张力扫描由算法输出生成，用于观察 TDP 与张力分布变化。",
    ),
)

_ASSUMPTIONS = (
    ("准三维缆线", "用弧长 s 描述缆线中心线，姿态由仰角 θ 与水平投影角 ψ 给出。"),
    ("小伸长轴向弹性", "轴向应变 ε = T / EA，用来把原长单元 ds 转为实际空间增量。"),
    ("Morison 拖曳", "流体力主要按相对速度二次项计算，切向/法向/副法向分量分别投影。"),
    ("边界条件驱动", "TDP 预张力、水深、船速、放缆速度和海流剖面决定求解入口。"),
    ("当前实现边界", "第 4 章 500kV 工况走输入驱动的三维准静态平衡路径；表 4-1 LA 时程走多单元角状态有限差分和张力递推。当前动态部分不能称为完整 3.5.5 实现，尚未实现论文 3.5.5 的 N_i/B_i 收敛迭代。论文基准只在测试集和验证报告中按百分比对比，剩余误差用于暴露边界条件和输入参数差异。"),
)

_DERIVATION_STEPS = (
    {
        "tag": "01",
        "title": "几何坐标与轴向伸长",
        "formula": "t = [cosθ cosψ, cosθ sinψ, sinθ],  ε = T / EA",
        "body": "用 θ 描述缆线相对水平面的仰角，用 ψ 描述水平投影方向。张力 T 通过轴向刚度 EA 转为伸长率 ε，因此一段原长 ds 的空间增量为 dR = (1 + ε)t ds。",
        "inputs": "θ, ψ, T, EA, ds",
        "outputs": "局部切向 t、伸长率 ε、坐标增量 dX/dY/dZ",
    },
    {
        "tag": "02",
        "title": "缆线速度与相对流速",
        "formula": "V_rc = V_c - V_cur,  V_cur = [u(h), v(h), 0]",
        "body": "缆线运动速度 V_c 由敷缆船速度、放缆速度和缆线姿态共同决定；海流速度按水深 h 给定。拖曳力只看缆线相对流体的速度。",
        "inputs": "船速 Vs、放缆速度 Vpo、流速剖面 u(h)/v(h)",
        "outputs": "相对速度 V_rc 及其 t/n/b 分量",
    },
    {
        "tag": "03",
        "title": "Morison 流体拖曳力",
        "formula": "D_t = -1/2 πρ C_t d√(1+ε) V_rt|V_rt|",
        "body": "拖曳力分解到切向、法向、副法向。切向阻力使用 Ct，法向和副法向阻力使用 Cn，并按相对速度平方增长。",
        "inputs": "ρ, d, Ct, Cn, ε, V_rt, V_rn, V_rb",
        "outputs": "D_t, D_n, D_b",
    },
    {
        "tag": "04",
        "title": "受力平衡方程",
        "formula": "T' + W + D = 0",
        "body": "当前实现中，每个缆线单元满足张力、水中重量和 Morison 拖曳的局部平衡。后续若引入动力学附加项，必须先补充方程和参数来源。",
        "inputs": "张力项、水中重量、Morison 拖曳力",
        "outputs": "dT/ds, dθ/ds, dψ/ds 的约束关系",
    },
    {
        "tag": "05",
        "title": "三维弧长积分",
        "formula": "T_next = T - q ds,  R_next = R + t ds",
        "body": "当前 500kV 实现从 TDP 边界向船端逐段积分，分布载荷 q 只由水中重量和 Morison 法向阻力组成。LA 动态时程使用多单元倾角/方位角有限差分、张力递推和局部切向加速度 Act，不读取论文目标值。",
        "inputs": "TDP 边界张力、水深、单元弧长、三维海流向量、缆线参数",
        "outputs": "三维缆线位形、张力分布、顶端张力时间历程诊断",
    },
    {
        "tag": "06",
        "title": "本仓库怎样对比结果",
        "formula": "误差 = 本地输出值 - 论文表格值",
        "body": "生产输出只写算法计算值；论文表格值放在测试集里，与算法输出做误差对比。这样不会把论文结果混入求解器，也不会在看板里伪造 0 误差。",
        "inputs": "算法 CSV 输出；测试侧论文表 4-1/4-3/4-4/4-5 基准",
        "outputs": "算法表、SVG 曲线、逐工况 profile；测试报告给出误差",
    },
)

_ALGORITHM_STAGES = (
    ("01 输入装配", "cases.py", "缆线参数、水深、流速/流向、船速、放缆速度、TDP 预张力。", "已实现"),
    ("02 公式辅助", "kinematics.py / loads.py", "方向余弦、轴向伸长、Reynolds 数、Morison 拖曳力。", "已实现"),
    ("03 竖向平衡退化", "solver.py::solve_case", "LA/HA 在无水平流和无 TDP 预张力时，由统一三维积分自然退化为竖向水中重量平衡。", "L1"),
    ("04 Chapter 4 准静态求解", "solver.py::_integrate_3d_profile_from_touchdown", "500kV 表 4-3/4-4/4-5 由水深、TDP 张力、流速/流向和 Morison 法向拖曳三维积分计算。", "3D 准静态"),
    ("05 表 4-1 时程诊断生成", "dynamic.py::_solve_finite_difference_angle_time_history", "表 4-1 相关工况使用多单元倾角/方位角有限差分、张力递推和局部切向加速度 Act；Act 只保留船体加速度切向投影，不使用目标角恢复或拟合增益。", "LA 多单元角运动"),
    ("06 论文基准对比", "tests/test_time_history.py", "论文表 4-1 数值只在测试集中作为参考基准，与动态算法输出计算误差。", "测试集"),
)

_SOURCE_AUDIT = (
    ("_solve_finite_difference_angle_time_history", "dynamic.py", "LA 时程诊断使用多单元角状态有限差分和张力递推，不读取论文表格目标值。", "l1"),
    ("_integrate_3d_profile_from_touchdown", "solver.py", "从 TDP 边界向船端积分三维位置和张力，不读取论文表格目标值。", "l1"),
    ("solve_case", "solver.py", "统一入口，LA/HA 与 500kV 工况都走同一三维积分路径。", "l1"),
    ("morison_drag_components", "loads.py", "实现局部 t/n/b 方向 Morison 阻力辅助函数，供动态近似模型复用。", "l1"),
)


def generate_dashboard(output_dir: Path | str) -> Path:
    """Generate `dashboard.html` in a paper reproduction output directory."""

    root = Path(output_dir)
    dashboard = root / "dashboard.html"
    table_sections = "\n".join(_render_table(root, spec) for spec in _TABLES)
    figure_cards = "\n".join(_render_figure(spec) for spec in _FIGURES)
    validation_sections = _render_validation_sections(root)
    case_count = _count_case_rows(root / "inputs" / "cases.csv")
    dynamic_count = _count_case_rows(root / "inputs" / "time_history_cases.csv")

    dashboard.write_text(
        _html_document(
            assumption_cards="\n".join(_render_assumption(title, body) for title, body in _ASSUMPTIONS),
            spatial_3d=_render_spatial_3d(root),
            formula_lab=_render_formula_lab(),
            derivation_cards="\n".join(_render_derivation_card(step) for step in _DERIVATION_STEPS),
            algorithm_rows="\n".join(_render_algorithm_row(*stage) for stage in _ALGORITHM_STAGES),
            source_cards="\n".join(_render_source_card(*item) for item in _SOURCE_AUDIT),
            validation_sections=validation_sections,
            table_sections=table_sections,
            figure_cards=figure_cards,
            case_count=case_count,
            dynamic_count=dynamic_count,
        ),
        encoding="utf-8",
    )
    return dashboard


def _render_assumption(title: str, body: str) -> str:
    return f"""
      <article class="assumption-card">
        <h3>{html.escape(title)}</h3>
        <p>{html.escape(body)}</p>
      </article>
    """


def _render_spatial_3d(root: Path) -> str:
    profile_path = root / "cases" / "power_current_direction_30" / "profile.csv"
    if not profile_path.exists():
        profile_path = root / "cases" / "power_current_speed_1p50" / "profile.csv"
    rows = _read_csv(profile_path) if profile_path.exists() else []
    points = [
        {
            "x": float(row["x_m"]),
            "y": float(row["y_m"]),
            "z": float(row["z_m"]),
            "tension": float(row.get("tension_n", 0.0) or 0.0),
        }
        for row in rows
    ]
    if points:
        step = max(1, len(points) // 160)
        sampled = points[::step]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
    else:
        sampled = []
    source_label = profile_path.as_posix() if profile_path.exists() else "profile.csv not generated"
    payload = {
        "source": profile_path.as_posix(),
        "points": sampled,
    }
    profile_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    markup = """
      <section class="spatial-3d direct-3d" aria-label="三维坐标 x/y/z 直接三维缆线场景">
        <div class="three-copy">
          <span class="badge badge-l1">Three.js 直接三维</span>
          <h2>三维坐标 x/y/z：可拖拽旋转</h2>
          <p>这一屏直接读取 profile.csv 里的 x_m、y_m、z_m 和 tension_n，把缆线画成空间曲线。二维剖面只放到后面的结果图里；这里先讲清楚空间坐标、TDP、海流方向和受力箭头。</p>
          <dl class="three-facts">
            <dt>数据源</dt><dd>__PROFILE_SOURCE__</dd>
            <dt>点数</dt><dd>__POINT_COUNT__ 个 profile 采样点</dd>
            <dt>交互</dt><dd>拖动画面旋转，松开后自动慢速转动</dd>
          </dl>
        </div>
        <div class="three-scene" data-scene="direct-3d">
          <canvas id="cable-three-canvas" class="three-canvas" aria-label="可拖拽旋转的三维缆线、海床、海流和受力箭头"></canvas>
          <div class="three-overlay">
            <b>受力箭头</b>
            <span><i class="dot tension"></i>T(s), T(s+ds)</span>
            <span><i class="dot drag"></i>D_t / D_n</span>
            <span><i class="dot weight"></i>W - B</span>
            <span><i class="dot inertia"></i>F_I / F_am</span>
          </div>
          <div class="three-status">x/y 是水平平面，z 是水深；红色空间曲线为 profile.csv 重建缆线。</div>
        </div>
        <script id="cable-profile-data" type="application/json">__PROFILE_JSON__</script>
        <script type="module">
          import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.module.js";

          const dataElement = document.getElementById("cable-profile-data");
          const canvas = document.getElementById("cable-three-canvas");
          const payload = JSON.parse(dataElement.textContent);
          const CABLE_PROFILE_3D = payload.points;
          window.CABLE_PROFILE_3D = CABLE_PROFILE_3D;

          if (canvas && CABLE_PROFILE_3D.length > 1) {
            const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
            renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
            const scene = new THREE.Scene();
            scene.fog = new THREE.Fog(0x071316, 16, 42);

            const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 80);
            camera.position.set(9, 6.5, 13);
            camera.lookAt(0, -2, 0);

            const key = new THREE.DirectionalLight(0xffffff, 2.2);
            key.position.set(5, 8, 7);
            scene.add(key);
            scene.add(new THREE.AmbientLight(0x9fd0c2, 1.05));

            const root = new THREE.Group();
            root.rotation.set(-0.1, -0.58, 0);
            scene.add(root);

            const xs = CABLE_PROFILE_3D.map((p) => p.x);
            const ys = CABLE_PROFILE_3D.map((p) => p.y);
            const zs = CABLE_PROFILE_3D.map((p) => p.z);
            const minX = Math.min(...xs), maxX = Math.max(...xs);
            const minY = Math.min(...ys), maxY = Math.max(...ys);
            const minZ = Math.min(...zs), maxZ = Math.max(...zs);
            const span = Math.max(maxX - minX, maxY - minY, maxZ - minZ, 1);
            const scale = 8 / span;
            const midX = (minX + maxX) / 2;
            const midY = (minY + maxY) / 2;
            const waterY = 2.2;
            const seabedY = waterY - maxZ * scale;

            const profilePoints = CABLE_PROFILE_3D.map((p) => new THREE.Vector3(
              (p.x - midX) * scale,
              waterY - p.z * scale,
              (p.y - midY) * scale
            ));
            const curve = new THREE.CatmullRomCurve3(profilePoints);

            const seabed = new THREE.Mesh(
              new THREE.PlaneGeometry(14, 11, 18, 14),
              new THREE.MeshStandardMaterial({ color: 0x586f63, roughness: 0.9, metalness: 0.02 })
            );
            seabed.rotation.x = -Math.PI / 2;
            seabed.position.y = seabedY - 0.04;
            root.add(seabed);

            const water = new THREE.Mesh(
              new THREE.PlaneGeometry(14, 11),
              new THREE.MeshBasicMaterial({ color: 0x6bb7c4, transparent: true, opacity: 0.22, side: THREE.DoubleSide })
            );
            water.rotation.x = -Math.PI / 2;
            water.position.y = waterY;
            root.add(water);

            const cable = new THREE.Mesh(
              new THREE.TubeGeometry(curve, Math.max(96, profilePoints.length * 2), 0.055, 14, false),
              new THREE.MeshStandardMaterial({ color: 0xb44332, roughness: 0.44, metalness: 0.18 })
            );
            root.add(cable);

            const line = new THREE.Line(
              new THREE.BufferGeometry().setFromPoints(profilePoints),
              new THREE.LineBasicMaterial({ color: 0xffd7c8, linewidth: 2 })
            );
            root.add(line);

            const start = profilePoints[0];
            const end = profilePoints[profilePoints.length - 1];
            const ship = new THREE.Group();
            const deck = new THREE.Mesh(new THREE.BoxGeometry(1.65, 0.18, 0.72), new THREE.MeshStandardMaterial({ color: 0x171d1f }));
            const hull = new THREE.Mesh(new THREE.BoxGeometry(1.25, 0.26, 0.52), new THREE.MeshStandardMaterial({ color: 0x1d6675, roughness: 0.55 }));
            deck.position.y = waterY + 0.32;
            hull.position.y = waterY + 0.08;
            ship.add(deck, hull);
            ship.position.set(start.x, 0, start.z);
            root.add(ship);

            const tdp = new THREE.Mesh(
              new THREE.SphereGeometry(0.16, 24, 18),
              new THREE.MeshStandardMaterial({ color: 0xf2c166, emissive: 0x5b3300, emissiveIntensity: 0.35 })
            );
            tdp.position.copy(end);
            root.add(tdp);

            const runner = new THREE.Mesh(
              new THREE.SphereGeometry(0.11, 24, 18),
              new THREE.MeshStandardMaterial({ color: 0xffd7c8, emissive: 0xb44332, emissiveIntensity: 0.65 })
            );
            root.add(runner);

            function label(text, color) {
              const labelCanvas = document.createElement("canvas");
              labelCanvas.width = 256;
              labelCanvas.height = 96;
              const context = labelCanvas.getContext("2d");
              context.font = "700 36px Microsoft YaHei, sans-serif";
              context.fillStyle = color;
              context.fillText(text, 12, 58);
              const texture = new THREE.CanvasTexture(labelCanvas);
              const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
              sprite.scale.set(1.3, 0.48, 1);
              return sprite;
            }

            function arrow(direction, origin, length, color, name) {
              const helper = new THREE.ArrowHelper(direction.clone().normalize(), origin, length, color, 0.22, 0.11);
              helper.name = name;
              root.add(helper);
              return helper;
            }

            const origin = new THREE.Vector3(-5.4, seabedY + 0.18, -4.2);
            arrow(new THREE.Vector3(1, 0, 0), origin, 2.0, 0xb44332, "x-axis");
            arrow(new THREE.Vector3(0, 0, 1), origin, 2.0, 0x26755a, "y-axis");
            arrow(new THREE.Vector3(0, 1, 0), origin, 2.0, 0xf2c166, "z-axis");
            const xLabel = label("x", "#ffb2a4"); xLabel.position.copy(origin).add(new THREE.Vector3(2.28, 0, 0));
            const yLabel = label("y", "#9fd0c2"); yLabel.position.copy(origin).add(new THREE.Vector3(0, 0, 2.28));
            const zLabel = label("z", "#f2c166"); zLabel.position.copy(origin).add(new THREE.Vector3(0, 2.28, 0));
            root.add(xLabel, yLabel, zLabel);

            for (let i = 0; i < 4; i += 1) {
              arrow(new THREE.Vector3(0.7, 0.02, 0.45), new THREE.Vector3(-4.6 + i * 2.4, waterY - 1.1 - i * 0.22, -3.6 + i * 0.58), 1.0, 0x75d4c2, "current");
            }

            const forcePoint = curve.getPoint(0.56);
            const tangent = curve.getTangent(0.56).normalize();
            const drag = new THREE.Vector3(-tangent.z, 0.12, tangent.x).normalize();
            arrow(tangent, forcePoint, 1.15, 0xb44332, "T(s+ds)");
            arrow(tangent.clone().multiplyScalar(-1), forcePoint, 0.88, 0xb44332, "T(s)");
            arrow(drag, forcePoint, 0.92, 0x1d6675, "D_t / D_n");
            arrow(new THREE.Vector3(0, -1, 0), forcePoint, 0.82, 0x26755a, "W - B");
            arrow(new THREE.Vector3(0.35, 0.45, -0.38), forcePoint, 0.74, 0xa36a14, "F_I / F_am");

            let dragging = false;
            let lastX = 0;
            let lastY = 0;
            canvas.addEventListener("pointerdown", (event) => {
              dragging = true;
              lastX = event.clientX;
              lastY = event.clientY;
              canvas.setPointerCapture(event.pointerId);
            });
            canvas.addEventListener("pointermove", (event) => {
              if (!dragging) return;
              const dx = event.clientX - lastX;
              const dy = event.clientY - lastY;
              root.rotation.y += dx * 0.009;
              root.rotation.x += dy * 0.006;
              root.rotation.x = Math.max(-0.65, Math.min(0.42, root.rotation.x));
              lastX = event.clientX;
              lastY = event.clientY;
            });
            canvas.addEventListener("pointerup", (event) => {
              dragging = false;
              canvas.releasePointerCapture(event.pointerId);
            });
            canvas.addEventListener("pointerleave", () => { dragging = false; });

            function resize() {
              const rect = canvas.parentElement.getBoundingClientRect();
              const width = Math.max(320, Math.floor(rect.width));
              const height = Math.max(360, Math.floor(rect.height));
              renderer.setSize(width, height, false);
              camera.aspect = width / height;
              camera.updateProjectionMatrix();
            }
            new ResizeObserver(resize).observe(canvas.parentElement);
            resize();

            function animate(time) {
              if (!dragging) root.rotation.y += 0.0018;
              runner.position.copy(curve.getPoint((time * 0.000075) % 1));
              renderer.render(scene, camera);
              window.__CABLE_THREE_READY__ = true;
              requestAnimationFrame(animate);
            }
            requestAnimationFrame(animate);
          }
        </script>
      </section>
    """
    return (
        markup.replace("__PROFILE_SOURCE__", html.escape(source_label))
        .replace("__POINT_COUNT__", str(len(sampled)))
        .replace("__PROFILE_JSON__", profile_json.replace("</", "<\\/"))
    )


def _render_formula_lab() -> str:
    return """
      <section class="formula-lab" aria-label="缆线动图、受力分析、力计算和输入输出">
        <article class="lab-panel cable-animation">
          <div class="lab-heading">
            <span>01</span>
            <h3>缆线动图</h3>
          </div>
          <svg viewBox="0 0 620 320" role="img" aria-label="缆线随船速、海流和 TDP 约束变化的动态图">
            <rect x="0" y="0" width="620" height="320" fill="#dcebed"/>
            <path d="M0 226 C130 204 250 228 382 210 C488 196 552 214 620 202 L620 320 L0 320 Z" fill="#c8d2cb"/>
            <g class="current-lines">
              <line x1="362" y1="72" x2="512" y2="72"/><line x1="396" y1="110" x2="554" y2="110"/><line x1="334" y1="148" x2="486" y2="148"/>
            </g>
            <rect x="62" y="48" width="132" height="20" fill="#171d1f"/>
            <path d="M84 68 L180 68 L162 96 L70 96 Z" fill="#1d6675"/>
            <line x1="132" y1="96" x2="166" y2="132" stroke="#b44332" stroke-width="5"/>
            <path class="live-cable" d="M166 132 C230 160 268 204 310 232 C360 266 422 260 486 226" fill="none" stroke="#b44332" stroke-width="8" stroke-linecap="round">
              <animate attributeName="d" dur="4.2s" repeatCount="indefinite"
                values="M166 132 C230 160 268 204 310 232 C360 266 422 260 486 226;
                        M166 132 C226 152 284 196 322 224 C370 252 430 252 486 226;
                        M166 132 C238 168 274 212 312 240 C360 274 418 266 486 226;
                        M166 132 C230 160 268 204 310 232 C360 266 422 260 486 226"/>
            </path>
            <circle cx="486" cy="226" r="9" fill="#171d1f"/>
            <g class="axis-mini">
              <line x1="78" y1="272" x2="188" y2="272"/><line x1="78" y1="272" x2="78" y2="172"/><line x1="78" y1="272" x2="128" y2="232"/>
              <text x="194" y="276">x</text><text x="66" y="170">z</text><text x="132" y="228">y</text>
            </g>
            <text x="198" y="58">V_s</text><text x="492" y="218">TDP</text><text x="360" y="58">V_cur(h)</text>
          </svg>
        </article>

        <article class="lab-panel force-analysis">
          <div class="lab-heading">
            <span>02</span>
            <h3>受力分析</h3>
          </div>
          <svg viewBox="0 0 420 300" role="img" aria-label="缆线单元受力分析图">
            <rect x="0" y="0" width="420" height="300" fill="#f8faf9"/>
            <path d="M142 136 C172 112 236 112 270 138" fill="none" stroke="#171d1f" stroke-width="10" stroke-linecap="round"/>
            <circle cx="206" cy="126" r="8" fill="#171d1f"/>
            <g class="force-arrow tension">
              <line x1="154" y1="133" x2="74" y2="98"/><polygon points="74,98 92,97 84,113"/>
              <line x1="260" y1="132" x2="338" y2="94"/><polygon points="338,94 326,108 320,91"/>
            </g>
            <g class="force-arrow drag">
              <line x1="206" y1="126" x2="322" y2="172"/><polygon points="322,172 304,172 312,156"/>
            </g>
            <g class="force-arrow weight">
              <line x1="206" y1="126" x2="206" y2="234"/><polygon points="206,234 198,216 214,216"/>
            </g>
            <g class="force-arrow inertia">
              <line x1="206" y1="126" x2="150" y2="42"/><polygon points="150,42 166,52 152,62"/>
            </g>
            <text x="38" y="94">T(s)</text><text x="316" y="82">T(s+ds)</text>
            <text x="324" y="184">D_t, D_n</text><text x="214" y="236">W - B</text><text x="112" y="42">F_I / F_am</text>
          </svg>
        </article>

        <article class="lab-panel force-calculation">
          <div class="lab-heading">
            <span>03</span>
            <h3>对应力的计算</h3>
          </div>
          <div class="calc-stack">
            <div><strong>轴向应变</strong><code>ε = T / EA</code><span>先由当前张力得到伸长。</span></div>
            <div><strong>相对速度</strong><code>V_r = V_c - V_cur</code><span>把船速、放缆速度、海流投影到局部坐标。</span></div>
            <div><strong>拖曳力</strong><code>D_t = -1/2 πρ C_t d√(1+ε)V_rt|V_rt|</code><span>法向/副法向同理使用 C_n。</span></div>
            <div><strong>平衡更新</strong><code>T' = -(W - B + D + F_am + F_I)</code><span>沿弧长迭代更新张力与姿态。</span></div>
            <div><strong>材料力</strong><code>T = EAε</code><span>对应力/应变关系回到缆线轴向拉力。</span></div>
          </div>
        </article>

        <article class="lab-panel io-flow">
          <div class="lab-heading">
            <span>04</span>
            <h3>输入输出</h3>
          </div>
          <div class="io-grid">
            <div><b>输入</b><span>水深 h、船速 V_s、放缆速度 V_po、海流 V_cur(h)、直径 d、EA、Ct/Cn、TDP 预张力</span></div>
            <div><b>计算</b><span>三维切向 t → 海流法向投影 → Morison 拖曳 → T_next = T - q ds → R_next = R + t ds</span></div>
            <div><b>输出</b><span>坐标 x/y/z、张力 T(s,t)、顶端张力 T_top、TDP 偏移、算法 CSV、SVG 曲线；论文误差由测试集报告</span></div>
          </div>
        </article>
      </section>
    """


def _render_derivation_card(step: dict[str, str]) -> str:
    return f"""
      <article class="formula-card">
        <div class="formula-tag">{html.escape(step["tag"])}</div>
        <div>
          <div class="equation-visual" aria-hidden="true">{_diagram_for_step(step["tag"])}</div>
          <h3>{html.escape(step["title"])}</h3>
          <div class="formula">{html.escape(step["formula"])}</div>
          <details>
            <summary>展开讲解</summary>
            <p>{html.escape(step["body"])}</p>
            <dl>
              <dt>输入</dt><dd>{html.escape(step["inputs"])}</dd>
              <dt>输出</dt><dd>{html.escape(step["outputs"])}</dd>
            </dl>
          </details>
        </div>
      </article>
    """


def _diagram_for_step(tag: str) -> str:
    diagrams = {
        "01": """
          <svg viewBox="0 0 220 120" role="img" aria-label="局部坐标与伸长">
            <path d="M28 88 C76 28 145 28 194 82" fill="none" stroke="#1d6675" stroke-width="5"/>
            <line x1="104" y1="58" x2="164" y2="34" stroke="#b44332" stroke-width="3"/>
            <line x1="104" y1="58" x2="130" y2="96" stroke="#26755a" stroke-width="3"/>
            <circle cx="104" cy="58" r="7" fill="#171d1f"/>
            <text x="168" y="32">t</text><text x="134" y="103">n</text><text x="48" y="92">ds</text>
          </svg>
        """,
        "02": """
          <svg viewBox="0 0 220 120" role="img" aria-label="相对流速">
            <line x1="36" y1="72" x2="162" y2="72" stroke="#1d6675" stroke-width="4"/>
            <line x1="36" y1="72" x2="92" y2="30" stroke="#26755a" stroke-width="4"/>
            <line x1="92" y1="30" x2="166" y2="70" stroke="#b44332" stroke-width="4"/>
            <polygon points="162,72 150,66 150,78" fill="#1d6675"/>
            <polygon points="166,70 152,69 158,59" fill="#b44332"/>
            <text x="166" y="83">V_rc</text><text x="78" y="28">V_c</text><text x="62" y="92">V_cur</text>
          </svg>
        """,
        "03": """
          <svg viewBox="0 0 220 120" role="img" aria-label="Morison 拖曳力">
            <ellipse cx="110" cy="64" rx="38" ry="18" fill="#dfe9e6" stroke="#171d1f" stroke-width="2"/>
            <line x1="24" y1="64" x2="78" y2="64" stroke="#1d6675" stroke-width="4"/>
            <line x1="110" y1="64" x2="174" y2="64" stroke="#b44332" stroke-width="4"/>
            <line x1="110" y1="64" x2="110" y2="24" stroke="#26755a" stroke-width="4"/>
            <polygon points="78,64 66,58 66,70" fill="#1d6675"/>
            <polygon points="174,64 160,58 160,70" fill="#b44332"/>
            <polygon points="110,24 104,38 116,38" fill="#26755a"/>
            <text x="30" y="55">V_r</text><text x="178" y="68">D_t</text><text x="118" y="30">D_n</text>
          </svg>
        """,
        "04": """
          <svg viewBox="0 0 220 120" role="img" aria-label="单元受力平衡">
            <rect x="82" y="42" width="56" height="34" rx="4" fill="#f8faf9" stroke="#171d1f" stroke-width="2"/>
            <line x1="82" y1="59" x2="30" y2="59" stroke="#b44332" stroke-width="4"/>
            <line x1="138" y1="59" x2="190" y2="59" stroke="#b44332" stroke-width="4"/>
            <line x1="110" y1="76" x2="110" y2="106" stroke="#1d6675" stroke-width="4"/>
            <line x1="110" y1="42" x2="110" y2="16" stroke="#26755a" stroke-width="4"/>
            <text x="20" y="54">T</text><text x="194" y="54">T+dT</text><text x="116" y="105">W,D</text>
          </svg>
        """,
        "05": """
          <svg viewBox="0 0 220 120" role="img" aria-label="三维弧长积分">
            <circle cx="38" cy="64" r="12" fill="#1d6675"/><circle cx="86" cy="64" r="12" fill="#1d6675"/>
            <circle cx="134" cy="64" r="12" fill="#1d6675"/><circle cx="182" cy="64" r="12" fill="#1d6675"/>
            <path d="M50 64 L74 64 M98 64 L122 64 M146 64 L170 64" stroke="#171d1f" stroke-width="3"/>
            <text x="29" y="34">i</text><text x="72" y="34">i+1</text><text x="115" y="34">i+2</text><text x="158" y="34">i+3</text>
            <text x="46" y="94">3D arc integration</text>
          </svg>
        """,
        "06": """
          <svg viewBox="0 0 220 120" role="img" aria-label="结果对比">
            <rect x="28" y="32" width="58" height="56" fill="#dfe9e6" stroke="#171d1f"/>
            <rect x="132" y="32" width="58" height="56" fill="#fff4df" stroke="#171d1f"/>
            <line x1="94" y1="60" x2="124" y2="60" stroke="#b44332" stroke-width="4"/>
            <text x="30" y="62">测试基准</text><text x="136" y="62">算法输出</text><text x="78" y="104">Δ 在 tests 中计算</text>
          </svg>
        """,
    }
    return diagrams.get(tag, "")


def _render_algorithm_row(index: str, module: str, body: str, status: str) -> str:
    return f"""
      <div class="algorithm-row">
        <strong>{html.escape(index)}</strong>
        <code>{html.escape(module)}</code>
        <span>{html.escape(body)}</span>
        <em>{html.escape(status)}</em>
      </div>
    """


def _render_source_card(symbol: str, file_name: str, body: str, evidence_level: str) -> str:
    return f"""
      <article class="source-card evidence-item" data-evidence="{html.escape(evidence_level)}">
        <div class="badge badge-{html.escape(evidence_level)}">{html.escape(evidence_level.upper())}</div>
        <h3>{html.escape(symbol)}</h3>
        <code>{html.escape(file_name)}</code>
        <p>{html.escape(body)}</p>
      </article>
    """


def _render_table(root: Path, spec: TableSpec) -> str:
    rows = _read_csv(root / spec.path)
    body_rows = []
    for row in rows:
        cells = [
            f'<td><span class="badge badge-{html.escape(spec.evidence_level)}">{html.escape(spec.evidence_level.upper())}</span></td>',
            f"<td>{html.escape(row[spec.variable_column])}</td>",
        ]
        for column in spec.value_columns:
            value = row[column]
            cells.append(f"<td>{html.escape(value)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    header_cells = ["<th>证据</th>", f"<th>{html.escape(spec.variable_label)}</th>"]
    for column in spec.value_columns:
        label = _pretty_column(column)
        header_cells.append(f"<th>{label}<br><span>算法输出</span></th>")

    return f"""
      <section class="table-panel evidence-item" id="{html.escape(spec.path)}" data-evidence="{html.escape(spec.evidence_level)}">
        <div class="panel-heading">
          <div>
            <span class="badge badge-{html.escape(spec.evidence_level)}">{html.escape(spec.evidence_label)}</span>
            <h2>{html.escape(spec.title)}</h2>
            <p>{html.escape(spec.evidence_note)}</p>
            <code>{html.escape(spec.source_note)}</code>
          </div>
          <a href="{html.escape(spec.path)}">打开 CSV</a>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>{''.join(header_cells)}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
          </table>
        </div>
      </section>
    """


def _render_validation_sections(root: Path) -> str:
    reports = [
        ("表 4-1 动态误差验证", "validation/table_4_1_dynamic_errors.csv"),
        ("第 4 章准静态误差验证", "validation/chapter_4_static_errors.csv"),
    ]
    rendered = []
    for title, relative_path in reports:
        path = root / relative_path
        if not path.exists():
            continue
        rows = _read_csv(path)
        body_rows = []
        for row in rows:
            abs_error = float(row["abs_error"])
            error_class = "ok" if abs_error <= 10.0 else "warn"
            signed_percent = row.get("signed_percent_error", "NA")
            abs_percent = row.get("abs_percent_error", "NA")
            percent_class = "warn"
            if abs_percent != "NA":
                percent_class = "ok" if float(abs_percent) <= 1.0 else "warn"
            body_rows.append(
                "<tr>"
                f"<td>{html.escape(row['case_name'])}</td>"
                f"<td>{html.escape(_pretty_column(row['quantity']))}</td>"
                f"<td>{html.escape(row['algorithm_value'])}</td>"
                f"<td>{html.escape(row['paper_reference'])}</td>"
                f"<td>{html.escape(row['signed_error'])}</td>"
                f'<td class="{error_class}">{html.escape(row["abs_error"])}</td>'
                f"<td>{html.escape(signed_percent)}%</td>"
                f'<td class="{percent_class}">{html.escape(abs_percent)}%</td>'
                "</tr>"
            )
        rendered.append(
            f"""
      <section class="table-panel validation-panel">
        <div class="panel-heading">
          <div>
            <span class="badge badge-l0">测试侧论文基准</span>
            <h2>{html.escape(title)}</h2>
            <p>这里才显示论文参考值和误差；求解器与算法 CSV 仍只输出算法值。</p>
            <code>{html.escape(relative_path)}</code>
          </div>
          <a href="{html.escape(relative_path)}">打开误差 CSV</a>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>工况</th>
                <th>指标</th>
                <th>算法输出</th>
                <th>论文参考</th>
                <th>signed_error</th>
                <th>abs_error</th>
                <th>signed_percent_error</th>
                <th>abs_percent_error</th>
              </tr>
            </thead>
            <tbody>{''.join(body_rows)}</tbody>
          </table>
        </div>
      </section>
            """
        )
    if rendered:
        return "\n".join(rendered)
    return """
      <section class="conclusion-panel">
        <h2>误差验证</h2>
        <p>未找到 validation/*.csv。请运行 <code>scripts/build_dashboard.py</code>，它会从测试侧论文基准生成误差报告后再刷新看板。</p>
      </section>
    """


def _render_figure(spec: FigureSpec) -> str:
    return f"""
      <article class="figure-card evidence-item" data-evidence="{html.escape(spec.evidence_level)}">
        <div class="figure-title">
          <div>
            <span class="badge badge-{html.escape(spec.evidence_level)}">{html.escape(spec.evidence_label)}</span>
            <h3>{html.escape(spec.title)}</h3>
          </div>
          <a href="{html.escape(spec.path)}">SVG</a>
        </div>
        <img src="{html.escape(spec.path)}" alt="{html.escape(spec.title)}">
        <details>
          <summary>展开讲解</summary>
          <p>{html.escape(spec.evidence_note)}</p>
        </details>
      </article>
    """


def _html_document(
    *,
    assumption_cards: str,
    spatial_3d: str,
    formula_lab: str,
    derivation_cards: str,
    algorithm_rows: str,
    source_cards: str,
    validation_sections: str,
    table_sections: str,
    figure_cards: str,
    case_count: int,
    dynamic_count: int,
) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>海底缆线张力论文复现对比看板</title>
  <style>
    :root {{
      --ink: #171d1f;
      --muted: #5e6a6e;
      --paper: #f3f5f2;
      --panel: #ffffff;
      --soft: #e8ede9;
      --line: #c8d0cc;
      --red: #b44332;
      --blue: #1d6675;
      --green: #26755a;
      --amber: #a36a14;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(23,29,31,.055) 1px, transparent 1px),
        linear-gradient(rgba(23,29,31,.045) 1px, transparent 1px),
        var(--paper);
      background-size: 30px 30px;
      font-family: "Noto Serif SC", "Source Han Serif SC", "Microsoft YaHei", serif;
    }}
    header {{
      min-height: 62vh;
      padding: 58px clamp(18px, 5vw, 76px) 34px;
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr);
      gap: 30px;
      align-items: center;
      border-bottom: 3px solid var(--ink);
      background: var(--soft);
    }}
    .eyebrow, .section-label, nav a, .badge, code, .algorithm-row strong, .algorithm-row em {{
      font-family: "Consolas", "Cascadia Mono", "Noto Sans Mono", monospace;
      letter-spacing: 0;
    }}
    .eyebrow {{
      color: var(--red);
      font-size: 13px;
      font-weight: 700;
    }}
    h1 {{
      margin: 16px 0 16px;
      max-width: 960px;
      font-size: clamp(40px, 6.6vw, 86px);
      line-height: .98;
    }}
    .lead {{
      max-width: 840px;
      margin: 0;
      color: #334044;
      font-size: clamp(17px, 1.55vw, 22px);
      line-height: 1.75;
    }}
    .briefing {{
      display: grid;
      gap: 12px;
      padding: 20px;
      background: var(--panel);
      border: 2px solid var(--ink);
      box-shadow: 12px 12px 0 rgba(23,29,31,.12);
    }}
    .hero-schematic {{
      border: 1px solid var(--ink);
      background: #dcebed;
      overflow: hidden;
    }}
    .hero-schematic svg {{
      display: block;
      width: 100%;
      aspect-ratio: 12 / 7;
    }}
    .hero-schematic text {{
      fill: #171d1f;
      font: 700 18px "Microsoft YaHei", sans-serif;
    }}
    .metric {{
      display: grid;
      grid-template-columns: 82px 1fr;
      gap: 14px;
      align-items: baseline;
      padding-bottom: 11px;
      border-bottom: 1px solid var(--line);
    }}
    .metric strong {{ color: var(--blue); font-size: 34px; }}
    .metric span {{ color: var(--muted); line-height: 1.45; }}
    nav {{
      position: sticky;
      top: 0;
      z-index: 5;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 12px clamp(16px, 4vw, 52px);
      background: rgba(243,245,242,.94);
      backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--line);
    }}
    nav a {{
      color: var(--ink);
      text-decoration: none;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 9px 12px;
      font-size: 13px;
      font-weight: 700;
    }}
    main {{ padding: 34px clamp(16px, 4vw, 52px) 86px; }}
    .section-label {{
      margin: 38px 0 12px;
      color: var(--red);
      font-size: 14px;
      font-weight: 700;
    }}
    section > h2, .table-panel h2 {{
      margin: 0 0 12px;
      font-size: clamp(26px, 3vw, 38px);
      line-height: 1.16;
    }}
    h3 {{ margin: 0; font-size: 18px; line-height: 1.32; }}
    p {{ line-height: 1.68; }}
    .problem-grid, .assumption-grid, .formula-grid, .evidence-grid, .figures {{
      display: grid;
      gap: 16px;
    }}
    .problem-grid {{
      grid-template-columns: minmax(0, 1.05fr) minmax(300px, .95fr);
    }}
    .visual-storyboard {{
      margin-top: 16px;
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 10px;
    }}
    .visual-storyboard div {{
      min-height: 88px;
      display: grid;
      align-content: center;
      gap: 8px;
      padding: 12px;
      color: white;
      background: var(--ink);
      border: 1px solid var(--ink);
    }}
    .visual-storyboard strong {{
      color: #9fd0c2;
      font: 700 18px "Consolas", monospace;
    }}
    .visual-storyboard span {{
      font-size: 17px;
      font-weight: 700;
    }}
    .assumption-grid {{
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }}
    .formula-grid {{
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    }}
    .spatial-3d.direct-3d {{
      width: 100vw;
      min-height: 74vh;
      margin: 20px calc(50% - 50vw) 22px;
      display: grid;
      grid-template-columns: minmax(280px, .32fr) minmax(0, 1fr);
      color: #eaf2ef;
      background:
        linear-gradient(120deg, rgba(10, 31, 36, .96), rgba(6, 19, 22, 1) 52%, rgba(15, 42, 43, .98));
      border-top: 3px solid var(--ink);
      border-bottom: 3px solid var(--ink);
      overflow: hidden;
    }}
    .three-copy {{
      display: grid;
      align-content: center;
      gap: 16px;
      padding: clamp(22px, 4vw, 48px);
      border-right: 1px solid rgba(255,255,255,.16);
    }}
    .three-copy .badge {{
      width: max-content;
      color: #9fd0c2;
      background: transparent;
    }}
    .three-copy h2 {{
      margin: 0;
      max-width: 560px;
      font-size: clamp(30px, 4.5vw, 64px);
      line-height: 1.02;
    }}
    .three-copy p {{
      max-width: 560px;
      margin: 0;
      color: #c7d5d2;
      font-size: 17px;
    }}
    .three-facts {{
      grid-template-columns: 72px 1fr;
      max-width: 560px;
      margin: 0;
      padding-top: 12px;
      border-top: 1px solid rgba(255,255,255,.18);
    }}
    .three-facts dt {{
      color: #f2c166;
    }}
    .three-facts dd {{
      color: #dde9e5;
    }}
    .three-scene {{
      position: relative;
      height: 74vh;
      min-height: 74vh;
      background:
        linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px),
        #071316;
      background-size: 42px 42px;
    }}
    .three-canvas {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 0;
      cursor: grab;
      touch-action: none;
    }}
    .three-canvas:active {{
      cursor: grabbing;
    }}
    .three-overlay {{
      position: absolute;
      right: clamp(12px, 2.4vw, 28px);
      top: clamp(12px, 2.4vw, 28px);
      display: grid;
      gap: 8px;
      min-width: 196px;
      padding: 12px 14px;
      color: #eef6f2;
      background: rgba(7, 19, 22, .76);
      border: 1px solid rgba(255,255,255,.22);
      backdrop-filter: blur(12px);
    }}
    .three-overlay b {{
      color: #f2c166;
    }}
    .three-overlay span {{
      display: flex;
      align-items: center;
      gap: 8px;
      font: 700 13px/1.2 "Consolas", "Microsoft YaHei", monospace;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      display: inline-block;
      border-radius: 50%;
    }}
    .dot.tension {{ background: #b44332; }}
    .dot.drag {{ background: #1d6675; }}
    .dot.weight {{ background: #26755a; }}
    .dot.inertia {{ background: #a36a14; }}
    .three-status {{
      position: absolute;
      left: clamp(12px, 2.4vw, 28px);
      bottom: clamp(12px, 2.4vw, 28px);
      max-width: min(520px, calc(100% - 32px));
      padding: 10px 12px;
      color: #dce9e5;
      background: rgba(7, 19, 22, .72);
      border: 1px solid rgba(255,255,255,.18);
      font-size: 14px;
      line-height: 1.5;
    }}
    .formula-lab {{
      display: grid;
      grid-template-columns: minmax(420px, 1.25fr) minmax(320px, .75fr);
      gap: 16px;
      margin-bottom: 18px;
    }}
    .lab-panel {{
      background: rgba(255,255,255,.96);
      border: 1px solid var(--line);
      box-shadow: 0 12px 28px rgba(23,29,31,.075);
      overflow: hidden;
    }}
    .lab-heading {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      background: #171d1f;
      color: white;
    }}
    .lab-heading span {{
      color: #9fd0c2;
      font: 700 16px "Consolas", monospace;
    }}
    .lab-panel svg {{
      display: block;
      width: 100%;
      min-height: 260px;
    }}
    .lab-panel text {{
      fill: #171d1f;
      font: 700 15px "Microsoft YaHei", sans-serif;
    }}
    .cable-animation {{
      grid-row: span 2;
    }}
    .current-lines line {{
      stroke: #26755a;
      stroke-width: 4;
      stroke-linecap: round;
      animation: currentSlide 2.6s linear infinite;
    }}
    .live-cable {{
      filter: drop-shadow(0 8px 10px rgba(180,67,50,.24));
    }}
    .axis-mini line {{
      stroke: #171d1f;
      stroke-width: 2;
    }}
    .force-arrow line {{
      stroke-width: 4;
      stroke-linecap: round;
      animation: forcePulse 2.2s ease-in-out infinite;
    }}
    .force-arrow polygon {{
      animation: forcePulse 2.2s ease-in-out infinite;
    }}
    .force-arrow.tension line, .force-arrow.tension polygon {{ stroke: #b44332; fill: #b44332; }}
    .force-arrow.drag line, .force-arrow.drag polygon {{ stroke: #1d6675; fill: #1d6675; }}
    .force-arrow.weight line, .force-arrow.weight polygon {{ stroke: #26755a; fill: #26755a; }}
    .force-arrow.inertia line, .force-arrow.inertia polygon {{ stroke: #a36a14; fill: #a36a14; }}
    .calc-stack {{
      display: grid;
      gap: 10px;
      padding: 14px;
    }}
    .calc-stack div {{
      display: grid;
      gap: 6px;
      padding: 10px;
      background: #f8faf9;
      border: 1px solid var(--line);
    }}
    .calc-stack strong, .io-grid b {{
      color: var(--blue);
    }}
    .calc-stack span, .io-grid span {{
      color: #435056;
      line-height: 1.55;
    }}
    .io-grid {{
      display: grid;
      gap: 10px;
      padding: 14px;
    }}
    .io-grid div {{
      min-height: 78px;
      display: grid;
      gap: 6px;
      align-content: start;
      padding: 12px;
      background: #f8faf9;
      border: 1px solid var(--line);
    }}
    @keyframes currentSlide {{
      0% {{ stroke-dasharray: 12 16; stroke-dashoffset: 0; }}
      100% {{ stroke-dasharray: 12 16; stroke-dashoffset: -56; }}
    }}
    @keyframes forcePulse {{
      0%, 100% {{ opacity: .55; }}
      50% {{ opacity: 1; }}
    }}
    .evidence-grid {{
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }}
    .figures {{
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    }}
    .problem-panel, .assumption-card, .formula-card, .algorithm-panel, .evidence-card,
    .source-card, .figure-card, .table-panel, .conclusion-panel {{
      background: rgba(255,255,255,.96);
      border: 1px solid var(--line);
      box-shadow: 0 12px 28px rgba(23,29,31,.075);
    }}
    .problem-panel, .assumption-card, .algorithm-panel, .evidence-card,
    .source-card, .conclusion-panel {{
      padding: 18px;
    }}
    .problem-panel strong {{
      display: block;
      color: var(--blue);
      margin-bottom: 8px;
    }}
    .assumption-card p, .source-card p, .evidence-card p, .conclusion-panel p {{
      margin: 10px 0 0;
      color: #39464a;
    }}
    .formula-card {{
      display: grid;
      grid-template-columns: 54px 1fr;
      gap: 14px;
      padding: 18px;
    }}
    .equation-visual {{
      margin: -2px 0 12px;
      background: #f8faf9;
      border: 1px solid var(--line);
    }}
    .equation-visual svg {{
      display: block;
      width: 100%;
      height: 132px;
    }}
    .equation-visual text {{
      fill: #171d1f;
      font: 700 14px "Consolas", "Microsoft YaHei", monospace;
    }}
    .formula-tag {{
      width: 44px;
      height: 44px;
      display: grid;
      place-items: center;
      color: white;
      background: var(--ink);
      font: 700 16px/1 "Consolas", monospace;
    }}
    .formula {{
      margin: 12px 0;
      padding: 12px;
      color: #101719;
      background: #eef3f1;
      border-left: 5px solid var(--blue);
      font: 700 15px/1.55 "Consolas", "Noto Sans Mono", monospace;
      overflow-x: auto;
    }}
    details {{
      margin-top: 10px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    summary {{ cursor: pointer; color: var(--blue); font-weight: 700; }}
    dl {{
      display: grid;
      grid-template-columns: 44px 1fr;
      gap: 6px 10px;
      margin: 10px 0 0;
      font-size: 13px;
      line-height: 1.5;
    }}
    dt {{ color: var(--red); font-weight: 700; }}
    dd {{ margin: 0; color: var(--muted); }}
    .algorithm-panel {{ display: grid; gap: 10px; }}
    .process-rail {{
      grid-template-columns: repeat(6, minmax(150px, 1fr));
      gap: 12px;
      overflow-x: auto;
      padding: 18px;
    }}
    .process-rail h2 {{
      grid-column: 1 / -1;
    }}
    .algorithm-row {{
      min-width: 160px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      align-content: start;
      padding: 14px;
      background: #f9fbfa;
      border: 1px solid var(--line);
    }}
    code {{
      color: #102a31;
      background: #eef3f1;
      padding: 2px 5px;
      font-size: .92em;
    }}
    .algorithm-row em {{
      color: var(--red);
      font-style: normal;
      font-weight: 700;
    }}
    .evidence-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 14px 0 18px;
    }}
    .evidence-toolbar button {{
      min-height: 36px;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 700;
    }}
    .evidence-toolbar button.is-active {{
      background: var(--ink);
      color: white;
      border-color: var(--ink);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 4px 8px;
      border: 1px solid currentColor;
      background: white;
      font-size: 12px;
      font-weight: 700;
    }}
    .badge-l0 {{ color: var(--red); }}
    .badge-l1 {{ color: var(--amber); }}
    .badge-l2 {{ color: var(--green); }}
    .figure-title, .panel-heading {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      padding: 15px 16px;
      border-bottom: 1px solid var(--line);
      background: #f8faf9;
    }}
    .figure-title p, .panel-heading p {{
      margin: 8px 0 8px;
      color: #435056;
      font-size: 14px;
    }}
    a {{ color: var(--blue); }}
    .figure-card img {{
      display: block;
      width: 100%;
      height: 460px;
      object-fit: contain;
      padding: 12px;
      background: white;
    }}
    .figure-wall {{
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      align-items: stretch;
    }}
    .figure-wall .figure-card:first-child {{
      grid-column: span 2;
    }}
    .figure-card details {{
      margin: 0;
      padding: 12px 16px 14px;
      border-top: 1px solid var(--line);
    }}
    .figure-card details p {{
      margin: 10px 0 0;
      color: #435056;
      font-size: 14px;
    }}
    .table-panel {{ margin-bottom: 18px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      min-width: 1040px;
      border-collapse: collapse;
      font-family: "Consolas", "Noto Sans Mono", monospace;
      font-size: 13px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    th {{
      color: #243034;
      background: #f3f6f4;
    }}
    th span {{
      color: var(--muted);
      font-weight: 400;
    }}
    td.ok {{ color: var(--green); font-weight: 700; }}
    td.warn {{ color: var(--red); font-weight: 700; }}
    .callout {{
      margin-top: 18px;
      padding: 16px;
      border-left: 6px solid var(--red);
      background: rgba(255,255,255,.88);
      color: #38464a;
      line-height: 1.72;
    }}
    [hidden] {{ display: none !important; }}
    @media (max-width: 900px) {{
      header, .problem-grid {{ grid-template-columns: 1fr; }}
      .spatial-3d.direct-3d {{
        width: auto;
        max-width: 100%;
        margin: 20px 0 22px;
        grid-template-columns: 1fr;
      }}
      .three-copy {{ border-right: 0; border-bottom: 1px solid rgba(255,255,255,.16); }}
      .three-scene {{ height: 58vh; min-height: 390px; max-width: 100%; overflow: hidden; }}
      .three-canvas {{ min-height: 0; }}
      .three-overlay {{ position: static; margin: 12px; }}
      .three-status {{ position: static; margin: 12px; }}
      .formula-lab {{ grid-template-columns: 1fr; }}
      .cable-animation {{ grid-row: auto; }}
      .visual-storyboard {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .process-rail {{ grid-template-columns: 1fr; overflow-x: visible; }}
      .algorithm-row {{ grid-template-columns: 1fr; }}
      .figure-wall .figure-card:first-child {{ grid-column: auto; }}
      .figure-card img {{ height: 320px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div class="eyebrow">Submarine Cable Tension Analysis / Classroom Reproduction Board</div>
      <h1>海底缆线张力论文复现对比看板</h1>
      <p class="lead">按“工程问题 → 物理假设 → 公式推导 → 数值算法 → 复现证据 → 工程结论”的顺序讲清楚：模型怎么算、当前代码算到了哪一步、算法输出是什么、论文基准怎样在测试集对比。</p>
    </div>
    <aside class="briefing" aria-label="reproduction summary">
      <div class="hero-schematic" aria-label="海底缆线敷设剖面示意">
        <svg viewBox="0 0 720 420" role="img" aria-label="敷缆船、缆线、海流、TDP 与顶端张力示意图">
          <rect x="0" y="0" width="720" height="420" fill="#dcebed"/>
          <path d="M0 274 C130 252 260 280 390 256 C510 234 610 260 720 242 L720 420 L0 420 Z" fill="#ccd5cd"/>
          <path d="M0 316 C135 296 272 320 420 300 C544 282 634 302 720 288 L720 420 L0 420 Z" fill="#bfc8bc"/>
          <rect x="76" y="70" width="170" height="26" fill="#171d1f"/>
          <path d="M104 96 L224 96 L198 132 L82 132 Z" fill="#1d6675"/>
          <line x1="174" y1="132" x2="208" y2="178" stroke="#b44332" stroke-width="5"/>
          <path d="M208 178 C282 216 312 260 342 300 C372 340 436 352 512 318" fill="none" stroke="#b44332" stroke-width="7"/>
          <circle cx="512" cy="318" r="10" fill="#171d1f"/>
          <line x1="174" y1="132" x2="174" y2="54" stroke="#171d1f" stroke-width="3"/>
          <polygon points="174,54 166,70 182,70" fill="#171d1f"/>
          <text x="186" y="58">T_top</text>
          <text x="520" y="314">TDP</text>
          <g stroke="#26755a" stroke-width="4">
            <line x1="424" y1="104" x2="544" y2="104"/><polygon points="544,104 530,96 530,112" fill="#26755a"/>
            <line x1="462" y1="142" x2="610" y2="142"/><polygon points="610,142 596,134 596,150" fill="#26755a"/>
            <line x1="388" y1="180" x2="520" y2="180"/><polygon points="520,180 506,172 506,188" fill="#26755a"/>
          </g>
          <text x="430" y="92">海流剖面</text>
          <text x="88" y="58">敷缆船</text>
          <text x="272" y="368">缆线位形 + 张力分布</text>
        </svg>
      </div>
      <div class="metric"><strong>{case_count}</strong><span>静态/参数扫描工况，保留原 CSV 与 profile 输出</span></div>
      <div class="metric"><strong>{dynamic_count}</strong><span>时间历程工况，由 LA 多单元角运动模型生成</span></div>
      <div class="metric"><strong>测试集</strong><span>论文基准只在测试集对比，不进入生产求解器</span></div>
      <div class="metric"><strong>分层模型</strong><span>500kV 走三维准静态，LA 时程走多单元角运动模型</span></div>
    </aside>
  </header>
  <nav>
    <a href="#problem">工程问题</a>
    <a href="#assumptions">物理假设</a>
    <a href="#derivation">公式推导</a>
    <a href="#algorithm">数值算法</a>
    <a href="#evidence">复现证据</a>
    <a href="#conclusion">工程结论</a>
    <a href="inputs/cases.csv">静态输入</a>
    <a href="inputs/time_history_cases.csv">动态输入</a>
  </nav>
  <main>
    <div class="section-label" id="problem">01 / 工程问题</div>
    <section class="problem-grid">
      <article class="problem-panel">
        <strong>要回答的问题</strong>
        <p>敷缆船运动、放缆速度、海流剖面和 TDP 预张力共同改变缆线空间位形与顶端张力。工程上关心顶端张力是否超限、TDP 是否偏移、动态加减速是否产生张力峰谷。</p>
      </article>
      <article class="problem-panel">
        <strong>这个看板的读法</strong>
        <p>先看物理假设和公式来源，再看当前仓库实现的数值层级，最后用表格、SVG、源码审计检查复现可信度。页面只展示算法输出，论文基准只在测试集对比。</p>
      </article>
    </section>
    <section class="visual-storyboard" aria-label="展示讲解路线">
      <div><strong>01</strong><span>工程问题</span></div>
      <div><strong>02</strong><span>物理假设</span></div>
      <div><strong>03</strong><span>公式推导</span></div>
      <div><strong>04</strong><span>数值算法</span></div>
      <div><strong>05</strong><span>复现证据</span></div>
      <div><strong>06</strong><span>工程结论</span></div>
    </section>

    <div class="section-label" id="assumptions">02 / 物理假设</div>
    <section class="assumption-grid">
      {assumption_cards}
    </section>

    <div class="section-label" id="derivation">03 / 公式推导</div>
    {spatial_3d}
    {formula_lab}
    <section class="formula-grid">
      {derivation_cards}
    </section>

    <div class="section-label" id="algorithm">04 / 数值算法 / 计算流程</div>
    <section class="algorithm-panel process-rail">
      <h2>从论文方程到当前程序的计算流程</h2>
      {algorithm_rows}
    </section>

    <div class="section-label" id="evidence">05 / 复现证据 / 结果对比</div>
    <section>
      <h2>可信度分级</h2>
      <div class="evidence-grid">
        <article class="evidence-card">
          <span class="badge badge-l0">L0 论文表格录入校验</span>
          <p>论文表格值只能作为测试基准或人工录入校验，不能放进生产求解器，也不能在看板里伪造成 0 误差对比。</p>
        </article>
        <article class="evidence-card">
          <span class="badge badge-l1">L1 简化模型/校准曲线</span>
          <p>使用简化关系、插值或平滑 profile 生成可视化趋势。当前主要用于 LA/HA 静态剖面展示。</p>
        </article>
        <article class="evidence-card">
          <span class="badge badge-l1">算法近似复现</span>
          <p>Chapter 4 表 4-3/4-4/4-5 采用三维准静态路径；LA 表 4-1 时程采用多单元角状态有限差分和张力递推。论文表只用于误差对照。</p>
        </article>
      </div>
      <div class="evidence-toolbar" aria-label="evidence filters">
        <button class="is-active" data-filter="all" onclick="filterEvidence('all')">全部证据</button>
        <button data-filter="l0" onclick="filterEvidence('l0')">只看 L0</button>
        <button data-filter="l1" onclick="filterEvidence('l1')">只看算法近似</button>
      </div>
      <h2>源码审计</h2>
      <div class="evidence-grid">
        {source_cards}
      </div>
    </section>

    <div class="section-label">误差验证</div>
    {validation_sections}

    <div class="section-label">结果图</div>
    <section class="figures figure-wall">
      {figure_cards}
    </section>

    <div class="section-label" id="tables">算法输出表</div>
    {table_sections}

    <div class="section-label" id="conclusion">06 / 工程结论</div>
    <section class="conclusion-panel">
      <h2>适合汇报时怎么说</h2>
      <p>当前仓库已经把生产求解和论文基准分开：`src/` 只生成算法输出，论文表格值放在测试集中计算误差。500kV 表 4-3/4-4/4-5 由三维准静态平衡路径输出；LA 表 4-1 时程由多单元倾角/方位角有限差分、张力递推和局部切向加速度 Act 输出。当前动态部分不能称为完整 3.5.5 实现，尚未实现论文 3.5.5 的 N_i/B_i 收敛迭代。若要继续缩小动态差异，需要补充论文边界条件、离散细节、输入参数或实验数据，而不是加入修正系数。</p>
      <div class="callout">
        重新生成顺序保持不变：先运行 <code>scripts/reproduce_paper.py</code> 写出 CSV/SVG，再运行 <code>scripts/build_dashboard.py</code> 刷新本地 HTML。已有 <code>figures/*.svg</code>、<code>tables/*.csv</code>、<code>inputs/*.csv</code>、<code>INPUT_OUTPUT.md</code> 路径保持向后兼容。
      </div>
    </section>
  </main>
  <script>
    function filterEvidence(level) {{
      document.querySelectorAll('.evidence-item').forEach(function (item) {{
        item.hidden = level !== 'all' && item.dataset.evidence !== level;
      }});
      document.querySelectorAll('.evidence-toolbar button').forEach(function (button) {{
        button.classList.toggle('is-active', button.dataset.filter === level);
      }});
    }}
  </script>
</body>
</html>
"""


def _pretty_column(column: str) -> str:
    labels = {
        "initial_tension_n": "初始张力 N",
        "extreme_tension_n": "峰/谷张力 N",
        "steady_tension_n": "稳态张力 N",
        "top_tension_n": "顶端张力 N",
        "tdp_x_m": "TDP X m",
        "tdp_y_m": "TDP Y m",
    }
    return labels.get(column, column)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _count_case_rows(path: Path) -> int:
    if not path.exists():
        return 0
    return len(_read_csv(path))

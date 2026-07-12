import { useEffect, useMemo, useState } from "react";
import { FileText, Table2 } from "lucide-react";
import { buildFileUrl } from "./api";
import { DynamicFrameViewer } from "./DynamicFrameViewer";
import { formatKiloNewton, formatMeters, formatNewton, formatNumber } from "./format";
import type { DynamicFrame, DynamicFramePoint, MotionSegmentInput, RunTimeHistoryResponse, SpeedSegmentInput, TimeHistoryPlotPoint } from "./types";

export function SimulationResultView({ apiBase, result }: { apiBase: string; result: RunTimeHistoryResponse }) {
  const frames = useMemo(() => result.plot_data.frames?.items ?? [], [result]);
  const [currentFrameIndex, setCurrentFrameIndex] = useState(0);
  const lastPoint = result.plot_data.time_history.points[result.plot_data.time_history.points.length - 1];
  const activeFrameIndex = Math.min(Math.max(currentFrameIndex, 0), Math.max(frames.length - 1, 0));
  const activeFrame = frames[activeFrameIndex];
  const activeTimeS = activeFrame?.time_s ?? lastPoint?.time_s ?? 0;
  const payoutInitial = result.summary.payout_initial_speed_mps ?? result.summary.initial_speed_mps;
  const payoutFinal = result.summary.payout_final_speed_mps ?? result.summary.final_speed_mps;
  const currentVesselSpeed = motionSpeedAtTime(
    result.summary.vessel_motion_segments,
    result.summary.initial_speed_mps,
    result.summary.final_speed_mps,
    result.summary.duration_s,
    activeTimeS,
  );
  const currentPayoutSpeed = scalarSpeedAtTime(
    result.summary.payout_speed_segments,
    payoutInitial,
    payoutFinal,
    result.summary.duration_s,
    activeTimeS,
  );
  const currentPloughSpeed = result.summary.plough_motion_segments?.length
    ? motionSpeedAtTime(
        result.summary.plough_motion_segments,
        result.summary.plough_motion_segments[0].start_speed_mps,
        result.summary.plough_motion_segments[result.summary.plough_motion_segments.length - 1].end_speed_mps,
        result.summary.duration_s,
        activeTimeS,
      )
    : result.summary.plough_speed_mps;
  const extremeLabel =
    result.summary.speed_change === "accel"
      ? "最低顶张力"
      : result.summary.speed_change === "decel"
        ? "最高顶张力"
        : "顶张力最值";

  useEffect(() => {
    setCurrentFrameIndex(0);
  }, [result]);

  return (
    <>
      <section className="result-block simulation-viewer" aria-label="dynamic frames output">
        <div className="block-heading stage-block-heading">
          <h3>三维仿真运动</h3>
        </div>
        <DynamicFrameViewer
          currentFrame={activeFrameIndex}
          frames={result.plot_data.frames}
          onCurrentFrameChange={setCurrentFrameIndex}
          summary={result.summary}
        />
      </section>
      <section className="tension-analysis" aria-label="缆线张力分析">
        <div className="analysis-tabs" aria-label="张力分析视图">
          <button className="active" type="button">张力分布</button>
        </div>
        <div className="tension-layout">
          <div className="tension-card tension-chart-card">
            <h3>缆线张力分布</h3>
            <span className="tension-frame-label">当前帧 {formatNumber(activeTimeS, 1)} s</span>
            <CableTensionDistribution frame={activeFrame} />
          </div>
          <div className="tension-card">
            <h3>关键参数</h3>
            <ResultRow label="当前帧" value={`${formatNumber(activeTimeS, 1)} s`} />
            <ResultRow
              label="水流"
              value={`${formatNumber(result.summary.current_speed_mps)} m/s / ${formatNumber(result.summary.current_direction_deg, 0)} deg`}
            />
            <ResultRow label="当前船速" value={`${formatNumber(currentVesselSpeed)} m/s`} />
            <ResultRow label="当前放缆" value={`${formatNumber(currentPayoutSpeed)} m/s`} />
            <ResultRow
              label="当前犁速"
              value={currentPloughSpeed === null || currentPloughSpeed === undefined ? "—" : `${formatNumber(currentPloughSpeed)} m/s`}
            />
            <ResultRow label="弯曲限值" value={formatMeters(result.summary.minimum_bend_radius_limit_m)} />
            <ResultRow label="边界处理" value={dynamicBoundaryLabel(result.summary.length_boundary_source)} />
          </div>
          <div className="tension-card tension-stat-card">
            <h3>张力统计</h3>
            <strong>{formatKiloNewton(result.summary.steady_tension_n)}</strong>
            <span>平均张力</span>
            <ResultRow label="初始顶张力" value={formatNewton(result.summary.initial_tension_n)} />
            <ResultRow label={extremeLabel} value={formatNewton(result.summary.extreme_tension_n)} />
            <ResultRow label="犁入口张力" value={formatKiloNewton(result.summary.plough_inlet_tension_final_n)} />
            <ResultRow label="最小弯曲半径" value={formatMeters(result.summary.minimum_bend_radius_min_m)} />
            <ResultRow label="弯曲半径裕度" value={formatBendMargin(result.summary.minimum_bend_radius_margin_m)} />
            <ResultRow label="弯曲状态" value={bendStatusLabel(result.summary.minimum_bend_radius_status)} />
            <ResultRow label="张力字段" value={dynamicTensionLabel(result.summary.evidence_level)} />
            <ResultRow label="求解器" value={dynamicSolverLabel(result.summary.evidence_level)} />
            <ResultRow label="犁入口角" value={lastPoint?.plough_entry_angle_deg === undefined ? "—" : `${formatNumber(lastPoint.plough_entry_angle_deg, 1)} deg`} />
          </div>
          <div className="tension-card risk-card">
            <h3>风险与可信度</h3>
            <ResultRow label="边界闭合" value={ploughTensionStatusLabel(result.summary.plough_tension_status)} />
            <ResultRow label="犁端边界张力" value={formatNewton(result.summary.plough_boundary_tension_final_n)} />
            <ResultRow label="相邻段张力" value={formatNewton(result.summary.plough_adjacent_segment_tension_final_n)} />
            <ResultRow label="Rmin 原始值" value={formatMeters(result.summary.minimum_bend_radius_raw_m)} />
            <ResultRow label="Rmin 过滤值" value={formatMeters(result.summary.minimum_bend_radius_min_m)} />
            <ResultRow label="Rmin 原始位置" value={bendLocationLabel(
              result.summary.minimum_bend_radius_raw_time_s,
              result.summary.minimum_bend_radius_raw_node_index,
              result.summary.minimum_bend_radius_raw_near_seabed,
            )} />
            <ResultRow label="Rmin 过滤位置" value={bendLocationLabel(
              result.summary.minimum_bend_radius_time_s,
              result.summary.minimum_bend_radius_node_index,
              result.summary.minimum_bend_radius_near_seabed,
            )} />
            <ResultRow label="内部步长" value={timeStepLabel(result.summary.integration_time_step_min_s, result.summary.integration_time_step_max_s)} />
            <ResultRow label="空间步长" value={spatialStepLabel(result.summary.spatial_step_min_m, result.summary.spatial_step_mean_m)} />
            <ResultRow label="轴向迭代" value={iterationRangeLabel(
              result.summary.xpbd_iterations_per_step_min,
              result.summary.xpbd_iterations_per_step_max ?? result.summary.xpbd_iterations_per_step,
              result.summary.xpbd_iteration_limit_per_solve,
            )} />
            <ResultRow label="轴向残差" value={residualLabel(result.summary.axial_constraint_residual_max_m)} />
          </div>
        </div>
        <TimeHistoryTrendPanel activeTimeS={activeTimeS} points={result.plot_data.time_history.points} />
        <div className="file-row">
          <a href={buildFileUrl(result.artifacts.time_summary_csv, apiBase)}>
            <FileText aria-hidden="true" />
            时程汇总 CSV
          </a>
          <a href={buildFileUrl(result.artifacts.time_history_csv, apiBase)}>
            <Table2 aria-hidden="true" />
            时程 CSV
          </a>
          <a href={buildFileUrl(result.artifacts.time_history_svg, apiBase)}>
            <FileText aria-hidden="true" />
            时程图 SVG
          </a>
        </div>
      </section>
    </>
  );
}

function TimeHistoryTrendPanel({ activeTimeS, points }: { activeTimeS: number; points: TimeHistoryPlotPoint[] }) {
  return (
    <section className="time-history-panel" aria-label="动态时程趋势">
      <div className="time-history-heading">
        <div>
          <h3>动态时程趋势</h3>
          <span>当前游标 {formatNumber(activeTimeS, 1)} s</span>
        </div>
      </div>
      <div className="trend-grid">
        <TrendChart
          activeTimeS={activeTimeS}
          formatValue={(value) => `${formatNumber(value, 2)} kN`}
          label="顶张力"
          points={points}
          unit="kN"
          value={(point) => point.top_tension_n / 1000}
        />
        <TrendChart
          activeTimeS={activeTimeS}
          formatValue={(value) => `${formatNumber(value, 2)} kN`}
          label="犁入口张力"
          points={points}
          unit="kN"
          value={(point) => point.plough_inlet_tension_n === undefined ? null : point.plough_inlet_tension_n / 1000}
        />
        <TrendChart
          activeTimeS={activeTimeS}
          formatValue={(value) => formatMeters(value)}
          label="悬垂长度"
          points={points}
          unit="m"
          value={(point) => point.suspended_length_m ?? null}
        />
      </div>
    </section>
  );
}

function TrendChart({
  activeTimeS,
  formatValue,
  label,
  points,
  unit,
  value,
}: {
  activeTimeS: number;
  formatValue: (value: number) => string;
  label: string;
  points: TimeHistoryPlotPoint[];
  unit: string;
  value: (point: TimeHistoryPlotPoint) => number | null;
}) {
  const series = points
    .map((point) => ({ time_s: point.time_s, value: value(point) }))
    .filter((point): point is { time_s: number; value: number } => point.value !== null && Number.isFinite(point.value));

  if (series.length < 2) {
    return (
      <div className="trend-card" aria-label={`${label}趋势`}>
        <div className="trend-card-heading">
          <h4>{label}</h4>
          <strong>—</strong>
        </div>
        <div className="empty-state compact">暂无可绘制时程。</div>
      </div>
    );
  }

  const width = 420;
  const height = 190;
  const margin = { top: 18, right: 20, bottom: 36, left: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxTime = Math.max(...series.map((point) => point.time_s), 1);
  const minValue = Math.min(...series.map((point) => point.value));
  const maxValue = Math.max(...series.map((point) => point.value));
  const padding = Math.max((maxValue - minValue) * 0.08, Math.abs(maxValue || minValue) * 0.02, 0.001);
  const yMin = minValue - padding;
  const yMax = maxValue + padding;
  const valueSpan = Math.max(yMax - yMin, 1.0e-9);
  const mapX = (timeS: number) => margin.left + (Math.max(0, Math.min(timeS, maxTime)) / maxTime) * plotWidth;
  const mapY = (nextValue: number) => margin.top + ((yMax - nextValue) / valueSpan) * plotHeight;
  const path = series
    .map((point, index) => `${index === 0 ? "M" : "L"} ${mapX(point.time_s).toFixed(1)} ${mapY(point.value).toFixed(1)}`)
    .join(" ");
  const activePoint = interpolatedTrendPoint(series, activeTimeS);
  const activeX = mapX(activePoint.time_s);

  return (
    <div className="trend-card" aria-label={`${label}趋势`}>
      <div className="trend-card-heading">
        <h4>{label}</h4>
        <strong>{formatValue(activePoint.value)}</strong>
      </div>
      <svg className="time-history-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}时程图`}>
        <rect className="chart-background" x="0" y="0" width={width} height={height} />
        {[0, 0.5, 1].map((ratio) => {
          const y = margin.top + ratio * plotHeight;
          const tickValue = yMax - ratio * valueSpan;
          return (
            <g className="chart-gridline" key={ratio}>
              <line x1={margin.left} x2={width - margin.right} y1={y} y2={y} />
              <text x={margin.left - 8} y={y + 4}>{formatNumber(tickValue, 2)}</text>
            </g>
          );
        })}
        {[0, 0.5, 1].map((ratio) => {
          const x = margin.left + ratio * plotWidth;
          return (
            <g className="chart-tick" key={ratio}>
              <line x1={x} x2={x} y1={height - margin.bottom} y2={height - margin.bottom + 5} />
              <text x={x} y={height - 12}>{formatNumber(maxTime * ratio, 0)}</text>
            </g>
          );
        })}
        <line className="chart-axis" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
        <line className="chart-axis" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
        <path className="time-history-line" d={path} />
        <line className="time-cursor-line" x1={activeX} x2={activeX} y1={margin.top} y2={height - margin.bottom} />
        <circle className="time-cursor-point" cx={mapX(activePoint.time_s)} cy={mapY(activePoint.value)} r="5" />
        <text className="chart-axis-label" x={width / 2} y={height - 2}>时间 (s)</text>
        <text className="chart-axis-label y-label" transform={`translate(14 ${height / 2}) rotate(-90)`}>{unit}</text>
      </svg>
    </div>
  );
}

function interpolatedTrendPoint(series: { time_s: number; value: number }[], activeTimeS: number): { time_s: number; value: number } {
  if (activeTimeS <= series[0].time_s) {
    return series[0];
  }
  for (let index = 1; index < series.length; index += 1) {
    const next = series[index];
    if (activeTimeS <= next.time_s) {
      const previous = series[index - 1];
      const span = Math.max(next.time_s - previous.time_s, 1.0e-9);
      const ratio = Math.max(0, Math.min((activeTimeS - previous.time_s) / span, 1));
      return {
        time_s: previous.time_s + ratio * span,
        value: previous.value + (next.value - previous.value) * ratio,
      };
    }
  }
  return series[series.length - 1];
}

function speedAtTime(initialSpeed: number, finalSpeed: number, durationS: number, timeS: number): number {
  if (timeS >= durationS) {
    return finalSpeed;
  }
  const fraction = Math.max(0, Math.min(1, timeS / Math.max(durationS, 1.0e-12)));
  return initialSpeed + (finalSpeed - initialSpeed) * fraction;
}

function motionSpeedAtTime(
  segments: MotionSegmentInput[] | undefined,
  initialSpeed: number,
  finalSpeed: number,
  durationS: number,
  timeS: number,
): number {
  return scalarSpeedAtTime(segments, initialSpeed, finalSpeed, durationS, timeS);
}

function scalarSpeedAtTime(
  segments: SpeedSegmentInput[] | MotionSegmentInput[] | undefined,
  initialSpeed: number,
  finalSpeed: number,
  durationS: number,
  timeS: number,
): number {
  if (!segments || segments.length === 0) {
    return speedAtTime(initialSpeed, finalSpeed, durationS, timeS);
  }
  let remaining = Math.max(0, timeS);
  let lastSegment = segments[segments.length - 1];
  for (const segment of segments) {
    const duration = Math.max(segment.duration_s, 1.0e-9);
    if (remaining <= duration) {
      const fraction = Math.max(0, Math.min(1, remaining / duration));
      return segment.start_speed_mps + (segment.end_speed_mps - segment.start_speed_mps) * fraction;
    }
    remaining -= duration;
    lastSegment = segment;
  }
  return lastSegment?.end_speed_mps ?? finalSpeed;
}

function CableTensionDistribution({ frame }: { frame?: DynamicFrame }) {
  const points = frame?.points ?? [];
  if (points.length < 2) {
    return <div className="empty-state compact">暂无逐段张力帧。</div>;
  }

  const arc = cumulativeArc(points);
  const tensions = points.map((point) => point.tension_n / 1000);
  const minTension = Math.min(...tensions);
  const maxTension = Math.max(...tensions);
  const maxArc = Math.max(arc[arc.length - 1] ?? 1, 1);
  const span = Math.max(maxTension - minTension, 1.0e-6);
  const width = 640;
  const height = 180;
  const margin = { top: 18, right: 20, bottom: 34, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const mapX = (value: number) => margin.left + (value / maxArc) * plotWidth;
  const mapY = (value: number) => margin.top + ((maxTension - value) / span) * plotHeight;
  const polyline = points
    .map((point, index) => `${mapX(arc[index] ?? 0).toFixed(1)},${mapY(point.tension_n / 1000).toFixed(1)}`)
    .join(" ");

  return (
    <svg className="tension-distribution-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="缆线张力分布图">
      <rect className="chart-background" x="0" y="0" width={width} height={height} />
      {[0, 0.5, 1].map((ratio) => {
        const y = margin.top + ratio * plotHeight;
        const value = maxTension - ratio * span;
        return (
          <g className="chart-gridline" key={ratio}>
            <line x1={margin.left} x2={width - margin.right} y1={y} y2={y} />
            <text x={margin.left - 8} y={y + 4}>{formatNumber(value, 2)}</text>
          </g>
        );
      })}
      {[0, 0.5, 1].map((ratio) => {
        const x = margin.left + ratio * plotWidth;
        return (
          <g className="chart-tick" key={ratio}>
            <line x1={x} x2={x} y1={height - margin.bottom} y2={height - margin.bottom + 5} />
            <text x={x} y={height - 12}>{formatNumber(maxArc * ratio, 0)}</text>
          </g>
        );
      })}
      <line className="chart-axis" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
      <line className="chart-axis" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
      <polyline className="tension-distribution-line" points={polyline} />
      {points.map((point, index) => {
        const tension = point.tension_n / 1000;
        return (
          <circle
            cx={mapX(arc[index] ?? 0)}
            cy={mapY(tension)}
            fill={tensionColorHex(tension, minTension, maxTension)}
            key={point.index}
            r="4"
          />
        );
      })}
      <text className="chart-axis-label" x={width / 2} y={height - 2}>弧长 (m)</text>
      <text className="chart-axis-label y-label" transform={`translate(14 ${height / 2}) rotate(-90)`}>张力 (kN)</text>
    </svg>
  );
}

function cumulativeArc(points: DynamicFramePoint[]): number[] {
  const arc = [0];
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const point = points[index];
    arc.push(
      arc[index - 1] +
        Math.hypot(point.x_m - previous.x_m, point.y_m - previous.y_m, point.z_m - previous.z_m),
    );
  }
  return arc;
}

function tensionColorHex(value: number, min: number, max: number): string {
  const span = Math.max(max - min, 1.0e-6);
  const ratio = Math.min(1, Math.max(0, (value - min) / span));
  if (ratio < 0.5) {
    return "#0d7ec6";
  }
  if (ratio < 0.78) {
    return "#16b86a";
  }
  if (ratio < 0.92) {
    return "#f0bd2f";
  }
  return "#f0442e";
}

function ResultRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatBendMargin(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${value >= 0 ? "+" : ""}${formatMeters(value)}`;
}

function bendStatusLabel(status: string | undefined): string {
  if (status === "ok") {
    return "当前口径未低于限值";
  }
  if (status === "below_limit") {
    return "低于限值";
  }
  if (status === "not_available") {
    return "无计算值";
  }
  return "未配置限值";
}

function ploughTensionStatusLabel(status: string | null | undefined): string {
  if (status === "carried") {
    return "边界张力已传入相邻段";
  }
  if (status === "slack_or_unclosed") {
    return "松弛或未闭合";
  }
  return "无闭合状态";
}

function bendLocationLabel(timeS: number | null | undefined, nodeIndex: number | null | undefined, nearSeabed: boolean | null | undefined): string {
  if (timeS === null || timeS === undefined || nodeIndex === null || nodeIndex === undefined) {
    return "—";
  }
  return `${formatNumber(timeS, 1)} s / 节点 ${nodeIndex}${nearSeabed ? " / 近海床" : ""}`;
}

function timeStepLabel(minS: number | null | undefined, maxS: number | null | undefined): string {
  if (minS === null || minS === undefined || maxS === null || maxS === undefined) {
    return "—";
  }
  return `${formatNumber(minS, 3)}-${formatNumber(maxS, 3)} s`;
}

function spatialStepLabel(minM: number | null | undefined, meanM: number | null | undefined): string {
  if (minM === null || minM === undefined || meanM === null || meanM === undefined) {
    return "—";
  }
  return `min ${formatMeters(minM)} / mean ${formatMeters(meanM)}`;
}

function iterationRangeLabel(
  minimum: number | null | undefined,
  maximum: number | null | undefined,
  limit: number | null | undefined,
): string {
  if (maximum === null || maximum === undefined) {
    return "—";
  }
  const range = minimum === null || minimum === undefined || minimum === maximum
    ? formatNumber(maximum, 0)
    : `${formatNumber(minimum, 0)}-${formatNumber(maximum, 0)}`;
  const limitLabel = limit === null || limit === undefined ? "" : ` / 单次上限 ${formatNumber(limit, 0)}`;
  return `${range} 次/步${limitLabel}`;
}

function residualLabel(residualM: number | null | undefined): string {
  return residualM === null || residualM === undefined || !Number.isFinite(residualM)
    ? "—"
    : `${residualM.toExponential(2)} m`;
}

function dynamicSolverLabel(evidenceLevel: string): string {
  return evidenceLevel.includes("XPBD") ? "节点坐标动态求解" : "动态时程求解";
}

function dynamicTensionLabel(evidenceLevel: string): string {
  return evidenceLevel.includes("segment tension output") ? "每段张力随时间输出" : "顶张力时程输出";
}

function dynamicBoundaryLabel(source: string): string {
  if (source === "known_plough_trajectory") {
    return "已知埋设犁轨迹";
  }
  return source;
}

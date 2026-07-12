import { Square } from "lucide-react";
import { DynamicFrameViewer } from "./DynamicFrameViewer";
import { formatKiloNewton, formatNumber } from "./format";
import type { RealtimeFrameResponse, RunTimeHistorySummary } from "./types";

type MotionSummary = Pick<
  RunTimeHistorySummary,
  "initial_speed_mps" | "final_speed_mps" | "duration_s" | "total_duration_s" | "current_speed_mps" | "current_direction_deg"
>;

export function RealtimeResultView({
  history,
  active,
  onStop,
  stopping,
  summary,
}: {
  history: RealtimeFrameResponse[];
  active: boolean;
  onStop: () => void;
  stopping: boolean;
  summary: MotionSummary;
}) {
  const latest = history[history.length - 1];
  if (!latest) {
    return null;
  }
  return (
    <section className="realtime-result" aria-label="准实时计算结果">
      <div className="realtime-status-bar">
        <div>
          <span className="live-indicator" aria-hidden="true" />
          <strong>5 s 准实时会话</strong>
          <span>帧 {latest.sequence}</span>
          <span>数据时刻 {formatNumber(latest.time_s, 1)} s</span>
          <span>单帧耗时 {formatNumber(latest.compute_wall_s * 1000, 0)} ms</span>
          <span>实时倍率 {latest.realtime_factor === null ? "初始化" : formatNumber(latest.realtime_factor, 2)}</span>
        </div>
        <button className="stop-realtime" disabled={stopping || !active} onClick={onStop} type="button">
          <Square aria-hidden="true" />
          {stopping ? "停止中" : active ? "停止会话" : "会话已停止"}
        </button>
      </div>
      <div className="realtime-grid">
        <section className="result-block simulation-viewer realtime-viewer">
          <div className="block-heading stage-block-heading"><h3>最新三维状态</h3></div>
          <DynamicFrameViewer
            currentFrame={history.length - 1}
            frames={{ source: "realtime_session", label: "实时状态序列", items: history.map((item) => item.frame) }}
            summary={summary}
          />
        </section>
        <aside className="realtime-metrics" aria-label="实时张力指标">
          <Metric label="船端张力" value={formatKiloNewton(latest.tensions.top_tension_n)} />
          <Metric label="犁入口张力" value={formatKiloNewton(latest.tensions.plough_inlet_tension_n)} />
          <Metric label="犁端边界张力" value={formatKiloNewton(latest.tensions.plough_boundary_tension_n)} />
          <Metric label="TDP 弧长" value={`${formatNumber(latest.contact.tdp_arc_length_m, 1)} m`} />
          <Metric label="海床接触长度" value={`${formatNumber(latest.contact.seabed_contact_length_m, 1)} m`} />
          <Metric label="轴向约束残差" value={`${formatNumber(latest.integration.axial_constraint_residual_max_m ?? 0, 4)} m`} />
        </aside>
      </div>
      <RealtimeTensionTrend history={history} />
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function RealtimeTensionTrend({ history }: { history: RealtimeFrameResponse[] }) {
  const width = 900;
  const height = 190;
  const pad = 34;
  const values = history.flatMap((item) => [item.tensions.top_tension_n, item.tensions.plough_inlet_tension_n]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const line = (selector: (item: RealtimeFrameResponse) => number) => history.map((item, index) => {
    const x = pad + (index / Math.max(history.length - 1, 1)) * (width - 2 * pad);
    const y = height - pad - ((selector(item) - min) / span) * (height - 2 * pad);
    return `${x},${y}`;
  }).join(" ");
  return (
    <section className="realtime-trend" aria-label="实时张力趋势">
      <div><h3>最近 {history.length} 帧张力趋势</h3><span className="top-line">船端</span><span className="plough-line">犁入口</span></div>
      <svg aria-label="张力随时间变化曲线" role="img" viewBox={`0 0 ${width} ${height}`}>
        <line x1={pad} x2={pad} y1={pad} y2={height - pad} />
        <line x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} />
        <polyline className="trend-top" fill="none" points={line((item) => item.tensions.top_tension_n)} />
        <polyline className="trend-plough" fill="none" points={line((item) => item.tensions.plough_inlet_tension_n)} />
      </svg>
    </section>
  );
}

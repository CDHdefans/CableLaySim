import type { ProfilePlotPoint, RunCaseResponse, TimeHistoryPlotData, TimeHistoryPlotPoint } from "./types";

const CHART_WIDTH = 640;
const CHART_HEIGHT = 390;
const MARGIN = { top: 44, right: 34, bottom: 58, left: 70 };
const PLOT_WIDTH = CHART_WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;

interface PlotPoint {
  x: number;
  y: number;
}

interface ChartSpec {
  title: string;
  xLabel: string;
  yLabel: string;
  points: PlotPoint[];
  yDown?: boolean;
  sourceLabel?: string;
  markerLabel?: string;
}

export function ResultPlots({ result }: { result: RunCaseResponse }) {
  const profile = result.plot_data?.profile ?? [];
  const timeHistory = result.plot_data?.time_history.points ?? [];
  if (profile.length < 2) {
    return null;
  }

  const specs: ChartSpec[] = [
    {
      title: "顶端张力随时间变化",
      xLabel: "时间 t (s)",
      yLabel: "顶端张力 T_top (kN)",
      points: topTensionSeries(timeHistory, result),
      sourceLabel: result.plot_data?.time_history.label,
    },
    {
      title: "落点轨迹 X-Y",
      xLabel: "X 坐标 (m)",
      yLabel: "Y 坐标 (m)",
      points: profile.map((point) => ({ x: point.x_m, y: point.y_m })),
      markerLabel: "TDP",
    },
    {
      title: "张力随水深变化",
      xLabel: "张力 T (kN)",
      yLabel: "水深 z (m)",
      points: profile.map((point) => ({ x: point.tension_n / 1000, y: point.z_m })),
      yDown: true,
    },
    {
      title: "水中位移曲线 Y-Z",
      xLabel: "横向位移 Y (m)",
      yLabel: "水深 z (m)",
      points: profile.map((point) => ({ x: point.y_m, y: point.z_m })),
      yDown: true,
    },
  ];

  return (
    <section className="plot-grid" aria-label="engineering result figures">
      {specs.map((spec) => (
        <ResultChart key={spec.title} spec={spec} />
      ))}
    </section>
  );
}

export function TimeHistoryFigure({ timeHistory }: { timeHistory: TimeHistoryPlotData }) {
  if (timeHistory.points.length < 2) {
    return null;
  }
  return (
    <section className="plot-grid" aria-label="dynamic time-history figure">
      <ResultChart
        spec={{
          title: "动态张力时程",
          xLabel: "时间 t (s)",
          yLabel: "顶端张力 T_top (kN)",
          points: topTensionPoints(timeHistory.points),
          sourceLabel: timeHistory.label,
        }}
      />
    </section>
  );
}

function topTensionSeries(timeHistory: TimeHistoryPlotPoint[], result: RunCaseResponse): PlotPoint[] {
  if (timeHistory.length >= 2) {
    return topTensionPoints(timeHistory);
  }
  return [
    { x: 0, y: result.summary.top_tension_initial_n / 1000 },
    { x: 0.5, y: result.summary.top_tension_min_n / 1000 },
    { x: 1, y: result.summary.top_tension_final_n / 1000 },
  ];
}

function topTensionPoints(timeHistory: TimeHistoryPlotPoint[]): PlotPoint[] {
  return timeHistory.map((point) => ({
    x: point.time_s,
    y: point.top_tension_n / 1000,
  }));
}

function ResultChart({ spec }: { spec: ChartSpec }) {
  const xScale = niceScale(spec.points.map((point) => point.x));
  const yScale = niceScale(spec.points.map((point) => point.y));
  const xDomain = xScale.domain;
  const yDomain = yScale.domain;
  const xTicks = xScale.ticks;
  const yTicks = yScale.ticks;
  const mapX = (value: number) => MARGIN.left + ((value - xDomain[0]) / (xDomain[1] - xDomain[0])) * PLOT_WIDTH;
  const mapY = (value: number) => {
    const ratio = (value - yDomain[0]) / (yDomain[1] - yDomain[0]);
    return spec.yDown ? MARGIN.top + ratio * PLOT_HEIGHT : MARGIN.top + (1 - ratio) * PLOT_HEIGHT;
  };
  const pathData = toPath(spec.points, mapX, mapY);
  const firstPoint = spec.points[0];
  const lastPoint = spec.points[spec.points.length - 1];

  return (
    <article className="result-figure">
      <div className="result-figure-heading">
        <h3>{spec.title}</h3>
        {spec.sourceLabel ? <span>{spec.sourceLabel}</span> : null}
      </div>
      <svg
        aria-label={spec.title}
        className="result-chart"
        role="img"
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      >
        <rect className="chart-background" height={CHART_HEIGHT} width={CHART_WIDTH} x="0" y="0" />
        {xTicks.map((tick) => (
          <g key={`x-${tick}`} className="chart-gridline">
            <line x1={mapX(tick)} x2={mapX(tick)} y1={MARGIN.top} y2={MARGIN.top + PLOT_HEIGHT} />
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y-${tick}`} className="chart-gridline">
            <line x1={MARGIN.left} x2={MARGIN.left + PLOT_WIDTH} y1={mapY(tick)} y2={mapY(tick)} />
          </g>
        ))}
        <line
          className="chart-axis"
          x1={MARGIN.left}
          x2={MARGIN.left}
          y1={MARGIN.top}
          y2={MARGIN.top + PLOT_HEIGHT}
        />
        <line
          className="chart-axis"
          x1={MARGIN.left}
          x2={MARGIN.left + PLOT_WIDTH}
          y1={MARGIN.top + PLOT_HEIGHT}
          y2={MARGIN.top + PLOT_HEIGHT}
        />
        {xTicks.map((tick) => (
          <g key={`x-label-${tick}`} className="chart-tick">
            <line x1={mapX(tick)} x2={mapX(tick)} y1={MARGIN.top + PLOT_HEIGHT} y2={MARGIN.top + PLOT_HEIGHT + 5} />
            <text x={mapX(tick)} y={MARGIN.top + PLOT_HEIGHT + 21}>
              {formatTick(tick)}
            </text>
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y-label-${tick}`} className="chart-tick y-tick">
            <line x1={MARGIN.left - 5} x2={MARGIN.left} y1={mapY(tick)} y2={mapY(tick)} />
            <text x={MARGIN.left - 10} y={mapY(tick) + 4}>
              {formatTick(tick)}
            </text>
          </g>
        ))}
        <text className="chart-axis-label x-axis-label" x={MARGIN.left + PLOT_WIDTH / 2} y={CHART_HEIGHT - 14}>
          {spec.xLabel}
        </text>
        <text
          className="chart-axis-label y-axis-label"
          transform={`translate(20 ${MARGIN.top + PLOT_HEIGHT / 2}) rotate(-90)`}
        >
          {spec.yLabel}
        </text>
        <path className="chart-line" d={pathData} />
        <circle className="chart-marker start" cx={mapX(firstPoint.x)} cy={mapY(firstPoint.y)} r="4" />
        <circle className="chart-marker end" cx={mapX(lastPoint.x)} cy={mapY(lastPoint.y)} r="4.8" />
        {spec.markerLabel ? (
          <text className="chart-point-label" x={mapX(lastPoint.x) - 2} y={mapY(lastPoint.y) - 10}>
            {spec.markerLabel}
          </text>
        ) : null}
      </svg>
    </article>
  );
}

function niceScale(values: number[], tickTarget = 5): { domain: [number, number]; ticks: number[] } {
  const domain = niceDomain(values, tickTarget);
  const tickStep = niceStep((domain[1] - domain[0]) / Math.max(1, tickTarget - 1));
  const ticks = rangeTicks(domain, tickStep);
  return { domain, ticks };
}

function niceDomain(values: number[], tickTarget = 5): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) {
    return [0, 1];
  }
  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (Math.abs(max - min) < 1.0e-9) {
    const step = niceStep(Math.max(Math.abs(max) * 0.02, 1) / Math.max(1, tickTarget - 1));
    return [roundToStep(min - step * 2, step), roundToStep(max + step * 2, step)];
  }
  const step = niceStep((max - min) / Math.max(1, tickTarget - 1));
  const lower = Math.floor(min / step) * step;
  const upper = Math.ceil(max / step) * step;
  return [roundToStep(lower, step), roundToStep(upper, step)];
}

function niceStep(rawStep: number): number {
  if (!Number.isFinite(rawStep) || rawStep <= 0) {
    return 1;
  }
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const fraction = rawStep / power;
  let niceFraction = 10;
  if (fraction <= 1) {
    niceFraction = 1;
  } else if (fraction <= 2) {
    niceFraction = 2;
  } else if (fraction <= 2.5) {
    niceFraction = 2.5;
  } else if (fraction <= 5) {
    niceFraction = 5;
  }
  return niceFraction * power;
}

function rangeTicks(domain: [number, number], step: number): number[] {
  const ticks: number[] = [];
  const start = Math.ceil(domain[0] / step) * step;
  for (let value = start; value <= domain[1] + step * 0.5; value += step) {
    ticks.push(roundToStep(value, step));
  }
  if (ticks.length === 0 || ticks[0] > domain[0]) {
    ticks.unshift(domain[0]);
  }
  if (ticks[ticks.length - 1] < domain[1]) {
    ticks.push(domain[1]);
  }
  return Array.from(new Set(ticks));
}

function roundToStep(value: number, step: number): number {
  const decimals = Math.max(0, -Math.floor(Math.log10(step)) + 2);
  return Number(value.toFixed(decimals));
}

function toPath(points: PlotPoint[], mapX: (value: number) => number, mapY: (value: number) => number): string {
  return points
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
    .map((point, index) => `${index === 0 ? "M" : "L"} ${mapX(point.x).toFixed(2)} ${mapY(point.y).toFixed(2)}`)
    .join(" ");
}

function formatTick(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 100) {
    return value.toFixed(0);
  }
  if (abs >= 10) {
    return value.toFixed(1);
  }
  return value.toFixed(2);
}

import {
  Activity,
  AlertTriangle,
  Cable,
  CheckCircle2,
  MonitorPlay,
  RefreshCcw,
  Server,
  SlidersHorizontal,
} from "lucide-react";
import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { advanceRealtimeSession, ApiError, createRealtimeSession, DEFAULT_API_BASE, deleteRealtimeSession, getHealth, getTimeHistoryCases, runTimeHistory } from "./api";
import { formatNumber } from "./format";
import {
  DEFAULT_DYNAMIC_FORM,
  groupTimeHistoryCases,
  labelForTimeHistoryCase,
  type ConsoleModule,
  type SpeedChange,
} from "./simulationConfig";
import {
  SimulationParameterPanel,
  type DynamicNumberField,
  type DynamicOptionalNumberField,
  type MotionSegmentField,
  type MotionTarget,
  type PayoutSegmentField,
} from "./SimulationParameterPanel";
import { SimulationResultView } from "./SimulationResultView";
import { RealtimeResultView } from "./RealtimeResultView";
import type {
  CreateRealtimeSessionRequest,
  DynamicTimeHistoryForm,
  HealthResponse,
  MotionSegmentInput,
  RunTimeHistoryResponse,
  RealtimeFrameResponse,
  RealtimeSensorPacket,
  SpeedSegmentInput,
  TimeHistoryCase,
  TimeHistoryCaseInputs,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE;
const ROUTE_LONGITUDINAL_TOLERANCE = 1e-9;
const REALTIME_UPDATE_INTERVAL_S = 5;

type MaterialFormFields = Pick<
  DynamicTimeHistoryForm,
  | "diameter_m"
  | "weight_air_n_per_m"
  | "submerged_weight_n_per_m"
  | "tangential_drag_coefficient"
  | "normal_drag_coefficient"
  | "axial_stiffness_n"
  | "min_bending_radius_m"
>;

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [timeHistoryCases, setTimeHistoryCases] = useState<TimeHistoryCase[]>([]);
  const [activeModule, setActiveModule] = useState<ConsoleModule>("parameters");
  const [dynamicForm, setDynamicForm] = useState<DynamicTimeHistoryForm>(DEFAULT_DYNAMIC_FORM);
  const [timeHistoryResult, setTimeHistoryResult] = useState<RunTimeHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMode, setRunMode] = useState<"batch" | "realtime">("batch");
  const [realtimeHistory, setRealtimeHistory] = useState<RealtimeFrameResponse[]>([]);
  const [realtimeSessionId, setRealtimeSessionId] = useState<string | null>(null);
  const [stoppingRealtime, setStoppingRealtime] = useState(false);
  const realtimeTimerRef = useRef<number | null>(null);
  const realtimeGenerationRef = useRef(0);
  const realtimeSessionRef = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [healthPayload, timeHistoryCasePayload] = await Promise.all([
          getHealth(API_BASE),
          getTimeHistoryCases(API_BASE),
        ]);
        if (!alive) {
          return;
        }
        setHealth(healthPayload);
        setTimeHistoryCases(timeHistoryCasePayload);
      } catch (caught) {
        if (alive) {
          setError(messageFrom(caught));
        }
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => () => {
    realtimeGenerationRef.current += 1;
    if (realtimeTimerRef.current !== null) window.clearTimeout(realtimeTimerRef.current);
    if (realtimeSessionRef.current) void deleteRealtimeSession(realtimeSessionRef.current, API_BASE);
  }, []);

  const visibleTimeHistoryCases = useMemo(
    () =>
      timeHistoryCases
        .filter((item) =>
          item.example === true
          && item.inputs.length_boundary_source === "known_plough_trajectory"
          && !item.name.includes("tdp_tension")
        )
        .sort((a, b) => (a.display_order ?? 999) - (b.display_order ?? 999) || a.label.localeCompare(b.label)),
    [timeHistoryCases],
  );
  const groupedTimeHistoryCases = useMemo(
    () => groupTimeHistoryCases(visibleTimeHistoryCases),
    [visibleTimeHistoryCases],
  );

  function updateDynamicText(field: "case_name", value: string) {
    setDynamicForm((current) => ({ ...current, [field]: value }));
  }

  function updateDynamicNumber(field: DynamicNumberField, value: string) {
    setDynamicForm((current) => syncTimeFields({ ...current, [field]: Number(value) }, field));
  }

  function updateDynamicOptionalNumber(field: DynamicOptionalNumberField, value: string) {
    setDynamicForm((current) => ({ ...current, [field]: value === "" ? null : Number(value) }));
  }

  function updateMotionSegment(target: MotionTarget, index: number, field: MotionSegmentField, value: string) {
    setDynamicForm((current) => {
      const numericValue = Number(value);
      const segments = [...(current[target] ?? [])];
      const existing = segments[index];
      if (!existing) {
        return current;
      }
      segments[index] = normalizeMotionSegment({ ...existing, [field]: numericValue });
      if (index === 0 && segments[1] && field === "end_speed_mps") {
        segments[1] = normalizeMotionSegment({ ...segments[1], start_speed_mps: numericValue, end_speed_mps: numericValue });
      }
      if (index === 0 && segments[1] && field === "heading_deg") {
        segments[1] = normalizeMotionSegment({ ...segments[1], heading_deg: numericValue });
      }
      if (index === 0 && segments[1] && field === "end_velocity_x_mps") {
        segments[1] = normalizeMotionSegment({
          ...segments[1],
          start_velocity_x_mps: numericValue,
          end_velocity_x_mps: numericValue,
        });
      }
      if (index === 0 && segments[1] && field === "end_velocity_y_mps") {
        segments[1] = normalizeMotionSegment({
          ...segments[1],
          start_velocity_y_mps: numericValue,
          end_velocity_y_mps: numericValue,
        });
      }
      return syncLegacyMotionFields({ ...current, [target]: segments });
    });
  }

  function updatePayoutSegment(index: number, field: PayoutSegmentField, value: string) {
    setDynamicForm((current) => {
      const segments = [...(current.payout_speed_segments ?? [])];
      const existing = segments[index];
      if (!existing) {
        return current;
      }
      segments[index] = { ...existing, [field]: Number(value) };
      if (index === 0 && segments[1] && field === "end_speed_mps") {
        segments[1] = { ...segments[1], start_speed_mps: Number(value), end_speed_mps: Number(value) };
      }
      return syncLegacyMotionFields({ ...current, payout_speed_segments: segments });
    });
  }

  function updateStageDuration(index: number, value: string) {
    setDynamicForm((current) => {
      const duration = Math.max(Number(value), 0.001);
      return syncLegacyMotionFields({
        ...current,
        vessel_motion_segments: updateSegmentDuration(current.vessel_motion_segments, index, duration),
        plough_motion_segments: updateSegmentDuration(current.plough_motion_segments, index, duration),
        payout_speed_segments: updateSegmentDuration(current.payout_speed_segments, index, duration),
      });
    });
  }

  function fillFromDynamicExample(item: TimeHistoryCase) {
    const motion = motionSegmentsFromInputs(item.inputs);
    const vesselSegments = item.inputs.vessel_motion_segments?.length
      ? normalizeMotionSegments(item.inputs.vessel_motion_segments)
      : motion.vessel;
    const ploughSegments = item.inputs.plough_motion_segments?.length
      ? normalizeMotionSegments(item.inputs.plough_motion_segments)
      : motion.plough;
    setActiveModule("parameters");
    setDynamicForm((current) => ({
      ...item.inputs,
      case_name: item.label,
      output_dir: item.suggested_output_dir,
      points: current.points,
      ...materialFieldsFrom(current),
      payout_initial_speed_mps: item.inputs.payout_initial_speed_mps ?? item.inputs.initial_speed_mps,
      payout_final_speed_mps: item.inputs.payout_final_speed_mps ?? item.inputs.final_speed_mps,
      length_boundary_source: "known_plough_trajectory",
      vessel_initial_x_m: item.inputs.vessel_initial_x_m ?? 0,
      vessel_initial_y_m: item.inputs.vessel_initial_y_m ?? 0,
      vessel_heading_deg: item.inputs.vessel_heading_deg ?? 0,
      plough_initial_x_m: item.inputs.plough_initial_x_m ?? -55,
      plough_initial_y_m: item.inputs.plough_initial_y_m ?? 0,
      plough_initial_z_m: item.inputs.plough_initial_z_m ?? item.inputs.water_depth_m,
      plough_speed_mps: item.inputs.plough_speed_mps ?? item.inputs.initial_speed_mps,
      plough_heading_deg: item.inputs.plough_heading_deg ?? 0,
      vessel_motion_segments: vesselSegments,
      plough_motion_segments: ploughSegments,
      payout_speed_segments: item.inputs.payout_speed_segments?.length ? item.inputs.payout_speed_segments : motion.payout,
    }));
    setTimeHistoryResult(null);
    setError(null);
  }

  function fillMaterialFromDynamicExample(item: TimeHistoryCase) {
    setActiveModule("parameters");
    setDynamicForm((current) => ({
      ...current,
      ...materialFieldsFrom(item.inputs),
    }));
    setTimeHistoryResult(null);
    setError(null);
  }

  async function handleRun(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setRunning(true);
    setError(null);
    setTimeHistoryResult(null);
    try {
      if (runMode === "realtime") {
        await startRealtimeSession();
        return;
      }
      if (realtimeSessionRef.current) await stopRealtimeSession();
      setRealtimeHistory([]);
      const payload = await runTimeHistory(dynamicForm, API_BASE);
      setTimeHistoryResult(payload);
      setActiveModule("simulation");
    } catch (caught) {
      setActiveModule("parameters");
      setError(messageFrom(caught));
    } finally {
      setRunning(false);
    }
  }

  async function startRealtimeSession() {
    realtimeGenerationRef.current += 1;
    const generation = realtimeGenerationRef.current;
    if (realtimeTimerRef.current !== null) window.clearTimeout(realtimeTimerRef.current);
    if (realtimeSessionRef.current) await deleteRealtimeSession(realtimeSessionRef.current, API_BASE);
    const initialPacket = realtimePacket(dynamicForm, 0, 0);
    const request = realtimeSessionRequest(dynamicForm, initialPacket);
    const first = await createRealtimeSession(request, API_BASE);
    setRealtimeSessionId(first.session_id);
    realtimeSessionRef.current = first.session_id;
    setRealtimeHistory([first]);
    setTimeHistoryResult(null);
    setActiveModule("simulation");
    scheduleRealtimeAdvance(
      first.session_id,
      request,
      1,
      generation,
      initialPacket.observed_at_unix_s * 1000,
    );
  }

  function scheduleRealtimeAdvance(
    sessionId: string,
    request: CreateRealtimeSessionRequest,
    sequence: number,
    generation: number,
    startedAtMs: number,
  ) {
    const deadlineMs = startedAtMs + sequence * REALTIME_UPDATE_INTERVAL_S * 1000;
    const delayMs = realtimeScheduleDelayMs(startedAtMs, sequence, Date.now());
    realtimeTimerRef.current = window.setTimeout(async () => {
      if (generation !== realtimeGenerationRef.current) return;
      if (Date.now() - deadlineMs >= REALTIME_UPDATE_INTERVAL_S * 1000) {
        setError("准实时会话已落后一个完整更新周期，已停止以避免输入积压。 ");
        void deleteRealtimeSession(sessionId, API_BASE).catch(() => undefined);
        setRealtimeSessionId(null);
        realtimeSessionRef.current = null;
        return;
      }
      try {
        const next = await advanceRealtimeSession(
          sessionId,
          realtimePacket(request, sequence, sequence * REALTIME_UPDATE_INTERVAL_S),
          API_BASE,
        );
        if (generation !== realtimeGenerationRef.current) return;
        setRealtimeHistory((current) => [...current, next].slice(-60));
        scheduleRealtimeAdvance(sessionId, request, sequence + 1, generation, startedAtMs);
      } catch (caught) {
        if (!isCurrentRealtimeRequest(generation, realtimeGenerationRef.current, sessionId, realtimeSessionRef.current)) {
          void deleteRealtimeSession(sessionId, API_BASE).catch(() => undefined);
          return;
        }
        setError(messageFrom(caught));
        void deleteRealtimeSession(sessionId, API_BASE).catch(() => undefined);
        setRealtimeSessionId(null);
        realtimeSessionRef.current = null;
      }
    }, delayMs);
  }

  async function stopRealtimeSession() {
    realtimeGenerationRef.current += 1;
    setStoppingRealtime(true);
    if (realtimeTimerRef.current !== null) window.clearTimeout(realtimeTimerRef.current);
    realtimeTimerRef.current = null;
    try {
      if (realtimeSessionRef.current) await deleteRealtimeSession(realtimeSessionRef.current, API_BASE);
    } catch (caught) {
      setError(messageFrom(caught));
    } finally {
      setRealtimeSessionId(null);
      realtimeSessionRef.current = null;
      setStoppingRealtime(false);
    }
  }

  const latestRealtime = realtimeHistory[realtimeHistory.length - 1];
  const activeTitle = timeHistoryResult
    ? labelForTimeHistoryCase(timeHistoryResult.case_name, timeHistoryCases)
    : dynamicForm.case_name;
  const outputTitle = latestRealtime ? `${dynamicForm.case_name} · 实时帧 ${latestRealtime.sequence}` : timeHistoryResult
    ? labelForTimeHistoryCase(timeHistoryResult.case_name, timeHistoryCases)
    : "等待计算";
  const vesselCommandSpeed = motionSegmentStartSpeed(dynamicForm.vessel_motion_segments?.[0]) ?? dynamicForm.initial_speed_mps;
  const ploughCommandSpeed = motionSegmentStartSpeed(dynamicForm.plough_motion_segments?.[0]) ?? dynamicForm.plough_speed_mps ?? 0;
  const ploughExitDisplay = ploughExitMaterialSpeedDisplay(dynamicForm, timeHistoryResult?.summary);

  return (
    <main className="shell console-shell">
      <header className="topbar">
        <div className="brand">
          <Cable aria-hidden="true" />
          <div>
            <h1>CableLaySim</h1>
            <p>铺缆船仿真分析系统</p>
          </div>
        </div>
        <div className="status-strip" aria-label="backend status">
          <span className={health ? "status ok" : "status warn"}>
            {health ? <CheckCircle2 aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
            {health ? "后端在线" : loading ? "连接中" : "后端未连接"}
          </span>
          <span className="status">
            <Server aria-hidden="true" />
            {API_BASE}
          </span>
          <span className="status">
            <RefreshCcw aria-hidden="true" />
            {activeTitle}
          </span>
        </div>
      </header>

      {error ? (
        <section className="error-band" role="alert">
          <AlertTriangle aria-hidden="true" />
          <span>{error}</span>
        </section>
      ) : null}

      <section className="workspace console-workspace">
        <aside className="parameter-sidebar" aria-label="仿真控制台">
          <nav className="console-nav" aria-label="主模块">
            <button
              aria-pressed={activeModule === "parameters"}
              className={activeModule === "parameters" ? "active" : ""}
              onClick={() => setActiveModule("parameters")}
              type="button"
            >
              <SlidersHorizontal aria-hidden="true" />
              仿真参数设置
            </button>
            <button
              aria-pressed={activeModule === "simulation"}
              className={activeModule === "simulation" ? "active" : ""}
              disabled={!timeHistoryResult && !latestRealtime}
              onClick={() => setActiveModule("simulation")}
              type="button"
            >
              <MonitorPlay aria-hidden="true" />
              仿真视图
            </button>
            <button
              aria-pressed={activeModule === "tension"}
              className={activeModule === "tension" ? "active" : ""}
              disabled={!timeHistoryResult && !latestRealtime}
              onClick={() => setActiveModule("tension")}
              type="button"
            >
              <Activity aria-hidden="true" />
              缆线张力
            </button>
          </nav>
        </aside>

        <section className="simulation-stage" aria-label="仿真视图">
          <div className="stage-heading">
            <div>
              <span className="eyebrow">仿真视图</span>
              <h2>{outputTitle}</h2>
            </div>
            <div className="condition-chips" aria-label="当前工况回显">
              <span>船速 {formatNumber(vesselCommandSpeed * 1.94384, 1)} kn</span>
              <span>水深 {formatNumber(dynamicForm.water_depth_m, 1)} m</span>
              <span>海流 {formatNumber(dynamicForm.current_speed_mps)} m/s</span>
              <span>犁速 {formatNumber(ploughCommandSpeed)} m/s</span>
              <span>{ploughExitDisplay}</span>
            </div>
          </div>
          {activeModule === "parameters" ? (
            <section className="parameter-settings-stage" aria-label="参数设置界面">
              <SimulationParameterPanel
                dynamicForm={dynamicForm}
                groupedTimeHistoryCases={groupedTimeHistoryCases}
                loading={loading}
                onExample={fillFromDynamicExample}
                onMaterialExample={fillMaterialFromDynamicExample}
                onNumberChange={updateDynamicNumber}
                onOptionalNumberChange={updateDynamicOptionalNumber}
                onMotionSegmentChange={updateMotionSegment}
                onPayoutSegmentChange={updatePayoutSegment}
                onRun={handleRun}
                onRunModeChange={setRunMode}
                onStageDurationChange={updateStageDuration}
                onTextChange={updateDynamicText}
                runMode={runMode}
                running={running}
              />
            </section>
          ) : latestRealtime ? (
            <RealtimeResultView
              active={realtimeSessionId !== null}
              history={realtimeHistory}
              onStop={stopRealtimeSession}
              stopping={stoppingRealtime}
              summary={realtimeMotionSummary(dynamicForm)}
            />
          ) : timeHistoryResult ? (
            <SimulationResultView apiBase={API_BASE} result={timeHistoryResult} />
          ) : (
            <div className="empty-state simulation-empty">
              <strong>等待仿真运行</strong>
              <span>左侧参数接入后端求解后，这里显示船、缆线和埋设犁的三维运动。</span>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

function realtimeSessionRequest(form: DynamicTimeHistoryForm, initialPacket: RealtimeSensorPacket): CreateRealtimeSessionRequest {
  const { points: _points, output_dir: _outputDir, ...inputs } = form;
  return { ...inputs, max_sensor_gap_s: 5.5, max_data_age_s: 6, initial_packet: initialPacket };
}

function realtimePacket(inputs: TimeHistoryCaseInputs, sequence: number, timeS: number): RealtimeSensorPacket {
  const vesselMotion = endpointMotionAtTime(
    inputs.vessel_motion_segments,
    inputs.vessel_initial_x_m ?? 0,
    inputs.vessel_initial_y_m ?? 0,
    inputs.initial_speed_mps,
    inputs.vessel_heading_deg ?? 0,
    timeS,
  );
  const ploughMotion = endpointMotionAtTime(
    inputs.plough_motion_segments,
    inputs.plough_initial_x_m ?? -55,
    inputs.plough_initial_y_m ?? 0,
    inputs.plough_speed_mps ?? inputs.initial_speed_mps,
    inputs.plough_heading_deg ?? 0,
    timeS,
  );
  const current = velocityComponents(inputs.current_speed_mps, inputs.current_direction_deg);
  const payout = segmentedScalarAtTime(
    inputs.payout_speed_segments,
    inputs.payout_initial_speed_mps ?? inputs.initial_speed_mps,
    inputs.payout_final_speed_mps ?? inputs.final_speed_mps,
    inputs.duration_s,
    timeS,
  );
  return {
    sequence,
    time_s: timeS,
    observed_at_unix_s: Date.now() / 1000,
    quality: "valid",
    vessel: {
      x_m: vesselMotion.x,
      y_m: vesselMotion.y,
      z_m: 0,
      velocity_x_mps: vesselMotion.velocity.x,
      velocity_y_mps: vesselMotion.velocity.y,
      velocity_z_mps: 0,
    },
    plough: {
      x_m: ploughMotion.x,
      y_m: ploughMotion.y,
      z_m: inputs.plough_initial_z_m ?? inputs.water_depth_m,
      velocity_x_mps: ploughMotion.velocity.x,
      velocity_y_mps: ploughMotion.velocity.y,
      velocity_z_mps: 0,
    },
    payout_speed_mps: payout,
    plough_exit_speed_mps: inputs.plough_exit_speed_mps ?? Math.max(ploughMotion.velocity.x, 0),
    current_velocity_x_mps: current.x,
    current_velocity_y_mps: current.y,
  };
}

function endpointMotionAtTime(
  segments: MotionSegmentInput[] | undefined,
  initialX: number,
  initialY: number,
  fallbackSpeed: number,
  fallbackHeading: number,
  timeS: number,
) {
  if (!segments?.length) {
    const velocity = velocityComponents(fallbackSpeed, fallbackHeading);
    return { x: initialX + velocity.x * timeS, y: initialY + velocity.y * timeS, velocity };
  }
  let x = initialX;
  let y = initialY;
  let remaining = Math.max(timeS, 0);
  let velocity = segmentVelocity(segments[0], 0);
  for (const segment of segments) {
    const elapsed = Math.min(remaining, segment.duration_s);
    const start = segmentVelocity(segment, 0);
    const end = segmentVelocity(segment, segment.duration_s <= 0 ? 1 : elapsed / segment.duration_s);
    x += 0.5 * (start.x + end.x) * elapsed;
    y += 0.5 * (start.y + end.y) * elapsed;
    velocity = end;
    remaining -= elapsed;
    if (remaining <= 0) return { x, y, velocity };
  }
  x += velocity.x * remaining;
  y += velocity.y * remaining;
  return { x, y, velocity };
}

function segmentVelocity(segment: MotionSegmentInput, fraction: number) {
  const t = Math.min(Math.max(fraction, 0), 1);
  if (hasCompleteVelocityComponents(segment)) {
    return {
      x: segment.start_velocity_x_mps + (segment.end_velocity_x_mps - segment.start_velocity_x_mps) * t,
      y: segment.start_velocity_y_mps + (segment.end_velocity_y_mps - segment.start_velocity_y_mps) * t,
    };
  }
  const speed = segment.start_speed_mps + (segment.end_speed_mps - segment.start_speed_mps) * t;
  return velocityComponents(speed, segment.heading_deg);
}

function segmentedScalarAtTime(
  segments: SpeedSegmentInput[] | undefined,
  initial: number,
  final: number,
  durationS: number,
  timeS: number,
) {
  if (!segments?.length) {
    return initial + (final - initial) * Math.min(Math.max(timeS / Math.max(durationS, 1.0e-9), 0), 1);
  }
  let remaining = Math.max(timeS, 0);
  for (const segment of segments) {
    if (remaining <= segment.duration_s) {
      const fraction = segment.duration_s <= 0 ? 1 : remaining / segment.duration_s;
      return segment.start_speed_mps + (segment.end_speed_mps - segment.start_speed_mps) * fraction;
    }
    remaining -= segment.duration_s;
  }
  return segments[segments.length - 1].end_speed_mps;
}

function realtimeMotionSummary(form: DynamicTimeHistoryForm) {
  return {
    initial_speed_mps: form.initial_speed_mps,
    final_speed_mps: form.final_speed_mps,
    duration_s: form.duration_s,
    total_duration_s: form.total_duration_s,
    current_speed_mps: form.current_speed_mps,
    current_direction_deg: form.current_direction_deg,
  };
}

export function realtimeScheduleDelayMs(startedAtMs: number, sequence: number, nowMs: number) {
  const deadlineMs = startedAtMs + sequence * REALTIME_UPDATE_INTERVAL_S * 1000;
  return Math.max(0, deadlineMs - nowMs);
}

export function isCurrentRealtimeRequest(
  generation: number,
  currentGeneration: number,
  sessionId: string,
  currentSessionId: string | null,
) {
  return generation === currentGeneration && sessionId === currentSessionId;
}

function materialFieldsFrom(inputs: DynamicTimeHistoryForm | TimeHistoryCase["inputs"]): MaterialFormFields {
  return {
    diameter_m: inputs.diameter_m,
    weight_air_n_per_m: inputs.weight_air_n_per_m,
    submerged_weight_n_per_m: inputs.submerged_weight_n_per_m,
    tangential_drag_coefficient: inputs.tangential_drag_coefficient,
    normal_drag_coefficient: inputs.normal_drag_coefficient,
    axial_stiffness_n: inputs.axial_stiffness_n,
    min_bending_radius_m: inputs.min_bending_radius_m ?? null,
  };
}

function motionSegmentsFromInputs(inputs: TimeHistoryCaseInputs): {
  vessel: MotionSegmentInput[];
  plough: MotionSegmentInput[];
  payout: SpeedSegmentInput[];
} {
  const rampDuration = Math.max(0.001, Math.min(inputs.duration_s, inputs.total_duration_s));
  const cruiseDuration = Math.max(0, inputs.total_duration_s - rampDuration);
  const vesselHeading = inputs.vessel_heading_deg ?? 0;
  const ploughHeading = inputs.plough_heading_deg ?? vesselHeading;
  const ploughSpeed = inputs.plough_speed_mps ?? inputs.initial_speed_mps;
  const payoutStart = inputs.payout_initial_speed_mps ?? inputs.initial_speed_mps;
  const payoutEnd = inputs.payout_final_speed_mps ?? inputs.final_speed_mps;
  return {
    vessel: buildMotionSegments({
      rampDuration,
      cruiseDuration,
      startSpeed: inputs.initial_speed_mps,
      endSpeed: inputs.final_speed_mps,
      headingDeg: vesselHeading,
    }),
    plough: buildMotionSegments({
      rampDuration,
      cruiseDuration,
      startSpeed: ploughSpeed,
      endSpeed: ploughSpeed,
      headingDeg: ploughHeading,
    }),
    payout: buildSpeedSegments({
      rampDuration,
      cruiseDuration,
      startSpeed: payoutStart,
      endSpeed: payoutEnd,
    }),
  };
}

function buildMotionSegments({
  cruiseDuration,
  endSpeed,
  headingDeg,
  rampDuration,
  startSpeed,
}: {
  cruiseDuration: number;
  endSpeed: number;
  headingDeg: number;
  rampDuration: number;
  startSpeed: number;
}): MotionSegmentInput[] {
  const startVelocity = velocityComponents(startSpeed, headingDeg);
  const endVelocity = velocityComponents(endSpeed, headingDeg);
  const segments: MotionSegmentInput[] = [
    {
      duration_s: rampDuration,
      start_speed_mps: startSpeed,
      end_speed_mps: endSpeed,
      heading_deg: headingDeg,
      start_velocity_x_mps: startVelocity.x,
      start_velocity_y_mps: startVelocity.y,
      end_velocity_x_mps: endVelocity.x,
      end_velocity_y_mps: endVelocity.y,
    },
  ];
  if (cruiseDuration > 0.001) {
    segments.push({
      duration_s: cruiseDuration,
      start_speed_mps: endSpeed,
      end_speed_mps: endSpeed,
      heading_deg: headingDeg,
      start_velocity_x_mps: endVelocity.x,
      start_velocity_y_mps: endVelocity.y,
      end_velocity_x_mps: endVelocity.x,
      end_velocity_y_mps: endVelocity.y,
    });
  }
  return segments;
}

function buildSpeedSegments({
  cruiseDuration,
  endSpeed,
  rampDuration,
  startSpeed,
}: {
  cruiseDuration: number;
  endSpeed: number;
  rampDuration: number;
  startSpeed: number;
}): SpeedSegmentInput[] {
  const segments: SpeedSegmentInput[] = [
    {
      duration_s: rampDuration,
      start_speed_mps: startSpeed,
      end_speed_mps: endSpeed,
    },
  ];
  if (cruiseDuration > 0.001) {
    segments.push({
      duration_s: cruiseDuration,
      start_speed_mps: endSpeed,
      end_speed_mps: endSpeed,
    });
  }
  return segments;
}

function syncTimeFields(form: DynamicTimeHistoryForm, changedField: DynamicNumberField): DynamicTimeHistoryForm {
  if (changedField !== "duration_s" && changedField !== "total_duration_s") {
    return form;
  }
  if (changedField === "total_duration_s") {
    return syncLegacyMotionFields({ ...form, total_duration_s: Math.max(form.total_duration_s, 0.001) });
  }
  const rampDuration = Math.max(0.001, Math.min(form.duration_s, form.total_duration_s));
  const cruiseDuration = Math.max(0, form.total_duration_s - rampDuration);
  return syncLegacyMotionFields({
    ...form,
    duration_s: rampDuration,
    vessel_motion_segments: resizeSegmentDurations(form.vessel_motion_segments ?? [], rampDuration, cruiseDuration),
    plough_motion_segments: resizeSegmentDurations(form.plough_motion_segments ?? [], rampDuration, cruiseDuration),
    payout_speed_segments: resizeSpeedSegmentDurations(form.payout_speed_segments ?? [], rampDuration, cruiseDuration),
  });
}

function updateSegmentDuration<T extends { duration_s: number }>(
  segments: T[] | undefined,
  index: number,
  duration: number,
): T[] | undefined {
  if (!segments?.[index]) return segments;
  return segments.map((segment, segmentIndex) =>
    segmentIndex === index ? { ...segment, duration_s: duration } : segment
  );
}

function resizeSegmentDurations(
  segments: MotionSegmentInput[],
  rampDuration: number,
  cruiseDuration: number,
): MotionSegmentInput[] {
  if (segments.length === 0) {
    return segments;
  }
  const next = [normalizeMotionSegment({ ...segments[0], duration_s: rampDuration })];
  const cruise = segments[1] ?? normalizeMotionSegment({
    duration_s: cruiseDuration,
    start_speed_mps: segments[0].end_speed_mps,
    end_speed_mps: segments[0].end_speed_mps,
    heading_deg: segments[0].heading_deg,
    start_velocity_x_mps: segments[0].end_velocity_x_mps,
    start_velocity_y_mps: segments[0].end_velocity_y_mps,
    end_velocity_x_mps: segments[0].end_velocity_x_mps,
    end_velocity_y_mps: segments[0].end_velocity_y_mps,
  });
  if (cruiseDuration > 0.001) {
    next.push(normalizeMotionSegment({ ...cruise, duration_s: cruiseDuration }));
  }
  return next;
}

function resizeSpeedSegmentDurations(
  segments: SpeedSegmentInput[],
  rampDuration: number,
  cruiseDuration: number,
): SpeedSegmentInput[] {
  if (segments.length === 0) {
    return segments;
  }
  const next = [{ ...segments[0], duration_s: rampDuration }];
  const cruise = segments[1] ?? {
    duration_s: cruiseDuration,
    start_speed_mps: segments[0].end_speed_mps,
    end_speed_mps: segments[0].end_speed_mps,
  };
  if (cruiseDuration > 0.001) {
    next.push({ ...cruise, duration_s: cruiseDuration });
  }
  return next;
}

function ploughExitMaterialSpeedDisplay(
  form: DynamicTimeHistoryForm,
  summary: RunTimeHistoryResponse["summary"] | undefined,
): string {
  if (summary?.plough_exit_speed_mps !== null && summary?.plough_exit_speed_mps !== undefined) {
    return `犁出口材料速度 ${formatNumber(summary.plough_exit_speed_mps)} m/s（${
      summary.plough_exit_speed_source === "no_slip_inferred" ? "无滑移推定" : "实测"
    }）`;
  }
  if (form.plough_exit_speed_mps !== null && form.plough_exit_speed_mps !== undefined) {
    return `犁出口材料速度 ${formatNumber(form.plough_exit_speed_mps)} m/s（实测）`;
  }
  const inferredSpeed = noSlipInferredPloughExitSpeed(form);
  return inferredSpeed === null
    ? "犁出口材料速度 需要实测 q_p"
    : `犁出口材料速度 ${formatNumber(inferredSpeed)} m/s（无滑移推定）`;
}

function noSlipInferredPloughExitSpeed(form: DynamicTimeHistoryForm): number | null {
  if (form.plough_motion_samples?.length) {
    return null;
  }
  const segments = form.plough_motion_segments ?? [];
  if (segments.length > 0) {
    if (!segments.every(isPositiveXMotionSegment)) {
      return null;
    }
    return positiveXStartSpeed(segments[0]);
  }
  if (!isPositiveXHeading(form.plough_heading_deg)) {
    return null;
  }
  return form.plough_speed_mps ?? null;
}

function isPositiveXMotionSegment(segment: MotionSegmentInput): boolean {
  if (hasCompleteVelocityComponents(segment)) {
    return (
      segment.start_velocity_x_mps >= -ROUTE_LONGITUDINAL_TOLERANCE
      && segment.end_velocity_x_mps >= -ROUTE_LONGITUDINAL_TOLERANCE
      && Math.abs(segment.start_velocity_y_mps) <= ROUTE_LONGITUDINAL_TOLERANCE
      && Math.abs(segment.end_velocity_y_mps) <= ROUTE_LONGITUDINAL_TOLERANCE
    );
  }
  return isPositiveXHeading(segment.heading_deg);
}

function positiveXStartSpeed(segment: MotionSegmentInput): number {
  return hasCompleteVelocityComponents(segment) ? segment.start_velocity_x_mps : segment.start_speed_mps;
}

function isPositiveXHeading(headingDeg: number | null | undefined): boolean {
  return (
    headingDeg !== null
    && headingDeg !== undefined
    && Math.abs(headingDeg % 360) <= ROUTE_LONGITUDINAL_TOLERANCE
  );
}

function syncLegacyMotionFields(form: DynamicTimeHistoryForm): DynamicTimeHistoryForm {
  const vesselSegments = normalizeMotionSegments(form.vessel_motion_segments ?? []);
  const ploughSegments = normalizeMotionSegments(form.plough_motion_segments ?? []);
  const vessel = vesselSegments[0];
  const payout = form.payout_speed_segments?.[0];
  const plough = ploughSegments[0];
  const totalDuration = Math.max(form.total_duration_s, 0.001);
  const vesselTerminal = endpointMotionAtTime(
    vesselSegments,
    0,
    0,
    form.initial_speed_mps,
    form.vessel_heading_deg ?? 0,
    totalDuration,
  ).velocity;
  const ploughTerminal = endpointMotionAtTime(
    ploughSegments,
    0,
    0,
    form.plough_speed_mps ?? form.initial_speed_mps,
    form.plough_heading_deg ?? 0,
    totalDuration,
  ).velocity;
  const initialVesselSpeed = motionSegmentStartSpeed(vessel) ?? form.initial_speed_mps;
  const terminalVesselSpeed = Math.hypot(vesselTerminal.x, vesselTerminal.y);
  const terminalPayoutSpeed = segmentedScalarAtTime(
    form.payout_speed_segments,
    payout?.start_speed_mps ?? form.payout_initial_speed_mps ?? form.initial_speed_mps,
    form.payout_final_speed_mps ?? form.final_speed_mps,
    form.duration_s,
    totalDuration,
  );
  const speedChange = speedChangeFrom(
    initialVesselSpeed,
    terminalVesselSpeed,
  );
  return {
    ...form,
    vessel_motion_segments: vesselSegments.length ? vesselSegments : form.vessel_motion_segments,
    plough_motion_segments: ploughSegments.length ? ploughSegments : form.plough_motion_segments,
    speed_change: speedChange,
    initial_speed_mps: initialVesselSpeed,
    final_speed_mps: terminalVesselSpeed,
    duration_s: Math.min(vessel?.duration_s ?? form.duration_s, totalDuration),
    total_duration_s: totalDuration,
    vessel_heading_deg: motionSegmentHeading(vessel) ?? form.vessel_heading_deg,
    payout_initial_speed_mps: payout?.start_speed_mps ?? form.payout_initial_speed_mps,
    payout_final_speed_mps: terminalPayoutSpeed,
    plough_speed_mps: Math.hypot(ploughTerminal.x, ploughTerminal.y),
    plough_heading_deg: motionSegmentHeading(plough) ?? form.plough_heading_deg,
  };
}

function normalizeMotionSegments(segments: MotionSegmentInput[]): MotionSegmentInput[] {
  return segments.map((segment) => normalizeMotionSegment(segment));
}

function normalizeMotionSegment(segment: MotionSegmentInput): MotionSegmentInput {
  if (!hasCompleteVelocityComponents(segment)) {
    return segment;
  }
  const startSpeed = Math.hypot(segment.start_velocity_x_mps, segment.start_velocity_y_mps);
  const endSpeed = Math.hypot(segment.end_velocity_x_mps, segment.end_velocity_y_mps);
  return {
    ...segment,
    start_speed_mps: startSpeed,
    end_speed_mps: endSpeed,
    heading_deg:
      headingFromVelocity(segment.start_velocity_x_mps, segment.start_velocity_y_mps) ??
      headingFromVelocity(segment.end_velocity_x_mps, segment.end_velocity_y_mps) ??
      segment.heading_deg,
  };
}

function hasCompleteVelocityComponents(
  segment: MotionSegmentInput,
): segment is MotionSegmentInput & Required<Pick<MotionSegmentInput, "start_velocity_x_mps" | "start_velocity_y_mps" | "end_velocity_x_mps" | "end_velocity_y_mps">> {
  return (
    Number.isFinite(segment.start_velocity_x_mps) &&
    Number.isFinite(segment.start_velocity_y_mps) &&
    Number.isFinite(segment.end_velocity_x_mps) &&
    Number.isFinite(segment.end_velocity_y_mps)
  );
}

function motionSegmentStartSpeed(segment?: MotionSegmentInput): number | undefined {
  return segment ? normalizeMotionSegment(segment).start_speed_mps : undefined;
}

function motionSegmentEndSpeed(segment?: MotionSegmentInput): number | undefined {
  return segment ? normalizeMotionSegment(segment).end_speed_mps : undefined;
}

function motionSegmentHeading(segment?: MotionSegmentInput): number | undefined {
  return segment ? normalizeMotionSegment(segment).heading_deg : undefined;
}

function velocityComponents(speedMps: number, headingDeg: number): { x: number; y: number } {
  const radians = (headingDeg * Math.PI) / 180;
  return {
    x: speedMps * Math.cos(radians),
    y: speedMps * Math.sin(radians),
  };
}

function headingFromVelocity(xMps: number, yMps: number): number | undefined {
  if (Math.hypot(xMps, yMps) <= 1.0e-12) {
    return undefined;
  }
  return (((Math.atan2(yMps, xMps) * 180) / Math.PI) + 360) % 360;
}

function sumDurations(segments?: { duration_s: number }[]): number {
  return segments?.reduce((total, segment) => total + segment.duration_s, 0) ?? 0;
}

function speedChangeFrom(startSpeed: number, endSpeed: number): SpeedChange {
  if (endSpeed > startSpeed) {
    return "accel";
  }
  if (endSpeed < startSpeed) {
    return "decel";
  }
  return "steady";
}

function messageFrom(caught: unknown): string {
  if (caught instanceof ApiError) {
    return caught.message;
  }
  if (caught instanceof Error) {
    return caught.message;
  }
  return "请求失败，请检查后端服务。";
}

import { Play } from "lucide-react";
import type { FormEvent } from "react";
import type { DynamicTimeHistoryForm, MotionSegmentInput, SpeedSegmentInput, TimeHistoryCase } from "./types";

export type DynamicNumberField =
  | "points"
  | "diameter_m"
  | "weight_air_n_per_m"
  | "submerged_weight_n_per_m"
  | "tangential_drag_coefficient"
  | "normal_drag_coefficient"
  | "axial_stiffness_n"
  | "current_speed_mps"
  | "current_direction_deg"
  | "initial_speed_mps"
  | "final_speed_mps"
  | "duration_s"
  | "total_duration_s"
  | "water_depth_m"
  | "element_count"
  | "touchdown_tension_n"
  | "vessel_initial_x_m"
  | "vessel_initial_y_m"
  | "vessel_heading_deg"
  | "plough_initial_x_m"
  | "plough_initial_y_m"
  | "plough_initial_z_m"
  | "plough_speed_mps"
  | "plough_heading_deg";

export type DynamicOptionalNumberField =
  | "payout_initial_speed_mps"
  | "payout_final_speed_mps"
  | "plough_exit_speed_mps"
  | "initial_suspended_length_m"
  | "min_bending_radius_m";

export type MotionTarget = "vessel_motion_segments" | "plough_motion_segments";
export type MotionSegmentField = keyof MotionSegmentInput;
export type PayoutSegmentField = keyof SpeedSegmentInput;

type TemplateGroupKind = "material" | "environment";

interface TemplateDisplayGroup {
  kind: TemplateGroupKind;
  label: string;
  description: string;
  cases: TimeHistoryCase[];
}

interface TemplateDisplayBuckets {
  environmentGroups: TemplateDisplayGroup[];
  materialCases: TimeHistoryCase[];
}

interface TemplateCopy {
  label: string;
  description: string;
}

const TEMPLATE_GROUPS: Record<TemplateGroupKind, Omit<TemplateDisplayGroup, "cases">> = {
  material: {
    kind: "material",
    label: "缆型/材料参数",
    description: "只切换缆径、单位重、阻力、刚度和弯曲限制，不改运动边界。",
  },
  environment: {
    kind: "environment",
    label: "环境/运动参数",
    description: "保持基准缆型，切换海流、船端运动、放缆、犁速或触地点约束。",
  },
};

const TEMPLATE_COPY_BY_NAME: Record<string, TemplateCopy> = {
  plough_straight_baseline_6min: {
    label: "常规基准",
    description: "稳定直线铺埋，用作铺设工况对比基准。",
  },
  plough_straight_low_speed_6min: {
    label: "低速铺埋",
    description: "整体放慢船端、放缆和犁端运动，观察悬垂段变化。",
  },
  plough_straight_high_speed_6min: {
    label: "高速铺埋",
    description: "整体提高运动节奏，观察速度敏感性。",
  },
  plough_straight_low_tdp_tension_6min: {
    label: "低触地张力",
    description: "降低触地点约束，观察入口张力和悬垂形态。",
  },
  plough_straight_high_tdp_tension_6min: {
    label: "高触地张力",
    description: "提高触地点约束，观察张力分布和悬垂形态。",
  },
  plough_cross_current_0p50_90deg_6min: {
    label: "横流偏载",
    description: "固定运动边界，观察横向来流下的侧偏和张力变化。",
  },
  plough_cross_current_0p95_90deg_6min: {
    label: "强横流偏载",
    description: "增强横向来流作用，观察侧偏和张力敏感性。",
  },
  plough_cross_current_0p95_60deg_6min: {
    label: "斜向来流",
    description: "来流与铺设航迹斜交，观察缆线侧偏变化。",
  },
  plough_cross_current_0p95_30deg_6min: {
    label: "小角度来流",
    description: "来流更接近铺设航迹，观察偏载减弱后的响应。",
  },
  plough_cross_current_0p95_0deg_6min: {
    label: "顺向来流",
    description: "来流沿铺设航迹作用，观察顺流铺埋状态。",
  },
  plough_decel_mild_6min: {
    label: "温和减速",
    description: "船端、放缆和犁端同步减速，观察张力峰值回落。",
  },
  plough_decel_strong_6min: {
    label: "强减速",
    description: "提高减速幅度，检查动态峰值和触地点迁移。",
  },
  plough_decel_long_6min: {
    label: "长历时减速",
    description: "拉长减速过程，观察冲击释放后的张力变化。",
  },
  plough_payout_matched_6min: {
    label: "同步放缆",
    description: "放缆和犁端运动保持同步，用作放缆偏差基准。",
  },
  plough_payout_fast_1p10_6min: {
    label: "轻微放缆偏快",
    description: "放缆略快于犁端，观察悬垂段增长。",
  },
  plough_payout_fast_1p25_6min: {
    label: "明显放缆偏快",
    description: "进一步提高放缆相对速度，检查入口张力和形态变化。",
  },
  plough_material_la_6min: {
    label: "LA 信号缆",
    description: "同一运动边界下的轻型信号缆材料对比。",
  },
  plough_material_ha_6min: {
    label: "HA 信号缆",
    description: "同一运动边界下的中重型信号缆材料对比。",
  },
  plough_material_power_500kv_6min: {
    label: "电力缆",
    description: "同一运动边界下的重型电力缆材料对比。",
  },
};

export function SimulationParameterPanel({
  dynamicForm,
  groupedTimeHistoryCases,
  loading,
  onExample,
  onMaterialExample,
  onNumberChange,
  onOptionalNumberChange,
  onMotionSegmentChange,
  onPayoutSegmentChange,
  onRun,
  onRunModeChange,
  onStageDurationChange,
  onTextChange,
  runMode,
  running,
}: {
  dynamicForm: DynamicTimeHistoryForm;
  groupedTimeHistoryCases: { label: string; cases: TimeHistoryCase[] }[];
  loading: boolean;
  onExample: (item: TimeHistoryCase) => void;
  onMaterialExample: (item: TimeHistoryCase) => void;
  onNumberChange: (field: DynamicNumberField, value: string) => void;
  onOptionalNumberChange: (field: DynamicOptionalNumberField, value: string) => void;
  onMotionSegmentChange: (target: MotionTarget, index: number, field: MotionSegmentField, value: string) => void;
  onPayoutSegmentChange: (index: number, field: PayoutSegmentField, value: string) => void;
  onRun: (event?: FormEvent<HTMLFormElement>) => void;
  onRunModeChange: (mode: "batch" | "realtime") => void;
  onStageDurationChange: (index: number, value: string) => void;
  onTextChange: (field: "case_name", value: string) => void;
  runMode: "batch" | "realtime";
  running: boolean;
}) {
  const { environmentGroups, materialCases } = buildTemplateDisplayBuckets(groupedTimeHistoryCases);
  const environmentCaseCount = environmentGroups.reduce((total, group) => total + group.cases.length, 0);

  return (
    <form aria-label="仿真参数设置" className="input-panel parameter-panel" noValidate onSubmit={onRun}>
      <div className="panel-heading">
        <div>
          <span className="eyebrow">仿真输入</span>
          <h2>{dynamicForm.case_name || "未命名计算"}</h2>
        </div>
        <div className="run-mode-actions">
          <div className="run-mode-switch" aria-label="求解模式">
            <button aria-pressed={runMode === "batch"} onClick={() => onRunModeChange("batch")} type="button">离线时程</button>
            <button aria-pressed={runMode === "realtime"} onClick={() => onRunModeChange("realtime")} type="button">5 s 准实时</button>
          </div>
          <button className="primary-action" disabled={running} type="submit">
            <Play aria-hidden="true" />
            {running ? "启动中" : runMode === "realtime" ? "启动实时会话" : "运行仿真"}
          </button>
        </div>
      </div>

      <div className="template-picker-grid">
        <section className="template-section condition-template-section" aria-label="工况模板">
          <div className="rail-heading">
            <h2>工况模板</h2>
            <span>{environmentGroups.length} 类 / {environmentCaseCount} 组</span>
          </div>
          {loading ? <p className="muted">正在读取参数例子...</p> : null}
          {environmentGroups.map((group) => (
            <div className={`case-group dynamic-case-group ${group.kind}-template-group`} key={group.kind}>
              <div className="template-group-heading">
                <h3>{group.label}</h3>
                <p>{group.description}</p>
              </div>
              {group.cases.map((item) => {
                const templateCopy = copyForTemplateCase(item);
                return (
                  <button
                    className={dynamicForm.output_dir === item.suggested_output_dir ? "case-button active" : "case-button"}
                    disabled={running}
                    key={item.name}
                    onClick={() => onExample(item)}
                    type="button"
                  >
                    <span>{templateCopy.label}</span>
                    <small>{templateCopy.description}</small>
                  </button>
                );
              })}
            </div>
          ))}
        </section>

        <section className="template-section material-selector-section" aria-label="材料选择">
          <div className="rail-heading">
            <h2>材料选择</h2>
            <span>{materialCases.length} 类</span>
          </div>
          <div className="case-group dynamic-case-group material-template-group">
            <div className="template-group-heading">
              <h3>{TEMPLATE_GROUPS.material.label}</h3>
              <p>{TEMPLATE_GROUPS.material.description}</p>
            </div>
            {materialCases.length > 0 ? (
              materialCases.map((item) => {
                const templateCopy = copyForTemplateCase(item);
                return (
                  <button
                    className={materialCaseMatchesForm(item, dynamicForm) ? "case-button active" : "case-button"}
                    disabled={running}
                    key={item.name}
                    onClick={() => onMaterialExample(item)}
                    type="button"
                  >
                    <span>{templateCopy.label}</span>
                    <small>{templateCopy.description}</small>
                  </button>
                );
              })
            ) : (
              <p className="muted">暂无材料参数模板</p>
            )}
          </div>
        </section>
      </div>

      <div className="form-section solver-section">
        <h3>数值求解与输出</h3>
        <div className="field-grid">
          <TextField label="计算名称" onChange={(value) => onTextChange("case_name", value)} value={dynamicForm.case_name} />
          <NumberField label="计算时长 s" min={0.001} onChange={(value) => onNumberChange("total_duration_s", value)} value={dynamicForm.total_duration_s} />
          <NumberField label="输出帧数（不改变内部积分步长）" min={3} onChange={(value) => onNumberChange("points", value)} step={1} value={dynamicForm.points} />
          <NumberField label="缆线离散单元数" min={2} onChange={(value) => onNumberChange("element_count", value)} step={1} value={dynamicForm.element_count} />
        </div>
        <h3 className="subsection-title motion-title">运动边界时程</h3>
        <StageSchedule
          onChange={onStageDurationChange}
          segments={dynamicForm.vessel_motion_segments ?? []}
          totalDurationS={dynamicForm.total_duration_s}
        />
        <div className="motion-control-grid" aria-label="运动控制分段">
          <MotionCommandTable
            headingLabel="船端导缆点速度"
            onChange={(index, field, value) => onMotionSegmentChange("vessel_motion_segments", index, field, value)}
            segments={dynamicForm.vessel_motion_segments ?? []}
          />
          <MotionCommandTable
            headingLabel="犁入口速度"
            onChange={(index, field, value) => onMotionSegmentChange("plough_motion_segments", index, field, value)}
            segments={dynamicForm.plough_motion_segments ?? []}
          />
          <PayoutCommandTable
            onChange={onPayoutSegmentChange}
            segments={dynamicForm.payout_speed_segments ?? []}
          />
        </div>
      </div>

      <div className="form-section dynamic-input-section">
        <h3 className="section-title">物理模型输入</h3>
        <h3 className="subsection-title material-title">材料属性</h3>
        <div className="field-grid">
          <NumberField label="缆径 m" min={0.001} onChange={(value) => onNumberChange("diameter_m", value)} value={dynamicForm.diameter_m} />
          <NumberField label="空气中单位重 N/m" min={0.001} onChange={(value) => onNumberChange("weight_air_n_per_m", value)} value={dynamicForm.weight_air_n_per_m} />
          <NumberField label="水中单位重 N/m" min={0.001} onChange={(value) => onNumberChange("submerged_weight_n_per_m", value)} value={dynamicForm.submerged_weight_n_per_m} />
          <NumberField label="切向阻力系数 Ct" min={0} onChange={(value) => onNumberChange("tangential_drag_coefficient", value)} value={dynamicForm.tangential_drag_coefficient} />
          <NumberField label="法向阻力系数 Cn" min={0} onChange={(value) => onNumberChange("normal_drag_coefficient", value)} value={dynamicForm.normal_drag_coefficient} />
          <NumberField label="轴向刚度 EA N" min={0.001} onChange={(value) => onNumberChange("axial_stiffness_n", value)} value={dynamicForm.axial_stiffness_n} />
          <OptionalNumberField label="最小弯曲半径 m" min={0.001} onChange={(value) => onOptionalNumberChange("min_bending_radius_m", value)} value={dynamicForm.min_bending_radius_m ?? null} />
        </div>
        <h3 className="subsection-title environment-title">环境条件</h3>
        <div className="field-grid">
          <NumberField label="均匀海流速度 m/s" min={0} onChange={(value) => onNumberChange("current_speed_mps", value)} value={dynamicForm.current_speed_mps} />
          <NumberField label="海流去向角 deg（0=作业纵向+X）" max={360} min={0} onChange={(value) => onNumberChange("current_direction_deg", value)} value={dynamicForm.current_direction_deg} />
          <NumberField label="作业水深 m" min={0.001} onChange={(value) => onNumberChange("water_depth_m", value)} value={dynamicForm.water_depth_m} />
        </div>
        <h3 className="subsection-title plough-title">初始几何与材料边界</h3>
        <div className="field-grid">
          <NumberField label="船端初始作业坐标 X m" onChange={(value) => onNumberChange("vessel_initial_x_m", value)} value={dynamicForm.vessel_initial_x_m ?? 0} />
          <NumberField label="船端初始作业坐标 Y m" onChange={(value) => onNumberChange("vessel_initial_y_m", value)} value={dynamicForm.vessel_initial_y_m ?? 0} />
          <NumberField label="犁入口初始作业坐标 X m" onChange={(value) => onNumberChange("plough_initial_x_m", value)} value={dynamicForm.plough_initial_x_m ?? -55} />
          <NumberField label="犁入口初始作业坐标 Y m" onChange={(value) => onNumberChange("plough_initial_y_m", value)} value={dynamicForm.plough_initial_y_m ?? 0} />
          <NumberField label="犁入口初始深度 Z m（向下为正）" min={0} onChange={(value) => onNumberChange("plough_initial_z_m", value)} value={dynamicForm.plough_initial_z_m ?? dynamicForm.water_depth_m} />
          <OptionalNumberField label="犁出口材料速度 q_p m/s（实测，可选）" min={0} onChange={(value) => onOptionalNumberChange("plough_exit_speed_mps", value)} value={dynamicForm.plough_exit_speed_mps ?? null} />
          <OptionalNumberField label="初始悬垂长度 m" min={0.001} onChange={(value) => onOptionalNumberChange("initial_suspended_length_m", value)} value={dynamicForm.initial_suspended_length_m ?? null} />
        </div>
      </div>
    </form>
  );
}

function StageSchedule({
  onChange,
  segments,
  totalDurationS,
}: {
  onChange: (index: number, value: string) => void;
  segments: MotionSegmentInput[];
  totalDurationS: number;
}) {
  let elapsedS = 0;
  return (
    <section className="stage-schedule" aria-label="统一工况时段">
      {segments.map((segment, index) => {
        const startS = elapsedS;
        const endS = startS + segment.duration_s;
        elapsedS = endS;
        return <div key={`stage-${index}`}>
          <strong>{motionStageLabel(segment, index)}</strong>
          <NumberField
            ariaLabel={`${motionStageLabel(segment, index)}时长 s`}
            label="时长 s"
            min={0.001}
            onChange={(value) => onChange(index, value)}
            value={segment.duration_s}
          />
          <span>{stageWindowStatus(startS, endS, totalDurationS)}</span>
        </div>
      })}
    </section>
  );
}

function MotionCommandTable({
  headingLabel,
  onChange,
  segments,
}: {
  headingLabel: string;
  onChange: (index: number, field: MotionSegmentField, value: string) => void;
  segments: MotionSegmentInput[];
}) {
  return (
    <section className="motion-command-card" aria-label={headingLabel}>
      <h4>{headingLabel}</h4>
      <div className="motion-table">
        <span>工况段</span>
        <span>段首 uX</span>
        <span>段首 vY</span>
        <span>段末 uX</span>
        <span>段末 vY</span>
        {segments.map((segment, index) => (
          <div className="motion-row" key={`${headingLabel}-${index}`}>
            <strong>{stageIndexLabel(index)}</strong>
            <NumberField
              ariaLabel={`${headingLabel}${stageIndexLabel(index)}段首纵向速度 uX m/s`}
              label="段首 uX"
              onChange={(value) => onChange(index, "start_velocity_x_mps", value)}
              value={motionVelocityComponent(segment, "start", "x")}
            />
            <NumberField
              ariaLabel={`${headingLabel}${stageIndexLabel(index)}段首横向速度 vY m/s`}
              label="段首 vY"
              onChange={(value) => onChange(index, "start_velocity_y_mps", value)}
              value={motionVelocityComponent(segment, "start", "y")}
            />
            <NumberField
              ariaLabel={`${headingLabel}${stageIndexLabel(index)}段末纵向速度 uX m/s`}
              label="段末 uX"
              onChange={(value) => onChange(index, "end_velocity_x_mps", value)}
              value={motionVelocityComponent(segment, "end", "x")}
            />
            <NumberField
              ariaLabel={`${headingLabel}${stageIndexLabel(index)}段末横向速度 vY m/s`}
              label="段末 vY"
              onChange={(value) => onChange(index, "end_velocity_y_mps", value)}
              value={motionVelocityComponent(segment, "end", "y")}
            />
          </div>
        ))}
      </div>
    </section>
  );
}

function PayoutCommandTable({
  onChange,
  segments,
}: {
  onChange: (index: number, field: PayoutSegmentField, value: string) => void;
  segments: SpeedSegmentInput[];
}) {
  return (
    <section className="motion-command-card" aria-label="放缆速度">
      <h4>放缆速度</h4>
      <div className="motion-table payout-table">
        <span>工况段</span>
        <span>段首 qf</span>
        <span>段末 qf</span>
        {segments.map((segment, index) => (
          <div className="motion-row payout-row" key={`payout-${index}`}>
            <strong>{stageIndexLabel(index)}</strong>
            <NumberField
              ariaLabel={`放缆${stageIndexLabel(index)}段首速度 qf m/s`}
              label="段首 qf"
              min={0}
              onChange={(value) => onChange(index, "start_speed_mps", value)}
              value={segment.start_speed_mps}
            />
            <NumberField
              ariaLabel={`放缆${stageIndexLabel(index)}段末速度 qf m/s`}
              label="段末 qf"
              min={0}
              onChange={(value) => onChange(index, "end_speed_mps", value)}
              value={segment.end_speed_mps}
            />
          </div>
        ))}
      </div>
    </section>
  );
}

function motionStageLabel(segment: MotionSegmentInput, index: number): string {
  const changed =
    Math.abs(motionVelocityComponent(segment, "start", "x") - motionVelocityComponent(segment, "end", "x")) > 1e-9
    || Math.abs(motionVelocityComponent(segment, "start", "y") - motionVelocityComponent(segment, "end", "y")) > 1e-9;
  return changed ? `变速段 ${index + 1}` : `匀速段 ${index + 1}`;
}

function stageIndexLabel(index: number): string {
  return `第${index + 1}段`;
}

function stageWindowStatus(startS: number, endS: number, totalDurationS: number): string {
  if (totalDurationS <= startS + 1e-9) return "本次不计算";
  if (totalDurationS < endS - 1e-9) return `计算至本段 ${(totalDurationS - startS).toFixed(1)} s`;
  return "本段完整计算";
}

function buildTemplateDisplayBuckets(groups: { label: string; cases: TimeHistoryCase[] }[]): TemplateDisplayBuckets {
  const casesByKind: Record<TemplateGroupKind, TimeHistoryCase[]> = {
    material: [],
    environment: [],
  };
  groups.forEach((group) => {
    group.cases.forEach((item) => {
      casesByKind[classifyTemplateCase(item)].push(item);
    });
  });

  return {
    environmentGroups:
      casesByKind.environment.length > 0
        ? [
            {
              ...TEMPLATE_GROUPS.environment,
              cases: casesByKind.environment,
            },
          ]
        : [],
    materialCases: casesByKind.material,
  };
}

function classifyTemplateCase(item: TimeHistoryCase): TemplateGroupKind {
  if (item.name.includes("material") || item.group.includes("信号缆") || item.group.includes("电力缆")) {
    return "material";
  }
  return "environment";
}

function copyForTemplateCase(item: TimeHistoryCase): TemplateCopy {
  return (
    TEMPLATE_COPY_BY_NAME[item.name] ?? {
      label: stripMeasurementText(item.label),
      description: stripMeasurementText(item.description),
    }
  );
}

function materialCaseMatchesForm(item: TimeHistoryCase, dynamicForm: DynamicTimeHistoryForm): boolean {
  return (
    numbersMatch(item.inputs.diameter_m, dynamicForm.diameter_m) &&
    numbersMatch(item.inputs.weight_air_n_per_m, dynamicForm.weight_air_n_per_m) &&
    numbersMatch(item.inputs.submerged_weight_n_per_m, dynamicForm.submerged_weight_n_per_m) &&
    numbersMatch(item.inputs.tangential_drag_coefficient, dynamicForm.tangential_drag_coefficient) &&
    numbersMatch(item.inputs.normal_drag_coefficient, dynamicForm.normal_drag_coefficient) &&
    numbersMatch(item.inputs.axial_stiffness_n, dynamicForm.axial_stiffness_n) &&
    optionalNumbersMatch(item.inputs.min_bending_radius_m ?? null, dynamicForm.min_bending_radius_m ?? null)
  );
}

function numbersMatch(left: number, right: number): boolean {
  return Math.abs(left - right) <= Math.max(1, Math.abs(left), Math.abs(right)) * 1e-9;
}

function optionalNumbersMatch(left: number | null, right: number | null): boolean {
  if (left === null || right === null) {
    return left === right;
  }
  return numbersMatch(left, right);
}

function stripMeasurementText(value: string): string {
  return (
    value
      .replace(/\d+(?:\.\d+)?\s*(?:m\/s|kN|N|deg|°|%|kV|s|m)\b/gi, "")
      .replace(/\d+(?:\.\d+)?\s*(?:°|%)/g, "")
      .replace(/\d+(?:\.\d+)?/g, "")
      .replace(/\s+/g, " ")
      .replace(/（\s*）|\(\s*\)/g, "")
      .trim() || "铺设工况"
  );
}

function motionVelocityComponent(segment: MotionSegmentInput, endpoint: "start" | "end", axis: "x" | "y"): number {
  const field = `${endpoint}_velocity_${axis}_mps` as keyof MotionSegmentInput;
  const direct = segment[field];
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct;
  }
  const speed = endpoint === "start" ? segment.start_speed_mps : segment.end_speed_mps;
  const radians = (segment.heading_deg * Math.PI) / 180;
  return axis === "x" ? speed * Math.cos(radians) : speed * Math.sin(radians);
}

function TextField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input aria-label={label} onChange={(event) => onChange(event.target.value)} type="text" value={value} />
    </label>
  );
}

function SelectField<T extends string>({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  value: T;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select aria-label={label} onChange={(event) => onChange(event.target.value as T)} value={value}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberField({
  ariaLabel,
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  ariaLabel?: string;
  label: string;
  max?: number;
  min?: number;
  onChange: (value: string) => void;
  step?: number;
  value: number;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        aria-label={ariaLabel ?? label}
        max={max}
        min={min}
        onChange={(event) => onChange(event.target.value)}
        step={step ?? "any"}
        type="number"
        value={Number.isFinite(value) ? value : ""}
      />
    </label>
  );
}

function OptionalNumberField({
  label,
  max,
  min,
  onChange,
  value,
}: {
  label: string;
  max?: number;
  min?: number;
  onChange: (value: string) => void;
  value: number | null;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        aria-label={label}
        max={max}
        min={min}
        onChange={(event) => onChange(event.target.value)}
        step="any"
        type="number"
        value={value ?? ""}
      />
    </label>
  );
}

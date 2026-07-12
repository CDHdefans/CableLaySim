export function formatNewton(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toFixed(2)} kN`;
  }
  return `${value.toFixed(2)} N`;
}

export function formatKiloNewton(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${(value / 1000).toFixed(2)} kN`;
}

export function formatMeters(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(2)} m`;
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

export function formatCaseName(caseName: string): string {
  const speedMatch = caseName.match(/^power_current_speed_(\d+)p(\d+)$/);
  if (speedMatch) {
    return `500kV电力缆｜流速${speedMatch[1]}.${speedMatch[2]} m/s`;
  }
  const directionMatch = caseName.match(/^power_current_direction_(\d+)$/);
  if (directionMatch) {
    return `500kV电力缆｜流向${directionMatch[1]}°`;
  }
  const pretensionMatch = caseName.match(/^power_pretension_(\d+)$/);
  if (pretensionMatch) {
    return `500kV电力缆｜触地点张力${pretensionMatch[1]} N`;
  }
  const layingMatch = caseName.match(/^(la|ha)_(accel|decel)_(\d+)m$/);
  if (layingMatch) {
    const cable = layingMatch[1].toUpperCase();
    const motion = layingMatch[2] === "accel" ? "加速铺设" : "减速铺设";
    return `${cable} 信号缆｜${motion} ${layingMatch[3]} m`;
  }
  const dynamicMatch = caseName.match(/^la_dynamic_(accel|decel)_current_(\d+)p(\d+)$/);
  if (dynamicMatch) {
    const motion = dynamicMatch[1] === "accel" ? "加速时程" : "减速时程";
    return `LA｜${motion}，流速${dynamicMatch[2]}.${dynamicMatch[3]} m/s`;
  }
  if (caseName.startsWith("la_")) {
    return caseName.replace(/^la_/, "LA ").replace(/_/g, " ").replace(/(\d+)p(\d+)/g, "$1.$2");
  }
  if (caseName.startsWith("ha_")) {
    return caseName.replace(/^ha_/, "HA ").replace(/_/g, " ").replace(/(\d+)p(\d+)/g, "$1.$2");
  }
  if (caseName.startsWith("power_")) {
    return caseName
      .replace("power_", "")
      .replace(/_/g, " ")
      .replace(/(\d+)p(\d+)/g, "$1.$2");
  }
  return caseName.replace(/_/g, " ");
}

"""Measure sustained per-packet latency of the stateful realtime solver."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cable_tension.dynamic import get_time_history_case
from cable_tension.realtime import RealtimeSensorPacket, RealtimeSimulationSession, SynchronizedEndpointSample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", type=int, default=60)
    parser.add_argument("--elements", type=int, default=24)
    parser.add_argument("--sample-interval-s", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.packets < 1 or args.elements < 4 or args.sample_interval_s <= 0.0:
        parser.error("packets must be >= 1, elements must be >= 4, and sample interval must be positive")

    case = replace(
        get_time_history_case("plough_payout_matched_6min"),
        element_count=args.elements,
        total_duration_s=float(args.packets) * args.sample_interval_s,
        duration_s=float(args.packets) * args.sample_interval_s,
        plough_exit_speed_mps=0.8,
    )
    now = time.time()
    session = RealtimeSimulationSession(
        session_id="benchmark",
        base_case=case,
        initial_packet=packet(0, 0.0, now),
        max_sensor_gap_s=args.sample_interval_s * 1.1,
        max_data_age_s=10_000.0,
        clock=lambda: now,
    )
    wall_start = time.perf_counter()
    latencies = []
    failures = 0
    result = session.latest
    for sequence in range(1, args.packets + 1):
        try:
            result = session.advance(packet(sequence, sequence * args.sample_interval_s, now))
        except Exception:
            failures += 1
            break
        else:
            latencies.append(result.compute_wall_s)
    total_wall_s = time.perf_counter() - wall_start
    physical_duration_s = session.current_time_s
    report = {
        "packets": args.packets,
        "elements": args.elements,
        "sample_interval_s": args.sample_interval_s,
        "total_wall_s": total_wall_s,
        "failure_count": failures,
        "mean_frame_wall_s": statistics.fmean(latencies) if latencies else None,
        "p50_frame_wall_s": percentile(latencies, 0.50) if latencies else None,
        "p95_frame_wall_s": percentile(latencies, 0.95) if latencies else None,
        "p99_frame_wall_s": percentile(latencies, 0.99) if latencies else None,
        "max_frame_wall_s": max(latencies) if latencies else None,
        "sustained_realtime_factor": physical_duration_s / total_wall_s if total_wall_s > 0 else None,
        "wall_time_utilization": total_wall_s / physical_duration_s if physical_duration_s > 0 else None,
        "integration_time_step_min_s": result.integration_time_step_min_s,
        "integration_time_step_max_s": result.integration_time_step_max_s,
        "axial_constraint_residual_max_m": result.axial_constraint_residual_max_m,
        "final_sequence": session.current_sequence,
        "final_time_s": session.current_time_s,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


def packet(sequence: int, time_s: float, observed_at: float) -> RealtimeSensorPacket:
    return RealtimeSensorPacket(
        sequence=sequence,
        time_s=time_s,
        observed_at_unix_s=observed_at,
        quality="valid",
        vessel=SynchronizedEndpointSample(0.8 * time_s, 0.0, 0.0, 0.8, 0.0, 0.0),
        plough=SynchronizedEndpointSample(-55.0 + 0.8 * time_s, 0.0, 80.0, 0.8, 0.0, 0.0),
        payout_speed_mps=0.8,
        plough_exit_speed_mps=0.8,
        current_velocity_x_mps=0.0,
        current_velocity_y_mps=0.35,
    )


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(fraction * len(ordered) + 0.999999) - 1))
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(main())

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as viewer from "./DynamicFrameViewer";
import { Color, Vector3 } from "three";
import type { DynamicFrame, DynamicFramePlotData } from "./types";

describe("DynamicFrameViewer", () => {
  it("shows a draggable timeline, vessel/plough markers, and active frame tension values", () => {
    render(<viewer.DynamicFrameViewer frames={frames} summary={summary} />);

    expect(screen.getByRole("img", { name: "动态三维帧" })).toBeInTheDocument();
    expect(screen.getByText("3 帧 / 3 节点")).toBeInTheDocument();
    expect(screen.getByText("全局铺设视图")).toBeInTheDocument();
    expect(screen.getByText("铺缆船")).toBeInTheDocument();
    expect(screen.getByText("船尾出缆")).toBeInTheDocument();
    expect(screen.getByText("船首向前")).toBeInTheDocument();
    expect(screen.getByText("犁后铺缆轨迹")).toBeInTheDocument();
    expect(screen.getByText("离散节点")).toBeInTheDocument();
    expect(screen.getByText("埋设犁")).toBeInTheDocument();
    expect(screen.getByText("海面")).toBeInTheDocument();
    expect(screen.getByText("海床网格")).toBeInTheDocument();
    expect(screen.getByLabelText("水深刻度")).toBeInTheDocument();
    expect(screen.getByLabelText("三维图层")).toBeInTheDocument();
    expect(screen.getByText("张力颜色")).toBeInTheDocument();
    expect(screen.getByText("张力 (kN)")).toBeInTheDocument();
    expect(screen.getByText("鼠标拖拽旋转，滚轮缩放，右键平移")).toBeInTheDocument();
    expect(screen.getByText("来流方向")).toBeInTheDocument();
    expect(screen.getByText("90° / 0.35 m/s")).toBeInTheDocument();
    expect(screen.getByText("低 0.34 kN")).toBeInTheDocument();
    expect(screen.getByText("高 1.30 kN")).toBeInTheDocument();
    expect(screen.getByLabelText("TDP 运动轨迹")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("时间轴"), { target: { value: "2" } });

    expect(screen.getByText("60.0 s")).toBeInTheDocument();
    expect(screen.getByText("船位 X=75.00 m")).toBeInTheDocument();
    expect(screen.getByText("船端 1.00 kN")).toBeInTheDocument();
    expect(screen.getByText("中段 0.48 kN")).toBeInTheDocument();
    expect(screen.getByText("触地点 0.00 kN")).toBeInTheDocument();
  });

  it("keeps the bow on the travel heading and releases cable from the stern", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;

    expect(geometry).toBeDefined();
    expect(geometry?.vesselYawFromForwardDirection(new Vector3(0, 0, 1))).toBeCloseTo(0);
    expect(geometry?.vesselYawFromForwardDirection(new Vector3(0, 0, -1))).toBeCloseTo(Math.PI);
    expect(geometry?.vesselYawFromForwardDirection(new Vector3(1, 0, 0))).toBeCloseTo(Math.PI / 2);
    expect(geometry?.ploughYawFromForwardDirection(new Vector3(1, 0, 0))).toBeCloseTo(0);
    expect(geometry?.ploughYawFromForwardDirection(new Vector3(0, 0, 1))).toBeCloseTo(-Math.PI / 2);

    const forward = new Vector3(0, 0, 1);
    const stern = geometry?.sternScenePointFromForwardDirection(new Vector3(0, 0, 0), forward, 100);

    expect(stern?.x).toBeCloseTo(0);
    expect(stern?.z).toBeLessThan(0);
    expect(stern?.y).toBeLessThan(1);
  });

  it("positions the vessel model so its stern roller sits on the backend boundary point", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const backendStern = new Vector3(3, -12, 8);
    const forward = new Vector3(0, 0, 1);
    const modelOrigin = geometry?.vesselModelOriginFromSternPoint(backendStern, forward, 343);
    const reconstructedStern = geometry?.sternScenePointFromForwardDirection(modelOrigin!, forward, 343);

    expect(reconstructedStern?.x).toBeCloseTo(backendStern.x);
    expect(reconstructedStern?.y).toBeCloseTo(backendStern.y);
    expect(reconstructedStern?.z).toBeCloseTo(backendStern.z);
  });

  it("uses a low-distortion side engineering camera instead of looking down the laying axis", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 0, centerY: 0, centerZ: 0, span: 100 };
    const cameraPosition = geometry?.defaultCameraPosition(bounds);

    expect(geometry?.defaultCameraFovDeg()).toBeLessThanOrEqual(24);
    expect(cameraPosition?.length()).toBeGreaterThan(bounds.span * 2.3);
    expect(cameraPosition?.z).toBeGreaterThan(bounds.span * 2.25);
    expect(cameraPosition?.y).toBeGreaterThan(bounds.span * 0.5);
    expect(Math.abs(cameraPosition?.x ?? 0)).toBeLessThan(bounds.span * 0.25);
    expect((cameraPosition?.z ?? 0) / Math.max(Math.abs(cameraPosition?.x ?? 0), 1)).toBeGreaterThan(8);
  });

  it("keeps the frontend scene axes aligned with backend laying coordinates", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 10, centerY: 20, centerZ: 30, span: 100 };
    const mapped = geometry?.mapPoint({ index: 0, x_m: 14, y_m: 28, z_m: 45, tension_n: 0 }, bounds);
    const heading0 = geometry?.currentDirectionSceneVector(0);
    const heading90 = geometry?.currentDirectionSceneVector(90);

    expect(mapped?.x).toBeCloseTo(4);
    expect(mapped?.y).toBeCloseTo(-15);
    expect(mapped?.z).toBeCloseTo(8);
    expect(heading0?.x).toBeCloseTo(1);
    expect(heading0?.z).toBeCloseTo(0);
    expect(heading90?.x).toBeCloseTo(0);
    expect(heading90?.z).toBeCloseTo(1);
  });

  it("maps tension to a high-contrast blue-green-yellow-red ramp", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const range = { min: 0, max: 1000 };
    const low = geometry?.tensionColor(0, range);
    const mid = geometry?.tensionColor(500, range);
    const high = geometry?.tensionColor(1000, range);

    expect(low?.getHexString()).toBe("004dff");
    expect(mid?.getHexString()).toBe("00d85a");
    expect(high?.getHexString()).toBe("ff2a2a");
    expect(colorDistance(low!, mid!)).toBeGreaterThan(0.85);
    expect(colorDistance(mid!, high!)).toBeGreaterThan(0.95);
  });

  it("starts the cable at the hull stern endpoint and leaves astern before sagging", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 0, centerY: 0, centerZ: 0, span: 100 };
    const forward = new Vector3(0, 0, 1);
    const cablePoints = geometry?.buildCableVisualPoints(
      {
        time_s: 0,
        vessel_x_m: 0,
        vessel_y_m: 0,
        vessel_z_m: 0,
        plough_x_m: 0,
        plough_y_m: -55,
        plough_z_m: 78,
        points: [
          { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 200 },
          { index: 1, x_m: 0, y_m: -2.2917, z_m: 3.5694, tension_n: 200 },
          { index: 2, x_m: 0, y_m: -4.5833, z_m: 7.1111, tension_n: 200 },
          { index: 3, x_m: 0, y_m: -6.875, z_m: 10.625, tension_n: 200 },
        ],
      },
      bounds,
      forward,
    );

    expect(cablePoints).toBeDefined();
    const stern = cablePoints![0].position;
    const firstFairleadPoint = cablePoints![1].position;
    const astern = forward.clone().multiplyScalar(-1);
    const firstHorizontalDirection = firstFairleadPoint.clone().sub(stern);
    firstHorizontalDirection.y = 0;

    expect(firstFairleadPoint.z).toBeLessThan(stern.z);
    expect(firstHorizontalDirection.normalize().dot(astern)).toBeGreaterThan(0.98);
    expect(firstFairleadPoint.y).toBeLessThanOrEqual(stern.y);
  });

  it("uses the backend vessel boundary as the stern cable origin at full scene scale", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 0, centerY: 0, centerZ: 0, span: 343 };
    const frame: DynamicFrame = {
      time_s: 0,
      vessel_x_m: 0,
      vessel_y_m: 0,
      vessel_z_m: 0,
      plough_x_m: 0,
      plough_y_m: -55,
      plough_z_m: 78,
      points: [
        { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 200 },
        { index: 1, x_m: 0, y_m: -2.2917, z_m: 3.5694, tension_n: 200 },
        { index: 2, x_m: 0, y_m: -4.5833, z_m: 7.1111, tension_n: 200 },
        { index: 3, x_m: 0, y_m: -6.875, z_m: 10.625, tension_n: 200 },
      ],
    };
    const backendBoundary = geometry?.mapPoint(frame.points[0], bounds);
    const cablePoints = geometry?.buildCableVisualPoints(frame, bounds, new Vector3(0, 0, 1));
    const stern = cablePoints?.[0].position;
    const nearSternMaxForward = Math.max(...cablePoints!.slice(1, 5).map((point) => point.position.z - stern!.z));

    expect(stern?.x).toBeCloseTo(backendBoundary!.x);
    expect(stern?.y).toBeCloseTo(backendBoundary!.y);
    expect(stern?.z).toBeCloseTo(backendBoundary!.z);
    expect(nearSternMaxForward).toBeLessThanOrEqual(0);
  });

  it("routes the cable through the plough before forming the laid cable trajectory", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 0, centerY: 0, centerZ: 0, span: 100 };
    const forward = new Vector3(0, 0, 1);
    const frame: DynamicFrame = {
      time_s: 10,
      plough_x_m: 0,
      plough_y_m: 70,
      plough_z_m: 100,
      points: [
        { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 1000 },
        { index: 1, x_m: 0, y_m: 30, z_m: 60, tension_n: 700 },
        { index: 2, x_m: 0, y_m: 50, z_m: 100, tension_n: 500 },
      ],
    };

    const cablePoints = geometry?.buildCableVisualPoints(frame, bounds, forward);

    expect(cablePoints?.at(-1)?.position.x).toBeCloseTo(0);
    expect(cablePoints?.at(-1)?.position.y).toBeCloseTo(-100);
    expect(cablePoints?.at(-1)?.position.z).toBeCloseTo(70);

    const laidPoints = geometry?.laidCableScenePoints(
      [
        { ...frame, time_s: 0, plough_y_m: 10 },
        { ...frame, time_s: 10, plough_y_m: 70 },
        { ...frame, time_s: 20, plough_y_m: 120 },
      ],
      bounds,
      1,
    );

    expect(laidPoints).toHaveLength(2);
    expect(laidPoints?.[0].z).toBeCloseTo(10);
    expect(laidPoints?.[1].z).toBeCloseTo(70);
  });

  it("keeps the stern release point aligned with the first cable node to avoid foldback", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 0, centerY: 0, centerZ: 0, span: 100 };
    const cablePoints = geometry?.buildCableVisualPoints(
      {
        time_s: 0,
        vessel_x_m: 0,
        vessel_y_m: 0,
        vessel_z_m: 0,
        plough_x_m: 0,
        plough_y_m: -55,
        plough_z_m: 78,
        points: [
          { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 200 },
          { index: 1, x_m: 0, y_m: -2.2917, z_m: 3.5694, tension_n: 200 },
          { index: 2, x_m: 0, y_m: -4.5833, z_m: 7.1111, tension_n: 200 },
        ],
      },
      bounds,
      new Vector3(0, 0, 1),
    );
    const stern = cablePoints?.[0].position;
    const release = cablePoints?.[1].position;
    const firstCableNode = cablePoints?.[2].position;

    expect(stern).toBeDefined();
    expect(release).toBeDefined();
    expect(firstCableNode).toBeDefined();

    const cableDirection = firstCableNode!.clone().sub(stern!);
    const releaseDirection = release!.clone().sub(stern!);
    const projection = releaseDirection.dot(cableDirection);

    expect(projection).toBeGreaterThan(0);
    expect(projection).toBeLessThanOrEqual(cableDirection.lengthSq());
  });

  it("smooths the stern fairlead into the solver cable instead of drawing a sharp elbow", () => {
    const geometry = (viewer as typeof viewer & { dynamicFrameGeometryForTest?: GeometryHelpers }).dynamicFrameGeometryForTest;
    const bounds = { centerX: 0, centerY: 0, centerZ: 0, span: 100 };
    const cablePoints = geometry?.buildCableVisualPoints(
      {
        time_s: 0,
        vessel_x_m: 0,
        vessel_y_m: 0,
        vessel_z_m: 0,
        plough_x_m: 0,
        plough_y_m: -55,
        plough_z_m: 78,
        points: [
          { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 200 },
          { index: 1, x_m: 0, y_m: -2.2917, z_m: 3.5694, tension_n: 200 },
          { index: 2, x_m: 0, y_m: -4.5833, z_m: 7.1111, tension_n: 200 },
          { index: 3, x_m: 0, y_m: -6.875, z_m: 10.625, tension_n: 200 },
          { index: 4, x_m: 0, y_m: -9.1667, z_m: 14.1111, tension_n: 200 },
        ],
      },
      bounds,
      new Vector3(0, 0, 1),
    );

    expect(cablePoints).toBeDefined();
    const nearSternAngles = cablePoints!.slice(0, 8).flatMap((point, index, points) => {
      const previous = points[index - 1]?.position;
      const next = points[index + 1]?.position;
      if (!previous || !next) {
        return [];
      }
      return [turnAngleDeg(previous, point.position, next)];
    });

    expect(Math.max(...nearSternAngles)).toBeLessThan(35);
  });
});

interface GeometryHelpers {
  vesselYawFromForwardDirection(forwardDir: Vector3): number;
  ploughYawFromForwardDirection(forwardDir: Vector3): number;
  sternScenePointFromForwardDirection(origin: Vector3, forwardDir: Vector3, span: number): Vector3;
  buildCableVisualPoints(frame: DynamicFrame, bounds: { centerX: number; centerY: number; centerZ: number; span: number }, forwardDir: Vector3): Array<{ position: Vector3 }>;
  laidCableScenePoints(frames: DynamicFrame[], bounds: { centerX: number; centerY: number; centerZ: number; span: number }, activeFrameIndex: number): Vector3[];
  defaultCameraFovDeg(): number;
  defaultCameraPosition(bounds: { centerX: number; centerY: number; centerZ: number; span: number }): Vector3;
  tensionColor(value: number, range: { min: number; max: number }): Color;
  mapPoint(point: { index: number; x_m: number; y_m: number; z_m: number; tension_n: number }, bounds: { centerX: number; centerY: number; centerZ: number; span: number }): Vector3;
  currentDirectionSceneVector(directionDeg: number): Vector3;
  vesselModelOriginFromSternPoint(sternPoint: Vector3, forwardDir: Vector3, span: number): Vector3;
}

function turnAngleDeg(previous: Vector3, current: Vector3, next: Vector3): number {
  const incoming = current.clone().sub(previous).normalize();
  const outgoing = next.clone().sub(current).normalize();
  return (incoming.angleTo(outgoing) * 180) / Math.PI;
}

function colorDistance(left: Color, right: Color): number {
  return Math.hypot(left.r - right.r, left.g - right.g, left.b - right.b);
}

const frames: DynamicFramePlotData = {
  source: "test_frames",
  label: "动态三维帧",
  items: [
    {
      time_s: 0,
      segment_tensions_n: [1300, 350],
      points: [
        { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 1200 },
        { index: 1, x_m: 4, y_m: 20, z_m: 50, tension_n: 500 },
        { index: 2, x_m: 9, y_m: 50, z_m: 100, tension_n: 0 },
      ],
    },
    {
      time_s: 30,
      segment_tensions_n: [1250, 360],
      points: [
        { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 1100 },
        { index: 1, x_m: 5, y_m: 22, z_m: 50, tension_n: 520 },
        { index: 2, x_m: 12, y_m: 55, z_m: 100, tension_n: 0 },
      ],
    },
    {
      time_s: 60,
      segment_tensions_n: [1180, 340],
      points: [
        { index: 0, x_m: 0, y_m: 0, z_m: 0, tension_n: 1000 },
        { index: 1, x_m: 6, y_m: 24, z_m: 50, tension_n: 480 },
        { index: 2, x_m: 15, y_m: 61, z_m: 100, tension_n: 0 },
      ],
    },
  ],
};

const summary = {
  initial_speed_mps: 0.5,
  final_speed_mps: 1.5,
  duration_s: 30,
  total_duration_s: 60,
  current_speed_mps: 0.35,
  current_direction_deg: 90,
};

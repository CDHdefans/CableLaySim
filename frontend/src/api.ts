import type {
  CableCase,
  CustomCaseRequest,
  GroupedCases,
  HealthResponse,
  ReproductionMetadata,
  CreateRealtimeSessionRequest,
  RealtimeFrameResponse,
  RealtimeSensorPacket,
  RunCaseRequest,
  RunCaseResponse,
  RunTimeHistoryRequest,
  RunTimeHistoryResponse,
  TimeHistoryCase,
} from "./types";

export const DEFAULT_API_BASE = "http://127.0.0.1:8765";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function buildFileUrl(relativePath: string, apiBase = DEFAULT_API_BASE): string {
  // 后端只接受相对 output 目录的文件路径，这里逐段编码，保留目录层级。
  const encoded = relativePath
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `${trimSlash(apiBase)}/api/files/${encoded}`;
}

export async function getHealth(apiBase = DEFAULT_API_BASE): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${trimSlash(apiBase)}/api/health`);
}

export async function getCases(apiBase = DEFAULT_API_BASE): Promise<CableCase[]> {
  const payload = await requestJson<{ cases: CableCase[] }>(`${trimSlash(apiBase)}/api/cases`);
  return payload.cases;
}

export async function getTimeHistoryCases(apiBase = DEFAULT_API_BASE): Promise<TimeHistoryCase[]> {
  const payload = await requestJson<{ cases: TimeHistoryCase[] }>(`${trimSlash(apiBase)}/api/time-history-cases`);
  return payload.cases;
}

export async function runCase(
  request: RunCaseRequest,
  apiBase = DEFAULT_API_BASE,
): Promise<RunCaseResponse> {
  return requestJson<RunCaseResponse>(`${trimSlash(apiBase)}/api/run-case`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function runCustomCase(
  request: CustomCaseRequest,
  apiBase = DEFAULT_API_BASE,
): Promise<RunCaseResponse> {
  return requestJson<RunCaseResponse>(`${trimSlash(apiBase)}/api/run-custom-case`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function runTimeHistory(
  request: RunTimeHistoryRequest,
  apiBase = DEFAULT_API_BASE,
): Promise<RunTimeHistoryResponse> {
  return requestJson<RunTimeHistoryResponse>(`${trimSlash(apiBase)}/api/run-time-history`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function createRealtimeSession(
  request: CreateRealtimeSessionRequest,
  apiBase = DEFAULT_API_BASE,
): Promise<RealtimeFrameResponse> {
  return requestJson<RealtimeFrameResponse>(`${trimSlash(apiBase)}/api/realtime-sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export async function advanceRealtimeSession(
  sessionId: string,
  packet: RealtimeSensorPacket,
  apiBase = DEFAULT_API_BASE,
): Promise<RealtimeFrameResponse> {
  return requestJson<RealtimeFrameResponse>(
    `${trimSlash(apiBase)}/api/realtime-sessions/${encodeURIComponent(sessionId)}/samples`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(packet),
    },
  );
}

export async function getRealtimeSession(
  sessionId: string,
  apiBase = DEFAULT_API_BASE,
): Promise<RealtimeFrameResponse> {
  return requestJson<RealtimeFrameResponse>(
    `${trimSlash(apiBase)}/api/realtime-sessions/${encodeURIComponent(sessionId)}`,
  );
}

export async function deleteRealtimeSession(
  sessionId: string,
  apiBase = DEFAULT_API_BASE,
): Promise<void> {
  await requestJson<unknown>(`${trimSlash(apiBase)}/api/realtime-sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function getReproduction(apiBase = DEFAULT_API_BASE): Promise<ReproductionMetadata> {
  return requestJson<ReproductionMetadata>(`${trimSlash(apiBase)}/api/reproduction`);
}

export async function reproduce(points: number, apiBase = DEFAULT_API_BASE): Promise<ReproductionMetadata> {
  return requestJson<ReproductionMetadata>(`${trimSlash(apiBase)}/api/reproduce`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ points }),
  });
}

export function groupCases(cases: CableCase[]): GroupedCases[] {
  const order = ["LA", "HA", "500kV", "Other"];
  return order
    .map((label) => ({
      label,
      cases: cases
        .filter((item) => item.group === label && item.example === true)
        .sort((a, b) => (a.display_order ?? 999) - (b.display_order ?? 999) || a.label.localeCompare(b.label)),
    }))
    .filter((group) => group.cases.length > 0);
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = init === undefined ? await fetch(url) : await fetch(url, init);
  const payload = await response.json().catch(() => undefined);
  if (!response.ok) {
    const errorPayload = isRecord(payload) ? payload : {};
    throw new ApiError(
      response.status,
      stringValue(errorPayload.error, "request_failed"),
      stringValue(errorPayload.message, `Request failed with status ${response.status}`),
      errorPayload.details,
    );
  }
  return payload as T;
}

function trimSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

import type { Request } from "express";

type LogLevel = "debug" | "info" | "warn" | "error";

export function log(level: LogLevel, message: string, meta: Record<string, unknown> = {}): void {
  const payload = {
    level,
    message,
    ...meta,
    at: new Date().toISOString(),
  };
  // eslint-disable-next-line no-console
  console.log(JSON.stringify(payload));
}

export function requestMeta(req: Request): Record<string, unknown> {
  const anyReq = req as Request & { requestId?: string };
  return {
    requestId: anyReq.requestId,
    method: req.method,
    path: req.path,
  };
}


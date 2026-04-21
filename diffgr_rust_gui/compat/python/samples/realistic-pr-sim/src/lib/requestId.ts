import crypto from "node:crypto";
import type { NextFunction, Request, Response } from "express";

export type RequestWithId = Request & { requestId?: string };

export function requestIdMiddleware(req: RequestWithId, _res: Response, next: NextFunction): void {
  // Prefer crypto.randomUUID() when available, fall back to random bytes.
  req.requestId =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : crypto.randomBytes(16).toString("hex");
  next();
}


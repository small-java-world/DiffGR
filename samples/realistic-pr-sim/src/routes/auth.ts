import type { Request, Response } from "express";
import { ensureEmail, ensureNonEmpty } from "../lib/validate.js";
import { log, requestMeta } from "../lib/logger.js";

const attemptsByIp = new Map<string, { count: number; resetAt: number }>();

function allowLoginAttempt(ip: string): boolean {
  const now = Date.now();
  const windowMs = 10_000;
  const maxAttempts = 5;
  const current = attemptsByIp.get(ip);
  if (!current || current.resetAt < now) {
    attemptsByIp.set(ip, { count: 1, resetAt: now + windowMs });
    return true;
  }
  current.count += 1;
  return current.count <= maxAttempts;
}

export function postLogin(req: Request, res: Response): void {
  const ip = req.ip || "unknown";
  if (!allowLoginAttempt(ip)) {
    log("warn", "rate_limited", { ...requestMeta(req), ip });
    res.status(429).json({ error: "too_many_attempts" });
    return;
  }

  try {
    const email = ensureEmail((req.body || {}).email, "email");
    const password = ensureNonEmpty((req.body || {}).password, "password");
    const ok = password.length >= 8;
    if (!ok) {
      res.status(401).json({ error: "invalid_credentials" });
      return;
    }
    res.json({ token: `fake-jwt-for:${email}` });
  } catch (err) {
    log("info", "bad_request", { ...requestMeta(req), err: String(err) });
    res.status(400).json({ error: "bad_request" });
  }
}


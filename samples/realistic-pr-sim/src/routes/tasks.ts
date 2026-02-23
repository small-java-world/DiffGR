import type { Request, Response } from "express";
import { listTasks } from "../db/index.js";
import { clamp, parseIntStrict } from "../lib/validate.js";

export function getTasks(req: Request, res: Response): void {
  const rawLimit = String(req.query.limit ?? "20");
  const limit = clamp(parseIntStrict(rawLimit, 20), 1, 100);
  const cursor = typeof req.query.cursor === "string" ? req.query.cursor : null;

  const result = listTasks({ limit, cursor });
  res.json(result);
}


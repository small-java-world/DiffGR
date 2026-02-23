import express from "express";
import { requestIdMiddleware } from "./lib/requestId.js";
import { log, requestMeta } from "./lib/logger.js";
import { getTasks } from "./routes/tasks.js";
import { postLogin } from "./routes/auth.js";

export function buildApp() {
  const app = express();
  app.disable("x-powered-by");

  app.use(express.json({ limit: "64kb" }));
  app.use(requestIdMiddleware);
  app.use((req, res, next) => {
    const start = Date.now();
    res.on("finish", () => {
      log("info", "request", { ...requestMeta(req), status: res.statusCode, ms: Date.now() - start });
    });
    next();
  });

  app.get("/health", (_req, res) => res.json({ ok: true }));
  app.post("/auth/login", postLogin);
  app.get("/tasks", getTasks);

  app.use((err: unknown, req: express.Request, res: express.Response, _next: express.NextFunction) => {
    log("error", "unhandled_error", { ...requestMeta(req), err: String(err) });
    res.status(500).json({ error: "internal_error" });
  });

  return app;
}

export async function startServer(port: number): Promise<void> {
  const app = buildApp();
  const server = app.listen(port);
  log("info", "listening", { port });

  const shutdown = async (signal: string) => {
    log("warn", "shutdown", { signal });
    server.close();
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}


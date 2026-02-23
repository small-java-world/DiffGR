export type Task = {
  id: string;
  title: string;
  completed: boolean;
  dueAt?: string;
};

const tasks: Task[] = [
  { id: "t-001", title: "Write docs", completed: false, dueAt: "2026-03-01T12:00:00Z" },
  { id: "t-002", title: "Fix flaky test", completed: true },
  { id: "t-003", title: "Ship v0.3.0", completed: false },
];

export type ListTasksResult = { items: Task[]; nextCursor: string | null };

export function listTasks(opts: { limit: number; cursor: string | null }): ListTasksResult {
  const start = cursor ? Math.max(0, tasks.findIndex((t) => t.id === cursor) + 1) : 0;
  const end = Math.min(tasks.length, start + opts.limit);
  const items = tasks.slice(start, end);
  const nextCursor = end >= tasks.length ? null : tasks[end - 1]?.id ?? null;
  return { items, nextCursor };
}


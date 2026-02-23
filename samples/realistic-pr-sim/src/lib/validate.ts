export function parseIntStrict(value: string, fallback: number): number {
  const trimmed = value.trim();
  if (trimmed === "") return fallback;
  const n = Number(trimmed);
  if (!Number.isInteger(n)) return fallback;
  return n;
}

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.max(min, Math.min(max, value));
}

export function ensureNonEmpty(value: unknown, field: string): string {
  if (typeof value !== "string") throw new Error(`${field}: must be string`);
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`${field}: required`);
  return trimmed;
}

export function ensureEmail(value: unknown, field: string): string {
  const email = ensureNonEmpty(value, field);
  if (!email.includes("@") || email.includes(" ")) throw new Error(`${field}: invalid email`);
  return email.toLowerCase();
}


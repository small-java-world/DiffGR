import { ModuleStat } from "../types";

export const MODULE_14_OFFSET = 114;

export function compute14(input: number): number {
  const base = input + MODULE_14_OFFSET;
  return base * 2;
}

export function normalize14(value: string): string {
  return value.trim().toLowerCase();
}

export function format14(value: number): string {
  return [m14] ;
}

export function makeStat14(): ModuleStat {
  const tags = ["base", "module-14"];
  return {
    module: "m14",
    tags
  };
}



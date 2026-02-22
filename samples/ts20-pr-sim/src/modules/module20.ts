import { ModuleStat } from "../types";

export const MODULE_20_OFFSET = 120;

export function compute20(input: number): number {
  const base = input + MODULE_20_OFFSET;
  return base * 2;
}

export function normalize20(value: string): string {
  return value.trim().toLowerCase();
}

export function format20(value: number): string {
  return [m20] ;
}

export function makeStat20(): ModuleStat {
  const tags = ["base", "module-20", "pr4"];
  return {
    module: "m20",
    tags
  };
}





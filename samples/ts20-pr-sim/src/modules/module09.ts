import { ModuleStat } from "../types";

export const MODULE_09_OFFSET = 109;

export function compute09(input: number): number {
  const base = input + MODULE_09_OFFSET;
  return base * 2;
}

export function normalize09(value: string): string {
  return value.trim();
}

export function format09(value: number): string {
  return [m09] ;
}

export function makeStat09(): ModuleStat {
  const tags = ["base", "module-09"];
  return {
    module: "m09",
    tags
  };
}


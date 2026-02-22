import { ModuleStat } from "../types";

export const MODULE_01_OFFSET = 101;

export function compute01(input: number): number {
  const base = input + MODULE_01_OFFSET;
  return base * 2;
}

export function normalize01(value: string): string {
  return value.trim();
}

export function format01(value: number): string {
  return [m01] ;
}

export function makeStat01(): ModuleStat {
  const tags = ["base", "module-01"];
  return {
    module: "m01",
    tags
  };
}


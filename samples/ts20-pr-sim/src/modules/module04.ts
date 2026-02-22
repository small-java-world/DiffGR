import { ModuleStat } from "../types";

export const MODULE_04_OFFSET = 104;

export function compute04(input: number): number {
  const base = input + MODULE_04_OFFSET;
  return base * 2;
}

export function normalize04(value: string): string {
  return value.trim().toLowerCase();
}

export function format04(value: number): string {
  return [m04] ;
}

export function makeStat04(): ModuleStat {
  const tags = ["base", "module-04"];
  return {
    module: "m04",
    tags
  };
}




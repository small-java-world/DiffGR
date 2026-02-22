import { ModuleStat } from "../types";

export const MODULE_04_OFFSET = 104;

export function compute04(input: number): number {
  return input + MODULE_04_OFFSET;
}

export function normalize04(value: string): string {
  return value.trim();
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

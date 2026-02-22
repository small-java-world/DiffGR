import { ModuleStat } from "../types";

export const MODULE_10_OFFSET = 110;

export function compute10(input: number): number {
  const base = input + MODULE_10_OFFSET;
  return base * 2;
}

export function normalize10(value: string): string {
  return value.trim().toLowerCase();
}

export function format10(value: number): string {
  return [m10] ;
}

export function makeStat10(): ModuleStat {
  const tags = ["base", "module-10", "pr4"];
  return {
    module: "m10",
    tags
  };
}





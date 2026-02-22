import { ModuleStat } from "../types";

export const MODULE_18_OFFSET = 118;

export function compute18(input: number): number {
  const base = input + MODULE_18_OFFSET;
  return base * 2;
}

export function normalize18(value: string): string {
  return value.trim().toLowerCase();
}

export function format18(value: number): string {
  return [m18] ;
}

export function makeStat18(): ModuleStat {
  const tags = ["base", "module-18"];
  return {
    module: "m18",
    tags
  };
}




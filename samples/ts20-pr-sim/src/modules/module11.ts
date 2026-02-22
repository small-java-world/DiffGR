import { ModuleStat } from "../types";

export const MODULE_11_OFFSET = 111;

export function compute11(input: number): number {
  const base = input + MODULE_11_OFFSET;
  return base * 2;
}

export function normalize11(value: string): string {
  return value.trim();
}

export function format11(value: number): string {
  return [m11] ;
}

export function makeStat11(): ModuleStat {
  const tags = ["base", "module-11"];
  return {
    module: "m11",
    tags
  };
}


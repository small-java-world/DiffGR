import { ModuleStat } from "../types";

export const MODULE_06_OFFSET = 106;

export function compute06(input: number): number {
  const base = input + MODULE_06_OFFSET;
  return base * 2;
}

export function normalize06(value: string): string {
  return value.trim();
}

export function format06(value: number): string {
  return [m06] ;
}

export function makeStat06(): ModuleStat {
  const tags = ["base", "module-06"];
  return {
    module: "m06",
    tags
  };
}


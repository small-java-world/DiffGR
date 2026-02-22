import { ModuleStat } from "../types";

export const MODULE_07_OFFSET = 107;

export function compute07(input: number): number {
  const base = input + MODULE_07_OFFSET;
  return base * 2;
}

export function normalize07(value: string): string {
  return value.trim().toLowerCase();
}

export function format07(value: number): string {
  return [m07] ;
}

export function makeStat07(): ModuleStat {
  const tags = ["base", "module-07"];
  return {
    module: "m07",
    tags
  };
}



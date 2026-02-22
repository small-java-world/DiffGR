import { ModuleStat } from "../types";

export const MODULE_07_OFFSET = 107;

export function compute07(input: number): number {
  return input + MODULE_07_OFFSET;
}

export function normalize07(value: string): string {
  return value.trim();
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

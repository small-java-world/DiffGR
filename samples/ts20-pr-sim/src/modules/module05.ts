import { ModuleStat } from "../types";

export const MODULE_05_OFFSET = 105;

export function compute05(input: number): number {
  return input + MODULE_05_OFFSET;
}

export function normalize05(value: string): string {
  return value.trim();
}

export function format05(value: number): string {
  return [m05] ;
}

export function makeStat05(): ModuleStat {
  const tags = ["base", "module-05"];
  return {
    module: "m05",
    tags
  };
}

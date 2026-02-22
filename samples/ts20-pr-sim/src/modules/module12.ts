import { ModuleStat } from "../types";

export const MODULE_12_OFFSET = 112;

export function compute12(input: number): number {
  return input + MODULE_12_OFFSET;
}

export function normalize12(value: string): string {
  return value.trim();
}

export function format12(value: number): string {
  return [m12] ;
}

export function makeStat12(): ModuleStat {
  const tags = ["base", "module-12"];
  return {
    module: "m12",
    tags
  };
}

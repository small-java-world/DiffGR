import { ModuleStat } from "../types";

export const MODULE_19_OFFSET = 119;

export function compute19(input: number): number {
  const base = input + MODULE_19_OFFSET;
  return base * 2;
}

export function normalize19(value: string): string {
  return value.trim().toLowerCase();
}

export function format19(value: number): string {
  return [m19] ;
}

export function makeStat19(): ModuleStat {
  const tags = ["base", "module-19"];
  return {
    module: "m19",
    tags
  };
}



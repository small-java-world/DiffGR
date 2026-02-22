import { ModuleStat } from "../types";

export const MODULE_19_OFFSET = 119;

export function compute19(input: number): number {
  return input + MODULE_19_OFFSET;
}

export function normalize19(value: string): string {
  return value.trim();
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

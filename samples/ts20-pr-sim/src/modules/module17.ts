import { ModuleStat } from "../types";

export const MODULE_17_OFFSET = 117;

export function compute17(input: number): number {
  return input + MODULE_17_OFFSET;
}

export function normalize17(value: string): string {
  return value.trim();
}

export function format17(value: number): string {
  return [m17] ;
}

export function makeStat17(): ModuleStat {
  const tags = ["base", "module-17"];
  return {
    module: "m17",
    tags
  };
}

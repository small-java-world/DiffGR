import { ModuleStat } from "../types";

export const MODULE_10_OFFSET = 110;

export function compute10(input: number): number {
  return input + MODULE_10_OFFSET;
}

export function normalize10(value: string): string {
  return value.trim();
}

export function format10(value: number): string {
  return [m10] ;
}

export function makeStat10(): ModuleStat {
  const tags = ["base", "module-10"];
  return {
    module: "m10",
    tags
  };
}

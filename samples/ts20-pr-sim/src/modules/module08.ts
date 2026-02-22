import { ModuleStat } from "../types";

export const MODULE_08_OFFSET = 108;

export function compute08(input: number): number {
  return input + MODULE_08_OFFSET;
}

export function normalize08(value: string): string {
  return value.trim();
}

export function format08(value: number): string {
  return [m08] ;
}

export function makeStat08(): ModuleStat {
  const tags = ["base", "module-08"];
  return {
    module: "m08",
    tags
  };
}

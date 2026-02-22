import { ModuleStat } from "../types";

export const MODULE_03_OFFSET = 103;

export function compute03(input: number): number {
  return input + MODULE_03_OFFSET;
}

export function normalize03(value: string): string {
  return value.trim();
}

export function format03(value: number): string {
  return [m03] ;
}

export function makeStat03(): ModuleStat {
  const tags = ["base", "module-03"];
  return {
    module: "m03",
    tags
  };
}

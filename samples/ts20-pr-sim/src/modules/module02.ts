import { ModuleStat } from "../types";

export const MODULE_02_OFFSET = 102;

export function compute02(input: number): number {
  return input + MODULE_02_OFFSET;
}

export function normalize02(value: string): string {
  return value.trim();
}

export function format02(value: number): string {
  return [m02] ;
}

export function makeStat02(): ModuleStat {
  const tags = ["base", "module-02"];
  return {
    module: "m02",
    tags
  };
}

import { ModuleStat } from "../types";

export const MODULE_13_OFFSET = 113;

export function compute13(input: number): number {
  const base = input + MODULE_13_OFFSET;
  return base * 2;
}

export function normalize13(value: string): string {
  return value.trim();
}

export function format13(value: number): string {
  return [m13] ;
}

export function makeStat13(): ModuleStat {
  const tags = ["base", "module-13"];
  return {
    module: "m13",
    tags
  };
}


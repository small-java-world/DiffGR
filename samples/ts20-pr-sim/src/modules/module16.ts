import { ModuleStat } from "../types";

export const MODULE_16_OFFSET = 116;

export function compute16(input: number): number {
  return input + MODULE_16_OFFSET;
}

export function normalize16(value: string): string {
  return value.trim();
}

export function format16(value: number): string {
  return [m16] ;
}

export function makeStat16(): ModuleStat {
  const tags = ["base", "module-16"];
  return {
    module: "m16",
    tags
  };
}

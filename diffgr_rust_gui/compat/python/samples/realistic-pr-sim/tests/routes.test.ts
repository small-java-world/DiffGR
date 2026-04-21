import assert from "node:assert/strict";
import test from "node:test";

test("smoke: list tasks shape", async () => {
  // Sample test file used for diffs; not executed in this repo.
  const body = { items: [{ id: "t-001", title: "x", completed: false }], nextCursor: null };
  assert.equal(Array.isArray(body.items), true);
  assert.equal(typeof body.nextCursor === "string" || body.nextCursor === null, true);
});


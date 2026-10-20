import assert from "node:assert/strict";
import test from "node:test";
import { isTerminalStatus } from "../src/api/types.ts";

test("terminal status checks agree for polling, forms and progress", () => {
  for (const status of ["completed", "failed", "cancelled"]) {
    assert.equal(isTerminalStatus(status), true);
  }
  for (const status of [null, "queued", "loading_model", "downloading", "extracting_audio", "transcribing", "exporting", "cancelling"]) {
    assert.equal(isTerminalStatus(status), false);
  }
});

import assert from "node:assert/strict";
import test from "node:test";

import { JOB_STORAGE_KEY, reducer, restoreJob } from "../src/context/jobState.ts";
import { loadJobUpdate } from "../src/lib/jobPolling.ts";

test("reload restores the saved job without discarding it", () => {
  const restored = restoreJob({ getItem: (key) => key === JOB_STORAGE_KEY ? "job_123abc" : null });
  assert.equal(restored.jobId, "job_123abc");
  assert.equal(restored.status, "queued");
  assert.equal(restoreJob({ getItem: () => "../invalid" }).jobId, null);
  assert.equal(restoreJob({ getItem: () => { throw Error("blocked"); } }).jobId, null);
});

test("connection failure preserves work and successful polling clears the warning", () => {
  const initial = restoreJob({ getItem: () => "job_123abc" });
  const disconnected = reducer(initial, { type: "CONNECTION_ERROR", message: "Reintentando" });
  assert.equal(disconnected.jobId, initial.jobId);
  assert.equal(disconnected.connectionMessage, "Reintentando");
  const recovered = reducer(disconnected, {
    type: "UPDATE_STATUS", status: "transcribing", stageMessage: "Procesando", progressPercent: 30, error: null,
  });
  assert.equal(recovered.connectionMessage, null);
  assert.equal(recovered.progressPercent, 30);
});

test("completed jobs fetch their saved result before returning a completed update", async () => {
  const paths = [];
  const result = { text: "Transcripción recuperada" };
  const update = await loadJobUpdate("job_123abc", async (path) => {
    paths.push(path);
    return path.endsWith("/result") ? result : { status: "completed" };
  });
  assert.deepEqual(paths, ["/api/jobs/job_123abc", "/api/jobs/job_123abc/result"]);
  assert.equal(update.result, result);
});

test("a failed result fetch propagates so polling can retry instead of showing empty completion", async () => {
  await assert.rejects(loadJobUpdate("job_123abc", async (path) => {
    if (path.endsWith("/result")) throw Error("connection lost");
    return { status: "completed" };
  }), /connection lost/);
});

test("an in-progress job never requests its result", async () => {
  let requests = 0;
  const update = await loadJobUpdate("job_123abc", async () => {
    requests += 1;
    return { status: "loading_model" };
  });
  assert.equal(requests, 1);
  assert.equal(update.result, null);
});

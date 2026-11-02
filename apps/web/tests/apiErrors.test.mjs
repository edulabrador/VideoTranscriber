import assert from "node:assert/strict";
import test from "node:test";

import { errorDetail, fallbackMessage, formatBytes } from "../src/lib/apiErrors.ts";

test("validation lists become one readable sentence, not [object Object]", () => {
  const detail = [
    {
      type: "string_pattern_mismatch",
      loc: ["body", "speakers", "Hablante 1"],
      msg: "String should match pattern '^[^\\r\\n<>]+$'",
    },
    { type: "string_too_long", loc: ["body", "segments", 0, "text"], msg: "too long" },
  ];
  const { code, message } = errorDetail(detail, "fallback");
  assert.equal(code, "invalid_request");
  assert.equal(
    message,
    "El nombre de un hablante contiene caracteres no permitidos (< > o saltos de línea). " +
      "El texto de un fragmento es demasiado largo.",
  );
  assert.doesNotMatch(message, /object Object/);
});

test("string and coded details are kept, anything else falls back", () => {
  assert.deepEqual(errorDetail("No encontrado", "x"), { message: "No encontrado" });
  assert.deepEqual(errorDetail({ code: "summary_failed", message: "Ollama caído" }, "x"), {
    code: "summary_failed",
    message: "Ollama caído",
  });
  assert.deepEqual(errorDetail(undefined, "x"), { message: "x" });
  assert.deepEqual(errorDetail([{ foo: 1 }], "x"), { code: "invalid_request", message: "x" });
  assert.match(fallbackMessage(413), /tamaño/);
});

test("sizes are shown in MB or GB", () => {
  assert.equal(formatBytes(512 * 1024 * 1024), "512 MB");
  assert.equal(formatBytes(1.5 * 1024 ** 3), "1,5 GB");
});

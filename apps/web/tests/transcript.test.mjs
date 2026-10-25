import assert from "node:assert/strict";
import test from "node:test";

import { copyableText, speakers } from "../src/lib/transcript.ts";

const segment = (text, speaker) => ({ start: 0, end: 1, text, words: [], speaker });

test("copied text groups consecutive segments by speaker", () => {
  const result = {
    text: "Hola. ¿Qué tal? Bien.",
    segments: [segment("Hola.", "Hablante 1"), segment("¿Qué tal?", "Hablante 1"), segment("Bien.", "Hablante 2")],
  };
  assert.deepEqual(speakers(result), ["Hablante 1", "Hablante 2"]);
  assert.equal(copyableText(result), "Hablante 1: Hola. ¿Qué tal?\n\nHablante 2: Bien.");
});

test("transcripts without speakers copy the plain text", () => {
  const result = { text: "Hola. Adiós.", segments: [segment("Hola."), segment("Adiós.")] };
  assert.deepEqual(speakers(result), []);
  assert.equal(copyableText(result), "Hola. Adiós.");
});

import { highlightParts, segmentAt, transcriptEdits } from "../src/lib/transcript.ts";

test("search highlights every match regardless of case", () => {
  assert.deepEqual(highlightParts("Hola hola HOLA", "hola").filter((p) => p.match).length, 3);
  assert.deepEqual(highlightParts("Sin coincidencias", "xyz"), [{ text: "Sin coincidencias", match: false }]);
  assert.deepEqual(highlightParts("texto", ""), [{ text: "texto", match: false }]);
});

test("playback position maps to the segment being heard", () => {
  const segments = [segment("a"), segment("b"), segment("c")].map((s, i) => ({ ...s, start: i * 10, end: i * 10 + 5 }));
  assert.equal(segmentAt(segments, 0), 0);
  assert.equal(segmentAt(segments, 12), 1);
  assert.equal(segmentAt(segments, 8), -1);
  assert.equal(segmentAt(segments, 99), -1);
});

test("only real changes are sent when saving edits", () => {
  const result = { text: "", segments: [segment("Hola."), segment("Adiós.")] };
  assert.deepEqual(
    transcriptEdits(result, { 0: "Hola. ", 1: "Hasta luego." }, { "Hablante 1": " Ana ", "Hablante 2": "" }),
    { segments: [{ index: 1, text: "Hasta luego." }], speakers: { "Hablante 1": "Ana" } },
  );
});

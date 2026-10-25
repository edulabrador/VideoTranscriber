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

import assert from "node:assert/strict";
import test from "node:test";

import { isKnownPlatformUrl, parseUrlList, timestampLink } from "../src/lib/videoUrls.ts";

test("known platforms are still recognised", () => {
  assert.equal(isKnownPlatformUrl("https://youtu.be/BaW_jenozKc"), true);
  assert.equal(isKnownPlatformUrl("https://www.instagram.com/reel/ABC_123/"), true);
  assert.equal(isKnownPlatformUrl("https://vimeo.com/123"), false);
});

test("pasted batches become unique links and keep invalid tokens apart", () => {
  const { urls, invalid } = parseUrlList(
    "https://youtu.be/a\n https://vimeo.com/1  https://youtu.be/a\nnot-a-link ftp://x.y/z",
  );
  assert.deepEqual(urls, ["https://youtu.be/a", "https://vimeo.com/1"]);
  assert.deepEqual(invalid, ["not-a-link", "ftp://x.y/z"]);
});

test("timestamps link to the right second on YouTube only", () => {
  assert.equal(
    timestampLink("https://www.youtube.com/watch?v=BaW_jenozKc&t=3", 75.9),
    "https://www.youtube.com/watch?v=BaW_jenozKc&t=75s",
  );
  assert.equal(timestampLink("https://vimeo.com/123", 10), null);
  assert.equal(timestampLink(undefined, 10), null);
});

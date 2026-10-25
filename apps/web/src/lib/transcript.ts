import type { TranscriptResult } from "../api/types";

/** Speaker names in order of appearance. */
export function speakers(result: TranscriptResult): string[] {
  const names: string[] = [];
  for (const segment of result.segments) {
    if (segment.speaker && !names.includes(segment.speaker)) names.push(segment.speaker);
  }
  return names;
}

/** Text to copy: plain text, or one "Speaker: ..." paragraph per speaker turn. */
export function copyableText(result: TranscriptResult): string {
  if (!speakers(result).length) return result.text;
  const turns: { speaker: string | null; parts: string[] }[] = [];
  for (const segment of result.segments) {
    const speaker = segment.speaker ?? null;
    const last = turns[turns.length - 1];
    if (last && last.speaker === speaker) last.parts.push(segment.text);
    else turns.push({ speaker, parts: [segment.text] });
  }
  return turns
    .map(({ speaker, parts }) => (speaker ? `${speaker}: ` : "") + parts.join(" "))
    .join("\n\n");
}

/** Split text into plain and matching parts for highlighting, ignoring case. */
export function highlightParts(text: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim().toLocaleLowerCase("es");
  if (!needle) return [{ text, match: false }];
  const haystack = text.toLocaleLowerCase("es");
  const parts: { text: string; match: boolean }[] = [];
  let cursor = 0;
  for (let found = haystack.indexOf(needle); found !== -1; found = haystack.indexOf(needle, cursor)) {
    if (found > cursor) parts.push({ text: text.slice(cursor, found), match: false });
    parts.push({ text: text.slice(found, found + needle.length), match: true });
    cursor = found + needle.length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false });
  return parts;
}

/** Index of the segment playing at a given second, or -1. */
export function segmentAt(segments: TranscriptResult["segments"], seconds: number): number {
  let low = 0;
  let high = segments.length - 1;
  let candidate = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (segments[middle].start <= seconds) {
      candidate = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return candidate !== -1 && seconds <= segments[candidate].end + 1 ? candidate : -1;
}

/** Changes between the original transcript and the edited drafts, ready for the API. */
export function transcriptEdits(
  result: TranscriptResult,
  texts: Record<number, string>,
  names: Record<string, string>,
) {
  const segments = Object.entries(texts)
    .map(([index, text]) => ({ index: Number(index), text: text.trim() }))
    .filter(({ index, text }) => result.segments[index] && result.segments[index].text !== text);
  const speakers = Object.fromEntries(
    Object.entries(names)
      .map(([old, name]) => [old, name.trim()])
      .filter(([old, name]) => name && name !== old),
  );
  return { segments, speakers };
}

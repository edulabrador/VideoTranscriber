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

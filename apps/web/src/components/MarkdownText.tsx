import type { ReactNode } from "react";

/** Inline **bold** and _italic_ as React elements; everything else stays text. */
function inline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*|_[^_]+_)/g)
    .filter(Boolean)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : part.startsWith("_") && part.endsWith("_") && part.length > 2 ? (
        <em key={index}>{part.slice(1, -1)}</em>
      ) : (
        part
      ),
    );
}

/**
 * The small Markdown subset local models write: headings, bullets and paragraphs.
 * Built from React elements, never innerHTML, so model output cannot inject markup.
 */
export function MarkdownText({ source }: { source: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      blocks.push(
        <ul key={blocks.length}>
          {bullets.map((item, index) => (
            <li key={index}>{inline(item)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  for (const raw of source.split("\n")) {
    const line = raw.trim();
    const bullet = /^[-*•]\s+(.*)$/.exec(line) ?? /^\d+[.)]\s+(.*)$/.exec(line);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    flush();
    if (!line) continue;
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const Tag = heading[1].length === 1 ? "h3" : "h4";
      blocks.push(<Tag key={blocks.length}>{inline(heading[2])}</Tag>);
    } else {
      blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <>{blocks}</>;
}

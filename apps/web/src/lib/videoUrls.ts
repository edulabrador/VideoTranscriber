const KNOWN_PLATFORM_PATTERN =
  /^https?:\/\/(?:(?:www\.|m\.)?instagram\.com\/(?:reel|reels|p|tv)\/[A-Za-z0-9_-]+|(?:www\.|m\.)?tiktok\.com\/@[^/]+\/video\/\d+|(?:www\.)?(?:vm|vt)\.tiktok\.com\/[A-Za-z0-9_-]+|(?:www\.|mobile\.)?(?:x\.com|twitter\.com)\/[^/]+\/status\/\d+(?:\/(?:video|photo)\/\d+|\/[Mm]edia[Vv]iewer)?)\/?(?:\?.*)?$/;

const YOUTUBE_HOSTS = ["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"];

export function youtubeVideoId(source: string): string | null {
  try {
    const url = new URL(source.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    const host = url.hostname.toLowerCase();
    let videoId = "";
    if (host === "youtu.be" || host === "www.youtu.be") {
      videoId = url.pathname.split("/").filter(Boolean)[0] ?? "";
    } else if (YOUTUBE_HOSTS.includes(host)) {
      if (url.pathname.replace(/\/$/, "") === "/watch") {
        videoId = url.searchParams.get("v") ?? "";
      } else {
        const parts = url.pathname.split("/").filter(Boolean);
        if (parts.length === 2 && ["shorts", "live", "embed"].includes(parts[0])) {
          videoId = parts[1];
        }
      }
    }
    return /^[A-Za-z0-9_-]+$/.test(videoId) ? videoId : null;
  } catch {
    return null;
  }
}

/** YouTube, Instagram, TikTok and X links, the platforms with dedicated handling. */
export function isKnownPlatformUrl(source: string): boolean {
  const value = source.trim();
  return KNOWN_PLATFORM_PATTERN.test(value) || youtubeVideoId(value) !== null;
}

/** Any web link. The server decides whether yt-dlp supports the site. */
export function isWebUrl(source: string): boolean {
  try {
    const url = new URL(source.trim());
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname);
  } catch {
    return false;
  }
}

/** Split pasted text into unique links, one per line or separated by spaces. */
export function parseUrlList(text: string): { urls: string[]; invalid: string[] } {
  const urls: string[] = [];
  const invalid: string[] = [];
  for (const token of text.split(/\s+/).map((value) => value.trim()).filter(Boolean)) {
    if (!isWebUrl(token)) invalid.push(token);
    else if (!urls.includes(token)) urls.push(token);
  }
  return { urls, invalid };
}

/** Link that opens a YouTube video at a given second, or null for other sources. */
export function timestampLink(source: string | undefined, seconds: number): string | null {
  const videoId = source ? youtubeVideoId(source) : null;
  return videoId ? `https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(seconds)}s` : null;
}

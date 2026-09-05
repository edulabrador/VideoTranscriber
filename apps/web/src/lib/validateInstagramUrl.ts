const SUPPORTED_URL_PATTERN =
  /^https?:\/\/(?:(?:www\.|m\.)?instagram\.com\/(?:reel|reels|p|tv)\/[A-Za-z0-9_-]+|(?:www\.|m\.)?tiktok\.com\/@[^/]+\/video\/\d+|(?:www\.)?(?:vm|vt)\.tiktok\.com\/[A-Za-z0-9_-]+|(?:www\.|mobile\.)?(?:x\.com|twitter\.com)\/[^/]+\/status\/\d+(?:\/(?:video|photo)\/\d+|\/[Mm]edia[Vv]iewer)?)\/?(?:\?.*)?$/;

export function isInstagramUrl(source: string): boolean {
  const value = source.trim();
  if (SUPPORTED_URL_PATTERN.test(value)) return true;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;

    const host = url.hostname.toLowerCase();
    let videoId = "";
    if (host === "youtu.be" || host === "www.youtu.be") {
      videoId = url.pathname.split("/").filter(Boolean)[0] ?? "";
    } else if (["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"].includes(host)) {
      if (url.pathname.replace(/\/$/, "") === "/watch") {
        videoId = url.searchParams.get("v") ?? "";
      } else {
        const parts = url.pathname.split("/").filter(Boolean);
        if (parts.length === 2 && ["shorts", "live", "embed"].includes(parts[0])) {
          videoId = parts[1];
        }
      }
    }
    return /^[A-Za-z0-9_-]+$/.test(videoId);
  } catch {
    return false;
  }
}

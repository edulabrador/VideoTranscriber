const SUPPORTED_URL_PATTERN =
  /^https?:\/\/(?:(?:www\.|m\.)?instagram\.com\/(?:reel|reels|p|tv)\/[A-Za-z0-9_-]+|(?:www\.|m\.)?tiktok\.com\/@[^/]+\/video\/\d+|(?:www\.)?(?:vm|vt)\.tiktok\.com\/[A-Za-z0-9_-]+|(?:www\.|mobile\.)?(?:x\.com|twitter\.com)\/[^/]+\/status\/\d+(?:\/(?:video|photo)\/\d+|\/[Mm]edia[Vv]iewer)?)\/?(?:\?.*)?$/;

export function isInstagramUrl(source: string): boolean {
  return SUPPORTED_URL_PATTERN.test(source.trim());
}

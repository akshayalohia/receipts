import { json, error } from "./_lib.js";

const ALLOWED_HOSTS = new Set(["x.com", "twitter.com", "mobile.twitter.com"]);
const STATUS_PATH_RE = /^\/([A-Za-z0-9_]{1,15})\/status(?:es)?\/(\d{1,25})\/?$/;

const ENTITIES = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  mdash: "-",
  ndash: "-",
  hellip: "...",
  rsquo: "'",
  lsquo: "'",
  rdquo: '"',
  ldquo: '"',
};

export function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, code) => {
    if (code[0] === "#") {
      const n = code[1] === "x" || code[1] === "X" ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      return Number.isFinite(n) && n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : m;
    }
    const v = ENTITIES[code.toLowerCase()];
    return v === undefined ? m : v;
  });
}

export function stripTags(html) {
  return decodeEntities(
    html
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<[^>]*>/g, ""),
  )
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

/** Validate and normalise a tweet URL. Returns {url, handle, id} or null. */
export function parseTweetUrl(raw) {
  if (!raw || typeof raw !== "string" || raw.length > 500) return null;
  let u;
  try {
    u = new URL(raw);
  } catch {
    return null;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  const host = u.hostname.toLowerCase();
  if (!ALLOWED_HOSTS.has(host)) return null;
  if (u.username || u.password || (u.port && u.port !== "443" && u.port !== "80")) return null;
  const m = STATUS_PATH_RE.exec(u.pathname);
  if (!m) return null;
  return { url: `https://x.com/${m[1]}/status/${m[2]}`, handle: m[1], id: m[2] };
}

/** Parse an oEmbed response body into {handle, author_name, text, date}. */
export function parseOembed(data, fallbackHandle) {
  const html = String((data && data.html) || "");
  const pMatch = /<p\b[^>]*>([\s\S]*?)<\/p>/i.exec(html);
  const text = pMatch ? stripTags(pMatch[1]) : "";

  // Date is the text of the last link in the blockquote ("October 1, 2026").
  const links = [...html.matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/gi)];
  const date = links.length ? stripTags(links[links.length - 1][1]) : "";

  let handle = "";
  const authorUrl = String((data && data.author_url) || "");
  const am = /^https?:\/\/(?:www\.|mobile\.)?(?:twitter|x)\.com\/([A-Za-z0-9_]{1,15})\/?$/i.exec(authorUrl);
  if (am) handle = am[1];
  if (!handle) {
    const hm = /\(@([A-Za-z0-9_]{1,15})\)/.exec(stripTags(html.replace(pMatch ? pMatch[0] : "", "")));
    if (hm) handle = hm[1];
  }
  if (!handle) handle = fallbackHandle || "";

  const author_name = stripTags(String((data && data.author_name) || "")) || handle;
  return { handle, author_name, text: text.slice(0, 1000), date };
}

export async function GET(request) {
  const reqUrl = new URL(request.url);
  const parsed = parseTweetUrl(reqUrl.searchParams.get("url"));
  if (!parsed) return error(400, "url must be an x.com or twitter.com status link");

  const oembedUrl =
    "https://publish.twitter.com/oembed?omit_script=1&url=" + encodeURIComponent(parsed.url);
  let res;
  try {
    res = await fetch(oembedUrl, { headers: { accept: "application/json" } });
  } catch {
    return error(502, "tweet lookup failed");
  }
  if (res.status === 404 || res.status === 403) return error(404, "tweet not found or not public");
  if (!res.ok) return error(502, "tweet lookup failed");

  let data;
  try {
    data = await res.json();
  } catch {
    return error(502, "tweet lookup failed");
  }
  const info = parseOembed(data, parsed.handle);
  // Never returns like counts (oEmbed does not provide them anyway).
  return json({ ok: true, ...info, url: parsed.url });
}

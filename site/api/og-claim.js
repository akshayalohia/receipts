// Serves the static claim page (dist/c/index.html) for /c/<slug> with per-slug
// og:/twitter: title and image, because link-preview crawlers don't run JS.
// vercel.json rewrites /c/:slug here and bundles dist/c/index.html via includeFiles;
// if the file isn't readable at runtime we fetch the static page from this deployment.
import { readFile } from "node:fs/promises";
import { getJSON, SLUG_RE } from "./_lib.js";

const TEMPLATE_PATHS = [
  new URL("../dist/c/index.html", import.meta.url),
  `${process.cwd()}/dist/c/index.html`,
];

let cachedTemplate = null;

async function loadTemplate(origin) {
  if (cachedTemplate) return cachedTemplate;
  for (const p of TEMPLATE_PATHS) {
    try {
      cachedTemplate = await readFile(p, "utf8");
      return cachedTemplate;
    } catch {
      // try next
    }
  }
  const res = await fetch(new URL("/c/index.html", origin));
  if (!res.ok) throw new Error(`claim page status ${res.status}`);
  cachedTemplate = await res.text();
  return cachedTemplate;
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function setMeta(html, attr, name, value) {
  const re = new RegExp(`(<meta\\s+${attr}="${name}"\\s+content=")[^"]*(")`, "i");
  return html.replace(re, `$1${escapeAttr(value)}$2`);
}

export function slugFrom(request) {
  const u = new URL(request.url);
  const q = u.searchParams.get("slug");
  if (q) return SLUG_RE.test(q) ? q : null;
  const m = /^\/c\/([^/]+)/.exec(u.pathname);
  let s = "";
  try {
    s = m ? decodeURIComponent(m[1]) : "";
  } catch {
    s = "";
  }
  return SLUG_RE.test(s) ? s : null;
}

/** Rewrites og/twitter title + image in the claim page for `claim`. */
export function personalise(html, claim, origin) {
  let out = html;
  if (claim.handle) {
    const title = `Trove · @${String(claim.handle).replace(/^@/, "")}, this one's yours`;
    out = setMeta(out, "property", "og:title", title);
    out = setMeta(out, "name", "twitter:title", title);
  }
  if (claim.og_image_b64) {
    const img = `${origin}/api/claim/${encodeURIComponent(claim.slug)}/og.png`;
    out = setMeta(out, "property", "og:image", img);
    out = setMeta(out, "name", "twitter:image", img);
  }
  return out;
}

export async function handleGet(request, env, template) {
  const origin = new URL(request.url).origin;
  let html;
  try {
    html = template ?? (await loadTemplate(origin));
  } catch {
    return new Response("claim page unavailable", {
      status: 502,
      headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
    });
  }
  const slug = slugFrom(request);
  if (slug) {
    let claim = null;
    try {
      claim = await getJSON(env, `claim:${slug}`);
    } catch {
      claim = null; // storage down: serve the generic page
    }
    if (claim) html = personalise(html, { ...claim, slug }, origin);
  }
  return new Response(html, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=60" },
  });
}

export function GET(request) {
  return handleGet(request, process.env);
}
